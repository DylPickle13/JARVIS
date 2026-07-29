#!/usr/bin/env node
import { spawn } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import { mkdir, readFile, writeFile, chmod } from 'node:fs/promises';
import { createServer } from 'node:http';
import { connect as netConnect } from 'node:net';
import { homedir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import puppeteer from 'puppeteer-core';

const __dirname = dirname(fileURLToPath(import.meta.url));
const projectRoot = process.env.JARVIS_PROJECT_DIR || resolve(__dirname, '../../..');

const DEFAULT_CHROME_PATHS = [
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta',
  '/Applications/Chromium.app/Contents/MacOS/Chromium',
  '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium-browser',
  '/usr/bin/chromium',
];

let projectEnvCache = null;
function projectEnv() {
  if (projectEnvCache) return projectEnvCache;
  projectEnvCache = {};
  const envPath = join(projectRoot, '.env');
  if (!existsSync(envPath)) return projectEnvCache;
  for (const line of readFileSync(envPath, 'utf8').split(/\r?\n/)) {
    const match = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/);
    if (!match || match[1].startsWith('#')) continue;
    let value = match[2];
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) value = value.slice(1, -1);
    projectEnvCache[match[1]] = value;
  }
  return projectEnvCache;
}

function envValue(name, fallback) {
  return process.env[name]?.trim() || projectEnv()[name]?.trim() || fallback;
}

function chromePath() {
  const configured = envValue('PI_BROWSER_CHROME_PATH');
  if (configured && existsSync(configured)) return configured;
  const found = DEFAULT_CHROME_PATHS.find((path) => existsSync(path));
  if (!found) throw new Error('Chrome executable not found. Set PI_BROWSER_CHROME_PATH to your Chrome/Chromium binary.');
  return found;
}

const profileDir = envValue('PI_BROWSER_PROFILE_DIR', join(homedir(), 'Library', 'Application Support', 'Google', 'Chrome'));
const profileDirectory = envValue('PI_BROWSER_PROFILE_DIRECTORY', 'Profile 1');
const host = envValue('PI_BROWSER_DAEMON_HOST', '127.0.0.1');
const port = Number(envValue('PI_BROWSER_DAEMON_PORT', '17322'));
const tokenFile = envValue('PI_BROWSER_DAEMON_TOKEN_FILE', join(homedir(), '.jarvis', 'chrome-bridge.token'));
const connectTimeoutMs = Number(envValue('PI_BROWSER_DAEMON_CONNECT_TIMEOUT_MS', '120000'));
const automationWindowTitle = 'JARVIS Browser — Automation Only';
const automationMarkerId = 'jarvis-browser-automation-window-v1';
const automationAnchorName = '__JARVIS_BROWSER_AUTOMATION_ANCHOR_V1__';
const automationTabNamePrefix = '__JARVIS_BROWSER_TAB_';
const automationMarkerUrl = `data:text/html;charset=utf-8,${encodeURIComponent(`<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="color-scheme" content="dark">
  <title>${automationWindowTitle}</title>
  <style>
    :root { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #e8edf5; background: #111827; }
    body { min-height: 100vh; box-sizing: border-box; margin: 0; display: grid; place-items: center; padding: 32px; }
    main { width: min(680px, 100%); padding: 36px; border: 1px solid #334155; border-radius: 18px; background: #172033; box-shadow: 0 18px 60px #0006; }
    h1 { margin: 0 0 12px; font-size: 30px; }
    p { margin: 8px 0; color: #bac7d9; line-height: 1.55; }
    strong { color: #f8fafc; }
    code { color: #93c5fd; }
  </style>
</head>
<body data-jarvis-browser-marker="${automationMarkerId}">
  <main>
    <h1>JARVIS Browser</h1>
    <p><strong>This Chrome window is reserved for browser-tool automation.</strong></p>
    <p>It uses the same signed-in Chrome profile as your personal windows, but JARVIS only controls tabs created by the current browser-tool session.</p>
    <p>Please keep this anchor tab open. If the window is closed, JARVIS will recreate it automatically.</p>
  </main>
  <script>window.name = ${JSON.stringify(automationAnchorName)};<\/script>
</body>
</html>`)}`;

let authToken = '';
let browser = null;
let activePage = null;
let automationWindowId = null;
let automationAnchorPage = null;
let automationWindowPromise = null;
const ownedAutomationPages = new Set();
const automationTabIds = new Map();
let connectPromise = null;
let lastError = '';
let lastConnectedAt = null;

function log(...args) {
  console.log(new Date().toISOString(), ...args);
}

function formatError(error) {
  if (error instanceof Error && error.message) return error.message;
  if (error && typeof error === 'object') {
    if (typeof error.message === 'string' && error.message) return error.message;
    const symbols = Object.getOwnPropertySymbols(error);
    for (const symbol of symbols) {
      const value = error[symbol];
      if (value instanceof Error && value.message) return value.message;
      if (typeof value === 'string' && value) return value;
    }
    try {
      return JSON.stringify(error);
    } catch {}
  }
  return String(error);
}

function connected() {
  return Boolean(browser && (browser.connected ?? browser.isConnected?.()));
}

async function loadOrCreateToken() {
  await mkdir(dirname(tokenFile), { recursive: true, mode: 0o700 });
  try {
    const existing = (await readFile(tokenFile, 'utf8')).trim();
    if (existing) {
      await chmod(tokenFile, 0o600).catch(() => undefined);
      return existing;
    }
  } catch {}
  const token = randomBytes(32).toString('hex');
  await writeFile(tokenFile, `${token}\n`, { mode: 0o600 });
  await chmod(tokenFile, 0o600).catch(() => undefined);
  return token;
}

function parseEndpoint(content) {
  const [rawPort, rawPath] = content.split('\n').map((line) => line.trim()).filter(Boolean);
  const parsedPort = Number(rawPort);
  if (!rawPort || !rawPath || !Number.isInteger(parsedPort) || parsedPort <= 0 || parsedPort > 65535) {
    throw new Error(`Invalid DevToolsActivePort content: ${JSON.stringify(content)}`);
  }
  return { endpoint: `ws://127.0.0.1:${parsedPort}${rawPath}`, port: parsedPort };
}

async function readDevToolsEndpoint() {
  const portPath = join(profileDir, 'DevToolsActivePort');
  const content = await readFile(portPath, 'utf8');
  return parseEndpoint(content);
}

async function isTcpOpen(tcpPort) {
  return new Promise((resolve) => {
    const socket = netConnect({ host: '127.0.0.1', port: tcpPort });
    const done = (value) => {
      socket.destroy();
      resolve(value);
    };
    socket.setTimeout(700);
    socket.once('connect', () => done(true));
    socket.once('timeout', () => done(false));
    socket.once('error', () => done(false));
  });
}

async function endpointAvailable() {
  try {
    const endpoint = await readDevToolsEndpoint();
    if (await isTcpOpen(endpoint.port)) return endpoint;
  } catch {}
  return null;
}

function spawnRegularChrome(url = 'about:blank', detached = false) {
  const args = [
    ...(profileDirectory ? [`--profile-directory=${profileDirectory}`] : []),
    url,
  ];
  const child = spawn(chromePath(), args, {
    stdio: detached ? 'ignore' : ['ignore', 'pipe', 'pipe'],
    detached,
    env: process.env,
  });
  if (detached) child.unref();
  return child;
}

async function ensureRegularChromeReady() {
  const existing = await endpointAvailable();
  if (existing) return existing;

  log('Starting regular Chrome profile', profileDirectory || '(default)');
  const child = spawnRegularChrome('about:blank');
  child.stderr?.on('data', (chunk) => log('[chrome stderr]', String(chunk).trim()));

  const deadline = Date.now() + 8000;
  while (Date.now() < deadline) {
    const endpoint = await endpointAvailable();
    if (endpoint) return endpoint;
    await new Promise((resolve) => setTimeout(resolve, 200));
  }

  log('Remote debugging not enabled yet; opening chrome://inspect/#remote-debugging');
  spawnRegularChrome('chrome://inspect/#remote-debugging', true);
  throw new Error('Regular Chrome remote debugging is not enabled. In Chrome, open chrome://inspect/#remote-debugging, enable remote debugging, allow the connection prompt, then restart or retry the daemon.');
}

async function runAppleScript(lines, operation) {
  const args = lines.flatMap((line) => ['-e', line]);
  return new Promise((resolvePromise, rejectPromise) => {
    const child = spawn('/usr/bin/osascript', args, { stdio: ['ignore', 'pipe', 'pipe'] });
    let stdout = '';
    let stderr = '';
    let settled = false;
    let timer;
    const finish = (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (error) rejectPromise(error);
      else resolvePromise(stdout.trim());
    };
    timer = setTimeout(() => {
      child.kill('SIGTERM');
      finish(new Error(`Timed out while ${operation}`));
    }, 10000);
    child.stdout?.on('data', (chunk) => {
      if (stdout.length < 8000) stdout += String(chunk).slice(0, 8000 - stdout.length);
    });
    child.stderr?.on('data', (chunk) => {
      if (stderr.length < 8000) stderr += String(chunk).slice(0, 8000 - stderr.length);
    });
    child.once('error', (error) => finish(error));
    child.once('close', (code, signal) => {
      if (code === 0) finish();
      else finish(new Error(`Could not complete ${operation} (${signal || `exit ${code}`}): ${stderr.trim() || 'unknown AppleScript error'}`));
    });
  });
}

async function createBackgroundTabInMacChromeWindow(windowId, url) {
  const numericWindowId = Number(windowId);
  if (!Number.isSafeInteger(numericWindowId) || numericWindowId <= 0) throw new Error(`Invalid Chrome automation window ID: ${windowId}`);
  if (!/^about:blank#[A-Za-z0-9_-]+$/.test(url)) throw new Error('Unsafe internal Chrome tab placeholder URL');

  const output = await runAppleScript([
    'tell application "Google Chrome"',
    'set previousFrontWindowId to id of front window',
    `set targetWindow to first window whose id is ${numericWindowId}`,
    'tell targetWindow',
    `set createdTab to make new tab at end of tabs with properties {URL:"${url}"}`,
    'end tell',
    `if (previousFrontWindowId as text) is not "${numericWindowId}" then set index of (first window whose id is previousFrontWindowId) to 1`,
    'return id of createdTab',
    'end tell',
  ], 'creating a background tab in the dedicated JARVIS Chrome window');
  const tabId = Number(output);
  if (!Number.isSafeInteger(tabId) || tabId <= 0) throw new Error(`Chrome returned an invalid automation tab ID: ${JSON.stringify(output)}`);
  return tabId;
}

async function activateBackgroundTabInMacChromeWindow(windowId, tabId) {
  const numericWindowId = Number(windowId);
  const numericTabId = Number(tabId);
  if (!Number.isSafeInteger(numericWindowId) || numericWindowId <= 0) throw new Error(`Invalid Chrome automation window ID: ${windowId}`);
  if (!Number.isSafeInteger(numericTabId) || numericTabId <= 0) throw new Error(`Invalid Chrome automation tab ID: ${tabId}`);

  await runAppleScript([
    'tell application "Google Chrome"',
    'set previousFrontWindowId to id of front window',
    `set targetWindow to first window whose id is ${numericWindowId}`,
    'set targetTabIndex to 0',
    'repeat with candidateIndex from 1 to count of tabs of targetWindow',
    `if (id of tab candidateIndex of targetWindow as text) is "${numericTabId}" then`,
    'set targetTabIndex to candidateIndex',
    'exit repeat',
    'end if',
    'end repeat',
    'if targetTabIndex is 0 then error "JARVIS automation tab is no longer open" number -1728',
    'set active tab index of targetWindow to targetTabIndex',
    `if (previousFrontWindowId as text) is not "${numericWindowId}" then set index of (first window whose id is previousFrontWindowId) to 1`,
    'end tell',
  ], 'activating a tab inside the background JARVIS Chrome window');
}

async function macChromeTabSnapshot(windowId) {
  const numericWindowId = Number(windowId);
  if (!Number.isSafeInteger(numericWindowId) || numericWindowId <= 0) throw new Error(`Invalid Chrome automation window ID: ${windowId}`);
  const output = await runAppleScript([
    'tell application "Google Chrome"',
    `set targetWindow to first window whose id is ${numericWindowId}`,
    'set activeTabId to id of active tab of targetWindow',
    'set rows to {"active" & (ASCII character 9) & (activeTabId as text)}',
    'repeat with candidateTab in tabs of targetWindow',
    'set end of rows to ((id of candidateTab as text) & (ASCII character 9) & (URL of candidateTab as text))',
    'end repeat',
    'set AppleScript\'s text item delimiters to linefeed',
    'return rows as text',
    'end tell',
  ], 'reading tab identities from the dedicated JARVIS Chrome window');
  const lines = output.split(/\r?\n/).filter(Boolean);
  const activeTabId = Number(lines.shift()?.split('\t')[1]);
  const tabs = lines.map((line) => {
    const separator = line.indexOf('\t');
    return { id: Number(line.slice(0, separator)), url: separator >= 0 ? line.slice(separator + 1) : '' };
  }).filter((tab) => Number.isSafeInteger(tab.id) && tab.id > 0);
  return { activeTabId, tabs };
}

async function refreshMacAutomationTabId(candidate) {
  if (process.platform !== 'darwin') return undefined;
  const snapshot = await macChromeTabSnapshot(automationWindowId);
  const matches = snapshot.tabs.filter((tab) => tab.url === candidate.url());
  const selected = matches.length === 1 ? matches[0] : matches.find((tab) => tab.id === snapshot.activeTabId);
  if (!selected) return undefined;
  automationTabIds.set(candidate, selected.id);
  return selected.id;
}

function targetFilter(target) {
  const url = target.url();
  if (url === 'chrome://newtab/' || url === 'chrome://new-tab-page/' || url.startsWith('chrome://inspect')) return true;
  return !url.startsWith('chrome://') && !url.startsWith('chrome-extension://') && !url.startsWith('devtools://');
}

async function connectedPages() {
  if (!connected()) return [];
  return (await browser.pages()).filter((candidate) => !candidate.isClosed() && !candidate.url().startsWith('devtools://'));
}

async function windowIdOf(candidate) {
  try {
    return await candidate.windowId();
  } catch {
    return null;
  }
}

async function isAutomationMarker(candidate) {
  if (!candidate || candidate.isClosed()) return false;
  if (candidate.url() === automationMarkerUrl) return true;
  if (!candidate.url().includes(automationMarkerId)) return false;
  const name = await candidate.evaluate(() => window.name).catch(() => '');
  return name === automationAnchorName;
}

async function ensureAutomationWindow() {
  if (!connected()) throw new Error('Chrome is not connected');
  if (automationWindowPromise) return automationWindowPromise;

  automationWindowPromise = (async () => {
    const all = await connectedPages();

    if (automationAnchorPage && !automationAnchorPage.isClosed()) {
      const currentWindowId = await windowIdOf(automationAnchorPage);
      if (currentWindowId && currentWindowId === automationWindowId) {
        if (automationAnchorPage.url() !== automationMarkerUrl) {
          await automationAnchorPage.goto(automationMarkerUrl, { waitUntil: 'domcontentloaded', timeout: 10000 });
        }
        return automationAnchorPage;
      }
    }

    automationAnchorPage = null;
    for (const candidate of all) {
      if (!(await isAutomationMarker(candidate))) continue;
      const existingWindowId = await windowIdOf(candidate);
      if (!existingWindowId) continue;
      automationAnchorPage = candidate;
      automationWindowId = existingWindowId;
      if (automationAnchorPage.url() !== automationMarkerUrl) {
        await automationAnchorPage.goto(automationMarkerUrl, { waitUntil: 'domcontentloaded', timeout: 10000 });
      }
      log('Reusing dedicated JARVIS browser window', automationWindowId);
      return automationAnchorPage;
    }

    // Never infer ownership from a window, URL, or persisted window.name. If the
    // anchor disappears, abandon the old work pages rather than risk closing a
    // personal tab the user navigated or moved into that window.
    ownedAutomationPages.clear();
    automationTabIds.clear();
    activePage = null;
    automationWindowId = null;

    const anchor = await browser.newPage({ type: 'window', background: true });
    try {
      await anchor.goto(automationMarkerUrl, { waitUntil: 'domcontentloaded', timeout: 10000 });
      const newWindowId = await windowIdOf(anchor);
      if (!newWindowId) throw new Error('Chrome did not return an ID for the dedicated automation window');
      automationAnchorPage = anchor;
      automationWindowId = newWindowId;
      log('Created dedicated JARVIS browser window', automationWindowId);
      return automationAnchorPage;
    } catch (error) {
      await anchor.close().catch(() => undefined);
      throw error;
    }
  })();

  try {
    return await automationWindowPromise;
  } finally {
    automationWindowPromise = null;
  }
}

async function connectBrowser() {
  if (connected()) return browser;
  if (connectPromise) return connectPromise;

  connectPromise = (async () => {
    try {
      const { endpoint } = await ensureRegularChromeReady();
      log('Connecting to regular Chrome CDP endpoint', endpoint.replace(/\/devtools\/browser\/.+$/, '/devtools/browser/<redacted>'));
      browser = await puppeteer.connect({
        browserWSEndpoint: endpoint,
        defaultViewport: null,
        handleDevToolsAsPage: true,
        targetFilter,
        protocolTimeout: connectTimeoutMs,
      });
      browser.on('disconnected', () => {
        log('Disconnected from Chrome');
        browser = null;
        activePage = null;
        automationWindowId = null;
        automationAnchorPage = null;
        automationWindowPromise = null;
        ownedAutomationPages.clear();
        automationTabIds.clear();
      });
      await ensureAutomationWindow();
      lastError = '';
      lastConnectedAt = new Date().toISOString();
      log('Connected to Chrome');
      return browser;
    } catch (error) {
      const formatted = formatError(error);
      lastError = /403|Forbidden|permission denied/i.test(formatted)
        ? `${formatted}. Chrome denied the remote-debugging WebSocket; approve the connection in regular Chrome, then retry.`
        : formatted;
      log('Connection failed:', lastError);
      await browser?.disconnect?.().catch(() => undefined);
      browser = null;
      activePage = null;
      automationWindowId = null;
      automationAnchorPage = null;
      automationWindowPromise = null;
      ownedAutomationPages.clear();
      automationTabIds.clear();
      throw error;
    } finally {
      connectPromise = null;
    }
  })();

  return connectPromise;
}

async function pages() {
  await connectBrowser();
  await ensureAutomationWindow();
  const all = await connectedPages();
  const sameWindow = [];
  for (const candidate of all) {
    if (candidate === automationAnchorPage || await isAutomationMarker(candidate)) continue;
    if (await windowIdOf(candidate) === automationWindowId) sameWindow.push(candidate);
  }

  // Ownership is deliberately session-local. On daemon restart, old tabs are
  // abandoned instead of being re-adopted from their URL, window, title, or
  // window.name; any of those may now represent the user's browsing.
  for (const candidate of [...ownedAutomationPages]) {
    if (candidate.isClosed() || !sameWindow.includes(candidate)) {
      ownedAutomationPages.delete(candidate);
      automationTabIds.delete(candidate);
    }
  }

  // Claim only new popup descendants of pages already owned in this daemon
  // session. The persistent anchor is intentionally not an ownership root, so
  // stale tabs opened by an earlier bridge process cannot be re-adopted.
  const ownedTargets = new Set([...ownedAutomationPages].map((candidate) => candidate.target()));
  let claimed = true;
  while (claimed) {
    claimed = false;
    for (const candidate of sameWindow) {
      if (ownedAutomationPages.has(candidate)) continue;
      if (!ownedTargets.has(candidate.target().opener())) continue;
      ownedAutomationPages.add(candidate);
      ownedTargets.add(candidate.target());
      claimed = true;
    }
  }

  return sameWindow.filter((candidate) => ownedAutomationPages.has(candidate));
}

async function isOpenAutomationPage(candidate) {
  if (!candidate || candidate.isClosed() || candidate === automationAnchorPage || !ownedAutomationPages.has(candidate)) return false;
  return await windowIdOf(candidate) === automationWindowId;
}

async function createAutomationPage() {
  await connectBrowser();
  await ensureAutomationWindow();
  const existingTargets = new Set(browser.targets());
  const timeout = Math.max(1000, Math.min(Number(envValue('PI_BROWSER_NEW_TAB_TIMEOUT_MS', '10000')), 60000));
  const token = randomBytes(10).toString('hex');
  const tabName = `${automationTabNamePrefix}${token}__`;
  const placeholderUrl = `about:blank#jarvis-${token}`;

  let target;
  let macTabId;
  if (process.platform === 'darwin') {
    [target, macTabId] = await Promise.all([
      browser.waitForTarget(
        (candidate) => !existingTargets.has(candidate) && candidate.type() === 'page' && candidate.url().includes(token),
        { timeout },
      ),
      createBackgroundTabInMacChromeWindow(automationWindowId, placeholderUrl),
    ]);
  } else {
    const anchor = automationAnchorPage;
    [target] = await Promise.all([
      browser.waitForTarget(
        (candidate) => !existingTargets.has(candidate) && candidate.type() === 'page' && candidate.opener() === anchor.target(),
        { timeout },
      ),
      anchor.evaluate(({ name, url }) => { window.open(url, name); }, { name: tabName, url: placeholderUrl }),
    ]);
  }

  const created = await target.page();
  if (!created) throw new Error('Chrome created an automation target without a page');
  if (await windowIdOf(created) !== automationWindowId) {
    await created.close().catch(() => undefined);
    throw new Error('Chrome opened the automation tab outside the dedicated JARVIS window; action aborted');
  }
  await created.evaluate((name) => { window.name = name; }, tabName);
  ownedAutomationPages.add(created);
  if (macTabId) automationTabIds.set(created, macTabId);
  return created;
}

async function ensureInteractivePage(candidate) {
  if (!(await isOpenAutomationPage(candidate))) throw new Error('The selected page is no longer owned by this browser-tool session');
  if (process.platform !== 'darwin') return;

  // Reading tab state does not reorder Chrome windows. Avoid the activate/restore
  // cycle entirely when this JARVIS tab is already active in its own window;
  // that removes the visible flicker from normal click/type/scroll sequences.
  const snapshot = await macChromeTabSnapshot(automationWindowId);
  let tabId = automationTabIds.get(candidate);
  if (!snapshot.tabs.some((tab) => tab.id === tabId)) {
    const matches = snapshot.tabs.filter((tab) => tab.url === candidate.url());
    const selected = matches.length === 1 ? matches[0] : matches.find((tab) => tab.id === snapshot.activeTabId);
    tabId = selected?.id;
    if (tabId) automationTabIds.set(candidate, tabId);
  }
  if (!tabId) throw new Error('Cannot safely identify this automation popup without risking the user’s Chrome focus');
  if (tabId === snapshot.activeTabId) return;
  await activateBackgroundTabInMacChromeWindow(automationWindowId, tabId);
}

async function page() {
  if (await isOpenAutomationPage(activePage)) return activePage;
  const all = await pages();
  activePage = all[0] ?? await createAutomationPage();
  return activePage;
}

async function titleOf(p) {
  try { return await p.title(); } catch { return ''; }
}

function randomInt(min, max) {
  return Math.floor(min + Math.random() * (max - min + 1));
}

async function viewportSize(p) {
  try {
    const viewport = p.viewport();
    if (viewport) return viewport;
    return await p.evaluate(() => ({ width: window.innerWidth, height: window.innerHeight }));
  } catch {
    return {};
  }
}

function assertViewportPoint(p, x, y, viewport) {
  const width = viewport?.width ?? p.viewport()?.width;
  const height = viewport?.height ?? p.viewport()?.height;
  if (!width || !height) return;
  if (x < 0 || y < 0 || x > width || y > height) {
    throw new Error(`Target resolved offscreen at ${Math.round(x)},${Math.round(y)} for viewport ${width}x${height}; action aborted`);
  }
}

async function activeElementEditable(p) {
  return p.evaluate(() => {
    const el = document.activeElement;
    if (!el) return false;
    if (el.isContentEditable) return true;
    const tag = el.tagName.toLowerCase();
    if (tag === 'textarea') return !el.disabled && !el.readOnly;
    if (tag === 'input') {
      const nonTextTypes = new Set(['button', 'checkbox', 'color', 'file', 'hidden', 'image', 'radio', 'range', 'reset', 'submit']);
      return !el.disabled && !el.readOnly && !nonTextTypes.has((el.type || 'text').toLowerCase());
    }
    if (tag === 'select') return !el.disabled;
    return false;
  });
}

async function firstVisibleHandle(p, selector) {
  const handles = await p.$$(selector);
  for (const handle of handles.slice(0, 50)) {
    const box = await handle.boundingBox().catch(() => null);
    if (box && box.width > 0 && box.height > 0) return handle;
  }
  return handles[0] ?? null;
}

async function handleFor(p, params = {}) {
  if (params.selector) {
    const handle = await firstVisibleHandle(p, params.selector);
    if (handle) return handle;
    throw new Error(`No element found for selector: ${params.selector}`);
  }

  if (params.text) {
    const handle = await p.evaluateHandle(({ text, exact }) => {
      const wanted = String(text).trim().toLowerCase();
      const visible = (el) => {
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
      };
      const label = (el) => [
        el.textContent || '',
        el.getAttribute?.('aria-label') || '',
        el.placeholder || '',
        el.value || '',
      ].join(' ').trim().replace(/\s+/g, ' ').toLowerCase();
      const candidates = Array.from(document.querySelectorAll('a,button,label,input,textarea,select,[role=button],[role=link],[aria-label],[placeholder],[contenteditable=true],summary,[onclick]'));
      return candidates.find((el) => {
        if (!visible(el)) return false;
        const haystack = label(el);
        return exact ? haystack === wanted : haystack.includes(wanted);
      }) ?? null;
    }, { text: params.text, exact: Boolean(params.exact) });
    const exists = await handle.evaluate((el) => Boolean(el)).catch(() => false);
    if (exists) return handle;
  }

  throw new Error('selector or text is required');
}

async function handleCenter(p, handle) {
  await handle.evaluate((el) => el.scrollIntoView({ block: 'center', inline: 'center', behavior: 'auto' })).catch(() => undefined);
  await new Promise((resolve) => setTimeout(resolve, 100));
  const box = await handle.boundingBox();
  if (!box) throw new Error('Target element has no visible bounding box');
  const size = await viewportSize(p);
  const x = box.x + box.width / 2 + randomInt(-2, 2);
  const y = box.y + box.height / 2 + randomInt(-2, 2);
  assertViewportPoint(p, x, y, size);
  return { x, y };
}

async function pressKey(p, key) {
  const parts = String(key).split('+').map((part) => part.trim()).filter(Boolean);
  if (parts.length <= 1) {
    await p.keyboard.press(key);
    return;
  }
  const last = parts.pop();
  for (const modifier of parts) await p.keyboard.down(modifier);
  try {
    await p.keyboard.press(last);
  } finally {
    for (const modifier of parts.reverse()) await p.keyboard.up(modifier);
  }
}

async function humanMove(p, x, y) {
  const steps = randomInt(12, 28);
  await p.mouse.move(x + randomInt(-3, 3), y + randomInt(-3, 3), { steps });
}

async function settleAfterClick(p, beforeUrl) {
  const timeoutMs = Math.max(0, Math.min(Number(envValue('PI_BROWSER_CLICK_NAV_WAIT_MS', '1500')), 10000));
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (p.isClosed()) return;
    if (p.url() !== beforeUrl) {
      await p.waitForNetworkIdle({ timeout: 2000, idleTime: 500 }).catch(() => undefined);
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
}

async function statusObject() {
  const all = connected() ? await pages().catch(() => []) : [];
  let endpoint;
  try { endpoint = await readDevToolsEndpoint(); } catch {}
  return {
    launchMode: 'cdp',
    running: connected(),
    connected: connected(),
    port: endpoint?.port,
    profileDir,
    profileDirectory,
    cdpUrl: endpoint?.endpoint,
    automationWindow: {
      dedicated: true,
      windowId: automationWindowId ?? undefined,
      title: automationWindowTitle,
      anchorOpen: Boolean(automationAnchorPage && !automationAnchorPage.isClosed()),
      avoidsForegroundActivation: true,
      sessionOwnedTabsOnly: true,
    },
    daemon: { host, port, tokenFile, connectedAt: lastConnectedAt, lastError, connecting: Boolean(connectPromise) },
    activeIndex: activePage ? all.indexOf(activePage) : -1,
    pages: await Promise.all(all.map(async (p, index) => ({ index, url: p.url(), title: await titleOf(p) }))),
  };
}

async function openPage(body) {
  let url = String(body?.url || 'about:blank');
  if (!/^https?:\/\//i.test(url) && !/^file:\/\//i.test(url) && !/^about:/i.test(url) && !/^chrome:/i.test(url)) url = `https://${url}`;
  await connectBrowser();
  const reuseActive = !body?.newTab && await isOpenAutomationPage(activePage);
  const p = reuseActive ? activePage : await createAutomationPage();
  activePage = p;
  await ensureInteractivePage(p);
  await p.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await p.waitForNetworkIdle({ timeout: 5000, idleTime: 500 }).catch(() => undefined);
  await refreshMacAutomationTabId(p);
  const all = await pages();
  return { url: p.url(), title: await titleOf(p), index: all.indexOf(p) };
}

async function tabsAction(body) {
  await connectBrowser();
  let all = await pages();
  const action = body?.action || 'list';
  const index = body?.index;
  if (action === 'switch') {
    if (index === undefined || !all[index]) throw new Error(`Tab index ${index} is not open`);
    // Keep the selected JARVIS tab active inside its own background window,
    // while restoring the user's previously front Chrome window.
    activePage = all[index];
    await ensureInteractivePage(activePage);
  } else if (action === 'close') {
    if (index === undefined || !all[index]) throw new Error(`Tab index ${index} is not open`);
    await all[index].close();
    all = await pages();
    activePage = all[0] ?? null;
  } else if (action !== 'list') {
    throw new Error(`Unsupported tabs action: ${action}`);
  }
  return statusObject();
}

async function extractPage(body) {
  const p = await page();
  const maxText = Math.max(500, Math.min(Number(body?.maxText || 12000), 50000));
  const selector = body?.selector;
  const text = selector
    ? await p.$eval(selector, (el) => (el instanceof HTMLElement ? el.innerText : el.textContent || '')).catch(() => '')
    : await p.$eval('body', (el) => (el instanceof HTMLElement ? el.innerText : el.textContent || '')).catch(() => '');
  const result = {
    url: p.url(),
    title: await titleOf(p),
    text: text.length > maxText ? `${text.slice(0, maxText)}\n… truncated …` : text,
  };
  if (body?.includeLinks) {
    result.links = await p.evaluate(() => Array.from(document.querySelectorAll('a[href]')).slice(0, 120).map((a) => ({
      text: (a.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 160),
      href: a.href,
    })));
  }
  return result;
}

async function screenshotPage(body) {
  const p = await page();
  let bytes;
  if (body?.selector) {
    const element = await p.$(body.selector);
    if (!element) throw new Error(`No element found for selector: ${body.selector}`);
    bytes = await element.screenshot({ type: 'png' });
  } else {
    bytes = await p.screenshot({ type: 'png', fullPage: Boolean(body?.fullPage) });
  }
  const viewport = p.viewport() || await p.evaluate(() => ({ width: window.innerWidth, height: window.innerHeight })).catch(() => ({}));
  return {
    data: Buffer.from(bytes).toString('base64'),
    mimeType: 'image/png',
    width: viewport.width,
    height: viewport.height,
    url: p.url(),
    title: await titleOf(p),
  };
}

async function clickPage(body) {
  const p = await page();
  await ensureInteractivePage(p);
  const beforeUrl = p.url();
  let x = body?.x;
  let y = body?.y;
  if (x === undefined || y === undefined) {
    const handle = await handleFor(p, body);
    const center = await handleCenter(p, handle);
    x = center.x;
    y = center.y;
  } else {
    assertViewportPoint(p, x, y);
  }
  await humanMove(p, x, y);
  await new Promise((resolve) => setTimeout(resolve, randomInt(80, 260)));
  await p.mouse.click(x, y, {
    button: body?.button ?? 'left',
    count: Math.max(1, Math.min(Number(body?.clicks ?? 1), 3)),
    delay: randomInt(45, 145),
  });
  await settleAfterClick(p, beforeUrl);
  await refreshMacAutomationTabId(p);
  return { x, y, url: p.url(), title: await titleOf(p) };
}

async function typePage(body) {
  const p = await page();
  await ensureInteractivePage(p);
  if (body?.selector) {
    const handle = await handleFor(p, { selector: body.selector });
    const center = await handleCenter(p, handle);
    await humanMove(p, center.x, center.y);
    await handle.click();
  }
  if (!(await activeElementEditable(p))) throw new Error('No editable element is focused. Provide a selector to browser_type, or click/focus an input before typing.');
  if (body?.clear) {
    const modifier = process.platform === 'darwin' ? 'Meta' : 'Control';
    await pressKey(p, `${modifier}+A`);
    await p.keyboard.press('Backspace');
    await new Promise((resolve) => setTimeout(resolve, randomInt(80, 220)));
  }
  const text = String(body?.text ?? '');
  await p.keyboard.type(text, { delay: body?.delayMs ?? randomInt(35, 95) });
  return { url: p.url(), title: await titleOf(p), typedCharacters: text.length };
}

async function uploadPage(body) {
  const p = await page();
  await ensureInteractivePage(p);
  const requestedFiles = [...(body?.paths ?? []), ...(body?.path ? [body.path] : [])].map((filePath) => resolve(filePath));
  if (!requestedFiles.length) throw new Error('Provide path or paths for browser_upload.');
  for (const filePath of requestedFiles) if (!existsSync(filePath)) throw new Error(`Upload file does not exist: ${filePath}`);
  const timeout = Math.max(500, Math.min(Number(body?.timeoutMs ?? 10000), 60000));
  let method = 'input';

  if (body?.selector || body?.text) {
    const target = await handleFor(p, { selector: body?.selector, text: body?.text, exact: body?.exact });
    const isFileInput = await target.evaluate((el) => el instanceof HTMLInputElement && (el.type || '').toLowerCase() === 'file').catch(() => false);
    if (isFileInput) {
      await target.uploadFile(...requestedFiles);
    } else {
      method = 'filechooser';
      const chooserPromise = p.waitForFileChooser({ timeout });
      await target.click();
      const chooser = await chooserPromise;
      await chooser.accept(requestedFiles);
    }
  } else {
    const input = await firstVisibleHandle(p, 'input[type="file"]');
    if (!input) throw new Error('No input[type=file] found. Provide selector/text for the upload control.');
    await input.uploadFile(...requestedFiles);
  }
  return { url: p.url(), title: await titleOf(p), files: requestedFiles, method };
}

async function keyPage(body) {
  const p = await page();
  const key = String(body?.key || '');
  const normalized = key.replace(/\s+/g, '').toLowerCase();
  if (normalized === 'meta+t' || normalized === 'control+t') {
    const newPage = await createAutomationPage();
    activePage = newPage;
    return { url: newPage.url(), title: await titleOf(newPage) };
  }
  if (normalized === 'meta+w' || normalized === 'control+w') {
    await p.close();
    activePage = (await pages())[0] ?? null;
    const next = await page();
    return { url: next.url(), title: await titleOf(next) };
  }
  await ensureInteractivePage(p);
  await pressKey(p, key);
  await refreshMacAutomationTabId(p);
  return { url: p.url(), title: await titleOf(p) };
}

async function scrollPage(body) {
  const p = await page();
  await ensureInteractivePage(p);
  const direction = body?.direction ?? 'down';
  const amount = Math.max(50, Math.min(Number(body?.amount ?? 700), 3000));
  if (body?.x !== undefined && body?.y !== undefined) await humanMove(p, body.x, body.y);
  const dx = direction === 'left' ? -amount : direction === 'right' ? amount : 0;
  const dy = direction === 'up' ? -amount : direction === 'down' ? amount : 0;
  const chunks = randomInt(3, 6);
  for (let i = 0; i < chunks; i++) {
    await p.mouse.wheel({ deltaX: dx / chunks, deltaY: dy / chunks });
    await new Promise((resolve) => setTimeout(resolve, randomInt(80, 220)));
  }
  return { url: p.url(), title: await titleOf(p), amount, direction };
}

async function waitPage(body) {
  const p = await page();
  const timeout = Math.max(250, Math.min(Number(body?.timeoutMs ?? 10000), 60000));
  if (body?.ms) await new Promise((resolve) => setTimeout(resolve, Math.max(0, Math.min(Number(body.ms), 60000))));
  if (body?.selector) await p.waitForSelector(body.selector, { visible: true, timeout });
  if (body?.text) {
    await p.waitForFunction(
      (text) => document.body?.innerText?.toLowerCase().includes(String(text).toLowerCase()),
      { timeout },
      body.text,
    );
  }
  if (body?.loadState === 'networkidle') await p.waitForNetworkIdle({ timeout, idleTime: 500 });
  if (body?.loadState === 'load') {
    const ready = await p.evaluate(() => document.readyState).catch(() => '');
    if (ready !== 'complete') await p.waitForNavigation({ waitUntil: 'load', timeout }).catch(() => undefined);
  }
  if (body?.loadState === 'domcontentloaded') {
    const ready = await p.evaluate(() => document.readyState).catch(() => '');
    if (ready !== 'interactive' && ready !== 'complete') await p.waitForNavigation({ waitUntil: 'domcontentloaded', timeout }).catch(() => undefined);
  }
  return { url: p.url(), title: await titleOf(p) };
}

async function closeAction(body) {
  if (body?.all === false) {
    const p = await page();
    await p.close();
    activePage = (await pages())[0] ?? null;
    return { closedAll: false, daemonKeptAlive: true };
  }
  // Keep the daemon's approved Chrome connection alive. This preserves the whole point of the bridge.
  return { closedAll: true, daemonKeptAlive: true, note: 'Daemon connection kept alive; use SIGTERM to stop the bridge.' };
}

async function readJson(req) {
  const chunks = [];
  let total = 0;
  for await (const chunk of req) {
    total += chunk.length;
    if (total > 1024 * 1024) throw new Error('Request body too large');
    chunks.push(chunk);
  }
  const raw = Buffer.concat(chunks).toString('utf8').trim();
  return raw ? JSON.parse(raw) : {};
}

function send(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(body),
    'cache-control': 'no-store',
  });
  res.end(body);
}

function authorized(req) {
  const auth = req.headers.authorization || '';
  const bearer = auth.startsWith('Bearer ') ? auth.slice(7) : '';
  const header = req.headers['x-jarvis-browser-token'] || '';
  return bearer === authToken || header === authToken;
}

async function route(req, res) {
  if (req.url === '/health') return send(res, 200, { ok: true });
  if (!authorized(req)) return send(res, 401, { ok: false, error: 'Unauthorized' });

  try {
    const url = new URL(req.url || '/', `http://${host}:${port}`);
    if (req.method === 'GET' && url.pathname === '/status') return send(res, 200, { ok: true, result: await statusObject() });
    if (req.method === 'POST' && url.pathname === '/connect') return send(res, 200, { ok: true, result: await statusObject(await connectBrowser()) });

    const body = req.method === 'POST' ? await readJson(req) : {};
    if (req.method === 'POST' && url.pathname === '/open') return send(res, 200, { ok: true, result: await openPage(body) });
    if (req.method === 'GET' && url.pathname === '/tabs') return send(res, 200, { ok: true, result: await tabsAction({ action: 'list' }) });
    if (req.method === 'POST' && url.pathname === '/tabs') return send(res, 200, { ok: true, result: await tabsAction(body) });
    if (req.method === 'POST' && url.pathname === '/extract') return send(res, 200, { ok: true, result: await extractPage(body) });
    if (req.method === 'POST' && url.pathname === '/screenshot') return send(res, 200, { ok: true, result: await screenshotPage(body) });
    if (req.method === 'POST' && url.pathname === '/click') return send(res, 200, { ok: true, result: await clickPage(body) });
    if (req.method === 'POST' && url.pathname === '/type') return send(res, 200, { ok: true, result: await typePage(body) });
    if (req.method === 'POST' && url.pathname === '/upload') return send(res, 200, { ok: true, result: await uploadPage(body) });
    if (req.method === 'POST' && url.pathname === '/key') return send(res, 200, { ok: true, result: await keyPage(body) });
    if (req.method === 'POST' && url.pathname === '/scroll') return send(res, 200, { ok: true, result: await scrollPage(body) });
    if (req.method === 'POST' && url.pathname === '/wait') return send(res, 200, { ok: true, result: await waitPage(body) });
    if (req.method === 'POST' && url.pathname === '/close') return send(res, 200, { ok: true, result: await closeAction(body) });
    return send(res, 404, { ok: false, error: 'Not found' });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return send(res, 500, { ok: false, error: message });
  }
}

authToken = await loadOrCreateToken();
const server = createServer((req, res) => void route(req, res));
server.listen(port, host, () => {
  log(`Chrome bridge daemon listening on http://${host}:${port}`);
  log(`Token file: ${tokenFile}`);
  void connectBrowser().catch(() => undefined);
});

process.on('SIGINT', async () => {
  await browser?.disconnect?.().catch(() => undefined);
  process.exit(0);
});
process.on('SIGTERM', async () => {
  await browser?.disconnect?.().catch(() => undefined);
  process.exit(0);
});
