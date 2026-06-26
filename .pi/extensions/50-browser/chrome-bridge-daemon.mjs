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

let authToken = '';
let browser = null;
let activePage = null;
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

function targetFilter(target) {
  const url = target.url();
  if (url === 'chrome://newtab/' || url === 'chrome://new-tab-page/' || url.startsWith('chrome://inspect')) return true;
  return !url.startsWith('chrome://') && !url.startsWith('chrome-extension://') && !url.startsWith('devtools://');
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
      });
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
      browser = null;
      activePage = null;
      throw error;
    } finally {
      connectPromise = null;
    }
  })();

  return connectPromise;
}

async function pages() {
  const b = await connectBrowser();
  return (await b.pages()).filter((page) => !page.isClosed());
}

async function page() {
  if (activePage && !activePage.isClosed()) return activePage;
  const all = await pages();
  activePage = all.find((p) => !p.url().startsWith('devtools://')) ?? await browser.newPage();
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
    daemon: { host, port, tokenFile, connectedAt: lastConnectedAt, lastError, connecting: Boolean(connectPromise) },
    activeIndex: activePage ? all.indexOf(activePage) : -1,
    pages: await Promise.all(all.map(async (p, index) => ({ index, url: p.url(), title: await titleOf(p) }))),
  };
}

async function openPage(body) {
  let url = String(body?.url || 'about:blank');
  if (!/^https?:\/\//i.test(url) && !/^file:\/\//i.test(url) && !/^about:/i.test(url) && !/^chrome:/i.test(url)) url = `https://${url}`;
  await connectBrowser();
  const p = body?.newTab || !activePage || activePage.isClosed() ? await browser.newPage() : await page();
  activePage = p;
  await p.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await p.waitForNetworkIdle({ timeout: 5000, idleTime: 500 }).catch(() => undefined);
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
    activePage = all[index];
    await activePage.bringToFront();
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
  await p.bringToFront().catch(() => undefined);
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
  return { x, y, url: p.url(), title: await titleOf(p) };
}

async function typePage(body) {
  const p = await page();
  await p.bringToFront().catch(() => undefined);
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
    const newPage = await browser.newPage();
    activePage = newPage;
    await newPage.goto('about:blank', { waitUntil: 'domcontentloaded', timeout: 5000 }).catch(() => undefined);
    return { url: newPage.url(), title: await titleOf(newPage) };
  }
  if (normalized === 'meta+w' || normalized === 'control+w') {
    await p.close();
    activePage = (await pages())[0] ?? null;
    const next = await page();
    return { url: next.url(), title: await titleOf(next) };
  }
  await p.bringToFront().catch(() => undefined);
  await pressKey(p, key);
  return { url: p.url(), title: await titleOf(p) };
}

async function scrollPage(body) {
  const p = await page();
  await p.bringToFront().catch(() => undefined);
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
