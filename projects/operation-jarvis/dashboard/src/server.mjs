import { createServer } from 'node:http';
import { execFile } from 'node:child_process';
import { readFile, readdir, stat, mkdir, writeFile } from 'node:fs/promises';
import { createReadStream, watch } from 'node:fs';
import { createHash, randomUUID } from 'node:crypto';
import os from 'node:os';
import path from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(__dirname, '..'); // projects/operation-jarvis/dashboard
const operationRoot = path.resolve(projectRoot, '..'); // projects/operation-jarvis
const workspaceRoot = path.resolve(operationRoot, '..'); // projects
const jarvisRoot = path.resolve(workspaceRoot, '..'); // repository root
const publicDir = path.join(projectRoot, 'public');
const operationMediaDir = path.join(operationRoot, 'media');
const operationDataDir = path.join(operationRoot, 'data');
const dashboardCameraMediaDir = path.join(operationMediaDir, 'dashboard-camera');
const jarvisCli = path.join(operationRoot, 'jarvis-cli');
const execFileAsync = promisify(execFile);

const HOST = process.env.HOST || '0.0.0.0';
const PORT = Number.parseInt(process.env.PORT || '8787', 10);
const DASHBOARD_WRITE_TOKEN = process.env.JARVIS_DASHBOARD_WRITE_TOKEN || '';
const ENABLE_DASHBOARD_COMMANDS = /^(1|true|yes|on)$/i.test(process.env.JARVIS_ENABLE_DASHBOARD_COMMANDS || 'false');
const ENABLE_DEBUG_ENDPOINTS = /^(1|true|yes|on)$/i.test(process.env.JARVIS_ENABLE_DASHBOARD_DEBUG_ENDPOINTS || process.env.JARVIS_DASHBOARD_DEBUG_ENDPOINTS || 'false');
const ENABLE_AMBIENT_PULSES = /^(1|true|yes|on)$/i.test(process.env.JARVIS_DASHBOARD_AMBIENT_PULSES || 'false');
const JARVIS_ACTION_TIMEOUT_MS = Number.parseInt(process.env.JARVIS_ACTION_TIMEOUT_MS || '120000', 10);
const JARVIS_LOCAL_STATUS_CACHE_MS = Number.parseInt(process.env.JARVIS_DASHBOARD_LOCAL_STATUS_CACHE_MS || '5000', 10);
const JARVIS_DISPLAY_LOCAL_STATUS_TIMEOUT_MS = Number.parseInt(process.env.JARVIS_DASHBOARD_DISPLAY_LOCAL_STATUS_TIMEOUT_MS || '2500', 10);
const PI_SESSION_STATUS_FILE = process.env.JARVIS_PI_SESSION_STATUS_FILE || path.join(jarvisRoot, '.pi', 'runtime', 'pi-rpc-sessions.json');
const PI_SESSION_STATUS_CACHE_MS = Number.parseInt(process.env.JARVIS_DASHBOARD_PI_SESSION_STATUS_CACHE_MS || '1500', 10);
const PI_SESSION_STATUS_TIMEOUT_MS = Number.parseInt(process.env.JARVIS_DASHBOARD_PI_SESSION_STATUS_TIMEOUT_MS || '1500', 10);
const PI_PROCESS_STATUS_TIMEOUT_MS = Number.parseInt(process.env.JARVIS_DASHBOARD_PI_PROCESS_STATUS_TIMEOUT_MS || '1200', 10);
const DISCORD_BOT_SCRIPT = process.env.JARVIS_DISCORD_BOT_SCRIPT || path.join(jarvisRoot, 'discord_bot.py');
const DISCORD_BOT_PID_FILE = process.env.JARVIS_DISCORD_BOT_PID_FILE || path.join(jarvisRoot, '.pi', 'runtime', 'discord_bot.pid');
const DISCORD_BOT_STATUS_CACHE_MS = Number.parseInt(process.env.JARVIS_DASHBOARD_DISCORD_BOT_STATUS_CACHE_MS || '2000', 10);
const DISCORD_BOT_STATUS_TIMEOUT_MS = Number.parseInt(process.env.JARVIS_DASHBOARD_DISCORD_BOT_STATUS_TIMEOUT_MS || '1200', 10);
const PI_LOCAL_SESSION_STATUS_DIR = process.env.JARVIS_PI_LOCAL_SESSION_STATUS_DIR || path.join(jarvisRoot, '.pi', 'runtime', 'local-pi-sessions');
const PI_AGENT_SESSIONS_DIR = process.env.JARVIS_PI_AGENT_SESSIONS_DIR || path.join(os.homedir(), '.pi', 'agent', 'sessions');
const PI_SESSION_COST_CWD = process.env.JARVIS_DASHBOARD_PI_SESSION_COST_CWD || jarvisRoot;
const PI_SESSION_COST_CACHE_MS = Number.parseInt(process.env.JARVIS_DASHBOARD_PI_SESSION_COST_CACHE_MS || String(60_000), 10);
const PI_SESSION_COST_MAX_FILES = Number.parseInt(process.env.JARVIS_DASHBOARD_PI_SESSION_COST_MAX_FILES || '5000', 10);
const PI_SESSION_COST_SCAN_MAX_BYTES = Number.parseInt(process.env.JARVIS_DASHBOARD_PI_SESSION_COST_SCAN_MAX_BYTES || String(1024 * 1024 * 1024), 10);
const LOCAL_PI_ACTIVE_WINDOW_MS = Number.parseInt(process.env.JARVIS_LOCAL_PI_ACTIVE_WINDOW_MS || '5000', 10);
const LOCAL_PI_STATUS_MAX_AGE_MS = Number.parseInt(process.env.JARVIS_LOCAL_PI_STATUS_MAX_AGE_MS || '15000', 10);
const DEFAULT_OMLX_SERVER_ID = '16';
const OMLX_16_DEFAULT_BASE_URL = 'http://127.0.0.1:8000/v1';
const OMLX_64_DEFAULT_BASE_URL = '';
const OMLX_SHARED_API_KEY = process.env.JARVIS_DASHBOARD_OMLX_API_KEY || process.env.DISCORD_VOICE_API_KEY || process.env.OMLX_API_KEY || '';
const OMLX_STATUS_CACHE_MS = parseInteger(process.env.JARVIS_DASHBOARD_OMLX_STATUS_CACHE_MS, 5000);
const OMLX_SERVERS = new Map([
  ['16', buildOmlxServerConfig({
    id: '16',
    name: 'OMLX-16',
    baseUrl: firstEnv([
      'JARVIS_DASHBOARD_OMLX_16_BASE_URL',
      'JARVIS_DASHBOARD_OMLX_BASE_URL',
      'DISCORD_VOICE_BASE_URL',
      'DISCORD_VOICE_MESSAGE_ASR_BASE_URL',
      'OMLX_BASE_URL'
    ], OMLX_16_DEFAULT_BASE_URL),
    apiKey: firstEnv(['JARVIS_DASHBOARD_OMLX_16_API_KEY', 'JARVIS_OMLX_16_API_KEY', 'OMLX_16_API_KEY'], OMLX_SHARED_API_KEY),
    statusTimeoutMs: parseInteger(firstEnv(['JARVIS_DASHBOARD_OMLX_16_STATUS_TIMEOUT_MS', 'JARVIS_DASHBOARD_OMLX_STATUS_TIMEOUT_MS'], '1500'), 1500),
    statusCacheMs: parseInteger(firstEnv(['JARVIS_DASHBOARD_OMLX_16_STATUS_CACHE_MS', 'JARVIS_DASHBOARD_OMLX_STATUS_CACHE_MS'], String(OMLX_STATUS_CACHE_MS)), OMLX_STATUS_CACHE_MS),
    controlTimeoutMs: parseInteger(firstEnv(['JARVIS_DASHBOARD_OMLX_16_CONTROL_TIMEOUT_MS', 'JARVIS_DASHBOARD_OMLX_CONTROL_TIMEOUT_MS'], '30000'), 30000),
    sshHost: firstEnv(['JARVIS_DASHBOARD_OMLX_16_SSH_HOST', 'JARVIS_DASHBOARD_OMLX_SSH_HOST', 'JARVIS_OMLX_16_SSH_HOST', 'JARVIS_OMLX_SSH_HOST'], ''),
    sshUser: firstEnv(['JARVIS_DASHBOARD_OMLX_16_SSH_USER', 'JARVIS_DASHBOARD_OMLX_SSH_USER', 'JARVIS_OMLX_16_SSH_USER', 'JARVIS_OMLX_SSH_USER'], ''),
    sshKey: firstEnv(['JARVIS_DASHBOARD_OMLX_16_SSH_KEY', 'JARVIS_DASHBOARD_OMLX_SSH_KEY', 'JARVIS_OMLX_16_SSH_KEY', 'JARVIS_OMLX_SSH_KEY'], '~/.ssh/jarvis_dashboard_host'),
    sshPort: parseInteger(firstEnv(['JARVIS_DASHBOARD_OMLX_16_SSH_PORT', 'JARVIS_DASHBOARD_OMLX_SSH_PORT', 'JARVIS_OMLX_16_SSH_PORT', 'JARVIS_OMLX_SSH_PORT'], '22'), 22),
    appPath: firstEnv(['JARVIS_DASHBOARD_OMLX_16_APP_PATH', 'JARVIS_DASHBOARD_OMLX_APP_PATH'], '/Applications/oMLX.app'),
    cliPath: firstEnv(['JARVIS_DASHBOARD_OMLX_16_CLI_PATH', 'JARVIS_DASHBOARD_OMLX_CLI_PATH'], '/Applications/oMLX.app/Contents/MacOS/omlx-cli'),
    basePath: firstEnv(['JARVIS_DASHBOARD_OMLX_16_BASE_PATH', 'JARVIS_DASHBOARD_OMLX_BASE_PATH'], '~/.omlx'),
    serverLog: firstEnv(['JARVIS_DASHBOARD_OMLX_16_SERVER_LOG', 'JARVIS_DASHBOARD_OMLX_SERVER_LOG'], '~/Library/Application Support/oMLX/logs/server.log'),
    localHealthUrl: firstEnv(['JARVIS_DASHBOARD_OMLX_16_LOCAL_HEALTH_URL', 'JARVIS_DASHBOARD_OMLX_LOCAL_HEALTH_URL'], 'http://127.0.0.1:8000/health')
  })],
  ['64', buildOmlxServerConfig({
    id: '64',
    name: 'OMLX-64',
    baseUrl: firstEnv(['JARVIS_DASHBOARD_OMLX_64_BASE_URL', 'JARVIS_OMLX_64_BASE_URL', 'OMLX_64_BASE_URL'], OMLX_64_DEFAULT_BASE_URL),
    apiKey: firstEnv(['JARVIS_DASHBOARD_OMLX_64_API_KEY', 'JARVIS_OMLX_64_API_KEY', 'OMLX_64_API_KEY'], OMLX_SHARED_API_KEY),
    statusTimeoutMs: parseInteger(firstEnv(['JARVIS_DASHBOARD_OMLX_64_STATUS_TIMEOUT_MS', 'JARVIS_DASHBOARD_OMLX_STATUS_TIMEOUT_MS'], '1500'), 1500),
    statusCacheMs: parseInteger(firstEnv(['JARVIS_DASHBOARD_OMLX_64_STATUS_CACHE_MS', 'JARVIS_DASHBOARD_OMLX_STATUS_CACHE_MS'], String(OMLX_STATUS_CACHE_MS)), OMLX_STATUS_CACHE_MS),
    controlTimeoutMs: parseInteger(firstEnv(['JARVIS_DASHBOARD_OMLX_64_CONTROL_TIMEOUT_MS', 'JARVIS_DASHBOARD_OMLX_CONTROL_TIMEOUT_MS'], '30000'), 30000),
    sshHost: firstEnv(['JARVIS_DASHBOARD_OMLX_64_SSH_HOST', 'JARVIS_OMLX_64_SSH_HOST'], ''),
    sshUser: firstEnv(['JARVIS_DASHBOARD_OMLX_64_SSH_USER', 'JARVIS_DASHBOARD_OMLX_SSH_USER', 'JARVIS_OMLX_64_SSH_USER', 'JARVIS_OMLX_SSH_USER'], ''),
    sshKey: firstEnv(['JARVIS_DASHBOARD_OMLX_64_SSH_KEY', 'JARVIS_DASHBOARD_OMLX_SSH_KEY', 'JARVIS_OMLX_64_SSH_KEY', 'JARVIS_OMLX_SSH_KEY'], '~/.ssh/jarvis_dashboard_host'),
    sshPort: parseInteger(firstEnv(['JARVIS_DASHBOARD_OMLX_64_SSH_PORT', 'JARVIS_DASHBOARD_OMLX_SSH_PORT', 'JARVIS_OMLX_64_SSH_PORT', 'JARVIS_OMLX_SSH_PORT'], '22'), 22),
    appPath: firstEnv(['JARVIS_DASHBOARD_OMLX_64_APP_PATH', 'JARVIS_DASHBOARD_OMLX_APP_PATH'], '/Applications/oMLX.app'),
    cliPath: firstEnv(['JARVIS_DASHBOARD_OMLX_64_CLI_PATH', 'JARVIS_DASHBOARD_OMLX_CLI_PATH'], '/Applications/oMLX.app/Contents/MacOS/omlx-cli'),
    basePath: firstEnv(['JARVIS_DASHBOARD_OMLX_64_BASE_PATH', 'JARVIS_DASHBOARD_OMLX_BASE_PATH'], '~/.omlx'),
    serverLog: firstEnv(['JARVIS_DASHBOARD_OMLX_64_SERVER_LOG', 'JARVIS_DASHBOARD_OMLX_SERVER_LOG'], '~/Library/Application Support/oMLX/logs/server.log'),
    localHealthUrl: firstEnv(['JARVIS_DASHBOARD_OMLX_64_LOCAL_HEALTH_URL', 'JARVIS_DASHBOARD_OMLX_LOCAL_HEALTH_URL'], 'http://127.0.0.1:8000/health')
  })]
]);
const OMLX_RUNTIME = new Map(Array.from(OMLX_SERVERS.keys(), (id) => [id, {
  cachedStatus: null,
  cachedStatusAt: 0,
  pendingStatus: null,
  pendingControl: null
}]));
const WEATHER_LATITUDE = Number.parseFloat(process.env.JARVIS_DASHBOARD_WEATHER_LATITUDE || '0');
const WEATHER_LONGITUDE = Number.parseFloat(process.env.JARVIS_DASHBOARD_WEATHER_LONGITUDE || '0');
const WEATHER_LOCATION = process.env.JARVIS_DASHBOARD_WEATHER_LOCATION || 'Configured location';
const WEATHER_STATUS_TIMEOUT_MS = Number.parseInt(process.env.JARVIS_DASHBOARD_WEATHER_STATUS_TIMEOUT_MS || '2500', 10);
const WEATHER_STATUS_CACHE_MS = Number.parseInt(process.env.JARVIS_DASHBOARD_WEATHER_STATUS_CACHE_MS || String(10 * 60_000), 10);
const WEATHER_STATUS_ERROR_CACHE_MS = Number.parseInt(process.env.JARVIS_DASHBOARD_WEATHER_STATUS_ERROR_CACHE_MS || '30000', 10);
const DASHBOARD_CAMERA_CLIENT_ENABLED = /^(1|true|yes|on)$/i.test(process.env.JARVIS_DASHBOARD_CAMERA_CLIENT_ENABLED || 'false');
const CAMERA_COMMAND_TIMEOUT_MS = Number.parseInt(process.env.JARVIS_DASHBOARD_CAMERA_COMMAND_TIMEOUT_MS || '30000', 10);
const CAMERA_RECORD_MAX_DURATION_MS = Number.parseInt(process.env.JARVIS_DASHBOARD_CAMERA_RECORD_MAX_DURATION_MS || '20000', 10);
const CAMERA_UPLOAD_MAX_BYTES = Number.parseInt(process.env.JARVIS_DASHBOARD_CAMERA_UPLOAD_MAX_BYTES || String(64 * 1024 * 1024), 10);
const DASHBOARD_VOICE_MAX_BYTES = Number.parseInt(process.env.JARVIS_DASHBOARD_VOICE_MAX_BYTES || String(12 * 1024 * 1024), 10);
const DASHBOARD_VOICE_TIMEOUT_MS = Number.parseInt(process.env.JARVIS_DASHBOARD_VOICE_TIMEOUT_MS || '45000', 10);
const DASHBOARD_VOICE_ROOM_AUDIO_URL = String(
  process.env.JARVIS_DASHBOARD_VOICE_ROOM_AUDIO_URL
  || process.env.JARVIS_DASHBOARD_RASPBERRY_PI_ROOM_AUDIO_SERVER_URL
  || process.env.JARVIS_ROOM_AUDIO_SERVER_URL
  || 'http://127.0.0.1:8791'
).replace(/\/+$/, '');
const DASHBOARD_VOICE_ROOM_AUDIO_TOKEN = process.env.JARVIS_DASHBOARD_VOICE_ROOM_AUDIO_TOKEN || process.env.JARVIS_ROOM_AUDIO_TOKEN || '';
const PHONE_ADB_SERIAL = process.env.JARVIS_DASHBOARD_PHONE_ADB_SERIAL || '';
const PHONE_ADB_PATH = process.env.JARVIS_DASHBOARD_PHONE_ADB_PATH || '$HOME/.local/share/android-platform-tools/platform-tools/adb';
const PHONE_ADB_SSH_HOST = process.env.JARVIS_DASHBOARD_PHONE_ADB_SSH_HOST || '';
const PHONE_ADB_SSH_USER = process.env.JARVIS_DASHBOARD_PHONE_ADB_SSH_USER || '';
const PHONE_ADB_SSH_KEY = process.env.JARVIS_DASHBOARD_PHONE_ADB_SSH_KEY || '~/.ssh/jarvis_dashboard_host';
const PHONE_ADB_TIMEOUT_MS = Number.parseInt(process.env.JARVIS_DASHBOARD_PHONE_ADB_TIMEOUT_MS || '6000', 10);
const RASPBERRY_PI_SSH_HOST = process.env.JARVIS_DASHBOARD_RASPBERRY_PI_SSH_HOST || process.env.JARVIS_RASPBERRY_PI_HOST || '';
const RASPBERRY_PI_SSH_USER = process.env.JARVIS_DASHBOARD_RASPBERRY_PI_SSH_USER || process.env.JARVIS_RASPBERRY_PI_USER || 'pi';
const RASPBERRY_PI_SSH_KEY = process.env.JARVIS_DASHBOARD_RASPBERRY_PI_SSH_KEY || process.env.JARVIS_RASPBERRY_PI_SSH_KEY || '~/.ssh/jarvis_dashboard_host';
const RASPBERRY_PI_SSH_PORT = Number.parseInt(process.env.JARVIS_DASHBOARD_RASPBERRY_PI_SSH_PORT || process.env.JARVIS_RASPBERRY_PI_SSH_PORT || '22', 10);
const RASPBERRY_PI_TIMEOUT_MS = Number.parseInt(process.env.JARVIS_DASHBOARD_RASPBERRY_PI_TIMEOUT_MS || '6000', 10);
const RASPBERRY_PI_ROOM_AUDIO_PATTERN = process.env.JARVIS_DASHBOARD_RASPBERRY_PI_ROOM_AUDIO_PATTERN || 'jarvis-room-audio-client.py';
const RASPBERRY_PI_ROOM_AUDIO_SERVICE = process.env.JARVIS_DASHBOARD_RASPBERRY_PI_ROOM_AUDIO_SERVICE || process.env.JARVIS_RASPBERRY_PI_ROOM_AUDIO_SERVICE || 'jarvis-room-audio.service';
const RASPBERRY_PI_ROOM_AUDIO_SERVER_URL = String(
  process.env.JARVIS_DASHBOARD_RASPBERRY_PI_ROOM_AUDIO_SERVER_URL
  || process.env.JARVIS_ROOM_AUDIO_SERVER_URL
  || ''
).replace(/\/+$/, '');
const RASPBERRY_PI_POWERCONF_MAC = process.env.JARVIS_DASHBOARD_RASPBERRY_PI_POWERCONF_MAC || process.env.JARVIS_ROOM_AUDIO_BLUETOOTH_MAC || '';
const SMART_PLUG_ROOT = process.env.JARVIS_DASHBOARD_SMART_PLUG_ROOT || path.join(operationRoot, 'smart-plug');
const SMART_PLUG_CONFIG = process.env.JARVIS_DASHBOARD_SMART_PLUG_CONFIG || path.join(SMART_PLUG_ROOT, 'plugs.json');
const SMART_PLUG_CLI = process.env.JARVIS_DASHBOARD_SMART_PLUG_CLI || path.join(SMART_PLUG_ROOT, '.venv', 'bin', 'plugctl');
const SMART_PLUG_TIMEOUT_MS = Number.parseInt(process.env.JARVIS_DASHBOARD_SMART_PLUG_TIMEOUT_MS || '8000', 10);
const SMART_PLUG_STATUS_CACHE_MS = Number.parseInt(process.env.JARVIS_DASHBOARD_SMART_PLUG_STATUS_CACHE_MS || '1500', 10);

function normalizeOpenAiBaseUrl(rawBaseUrl) {
  const baseUrl = String(rawBaseUrl || '').trim().replace(/\/+$/, '');
  if (!baseUrl) return 'http://127.0.0.1:8000/v1';
  return /\/v1$/i.test(baseUrl) ? baseUrl : `${baseUrl}/v1`;
}

function openAiBaseUrlToRoot(rawBaseUrl) {
  return String(rawBaseUrl || '').trim().replace(/\/+$/, '').replace(/\/v1$/i, '');
}

const contentTypes = new Map([
  ['.html', 'text/html; charset=utf-8'],
  ['.css', 'text/css; charset=utf-8'],
  ['.js', 'text/javascript; charset=utf-8'],
  ['.mjs', 'text/javascript; charset=utf-8'],
  ['.json', 'application/json; charset=utf-8'],
  ['.webmanifest', 'application/manifest+json; charset=utf-8'],
  ['.svg', 'image/svg+xml'],
  ['.png', 'image/png'],
  ['.jpg', 'image/jpeg'],
  ['.jpeg', 'image/jpeg'],
  ['.ico', 'image/x-icon'],
  ['.webp', 'image/webp'],
  ['.wasm', 'application/wasm'],
  ['.onnx', 'application/octet-stream'],
  ['.mp4', 'video/mp4'],
  ['.mov', 'video/quicktime'],
  ['.m4v', 'video/x-m4v'],
  ['.webm', 'video/webm'],
  ['.mp3', 'audio/mpeg'],
  ['.m4a', 'audio/mp4'],
  ['.wav', 'audio/wav'],
  ['.aiff', 'audio/aiff'],
  ['.txt', 'text/plain; charset=utf-8']
]);

function getLanAddresses() {
  const addresses = [];
  const interfaces = os.networkInterfaces();

  for (const [name, entries = []] of Object.entries(interfaces)) {
    for (const entry of entries) {
      if (entry.family === 'IPv4' && !entry.internal) {
        addresses.push({ interface: name, address: entry.address });
      }
    }
  }

  return addresses.sort((a, b) => a.interface.localeCompare(b.interface));
}

function dashboardHeaders(extra = {}) {
  return {
    'cross-origin-opener-policy': 'same-origin',
    'cross-origin-embedder-policy': 'require-corp',
    'cross-origin-resource-policy': 'same-origin',
    ...extra
  };
}

function json(res, statusCode, body) {
  const payload = JSON.stringify(body, null, 2);
  res.writeHead(statusCode, dashboardHeaders({
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store'
  }));
  res.end(payload);
}

const projectMetadata = new Map([
  ['operation-jarvis', {
    icon: '◈',
    status: 'Live system',
    tone: 'cyan',
    tags: ['Discord', 'DashboardCam', 'Cast', 'Voice', 'Dashboard'],
    mission: 'Real-world JARVIS loop for dashboard telemetry, camera controls, speech, and room control.'
  }],
  ['workout-tracker', {
    icon: '◆',
    status: 'Active',
    tone: 'green',
    tags: ['Discord UI', 'Fitness', 'Logs'],
    mission: 'Low-friction workout logging with buttons, embeds, and local history.'
  }],
  ['smart-glasses', {
    icon: '◐',
    status: 'Research',
    tone: 'violet',
    tags: ['Wearables', 'Canada', 'AI glasses'],
    mission: 'Canada-first smart glasses buying and developer-platform research.'
  }],
  ['job-search', {
    icon: '▣',
    status: 'Tracking',
    tone: 'amber',
    tags: ['Jobs', 'AI/ML', 'Applications'],
    mission: 'Opportunity tracker and application research archive.'
  }],
  ['apple_refurb_scraper', {
    icon: '⬡',
    status: 'Automation',
    tone: 'silver',
    tags: ['Apple', 'Scraper', 'Inventory'],
    mission: 'Cron-friendly refurbished workstation inventory watcher.'
  }],
  ['projects-drive-backup', {
    icon: '▰',
    status: 'Scheduled',
    tone: 'indigo',
    tags: ['Backup', 'Google Drive', 'Cron'],
    mission: 'Nightly Google Drive archive of every JARVIS project.'
  }],
  ['quotas', {
    icon: '◍',
    status: 'Utility',
    tone: 'orange',
    tags: ['Pi', 'Codex', 'Copilot'],
    mission: 'Provider quota and model availability checker for Pi/JARVIS.'
  }]
]);

function titleFromName(name) {
  return name
    .replace(/[-_]+/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function summarizeReadme(markdown) {
  const lines = markdown.split(/\r?\n/);
  const title = lines.find((line) => line.startsWith('# '))?.replace(/^#\s+/, '').trim();
  const paragraph = [];

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#') || trimmed.startsWith('```')) {
      if (paragraph.length > 0) break;
      continue;
    }
    if (trimmed.startsWith('|') || trimmed.startsWith('- ') || trimmed.startsWith('* ')) continue;
    paragraph.push(trimmed);
    if (paragraph.join(' ').length > 180) break;
  }

  return {
    title,
    summary: paragraph.join(' ').replace(/\s+/g, ' ').slice(0, 240)
  };
}

async function findReadme(dir) {
  for (const candidate of ['README.md', 'readme.md', 'Readme.md']) {
    const filePath = path.join(dir, candidate);
    try {
      return { name: candidate, text: await readFile(filePath, 'utf8') };
    } catch {
      // try next candidate
    }
  }
  return null;
}

async function collectProjectStats(dir) {
  const ignored = new Set(['.git', '.venv', 'node_modules', '__pycache__', '.DS_Store']);
  const stats = { files: 0, dirs: 0, markdown: 0, latestModifiedMs: 0 };

  async function walk(currentDir, depth = 0) {
    if (depth > 3) return;
    let entries = [];
    try {
      entries = await readdir(currentDir, { withFileTypes: true });
    } catch {
      return;
    }

    for (const entry of entries) {
      if (ignored.has(entry.name)) continue;
      const entryPath = path.join(currentDir, entry.name);
      let entryStat;
      try {
        entryStat = await stat(entryPath);
      } catch {
        continue;
      }

      stats.latestModifiedMs = Math.max(stats.latestModifiedMs, entryStat.mtimeMs);
      if (entry.isDirectory()) {
        stats.dirs += 1;
        await walk(entryPath, depth + 1);
      } else if (entry.isFile()) {
        stats.files += 1;
        if (entry.name.toLowerCase().endsWith('.md')) stats.markdown += 1;
      }
    }
  }

  await walk(dir);
  return stats;
}

async function getProjects() {
  const entries = await readdir(workspaceRoot, { withFileTypes: true });
  const projects = [];

  for (const entry of entries) {
    if (!entry.isDirectory() || entry.name.startsWith('.')) continue;

    const dir = path.join(workspaceRoot, entry.name);
    const readme = await findReadme(dir);
    const readmeInfo = readme ? summarizeReadme(readme.text) : {};
    const stats = await collectProjectStats(dir);
    const meta = projectMetadata.get(entry.name) || {};

    projects.push({
      name: entry.name,
      title: readmeInfo.title || titleFromName(entry.name),
      summary: meta.mission || readmeInfo.summary || 'Project workspace in the JARVIS system.',
      readmeSummary: readmeInfo.summary || '',
      icon: meta.icon || '✧',
      status: meta.status || 'Workspace',
      tone: meta.tone || 'cyan',
      tags: meta.tags || [],
      path: `projects/${entry.name}`,
      readme: readme?.name || null,
      stats: {
        files: stats.files,
        dirs: stats.dirs,
        markdown: stats.markdown,
        latestModified: stats.latestModifiedMs ? new Date(stats.latestModifiedMs).toISOString() : null
      }
    });
  }

  return projects.sort((a, b) => {
    if (a.name === 'operation-jarvis') return -1;
    if (b.name === 'operation-jarvis') return 1;
    return (b.stats.latestModified || '').localeCompare(a.stats.latestModified || '');
  });
}


const jarvisDevices = new Set(['tv', 'speakers']);
const jarvisActionAllowlist = new Set([
  'status',
  'cast-status',
  'speak',
  'cast-stop',
  'cast-volume',
  'look',
  'analyze-view'
]);
const recentJarvisEvents = [];
const latestArtifactLimit = 60;

function parseJsonMaybe(text) {
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    const start = text.indexOf('{');
    const end = text.lastIndexOf('}');
    if (start >= 0 && end > start) {
      try {
        return JSON.parse(text.slice(start, end + 1));
      } catch {
        return null;
      }
    }
    return null;
  }
}

function safeDevice(value, fallback = 'speakers') {
  return jarvisDevices.has(value) ? value : fallback;
}

function clampText(value, maxLength) {
  return String(value || '').replace(/\s+/g, ' ').trim().slice(0, maxLength);
}

function clientPresentedWriteToken(req) {
  if (!DASHBOARD_WRITE_TOKEN) return false;
  const headerToken = req.headers['x-jarvis-token'];
  const auth = req.headers.authorization || '';
  const bearer = auth.startsWith('Bearer ') ? auth.slice(7) : '';
  return headerToken === DASHBOARD_WRITE_TOKEN || bearer === DASHBOARD_WRITE_TOKEN;
}

function clientHasWriteToken(req) {
  if (!DASHBOARD_WRITE_TOKEN) return true;
  return clientPresentedWriteToken(req);
}

function clientIsLoopback(req) {
  const raw = req.socket?.remoteAddress || '';
  const address = raw.replace(/^::ffff:/, '');
  return address === '127.0.0.1' || address === '::1' || address === 'localhost';
}

function clientCanUseDebugEndpoint(req) {
  return clientIsLoopback(req) || ENABLE_DEBUG_ENDPOINTS || clientPresentedWriteToken(req);
}

function readRequestBody(req, maxBytes = 64 * 1024) {
  return new Promise((resolve, reject) => {
    let body = '';
    let settled = false;
    req.setEncoding('utf8');
    req.on('data', (chunk) => {
      if (settled) return;
      body += chunk;
      if (Buffer.byteLength(body) > maxBytes) {
        settled = true;
        const error = new Error('Request body too large');
        error.statusCode = 413;
        reject(error);
        req.destroy();
      }
    });
    req.on('end', () => {
      if (!settled) resolve(body);
    });
    req.on('error', (error) => {
      if (!settled) reject(error);
    });
  });
}

function readBufferBody(req, maxBytes = 1024 * 1024) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let total = 0;
    let settled = false;
    req.on('data', (chunk) => {
      if (settled) return;
      total += chunk.length;
      if (total > maxBytes) {
        settled = true;
        const error = new Error('Upload too large');
        error.statusCode = 413;
        reject(error);
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on('end', () => {
      if (!settled) resolve(Buffer.concat(chunks));
    });
    req.on('error', (error) => {
      if (!settled) reject(error);
    });
  });
}

async function readJsonBody(req, maxBytes = 64 * 1024) {
  const body = await readRequestBody(req, maxBytes);
  if (!body.trim()) return {};
  return JSON.parse(body);
}

function storeJarvisEvent(event) {
  recentJarvisEvents.unshift(event);
  recentJarvisEvents.splice(100);
}

function broadcastJarvisEvent(event) {
  storeJarvisEvent(event);
  broadcastWebSocket({ type: 'jarvis-event', ...event });
  broadcastEvent('jarvis-event', event);
  if (event.eventType !== 'action.start') {
    broadcastWebSocket({
      type: 'pulse',
      ok: true,
      reason: `jarvis-${event.eventType || 'event'}`,
      tone: event.ok === false ? 'orange' : 'cyan',
      message: event.summary || event.action || 'Operation JARVIS event',
      at: event.at,
      clients: wsClients.size
    });
  }
}

async function runJarvisCli(commandArgs, { timeoutMs = JARVIS_ACTION_TIMEOUT_MS, emitEvents = true } = {}) {
  const args = ['--json', ...commandArgs];
  const env = {
    ...process.env,
    JARVIS_DASHBOARD_URL: process.env.JARVIS_DASHBOARD_URL || `http://127.0.0.1:${PORT}`,
    JARVIS_DASHBOARD_EMIT_EVENTS: emitEvents ? '1' : '0'
  };
  if (DASHBOARD_WRITE_TOKEN && !env.JARVIS_DASHBOARD_TOKEN) {
    env.JARVIS_DASHBOARD_TOKEN = DASHBOARD_WRITE_TOKEN;
  }

  try {
    const { stdout, stderr } = await execFileAsync(jarvisCli, args, {
      cwd: operationRoot,
      env,
      timeout: timeoutMs,
      maxBuffer: 5 * 1024 * 1024
    });
    const payload = parseJsonMaybe(stdout) || { ok: true, stdout };
    if (stderr?.trim()) payload.stderr = stderr.trim();
    payload.command = [jarvisCli, ...args];
    return payload;
  } catch (error) {
    const stdout = error.stdout || '';
    const stderr = error.stderr || '';
    const payload = parseJsonMaybe(stdout) || parseJsonMaybe(stderr) || {};
    const message = payload.error || stderr.trim() || stdout.trim() || error.message;
    const wrapped = new Error(message);
    wrapped.statusCode = error.killed ? 504 : 500;
    wrapped.payload = {
      ok: false,
      action: commandArgs[0],
      error: message,
      stdout: stdout.trim(),
      stderr: stderr.trim(),
      command: [jarvisCli, ...args]
    };
    throw wrapped;
  }
}

function buildJarvisActionArgs(action, inputArgs = {}) {
  if (!jarvisActionAllowlist.has(action)) {
    throw new Error(`Action is not allowlisted: ${action}`);
  }

  if (action === 'status') return ['status', '--no-cast'];

  if (action === 'cast-status') {
    return ['cast-status', '--device', safeDevice(inputArgs.device, 'tv'), '--cast-timeout', '10'];
  }

  if (action === 'speak') {
    const text = clampText(inputArgs.text || 'JARVIS online.', 220);
    if (!text) throw new Error('Text is required for speak.');
    return ['speak', '--device', safeDevice(inputArgs.device), '--max-chars', '220', '--post-cast-serve-seconds', '2', text];
  }

  if (action === 'cast-stop') {
    return ['cast-stop', '--device', safeDevice(inputArgs.device, 'tv'), '--quit-app', '--cast-timeout', '20'];
  }

  if (action === 'cast-volume') {
    const level = Number(inputArgs.level);
    if (!Number.isFinite(level) || level < 0 || level > 100) {
      throw new Error('Volume level must be between 0 and 100.');
    }
    return ['cast-volume', String(Math.round(level)), '--device', safeDevice(inputArgs.device), '--cast-timeout', '20'];
  }

  if (action === 'look') {
    return ['look', '--timeout', '8'];
  }

  if (action === 'analyze-view') {
    const prompt = clampText(inputArgs.prompt || 'Describe what is visible using only visible evidence. Be concise.', 260);
    return ['analyze-view', '--duration', '3', '--interval', '999', '--prompt', prompt];
  }


  throw new Error(`Unsupported action: ${action}`);
}

async function readJarvisLocalStatusUncached() {
  const castScript = path.join(operationRoot, 'scripts', 'tv.py');
  const local = {
    operationRoot,
    jarvisCli,
    exists: {
      operationRoot: await pathExists(operationRoot),
      jarvisCli: await pathExists(jarvisCli),
      mediaDir: await pathExists(operationMediaDir),
      dataDir: await pathExists(operationDataDir),
      castScript: await pathExists(castScript)
    },
    commandsEnabled: ENABLE_DASHBOARD_COMMANDS && Boolean(DASHBOARD_WRITE_TOKEN),
    commandsRequested: ENABLE_DASHBOARD_COMMANDS,
    writeTokenConfigured: Boolean(DASHBOARD_WRITE_TOKEN),
    debugEndpointsEnabled: ENABLE_DEBUG_ENDPOINTS,
    recentEvents: recentJarvisEvents.slice(0, 8)
  };
  const cameraStatus = getDashboardCameraStatus();
  const ok = Boolean(local.exists.operationRoot && local.exists.jarvisCli && local.exists.mediaDir && local.exists.dataDir);
  const status = {
    ok,
    action: 'status',
    operationRoot,
    dashboardUrl: `http://127.0.0.1:${PORT}`,
    castScript,
    checks: {
      operationRootExists: local.exists.operationRoot,
      dashboardCameraReady: Boolean(cameraStatus.ok),
      castScriptExists: local.exists.castScript
    },
    camera: cameraStatus,
    summary: ok
      ? `Operation JARVIS local files are installed. Dashboard camera status=${cameraStatus.status}; Cast status was skipped.`
      : 'Operation JARVIS local file check is incomplete.'
  };

  return ok
    ? { ok: true, name: 'operation-jarvis', local, status }
    : { ok: false, name: 'operation-jarvis', local, status, error: status.summary };
}

let cachedJarvisLocalStatus = null;
let cachedJarvisLocalStatusAt = 0;
let pendingJarvisLocalStatus = null;

function fallbackJarvisLocalStatus(message, stalePayload = null) {
  if (stalePayload) {
    return {
      ...stalePayload,
      stale: true,
      local: {
        ...(stalePayload.local || {}),
        statusStale: true,
        statusStaleReason: message
      }
    };
  }

  return {
    ok: false,
    name: 'operation-jarvis',
    stale: true,
    local: {
      operationRoot,
      jarvisCli,
      exists: {
        operationRoot: true,
        jarvisCli: true,
        mediaDir: true,
        dataDir: true
      },
      commandsEnabled: ENABLE_DASHBOARD_COMMANDS && Boolean(DASHBOARD_WRITE_TOKEN),
      commandsRequested: ENABLE_DASHBOARD_COMMANDS,
      writeTokenConfigured: Boolean(DASHBOARD_WRITE_TOKEN),
      debugEndpointsEnabled: ENABLE_DEBUG_ENDPOINTS,
      statusStale: true,
      statusStaleReason: message,
      recentEvents: recentJarvisEvents.slice(0, 8)
    },
    error: message,
    status: {
      ok: false,
      action: 'status',
      summary: message,
      camera: getDashboardCameraStatus(),
      checks: {
        operationRootExists: true,
        jarvisCliExists: true,
        dashboardCameraReady: wsClients.size > 0
      }
    }
  };
}

async function getJarvisLocalStatus({ cacheMs = JARVIS_LOCAL_STATUS_CACHE_MS, timeoutMs = 15_000, allowStale = true } = {}) {
  const now = Date.now();
  const safeCacheMs = Math.max(0, Number(cacheMs) || 0);
  if (cachedJarvisLocalStatus && safeCacheMs > 0 && now - cachedJarvisLocalStatusAt < safeCacheMs) {
    return cachedJarvisLocalStatus;
  }

  if (!pendingJarvisLocalStatus) {
    pendingJarvisLocalStatus = readJarvisLocalStatusUncached()
      .then((payload) => {
        cachedJarvisLocalStatus = payload;
        cachedJarvisLocalStatusAt = Date.now();
        return payload;
      })
      .finally(() => {
        pendingJarvisLocalStatus = null;
      });
  }

  const safeTimeoutMs = Math.max(0, Number(timeoutMs) || 0);
  if (safeTimeoutMs <= 0) return pendingJarvisLocalStatus;

  let timer = null;
  const timeout = new Promise((resolve) => {
    timer = setTimeout(() => resolve(null), safeTimeoutMs);
    timer.unref?.();
  });
  const result = await Promise.race([pendingJarvisLocalStatus, timeout]);
  if (timer) clearTimeout(timer);
  if (result) return result;

  const message = `Operation JARVIS local status is still pending after ${(safeTimeoutMs / 1000).toFixed(1)}s.`;
  return allowStale ? fallbackJarvisLocalStatus(message, cachedJarvisLocalStatus) : fallbackJarvisLocalStatus(message);
}

async function handleJarvisStatus(_req, res) {
  const payload = await getJarvisLocalStatus({ timeoutMs: 15_000, cacheMs: 1_000, allowStale: true });
  json(res, payload.ok ? 200 : 500, payload);
}

function ageMs(iso) {
  if (!iso) return Number.POSITIVE_INFINITY;
  const parsed = Date.parse(iso);
  return Number.isFinite(parsed) ? Date.now() - parsed : Number.POSITIVE_INFINITY;
}

function pidIsAlive(pid) {
  const numericPid = Number(pid);
  if (!Number.isInteger(numericPid) || numericPid <= 0) return false;
  try {
    process.kill(numericPid, 0);
    return true;
  } catch {
    return false;
  }
}

function normalizePiSessions(payload) {
  return Object.values(payload.sessions || {})
    .filter((session) => session && typeof session === 'object')
    .filter((session) => session.active === true && session.command === 'prompt' && pidIsAlive(session.pid))
    .map((session) => ({
      id: session.id || '',
      kind: 'discord-active-generation',
      source: 'discord-status-file',
      pid: session.pid || null,
      model: session.model || '',
      channel: session.channelName || session.channelId || '',
      startedAt: session.startedAt || null,
      updatedAt: session.updatedAt || null
    }))
    .sort((a, b) => String(a.id).localeCompare(String(b.id)));
}

function parsePsRows(stdout) {
  return stdout
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const match = line.match(/^(\d+)\s+(\d+)\s+(\S+)\s*(.*)$/);
      if (!match) return null;
      return {
        pid: Number(match[1]),
        ppid: Number(match[2]),
        comm: match[3] || '',
        command: match[4] || ''
      };
    })
    .filter(Boolean);
}

function isPiProcess(row) {
  const commBase = path.basename(row.comm || '');
  const command = String(row.command || '').trim();
  return commBase === 'pi' || command === 'pi' || command.startsWith('pi ') || /\/pi(\s|$)/.test(command);
}

function isDiscordBotProcess(row) {
  const command = String(row.command || '').trim();
  if (!command) return false;
  if (command.includes(DISCORD_BOT_SCRIPT)) return true;
  return /(^|\s|\/)discord_bot\.py(\s|$)/.test(command) && !/discord_voice_bot\.py(\s|$)/.test(command);
}

function parsePidFileValue(raw) {
  const pid = Number(String(raw || '').trim());
  return Number.isInteger(pid) && pid > 0 ? pid : null;
}

let cachedDiscordBotStatus = null;
let cachedDiscordBotStatusAt = 0;
let pendingDiscordBotStatus = null;

async function readDiscordBotStatusUncached() {
  const checkedAt = new Date().toISOString();
  let pidFilePid = null;

  try {
    pidFilePid = parsePidFileValue(await readFile(DISCORD_BOT_PID_FILE, 'utf8'));
  } catch {
    // Missing or stale PID files are expected when the bot is offline.
  }

  try {
    const { stdout } = await execFileAsync('/bin/ps', ['-axo', 'pid=,ppid=,comm=,command='], {
      timeout: Math.max(300, Number(DISCORD_BOT_STATUS_TIMEOUT_MS) || 1200),
      maxBuffer: 2 * 1024 * 1024
    });
    const rows = parsePsRows(stdout).filter(isDiscordBotProcess);
    const pidFileMatches = pidFilePid ? rows.some((row) => row.pid === pidFilePid) : false;
    const primary = (pidFileMatches ? rows.find((row) => row.pid === pidFilePid) : rows[0]) || null;

    return {
      ok: true,
      running: rows.length > 0,
      status: rows.length > 0 ? 'online' : 'offline',
      label: rows.length > 0 ? 'ONLINE' : 'OFFLINE',
      pid: primary?.pid || null,
      pids: rows.map((row) => row.pid),
      processCount: rows.length,
      command: primary?.command || '',
      script: DISCORD_BOT_SCRIPT,
      pidFile: DISCORD_BOT_PID_FILE,
      pidFilePid,
      pidFileMatches,
      checkedAt,
      summary: rows.length > 0
        ? `discord_bot.py is running${primary?.pid ? ` as PID ${primary.pid}` : ''}.`
        : 'discord_bot.py is not running.'
    };
  } catch (error) {
    const fallbackRunning = pidFilePid ? pidIsAlive(pidFilePid) : false;
    return {
      ok: false,
      running: fallbackRunning,
      status: fallbackRunning ? 'unknown' : 'offline',
      label: fallbackRunning ? 'UNKNOWN' : 'OFFLINE',
      pid: fallbackRunning ? pidFilePid : null,
      pids: fallbackRunning ? [pidFilePid] : [],
      processCount: fallbackRunning ? 1 : 0,
      command: '',
      script: DISCORD_BOT_SCRIPT,
      pidFile: DISCORD_BOT_PID_FILE,
      pidFilePid,
      pidFileMatches: false,
      checkedAt,
      error: error?.message || String(error),
      summary: fallbackRunning
        ? `PID ${pidFilePid} is alive, but discord_bot.py status could not be verified.`
        : 'discord_bot.py status could not be verified.'
    };
  }
}

async function readDiscordBotStatus() {
  const now = Date.now();
  const cacheMs = Math.max(0, Number(DISCORD_BOT_STATUS_CACHE_MS) || 0);
  if (cachedDiscordBotStatus && cacheMs > 0 && now - cachedDiscordBotStatusAt < cacheMs) return cachedDiscordBotStatus;
  if (!pendingDiscordBotStatus) {
    pendingDiscordBotStatus = readDiscordBotStatusUncached()
      .then((payload) => {
        cachedDiscordBotStatus = payload;
        cachedDiscordBotStatusAt = Date.now();
        return payload;
      })
      .finally(() => {
        pendingDiscordBotStatus = null;
      });
  }
  return pendingDiscordBotStatus;
}

function collectAncestorPids(row, rowsByPid) {
  const ancestors = [];
  const seen = new Set([row.pid]);
  let current = rowsByPid.get(row.ppid);
  for (let depth = 0; depth < 24 && current && !seen.has(current.pid); depth += 1) {
    ancestors.push(current.pid);
    seen.add(current.pid);
    current = rowsByPid.get(current.ppid);
  }
  return ancestors;
}

function processHasAncestor(row, rowsByPid, predicate) {
  if (predicate(row)) return true;
  return collectAncestorPids(row, rowsByPid).some((pid) => {
    const ancestor = rowsByPid.get(pid);
    return ancestor ? predicate(ancestor) : false;
  });
}

async function readPiProcessSessions(activeDiscordSessions = []) {
  try {
    const { stdout } = await execFileAsync('/bin/ps', ['-axo', 'pid=,ppid=,comm=,command='], {
      timeout: Math.max(300, Number(PI_PROCESS_STATUS_TIMEOUT_MS) || 1200),
      maxBuffer: 2 * 1024 * 1024
    });
    const rows = parsePsRows(stdout);
    const rowsByPid = new Map(rows.map((row) => [row.pid, row]));
    const statusPids = new Set(activeDiscordSessions.map((session) => Number(session.pid)).filter(Number.isInteger));

    const processSessions = rows
      .filter((row) => row.pid !== process.pid && isPiProcess(row))
      .filter((row) => !statusPids.has(row.pid))
      .map((row) => {
        const ancestorPids = collectAncestorPids(row, rowsByPid);
        const discordManaged = processHasAncestor(row, rowsByPid, (ancestor) => /(^|\/)discord_bot\.py(\s|$)/.test(ancestor.command));
        return {
          id: `process:${row.pid}`,
          kind: discordManaged ? 'discord-pi-process' : 'local-pi-process',
          source: discordManaged ? 'discord-process-tree' : 'process-table',
          pid: row.pid,
          ppid: row.ppid,
          ancestorPids,
          model: '',
          channel: '',
          startedAt: null,
          updatedAt: null,
          command: row.command || row.comm || 'pi',
          discordManaged
        };
      })
      .sort((a, b) => a.pid - b.pid);

    return { ok: true, sessions: processSessions };
  } catch (error) {
    return { ok: false, sessions: [], error: error.message };
  }
}

function normalizeLocalPiSessionStatus(payload, filePath, now = Date.now()) {
  if (!payload || typeof payload !== 'object') return null;
  const pid = Number(payload.pid);
  if (!Number.isInteger(pid) || pid <= 0 || !pidIsAlive(pid)) return null;
  const updatedAt = typeof payload.updatedAt === 'string' ? payload.updatedAt : null;
  const statusAgeMs = ageMs(updatedAt);
  const maxAgeMs = Number.isFinite(LOCAL_PI_STATUS_MAX_AGE_MS) && LOCAL_PI_STATUS_MAX_AGE_MS > 0
    ? LOCAL_PI_STATUS_MAX_AGE_MS
    : 15_000;
  if (!Number.isFinite(statusAgeMs) || statusAgeMs < -5_000 || statusAgeMs > maxAgeMs) return null;
  return {
    id: String(payload.id || `local:${pid}`),
    kind: payload.active === true ? 'local-active-pi-extension' : 'local-idle-pi-extension',
    source: 'local-pi-session-status',
    pid,
    model: '',
    channel: '',
    startedAt: null,
    updatedAt,
    statusAgeMs: Math.round(statusAgeMs),
    path: typeof payload.sessionFile === 'string' ? payload.sessionFile : '',
    cwd: typeof payload.cwd === 'string' ? payload.cwd : '',
    statusFile: filePath,
    active: payload.active === true
  };
}

async function readLocalPiSessionStatuses() {
  const statuses = [];
  const now = Date.now();
  let entries = [];
  try {
    entries = await readdir(PI_LOCAL_SESSION_STATUS_DIR, { withFileTypes: true });
  } catch (error) {
    if (error?.code === 'ENOENT') {
      return { ok: true, sessions: [], source: PI_LOCAL_SESSION_STATUS_DIR };
    }
    return { ok: false, sessions: [], source: PI_LOCAL_SESSION_STATUS_DIR, error: error.message };
  }

  for (const entry of entries) {
    if (!entry.isFile() || !entry.name.endsWith('.json')) continue;
    const entryPath = path.join(PI_LOCAL_SESSION_STATUS_DIR, entry.name);
    try {
      const payload = JSON.parse(await readFile(entryPath, 'utf8'));
      const normalized = normalizeLocalPiSessionStatus(payload, entryPath, now);
      if (normalized) statuses.push(normalized);
    } catch {
      // Ignore half-written or invalid best-effort telemetry files.
    }
  }

  statuses.sort((a, b) => Date.parse(b.updatedAt || 0) - Date.parse(a.updatedAt || 0));
  return { ok: true, sessions: statuses, source: PI_LOCAL_SESSION_STATUS_DIR };
}

async function readRecentPiSessionFiles() {
  const recent = [];
  const now = Date.now();
  const maxAgeMs = Number.isFinite(LOCAL_PI_ACTIVE_WINDOW_MS) && LOCAL_PI_ACTIVE_WINDOW_MS > 0
    ? LOCAL_PI_ACTIVE_WINDOW_MS
    : 5_000;

  async function walk(dir, depth = 0) {
    if (depth > 4) return;
    let entries = [];
    try {
      entries = await readdir(dir, { withFileTypes: true });
    } catch {
      return;
    }

    for (const entry of entries) {
      if (entry.name.startsWith('.')) continue;
      const entryPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        await walk(entryPath, depth + 1);
        continue;
      }
      if (!entry.isFile() || !entry.name.endsWith('.jsonl')) continue;

      try {
        const entryStat = await stat(entryPath);
        const age = now - entryStat.mtimeMs;
        if (age >= 0 && age <= maxAgeMs) {
          recent.push({
            id: `session-file:${Buffer.from(entryPath).toString('base64url')}`,
            kind: 'local-active-session-file',
            source: 'recent-session-file',
            pid: null,
            model: '',
            channel: '',
            startedAt: null,
            updatedAt: entryStat.mtime.toISOString(),
            path: entryPath,
            ageMs: Math.round(age),
            activeWindowMs: maxAgeMs
          });
        }
      } catch {
        // Ignore files that vanish while scanning.
      }
    }
  }

  await walk(PI_AGENT_SESSIONS_DIR);
  recent.sort((a, b) => Date.parse(b.updatedAt || 0) - Date.parse(a.updatedAt || 0));
  return { ok: true, sessions: recent, source: PI_AGENT_SESSIONS_DIR, activeWindowMs: maxAgeMs };
}

const NON_BILLABLE_PI_COST_PROVIDERS = new Set([
  'github-copilot',
  'local',
  'llama.cpp',
  'llamacpp',
  'lmstudio',
  'mlx',
  'ollama',
  'omlx',
  'omlx-voice'
]);
const NON_BILLABLE_PI_COST_MODEL_HINTS = ['mlx-community/', 'gguf'];

function numericCostValue(value) {
  const number = Number(value || 0);
  return Number.isFinite(number) ? number : 0;
}

function integerTokenValue(value) {
  const number = Number(value || 0);
  return Number.isFinite(number) ? Math.trunc(number) : 0;
}

function usageCostTotal(cost = {}) {
  if (!cost || typeof cost !== 'object') return 0;
  if (Object.hasOwn(cost, 'total')) return numericCostValue(cost.total);
  return ['input', 'output', 'cacheRead', 'cacheWrite']
    .reduce((sum, key) => sum + numericCostValue(cost[key]), 0);
}

function isNonBillablePiCost(provider = '', model = '') {
  const providerKey = String(provider || '').toLowerCase();
  const modelKey = String(model || '').toLowerCase();
  if (NON_BILLABLE_PI_COST_PROVIDERS.has(providerKey)) return true;
  return NON_BILLABLE_PI_COST_MODEL_HINTS.some((hint) => modelKey.includes(hint));
}

function emptyPiCostTotals() {
  return {
    inputTokens: 0,
    outputTokens: 0,
    cacheReadTokens: 0,
    cacheWriteTokens: 0,
    totalTokens: 0,
    rawLoggedCostUsd: 0,
    billableCostUsd: 0,
    ignoredNonBillableCostUsd: 0,
    usageRecords: 0,
    nonBillableUsageRecords: 0
  };
}

function addPiCostTotals(target, source) {
  target.inputTokens += source.inputTokens || 0;
  target.outputTokens += source.outputTokens || 0;
  target.cacheReadTokens += source.cacheReadTokens || 0;
  target.cacheWriteTokens += source.cacheWriteTokens || 0;
  target.totalTokens += source.totalTokens || 0;
  target.rawLoggedCostUsd += source.rawLoggedCostUsd || 0;
  target.billableCostUsd += source.billableCostUsd || 0;
  target.ignoredNonBillableCostUsd += source.ignoredNonBillableCostUsd || 0;
  target.usageRecords += source.usageRecords || 0;
  target.nonBillableUsageRecords += source.nonBillableUsageRecords || 0;
}

function piCostTotalsFromUsage(usage = {}, nonBillable = false) {
  const rawLoggedCostUsd = usageCostTotal(usage.cost);
  return {
    inputTokens: integerTokenValue(usage.input),
    outputTokens: integerTokenValue(usage.output),
    cacheReadTokens: integerTokenValue(usage.cacheRead),
    cacheWriteTokens: integerTokenValue(usage.cacheWrite),
    totalTokens: integerTokenValue(usage.totalTokens || usage.total),
    rawLoggedCostUsd,
    billableCostUsd: nonBillable ? 0 : rawLoggedCostUsd,
    ignoredNonBillableCostUsd: nonBillable ? rawLoggedCostUsd : 0,
    usageRecords: 1,
    nonBillableUsageRecords: nonBillable ? 1 : 0
  };
}

async function collectPiSessionCostFiles(rootDir) {
  const files = [];

  async function walk(dir, depth = 0) {
    if (depth > 7) return;
    let entries = [];
    try {
      entries = await readdir(dir, { withFileTypes: true });
    } catch {
      return;
    }

    for (const entry of entries) {
      if (entry.name.startsWith('.')) continue;
      const entryPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        await walk(entryPath, depth + 1);
      } else if (entry.isFile() && entry.name.endsWith('.jsonl')) {
        try {
          const fileStat = await stat(entryPath);
          files.push({ path: entryPath, size: fileStat.size, mtimeMs: fileStat.mtimeMs });
        } catch {
          // Ignore files that rotate during the scan.
        }
      }
    }
  }

  await walk(rootDir);
  files.sort((a, b) => b.mtimeMs - a.mtimeMs || a.path.localeCompare(b.path));

  const maxFiles = Math.max(1, Number(PI_SESSION_COST_MAX_FILES) || 120);
  const maxBytes = Math.max(512 * 1024, Number(PI_SESSION_COST_SCAN_MAX_BYTES) || (32 * 1024 * 1024));
  const selected = [];
  let selectedBytes = 0;
  for (const file of files) {
    if (selected.length >= maxFiles) break;
    if (selected.length > 0 && selectedBytes + file.size > maxBytes) continue;
    selected.push(file.path);
    selectedBytes += file.size;
  }
  return selected;
}

async function readPiSessionCostFile(filePath) {
  const session = {
    path: filePath,
    sessionId: '',
    cwd: '',
    startedAt: '',
    endedAt: '',
    totals: emptyPiCostTotals(),
    byProviderModel: new Map(),
    parseErrors: 0
  };
  let currentProvider = '';
  let currentModel = '';
  const stream = createReadStream(filePath, { encoding: 'utf8' });
  const lines = createInterface({ input: stream, crlfDelay: Infinity });

  try {
    for await (const line of lines) {
      if (!line.trim()) continue;
      let event;
      try {
        event = JSON.parse(line);
      } catch {
        session.parseErrors += 1;
        continue;
      }

      if (event.timestamp) session.endedAt = event.timestamp;
      if (event.type === 'session') {
        session.sessionId = String(event.id || session.sessionId);
        session.startedAt = String(event.timestamp || session.startedAt);
        session.cwd = String(event.cwd || session.cwd);
        continue;
      }
      if (event.type === 'model_change') {
        currentProvider = String(event.provider || currentProvider);
        currentModel = String(event.modelId || currentModel);
        continue;
      }
      if (event.type !== 'message') continue;

      const message = event.message || {};
      if (message.role !== 'assistant') continue;
      const usage = message.usage || {};
      if (!usage || typeof usage !== 'object' || Object.keys(usage).length === 0) continue;

      const provider = String(message.provider || currentProvider || 'unknown');
      const model = String(message.model || currentModel || 'unknown');
      const nonBillable = isNonBillablePiCost(provider, model);
      const totals = piCostTotalsFromUsage(usage, nonBillable);
      addPiCostTotals(session.totals, totals);

      const key = `${provider}\u0000${model}`;
      if (!session.byProviderModel.has(key)) {
        session.byProviderModel.set(key, { provider, model, totals: emptyPiCostTotals() });
      }
      addPiCostTotals(session.byProviderModel.get(key).totals, totals);
    }
  } finally {
    stream.destroy();
  }

  if (!session.sessionId) session.sessionId = path.basename(filePath).split('_').pop()?.replace(/\.jsonl$/i, '') || '';
  if (!session.startedAt) session.startedAt = path.basename(filePath).split('_')[0] || '';
  return session;
}

let cachedPiSessionCostStatus = null;
let cachedPiSessionCostStatusAt = 0;
let pendingPiSessionCostStatus = null;

async function readPiSessionCostStatus() {
  const now = Date.now();
  const cacheMs = Number.isFinite(PI_SESSION_COST_CACHE_MS) && PI_SESSION_COST_CACHE_MS > 0
    ? PI_SESSION_COST_CACHE_MS
    : 60_000;
  if (cachedPiSessionCostStatus && now - cachedPiSessionCostStatusAt < cacheMs) return cachedPiSessionCostStatus;
  if (pendingPiSessionCostStatus) return pendingPiSessionCostStatus;

  pendingPiSessionCostStatus = (async () => {
    const updatedAt = new Date().toISOString();
    const totals = emptyPiCostTotals();
    const byProviderModel = new Map();
    let sessionsScanned = 0;
    let sessionsIncluded = 0;
    let parseErrors = 0;

    try {
      const files = await collectPiSessionCostFiles(PI_AGENT_SESSIONS_DIR);
      sessionsScanned = files.length;
      for (const filePath of files) {
        let session;
        try {
          session = await readPiSessionCostFile(filePath);
        } catch {
          // Session files can vanish or be briefly unreadable while Pi writes/rotates them.
          parseErrors += 1;
          continue;
        }
        parseErrors += session.parseErrors;
        if (PI_SESSION_COST_CWD && session.cwd !== PI_SESSION_COST_CWD) continue;
        if (session.totals.usageRecords <= 0) continue;
        sessionsIncluded += 1;
        addPiCostTotals(totals, session.totals);
        for (const [key, row] of session.byProviderModel.entries()) {
          if (!byProviderModel.has(key)) {
            byProviderModel.set(key, { provider: row.provider, model: row.model, totals: emptyPiCostTotals() });
          }
          addPiCostTotals(byProviderModel.get(key).totals, row.totals);
        }
      }

      return {
        ok: true,
        source: PI_AGENT_SESSIONS_DIR,
        cwd: PI_SESSION_COST_CWD || null,
        cacheMs,
        updatedAt,
        sessionsScanned,
        sessionsIncluded,
        parseErrors,
        ...totals,
        byProviderModel: [...byProviderModel.values()]
          .map((row) => ({ provider: row.provider, model: row.model, ...row.totals }))
          .sort((a, b) => b.billableCostUsd - a.billableCostUsd)
      };
    } catch (error) {
      if (cachedPiSessionCostStatus) {
        return {
          ...cachedPiSessionCostStatus,
          ok: false,
          stale: true,
          error: error?.message || String(error),
          checkedAt: updatedAt
        };
      }
      return {
        ok: false,
        source: PI_AGENT_SESSIONS_DIR,
        cwd: PI_SESSION_COST_CWD || null,
        cacheMs,
        updatedAt,
        sessionsScanned,
        sessionsIncluded,
        parseErrors,
        ...totals,
        byProviderModel: [],
        error: error?.message || String(error)
      };
    }
  })();

  try {
    cachedPiSessionCostStatus = await pendingPiSessionCostStatus;
    cachedPiSessionCostStatusAt = Date.now();
    return cachedPiSessionCostStatus;
  } finally {
    pendingPiSessionCostStatus = null;
  }
}

async function readPiSessionStatusUncached() {
  let activeDiscordSessions = [];
  let statusUpdatedAt = null;
  let statusOk = true;
  let statusError = null;

  try {
    const raw = await readFile(PI_SESSION_STATUS_FILE, 'utf8');
    const payload = JSON.parse(raw);
    activeDiscordSessions = normalizePiSessions(payload);
    statusUpdatedAt = payload.updatedAt || null;
  } catch (error) {
    if (error?.code !== 'ENOENT') {
      statusOk = false;
      statusError = error.message;
    }
  }

  const processStatus = await readPiProcessSessions(activeDiscordSessions);
  const [recentFileStatus, localStatus] = await Promise.all([
    readRecentPiSessionFiles(),
    readLocalPiSessionStatuses()
  ]);
  const processSessions = processStatus.sessions || [];
  const localSessions = processSessions.filter((session) => !session.discordManaged);
  const discordProcessSessions = processSessions.filter((session) => session.discordManaged);
  const processSessionsByPid = new Map(processSessions.map((session) => [Number(session.pid), session]));
  const activeDiscordRootPids = new Set(activeDiscordSessions.map((session) => Number(session.pid)).filter(Number.isInteger));
  const localProcessPids = new Set(localSessions.map((session) => Number(session.pid)).filter(Number.isInteger));
  const localStatusSessions = (localStatus.sessions || []).filter((session) => localProcessPids.has(Number(session.pid)));
  const activeLocalStatusSessions = localStatusSessions.filter((session) => session.active === true);
  const discordExtensionActiveSessions = (localStatus.sessions || [])
    .filter((session) => session.active === true)
    .filter((session) => {
      const processSession = processSessionsByPid.get(Number(session.pid));
      if (!processSession?.discordManaged) return false;
      return !(processSession.ancestorPids || []).some((pid) => activeDiscordRootPids.has(Number(pid)));
    })
    .map((session) => ({
      ...session,
      kind: 'discord-active-pi-extension',
      source: 'local-pi-session-status-discord-process-tree'
    }));
  const statusCoveredPids = new Set(localStatusSessions.map((session) => Number(session.pid)).filter(Number.isInteger));
  const fallbackLocalCapacity = Math.max(0, localSessions.length - statusCoveredPids.size);
  const fallbackLocalActiveSessions = (recentFileStatus.sessions || [])
    .filter((session) => !activeLocalStatusSessions.some((statusSession) => statusSession.path && statusSession.path === session.path))
    .slice(0, fallbackLocalCapacity);
  const localActiveSessions = [...activeLocalStatusSessions, ...fallbackLocalActiveSessions];
  const discordActiveSessions = [...activeDiscordSessions, ...discordExtensionActiveSessions];
  const sessions = [...discordActiveSessions, ...localActiveSessions];
  const activeCount = discordActiveSessions.length + localActiveSessions.length;

  return {
    ok: statusOk && processStatus.ok && recentFileStatus.ok && localStatus.ok,
    activeCount,
    activeGenerating: activeCount,
    discordActiveGenerating: discordActiveSessions.length,
    localActive: localActiveSessions.length,
    localOpen: localSessions.length,
    localDirectOpen: localSessions.length,
    discordProcessOpen: discordProcessSessions.length,
    openPiProcesses: processSessions.length,
    totalSessions: activeCount,
    sessions,
    activeSessions: sessions,
    discordSessions: discordActiveSessions,
    activeDiscordStatusSessions: activeDiscordSessions,
    discordExtensionActiveSessions,
    localActiveSessions,
    localStatusSessions,
    fallbackLocalActiveSessions,
    recentSessionFiles: recentFileStatus.sessions || [],
    processSessions,
    localSessions,
    source: PI_SESSION_STATUS_FILE,
    updatedAt: statusUpdatedAt,
    processSource: '/bin/ps',
    localStatusSource: localStatus.source,
    sessionFileSource: recentFileStatus.source,
    localActiveWindowMs: recentFileStatus.activeWindowMs,
    localStatusMaxAgeMs: Number.isFinite(LOCAL_PI_STATUS_MAX_AGE_MS) ? LOCAL_PI_STATUS_MAX_AGE_MS : 15_000,
    error: statusError || processStatus.error || recentFileStatus.error || localStatus.error || null
  };
}

let cachedPiSessionStatus = null;
let cachedPiSessionStatusAt = 0;
let pendingPiSessionStatus = null;

function fallbackPiSessionStatus(message, stalePayload = null) {
  if (stalePayload) {
    return {
      ...stalePayload,
      stale: true,
      staleReason: message,
      error: stalePayload.error || message
    };
  }

  return {
    ok: false,
    activeCount: 0,
    activeGenerating: 0,
    discordActiveGenerating: 0,
    localActive: 0,
    localOpen: 0,
    localDirectOpen: 0,
    discordProcessOpen: 0,
    openPiProcesses: 0,
    totalSessions: 0,
    sessions: [],
    activeSessions: [],
    discordSessions: [],
    activeDiscordStatusSessions: [],
    discordExtensionActiveSessions: [],
    localActiveSessions: [],
    localStatusSessions: [],
    fallbackLocalActiveSessions: [],
    recentSessionFiles: [],
    processSessions: [],
    localSessions: [],
    source: PI_SESSION_STATUS_FILE,
    updatedAt: null,
    processSource: '/bin/ps',
    localStatusSource: PI_LOCAL_SESSION_STATUS_DIR,
    sessionFileSource: PI_AGENT_SESSIONS_DIR,
    localActiveWindowMs: Number.isFinite(LOCAL_PI_ACTIVE_WINDOW_MS) ? LOCAL_PI_ACTIVE_WINDOW_MS : 5_000,
    localStatusMaxAgeMs: Number.isFinite(LOCAL_PI_STATUS_MAX_AGE_MS) ? LOCAL_PI_STATUS_MAX_AGE_MS : 15_000,
    stale: true,
    staleReason: message,
    error: message
  };
}

async function readPiSessionStatus({ cacheMs = PI_SESSION_STATUS_CACHE_MS, timeoutMs = PI_SESSION_STATUS_TIMEOUT_MS, allowStale = true } = {}) {
  const now = Date.now();
  const safeCacheMs = Math.max(0, Number(cacheMs) || 0);
  if (cachedPiSessionStatus && safeCacheMs > 0 && now - cachedPiSessionStatusAt < safeCacheMs) {
    return cachedPiSessionStatus;
  }

  if (!pendingPiSessionStatus) {
    pendingPiSessionStatus = readPiSessionStatusUncached()
      .then((payload) => {
        cachedPiSessionStatus = payload;
        cachedPiSessionStatusAt = Date.now();
        return payload;
      })
      .finally(() => {
        pendingPiSessionStatus = null;
      });
  }

  const safeTimeoutMs = Math.max(0, Number(timeoutMs) || 0);
  if (safeTimeoutMs <= 0) return pendingPiSessionStatus;

  let timer = null;
  const timeout = new Promise((resolve) => {
    timer = setTimeout(() => resolve(null), safeTimeoutMs);
    timer.unref?.();
  });
  const result = await Promise.race([pendingPiSessionStatus, timeout]);
  if (timer) clearTimeout(timer);
  if (result) return result;

  const message = `Pi session status is still pending after ${(safeTimeoutMs / 1000).toFixed(1)}s.`;
  return allowStale ? fallbackPiSessionStatus(message, cachedPiSessionStatus) : fallbackPiSessionStatus(message);
}

function piSessionStatusSignature(piSessions) {
  return JSON.stringify({
    ok: piSessions.ok,
    activeCount: piSessions.activeCount,
    activeGenerating: piSessions.activeGenerating,
    discordActiveGenerating: piSessions.discordActiveGenerating,
    localActive: piSessions.localActive,
    localOpen: piSessions.localOpen,
    discordProcessOpen: piSessions.discordProcessOpen,
    openPiProcesses: piSessions.openPiProcesses,
    totalSessions: piSessions.totalSessions,
    updatedAt: piSessions.updatedAt || null,
    error: piSessions.error || null,
    sessions: (piSessions.sessions || []).map((session) => ({
      id: session.id,
      kind: session.kind,
      source: session.source,
      pid: session.pid,
      ppid: session.ppid,
      model: session.model,
      channel: session.channel,
      startedAt: session.startedAt,
      updatedAt: session.updatedAt,
      ageMs: session.ageMs,
      statusAgeMs: session.statusAgeMs,
      active: session.active
    }))
  });
}

let lastPiSessionStatusSignature = '';
let piSessionStatusTimer = null;
let piSessionStatusWatcher = null;

async function publishPiSessionStatus(reason = 'poll') {
  const piSessions = await readPiSessionStatus();
  const signature = piSessionStatusSignature(piSessions);
  if (signature === lastPiSessionStatusSignature) return piSessions;

  lastPiSessionStatusSignature = signature;
  const event = {
    type: 'pi-sessions',
    ok: piSessions.ok,
    reason,
    piSessions,
    at: new Date().toISOString(),
    clients: wsClients.size + eventClients.size
  };
  broadcastWebSocket(event);
  broadcastEvent('pi-sessions', event);
  return piSessions;
}

function schedulePiSessionStatusBroadcast(reason = 'watch') {
  if (piSessionStatusTimer) clearTimeout(piSessionStatusTimer);
  piSessionStatusTimer = setTimeout(() => {
    piSessionStatusTimer = null;
    publishPiSessionStatus(reason).catch((error) => {
      console.error(`[operation-jarvis-dashboard] failed to publish Pi session status: ${error.message}`);
    });
  }, 75);
  piSessionStatusTimer.unref?.();
}

async function startPiSessionStatusWatcher() {
  const statusDir = path.dirname(PI_SESSION_STATUS_FILE);
  const statusName = path.basename(PI_SESSION_STATUS_FILE);

  try {
    await mkdir(statusDir, { recursive: true });
    piSessionStatusWatcher = watch(statusDir, { persistent: false }, (_eventType, filename) => {
      if (!filename || filename.toString() === statusName) {
        schedulePiSessionStatusBroadcast('file-watch');
      }
    });
    piSessionStatusWatcher.on('error', (error) => {
      console.error(`[operation-jarvis-dashboard] Pi session watcher error: ${error.message}`);
    });
  } catch (error) {
    console.error(`[operation-jarvis-dashboard] Pi session watcher disabled: ${error.message}`);
  }

  // Cheap 1s safety net: catches missed file-system events and clears counts
  // quickly if a writer process dies before removing its session entry.
  const poll = setInterval(() => {
    publishPiSessionStatus('poll').catch((error) => {
      console.error(`[operation-jarvis-dashboard] failed to poll Pi session status: ${error.message}`);
    });
  }, 1_000);
  poll.unref?.();

  await publishPiSessionStatus('startup');
}

function actionState(action = '') {
  const normalized = String(action || '').toLowerCase();
  if (normalized.includes('speak')) return { key: 'speaking', label: 'SPEAKING', tone: 'green' };
  if (normalized.includes('look') || normalized.includes('view') || normalized.includes('photo')) return { key: 'looking', label: 'LOOKING', tone: 'cyan' };
  if (normalized.includes('cast') || normalized.includes('youtube') || normalized.includes('spotify')) return { key: 'casting', label: 'CASTING', tone: 'blue' };
  if (normalized.includes('monitor')) return { key: 'monitoring', label: 'MONITORING', tone: 'violet' };
  return { key: 'running', label: 'RUNNING', tone: 'amber' };
}

function deriveRoomDisplayState(jarvisPayload) {
  const events = jarvisPayload.local?.recentEvents || [];
  const latest = events[0] || null;
  const activeStart = latest?.eventType === 'action.start' && ageMs(latest.at) < 120_000 ? latest : null;
  const latestNonStart = events.find((event) => event.eventType !== 'action.start') || latest;
  const recentError = events.find((event) => (event.ok === false || event.error) && ageMs(event.at) < 10 * 60_000);

  if (!jarvisPayload.ok || recentError) {
    return {
      key: 'error',
      label: 'ATTENTION',
      tone: 'orange',
      detail: recentError?.summary || recentError?.error || jarvisPayload.error || 'Operation JARVIS needs attention.'
    };
  }

  if (activeStart) {
    const state = actionState(activeStart.action);
    return {
      ...state,
      detail: activeStart.summary || `${activeStart.action || 'Command'} in progress`
    };
  }

  if (latestNonStart && ageMs(latestNonStart.at) < 45_000) {
    return {
      key: 'complete',
      label: 'COMPLETE',
      tone: 'green',
      detail: latestNonStart.summary || `${latestNonStart.action || 'Command'} complete`
    };
  }

  return {
    key: 'idle',
    label: 'IDLE',
    tone: 'cyan',
    detail: jarvisPayload.status?.summary || 'Operation JARVIS is standing by.'
  };
}

function latestRoomOutput(events = []) {
  const output = events.find((event) => /speak|cast|youtube|spotify/i.test(event.action || ''));
  if (!output) {
    return { label: 'Room output', status: 'Quiet', detail: 'No recent speaker or TV activity.', at: null };
  }

  const active = output.eventType === 'action.start' && ageMs(output.at) < 90_000;
  return {
    label: /speak/i.test(output.action || '') ? 'Speaker' : 'TV / Cast',
    status: active ? 'Active' : 'Last output',
    detail: output.summary || output.action || 'Room output update',
    at: output.at
  };
}

function firstEnv(keys = [], fallback = '') {
  for (const key of keys) {
    const value = process.env[key];
    if (value !== undefined && String(value).trim() !== '') return value;
  }
  return fallback;
}

function parseInteger(value, fallback) {
  const parsed = Number.parseInt(String(value ?? ''), 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function buildOmlxServerConfig(config = {}) {
  const id = String(config.id || DEFAULT_OMLX_SERVER_ID);
  const baseUrl = normalizeOpenAiBaseUrl(config.baseUrl || OMLX_16_DEFAULT_BASE_URL);
  return {
    id,
    name: String(config.name || `OMLX-${id}`),
    baseUrl,
    rootUrl: openAiBaseUrlToRoot(baseUrl),
    apiKey: String(config.apiKey || ''),
    statusTimeoutMs: parseInteger(config.statusTimeoutMs, 1500),
    statusCacheMs: parseInteger(config.statusCacheMs, OMLX_STATUS_CACHE_MS),
    controlTimeoutMs: parseInteger(config.controlTimeoutMs, 30000),
    sshHost: String(config.sshHost || '').trim(),
    sshUser: String(config.sshUser || '').trim(),
    sshKey: String(config.sshKey || '').trim(),
    sshPort: parseInteger(config.sshPort, 22),
    appPath: String(config.appPath || '/Applications/oMLX.app'),
    cliPath: String(config.cliPath || '/Applications/oMLX.app/Contents/MacOS/omlx-cli'),
    basePath: String(config.basePath || '~/.omlx'),
    serverLog: String(config.serverLog || '~/Library/Application Support/oMLX/logs/server.log'),
    localHealthUrl: String(config.localHealthUrl || 'http://127.0.0.1:8000/health')
  };
}

function normalizeOmlxServerId(raw = DEFAULT_OMLX_SERVER_ID) {
  const value = String(raw || '').trim().toLowerCase();
  if (!value || value === 'default' || value === 'primary' || value === 'omlx') return DEFAULT_OMLX_SERVER_ID;
  const normalized = value.replace(/^omlx[-_]?/, '');
  return OMLX_SERVERS.has(normalized) ? normalized : '';
}

function resolveOmlxServerIdFromRequest(requestUrl) {
  const queryServer = requestUrl.searchParams.get('server') || requestUrl.searchParams.get('serverId') || requestUrl.searchParams.get('id');
  if (queryServer) return normalizeOmlxServerId(queryServer);

  const parts = requestUrl.pathname.split('/').filter(Boolean);
  const omlxSegment = parts[2] || '';
  const segmentMatch = omlxSegment.match(/^omlx[-_]?(16|64)$/i);
  if (segmentMatch) return normalizeOmlxServerId(segmentMatch[1]);

  const pathServer = parts[3] || '';
  if (/^(16|64)$/i.test(pathServer)) return normalizeOmlxServerId(pathServer);

  return DEFAULT_OMLX_SERVER_ID;
}

function normalizeOmlxRequestPath(pathname = '') {
  return String(pathname || '')
    .replace(/^\/api\/jarvis\/omlx[-_]?(16|64)(?=\/|$)/i, '/api/jarvis/omlx')
    .replace(/^\/api\/jarvis\/omlx\/(16|64)(?=\/|$)/i, '/api/jarvis/omlx');
}

function getOmlxServerConfig(serverId = DEFAULT_OMLX_SERVER_ID) {
  const normalized = normalizeOmlxServerId(serverId);
  return normalized ? OMLX_SERVERS.get(normalized) : null;
}

function getOmlxRuntime(serverId = DEFAULT_OMLX_SERVER_ID) {
  const normalized = normalizeOmlxServerId(serverId) || DEFAULT_OMLX_SERVER_ID;
  if (!OMLX_RUNTIME.has(normalized)) {
    OMLX_RUNTIME.set(normalized, {
      cachedStatus: null,
      cachedStatusAt: 0,
      pendingStatus: null,
      pendingControl: null
    });
  }
  return OMLX_RUNTIME.get(normalized);
}

function unknownOmlxServerStatus(serverId = '') {
  const checkedAt = new Date().toISOString();
  const name = serverId ? `OMLX-${serverId}` : 'oMLX';
  return {
    ok: false,
    status: 'offline',
    state: 'offline',
    label: 'OFFLINE',
    serverId: String(serverId || ''),
    name,
    displayName: name,
    error: 'Unknown oMLX server',
    checkedAt,
    durationMs: 0
  };
}

function omlxHeaders(server) {
  const headers = { accept: 'application/json' };
  if (server?.apiKey) headers.authorization = `Bearer ${server.apiKey}`;
  return headers;
}

async function fetchJsonWithTimeout(url, { timeoutMs = 1500, headers = {} } = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), Math.max(300, Number(timeoutMs) || 1500));
  try {
    const response = await fetch(url, {
      method: 'GET',
      headers,
      signal: controller.signal
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.json().catch(() => ({}));
  } finally {
    clearTimeout(timeout);
  }
}

async function readOmlxStatus(serverOrOptions = DEFAULT_OMLX_SERVER_ID, maybeOptions = {}) {
  let serverId = serverOrOptions;
  let options = maybeOptions;
  if (serverOrOptions && typeof serverOrOptions === 'object' && !Array.isArray(serverOrOptions)) {
    serverId = DEFAULT_OMLX_SERVER_ID;
    options = serverOrOptions;
  }

  const server = getOmlxServerConfig(serverId);
  if (!server) return unknownOmlxServerStatus(serverId);

  const runtime = getOmlxRuntime(server.id);
  const force = Boolean(options?.force);
  const now = Date.now();
  if (!force && runtime.cachedStatus && now - runtime.cachedStatusAt < server.statusCacheMs) return runtime.cachedStatus;
  if (!force && runtime.pendingStatus) return runtime.pendingStatus;

  runtime.pendingStatus = (async () => {
    const checkedAt = new Date().toISOString();
    const headers = omlxHeaders(server);
    const healthUrl = `${server.rootUrl}/health`;
    const statusUrl = `${server.rootUrl}/api/status`;
    const modelsUrl = `${server.baseUrl}/models`;
    const startedMs = Date.now();

    try {
      const health = await fetchJsonWithTimeout(healthUrl, { timeoutMs: server.statusTimeoutMs, headers });
      let apiStatus = null;
      let models = null;
      try {
        apiStatus = await fetchJsonWithTimeout(statusUrl, { timeoutMs: Math.max(500, server.statusTimeoutMs), headers });
      } catch {
        // The health endpoint is authoritative for server on/off state.
      }
      try {
        const modelsBody = await fetchJsonWithTimeout(modelsUrl, { timeoutMs: Math.max(500, server.statusTimeoutMs), headers });
        models = Array.isArray(modelsBody.data) ? modelsBody.data : null;
      } catch {
        // Model listing is useful detail, not required for server state.
      }

      const modelCount = Number.isFinite(Number(apiStatus?.models_discovered))
        ? Number(apiStatus.models_discovered)
        : (Number.isFinite(Number(health?.engine_pool?.model_count))
          ? Number(health.engine_pool.model_count)
          : (Array.isArray(models) ? models.length : null));
      const loadedCount = Number.isFinite(Number(apiStatus?.models_loaded))
        ? Number(apiStatus.models_loaded)
        : (Number.isFinite(Number(health?.engine_pool?.loaded_count)) ? Number(health.engine_pool.loaded_count) : null);

      return {
        ok: true,
        status: 'online',
        label: 'ONLINE',
        serverId: server.id,
        name: server.name,
        displayName: server.name,
        baseUrl: server.baseUrl,
        rootUrl: server.rootUrl,
        healthUrl,
        modelCount,
        loadedCount,
        defaultModel: apiStatus?.default_model || health?.default_model || '',
        version: apiStatus?.version || '',
        uptimeSeconds: Number.isFinite(Number(apiStatus?.uptime_seconds)) ? Number(apiStatus.uptime_seconds) : null,
        activeRequests: Number.isFinite(Number(apiStatus?.active_requests)) ? Number(apiStatus.active_requests) : null,
        checkedAt,
        durationMs: Date.now() - startedMs
      };
    } catch (error) {
      return {
        ok: false,
        status: 'offline',
        label: 'OFFLINE',
        serverId: server.id,
        name: server.name,
        displayName: server.name,
        baseUrl: server.baseUrl,
        rootUrl: server.rootUrl,
        healthUrl,
        error: error?.name === 'AbortError' ? 'Timed out' : (error?.message || 'Unavailable'),
        checkedAt,
        durationMs: Date.now() - startedMs
      };
    }
  })();

  try {
    runtime.cachedStatus = await runtime.pendingStatus;
    runtime.cachedStatusAt = Date.now();
    return runtime.cachedStatus;
  } finally {
    runtime.pendingStatus = null;
  }
}

function shellQuote(value = '') {
  return `'${String(value).replaceAll("'", `'\\''`)}'`;
}

function expandHome(rawPath = '') {
  const value = String(rawPath || '').trim();
  if (!value) return value;
  if (value === '~') return os.homedir();
  if (value.startsWith('~/')) return path.join(os.homedir(), value.slice(2));
  return value;
}

function shellDoubleQuote(value = '') {
  return `"${String(value).replace(/["\\$`]/g, (char) => `\\${char}`)}"`;
}

function remoteShellPath(rawPath = '') {
  const value = String(rawPath || '').trim();
  if (value === '~') return '"$HOME"';
  if (value.startsWith('~/')) return `"$HOME/${String(value.slice(2)).replace(/["\\$`]/g, (char) => `\\${char}`)}"`;
  if (value.startsWith('$HOME/')) return `"$HOME/${String(value.slice(6)).replace(/["\\$`]/g, (char) => `\\${char}`)}"`;
  return shellQuote(value);
}

function parseKeyValueLines(stdout = '') {
  const values = {};
  for (const line of String(stdout || '').split(/\r?\n/)) {
    const index = line.indexOf('=');
    if (index <= 0) continue;
    values[line.slice(0, index).trim()] = line.slice(index + 1).trim();
  }
  return values;
}

function waitMs(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function buildOmlxControlScript(server, action) {
  const safeAction = action === 'stop' ? 'stop' : 'start';
  const appPath = shellQuote(server.appPath);
  const cliPath = shellQuote(server.cliPath);
  const basePath = remoteShellPath(server.basePath);
  const serverLog = remoteShellPath(server.serverLog);
  const healthUrl = shellQuote(server.localHealthUrl);
  return [
    'set -u',
    `action=${shellQuote(safeAction)}`,
    `app_path=${appPath}`,
    `cli_path=${cliPath}`,
    `base_path=${basePath}`,
    `server_log=${serverLog}`,
    `health_url=${healthUrl}`,
    'port="$(printf "%s" "$health_url" | sed -E "s#^[a-zA-Z]+://[^:/]+:([0-9]+).*#\\1#")"',
    'case "$port" in ""|*[!0-9]*) port=8000;; esac',
    'echo "requestedAction=$action"',
    'echo "appPath=$app_path"',
    'echo "cliPath=$cli_path"',
    'echo "basePath=$base_path"',
    'echo "healthUrl=$health_url"',
    'echo "port=$port"',
    'health_ok() { command -v curl >/dev/null 2>&1 && curl -fsS --max-time 1 "$health_url" >/dev/null 2>&1; }',
    'wait_health_state() { desired="$1"; seconds="$2"; end=$(( $(date +%s) + seconds )); while [ "$(date +%s)" -le "$end" ]; do if health_ok; then current=up; else current=down; fi; [ "$current" = "$desired" ] && return 0; sleep 1; done; return 1; }',
    'server_pids() { if command -v lsof >/dev/null 2>&1; then lsof -nP -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | while read -r pid; do [ -n "$pid" ] || continue; cmd="$(ps -p "$pid" -o command= 2>/dev/null || true)"; case "$cmd" in *"omlx.cli serve"*|*"omlx-cli serve"*) echo "$pid";; esac; done; else pgrep -f "omlx.cli serve.*--port $port" 2>/dev/null || true; fi; }',
    'stop_server_processes() { pids="$(server_pids | tr "\\n" " " | sed "s/[[:space:]]*$//")"; echo "serverPids=$pids"; [ -n "$pids" ] || return 1; for pid in $pids; do kill -TERM "$pid" 2>/dev/null || true; done; wait_health_state down 8 && return 0; for pid in $pids; do kill -KILL "$pid" 2>/dev/null || true; done; wait_health_state down 5; }',
    'if [ "$action" = "stop" ]; then if ! health_ok; then echo "action=stop"; echo "actionOk=true"; echo "serverRunning=false"; echo "alreadyStopped=true"; exit 0; fi; if stop_server_processes; then echo "action=stop"; echo "actionOk=true"; echo "serverRunning=false"; exit 0; else echo "action=stop"; echo "actionOk=false"; echo "serverRunning=true"; echo "error=oMLX server is responding, but no owned server process was stopped"; exit 14; fi; fi',
    'if health_ok; then echo "action=start"; echo "actionOk=true"; echo "serverRunning=true"; echo "alreadyRunning=true"; exit 0; fi',
    'if [ ! -x "$cli_path" ]; then echo "action=start"; echo "actionOk=false"; echo "serverRunning=false"; echo "error=oMLX CLI not found or not executable"; exit 15; fi',
    'mkdir -p "$(dirname "$server_log")" "$base_path"',
    'nohup "$cli_path" serve --base-path "$base_path" --port "$port" >> "$server_log" 2>&1 &',
    'server_pid=$!',
    'echo "serverPid=$server_pid"',
    'if wait_health_state up 30; then echo "action=start"; echo "actionOk=true"; echo "serverRunning=true"; exit 0; else echo "action=start"; echo "actionOk=false"; echo "serverRunning=false"; echo "error=oMLX server did not become healthy"; exit 16; fi'
  ].join('\n');
}

function buildOmlxSshArgs(server, script) {
  const sshTarget = server.sshUser
    ? `${server.sshUser}@${server.sshHost}`
    : server.sshHost;
  const sshArgs = [
    '-o', 'BatchMode=yes',
    '-o', 'ConnectTimeout=3'
  ];
  if (server.sshKey) {
    sshArgs.push('-i', expandHome(server.sshKey), '-o', 'IdentitiesOnly=yes');
  }
  if (Number.isFinite(server.sshPort) && server.sshPort > 0 && server.sshPort !== 22) {
    sshArgs.push('-p', String(server.sshPort));
  }
  sshArgs.push(sshTarget, script);
  return { sshTarget, sshArgs };
}

async function setOmlxServerPower(serverOrAction = DEFAULT_OMLX_SERVER_ID, desiredAction = 'toggle') {
  let serverId = serverOrAction;
  let requestedAction = desiredAction;
  if (arguments.length === 1 && ['start', 'stop', 'toggle'].includes(String(serverOrAction || '').toLowerCase())) {
    serverId = DEFAULT_OMLX_SERVER_ID;
    requestedAction = serverOrAction;
  }

  const server = getOmlxServerConfig(serverId);
  if (!server) return unknownOmlxServerStatus(serverId);
  if (!server.sshHost) {
    const checkedAt = new Date().toISOString();
    const status = await readOmlxStatus(server.id, { force: true });
    const message = `${server.name} SSH host is not configured`;
    return {
      ...status,
      control: {
        ok: false,
        action: String(requestedAction || 'toggle').toLowerCase(),
        host: '',
        checkedAt,
        durationMs: 0,
        ready: false,
        error: message
      },
      error: message
    };
  }

  const runtime = getOmlxRuntime(server.id);
  if (runtime.pendingControl) return runtime.pendingControl;
  runtime.pendingControl = (async () => {
    const before = await readOmlxStatus(server.id, { force: true });
    const normalizedAction = String(requestedAction || 'toggle').toLowerCase();
    const action = normalizedAction === 'stop' ? 'stop' : (normalizedAction === 'start' ? 'start' : (before.ok ? 'stop' : 'start'));
    const checkedAt = new Date().toISOString();
    const startedMs = Date.now();
    const { sshTarget, sshArgs } = buildOmlxSshArgs(server, buildOmlxControlScript(server, action));
    let control = {
      ok: false,
      action,
      host: sshTarget,
      checkedAt,
      durationMs: 0,
      error: ''
    };

    try {
      const { stdout } = await execFileAsync('ssh', sshArgs, {
        timeout: Math.max(server.controlTimeoutMs, action === 'start' ? 35_000 : 20_000),
        maxBuffer: 128 * 1024
      });
      const values = parseKeyValueLines(stdout);
      control = {
        ...control,
        ok: values.actionOk === 'true',
        action: values.action || action,
        appPath: values.appPath || server.appPath,
        cliPath: values.cliPath || server.cliPath,
        basePath: values.basePath || server.basePath,
        healthUrl: values.healthUrl || server.localHealthUrl,
        port: values.port || '',
        serverPid: values.serverPid || '',
        serverPids: values.serverPids || '',
        alreadyRunning: values.alreadyRunning === 'true',
        alreadyStopped: values.alreadyStopped === 'true',
        serverRunning: values.serverRunning === 'true',
        error: values.error || ''
      };
    } catch (error) {
      const values = parseKeyValueLines(error.stdout || '');
      const message = values.error
        || String(error.stderr || '').trim()
        || String(error.stdout || '').trim()
        || (error.killed ? 'oMLX server switch timed out' : error.message)
        || 'oMLX server switch failed';
      control = {
        ...control,
        ok: false,
        action: values.action || action,
        appPath: values.appPath || server.appPath,
        cliPath: values.cliPath || server.cliPath,
        basePath: values.basePath || server.basePath,
        healthUrl: values.healthUrl || server.localHealthUrl,
        port: values.port || '',
        serverPid: values.serverPid || '',
        serverPids: values.serverPids || '',
        serverRunning: values.serverRunning === 'true',
        error: message.split(/\r?\n/).slice(0, 3).join(' · ')
      };
    }

    control.durationMs = Date.now() - startedMs;
    let status = await readOmlxStatus(server.id, { force: true });
    const deadline = Date.now() + (action === 'start' ? 12_000 : 7_000);
    let readinessPolls = 1;
    while (Date.now() < deadline) {
      const ready = action === 'start' ? status.ok : !status.ok;
      if (ready) break;
      await waitMs(action === 'start' ? 1500 : 800);
      status = await readOmlxStatus(server.id, { force: true });
      readinessPolls += 1;
    }

    const ready = action === 'start' ? status.ok : !status.ok;
    return {
      ...status,
      control: {
        ...control,
        ready,
        readinessPolls,
        durationMs: Date.now() - startedMs
      },
      error: control.error || status.error || ''
    };
  })().finally(() => {
    runtime.pendingControl = null;
  });
  return runtime.pendingControl;
}

async function handleOmlxRequest(req, res) {
  const requestUrl = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
  const serverId = resolveOmlxServerIdFromRequest(requestUrl);
  if (!serverId || !OMLX_SERVERS.has(serverId)) {
    json(res, 404, unknownOmlxServerStatus(serverId));
    return;
  }

  const pathname = normalizeOmlxRequestPath(requestUrl.pathname);
  if (pathname === '/api/jarvis/omlx/server/toggle' || pathname === '/api/jarvis/omlx/toggle') {
    if (req.method !== 'POST') {
      json(res, 405, { ok: false, error: 'Method not allowed. Use POST.' });
      return;
    }
    const desired = requestUrl.searchParams.get('action') || requestUrl.searchParams.get('state') || 'toggle';
    json(res, 200, await setOmlxServerPower(serverId, String(desired).toLowerCase()));
    return;
  }

  if (pathname === '/api/jarvis/omlx/status' || pathname === '/api/jarvis/omlx') {
    if (!['GET', 'POST'].includes(req.method || 'GET')) {
      json(res, 405, { ok: false, error: 'Method not allowed' });
      return;
    }
    json(res, 200, await readOmlxStatus(serverId, { force: true }));
    return;
  }

  json(res, 404, { ok: false, error: 'Unknown oMLX endpoint' });
}

function buildRaspberryPiToggleServiceScript() {
  const serviceName = shellQuote(RASPBERRY_PI_ROOM_AUDIO_SERVICE);
  return [
    'set -u',
    `service_name=${serviceName}`,
    'if ! command -v systemctl >/dev/null 2>&1; then echo "action=error"; echo "error=systemctl not found"; exit 127; fi',
    'if systemctl is-active --quiet "$service_name"; then action=stop; else action=start; fi',
    'if [ "$(id -u 2>/dev/null || echo 1)" = "0" ]; then systemctl "$action" "$service_name"; else sudo -n systemctl "$action" "$service_name"; fi',
    'sleep 0.7',
    'echo "action=$action"',
    'echo "serviceName=$service_name"',
    'echo "toggleOk=true"'
  ].join('; ');
}

function buildRaspberryPiStatusScript() {
  const processPattern = shellQuote(RASPBERRY_PI_ROOM_AUDIO_PATTERN);
  const serviceName = shellQuote(RASPBERRY_PI_ROOM_AUDIO_SERVICE);
  const serverUrl = shellQuote(RASPBERRY_PI_ROOM_AUDIO_SERVER_URL);
  const powerconfMac = shellQuote(RASPBERRY_PI_POWERCONF_MAC);
  return [
    'set -u',
    `service_name=${serviceName}`,
    `server_url=${serverUrl}`,
    `powerconf_mac=${powerconfMac}`,
    'hostname_value="$(hostname 2>/dev/null || uname -n 2>/dev/null || echo raspberrypi)"',
    'uptime_seconds="$(cut -d. -f1 /proc/uptime 2>/dev/null || echo 0)"',
    'load_average="$(cut -d " " -f1-3 /proc/loadavg 2>/dev/null || echo "")"',
    'service_active=unknown',
    'service_enabled=unknown',
    'service_active_state=unknown',
    'service_sub_state=unknown',
    'service_result=unknown',
    'service_pid=0',
    'service_main_status=',
    'service_restart_count=0',
    'bluetooth_active=unknown',
    'bluealsa_active=unknown',
    'if command -v systemctl >/dev/null 2>&1; then service_active="$(systemctl is-active "$service_name" 2>/dev/null || true)"; service_enabled="$(systemctl is-enabled "$service_name" 2>/dev/null || true)"; service_active_state="$(systemctl show "$service_name" -p ActiveState --value 2>/dev/null || true)"; service_sub_state="$(systemctl show "$service_name" -p SubState --value 2>/dev/null || true)"; service_result="$(systemctl show "$service_name" -p Result --value 2>/dev/null || true)"; service_pid="$(systemctl show "$service_name" -p ExecMainPID --value 2>/dev/null || true)"; service_main_status="$(systemctl show "$service_name" -p ExecMainStatus --value 2>/dev/null || true)"; service_restart_count="$(systemctl show "$service_name" -p NRestarts --value 2>/dev/null || true)"; bluetooth_active="$(systemctl is-active bluetooth.service 2>/dev/null || true)"; bluealsa_active="$(systemctl is-active bluealsa.service 2>/dev/null || true)"; fi',
    'case "${service_pid:-0}" in ""|*[!0-9]*) service_pid=0;; esac',
    'case "${service_restart_count:-0}" in ""|*[!0-9]*) service_restart_count=0;; esac',
    'if [ "$service_active" = "active" ] && [ "$service_sub_state" = "running" ] && [ "${service_pid:-0}" -gt 0 ]; then service_running=true; else service_running=false; fi',
    `client_processes="$(pgrep -af ${processPattern} 2>/dev/null | grep -v "pgrep -af" | wc -l | tr -d " ")"`,
    'if [ "${client_processes:-0}" -gt 0 ]; then client_running=true; else client_running=false; fi',
    'powerconf_connected=false',
    'powerconf_state=not-configured',
    'if [ -z "$powerconf_mac" ]; then powerconf_connected=true; powerconf_state=not-configured; elif command -v bluetoothctl >/dev/null 2>&1; then powerconf_info="$(bluetoothctl info "$powerconf_mac" 2>/dev/null || true)"; if printf "%s" "$powerconf_info" | grep -q "Connected: yes"; then powerconf_connected=true; powerconf_state=connected; else powerconf_state=disconnected; fi; else powerconf_state=missing-bluetoothctl; fi',
    'room_server_ok=false',
    'room_server_status=not-configured',
    'if [ -z "$server_url" ]; then room_server_ok=true; room_server_status=not-configured; elif command -v curl >/dev/null 2>&1; then room_health_url="${server_url%/}/health"; if room_health_body="$(curl -fsS --max-time 2 "$room_health_url" 2>&1)"; then room_server_ok=true; room_server_status=ok; else room_server_status="$(printf "%s" "$room_health_body" | head -n 1 | cut -c1-120)"; [ -n "$room_server_status" ] || room_server_status=unreachable; fi; else room_server_status=missing-curl; fi',
    'echo "hostname=$hostname_value"',
    'echo "uptimeSeconds=${uptime_seconds:-0}"',
    'echo "loadAverage=$load_average"',
    'echo "serviceName=$service_name"',
    'echo "serviceActive=$service_active"',
    'echo "serviceEnabled=$service_enabled"',
    'echo "serviceActiveState=$service_active_state"',
    'echo "serviceSubState=$service_sub_state"',
    'echo "serviceResult=$service_result"',
    'echo "servicePid=${service_pid:-0}"',
    'echo "serviceMainStatus=$service_main_status"',
    'echo "serviceRestartCount=${service_restart_count:-0}"',
    'echo "serviceRunning=$service_running"',
    'echo "clientRunning=$client_running"',
    'echo "clientProcesses=${client_processes:-0}"',
    'echo "bluetoothState=$bluetooth_active"',
    'echo "bluealsaState=$bluealsa_active"',
    'echo "powerconfMac=$powerconf_mac"',
    'echo "powerconfConnected=$powerconf_connected"',
    'echo "powerconfState=$powerconf_state"',
    'echo "roomAudioServerUrl=$server_url"',
    'echo "roomAudioServerOk=$room_server_ok"',
    'echo "roomAudioServerStatus=$room_server_status"'
  ].join('; ');
}

function buildRaspberryPiSshArgs(script) {
  const sshTarget = RASPBERRY_PI_SSH_USER
    ? `${RASPBERRY_PI_SSH_USER}@${RASPBERRY_PI_SSH_HOST}`
    : RASPBERRY_PI_SSH_HOST;
  const sshArgs = [
    '-o', 'BatchMode=yes',
    '-o', 'ConnectTimeout=3'
  ];
  if (RASPBERRY_PI_SSH_KEY) {
    sshArgs.push('-i', expandHome(RASPBERRY_PI_SSH_KEY), '-o', 'IdentitiesOnly=yes');
  }
  if (Number.isFinite(RASPBERRY_PI_SSH_PORT) && RASPBERRY_PI_SSH_PORT > 0 && RASPBERRY_PI_SSH_PORT !== 22) {
    sshArgs.push('-p', String(RASPBERRY_PI_SSH_PORT));
  }
  sshArgs.push(sshTarget, script);
  return { sshTarget, sshArgs };
}

function raspberryPiNotConfiguredStatus(checkedAt, startedMs, message) {
  return {
    ok: false,
    reachable: false,
    status: 'offline',
    label: 'NOT CONFIGURED',
    host: '',
    hostname: '',
    uptimeSeconds: 0,
    loadAverage: '',
    serviceName: RASPBERRY_PI_ROOM_AUDIO_SERVICE,
    serviceRunning: false,
    serviceActive: false,
    serviceState: 'unknown',
    serviceEnabled: false,
    serviceEnabledState: 'unknown',
    serviceActiveState: '',
    serviceSubState: '',
    serviceResult: '',
    servicePid: 0,
    serviceMainStatus: '',
    serviceRestartCount: 0,
    clientRunning: false,
    clientProcesses: 0,
    processPattern: RASPBERRY_PI_ROOM_AUDIO_PATTERN,
    bluetoothActive: false,
    bluetoothState: 'unknown',
    bluealsaActive: false,
    bluealsaState: 'unknown',
    powerconfMac: RASPBERRY_PI_POWERCONF_MAC,
    powerconfConnected: false,
    powerconfState: 'unknown',
    roomAudioServerOk: false,
    roomAudioServerUrl: RASPBERRY_PI_ROOM_AUDIO_SERVER_URL,
    roomAudioServerStatus: 'unknown',
    checkedAt,
    durationMs: Date.now() - startedMs,
    error: message,
    issues: [message]
  };
}

async function readRaspberryPiStatus() {
  const checkedAt = new Date().toISOString();
  const startedMs = Date.now();
  if (!RASPBERRY_PI_SSH_HOST) return raspberryPiNotConfiguredStatus(checkedAt, startedMs, 'Raspberry Pi SSH host is not configured');
  const { sshTarget, sshArgs } = buildRaspberryPiSshArgs(buildRaspberryPiStatusScript());

  try {
    const { stdout } = await execFileAsync('ssh', sshArgs, {
      timeout: RASPBERRY_PI_TIMEOUT_MS,
      maxBuffer: 128 * 1024
    });
    const values = parseKeyValueLines(stdout);
    const clientRunning = values.clientRunning === 'true';
    const serviceRunning = values.serviceRunning === 'true';
    const serviceState = values.serviceActive || values.serviceActiveState || 'unknown';
    const serviceActive = serviceState === 'active' || values.serviceActiveState === 'active';
    const serviceEnabledState = values.serviceEnabled || 'unknown';
    const serviceEnabled = ['enabled', 'enabled-runtime', 'static', 'generated', 'indirect', 'alias'].includes(serviceEnabledState);
    const bluetoothState = values.bluetoothState || 'unknown';
    const bluealsaState = values.bluealsaState || 'unknown';
    const bluetoothActive = bluetoothState === 'active';
    const bluealsaActive = bluealsaState === 'active';
    const powerconfConnected = values.powerconfConnected === 'true';
    const roomAudioServerOk = values.roomAudioServerOk === 'true';
    const uptimeSeconds = Number.parseInt(values.uptimeSeconds || '0', 10);
    const servicePid = Number.parseInt(values.servicePid || '0', 10);
    const serviceRestartCount = Number.parseInt(values.serviceRestartCount || '0', 10);
    const clientProcesses = Number.parseInt(values.clientProcesses || '0', 10) || 0;
    const issues = [];
    if (!serviceRunning) {
      const serviceDetail = [serviceState, values.serviceSubState].filter(Boolean).join('/');
      issues.push(`Room-audio service ${serviceDetail || 'not running'}`);
    }
    if (!serviceEnabled) issues.push(`Room-audio service ${serviceEnabledState}`);
    if (!clientRunning) issues.push('client process not found');
    if (!bluetoothActive) issues.push(`bluetooth.service ${bluetoothState}`);
    if (!bluealsaActive) issues.push(`bluealsa.service ${bluealsaState}`);
    if (!powerconfConnected) issues.push(`PowerConf ${values.powerconfState || 'disconnected'}`);
    if (!roomAudioServerOk) issues.push(`room server ${values.roomAudioServerStatus || 'unreachable'}`);
    const ok = issues.length === 0;
    return {
      ok,
      reachable: true,
      status: ok ? 'online' : 'degraded',
      label: ok ? 'ONLINE' : 'ROOM AUDIO DEGRADED',
      host: sshTarget,
      hostname: values.hostname || '',
      uptimeSeconds: Number.isFinite(uptimeSeconds) ? uptimeSeconds : 0,
      loadAverage: values.loadAverage || '',
      serviceName: values.serviceName || RASPBERRY_PI_ROOM_AUDIO_SERVICE,
      serviceRunning,
      serviceActive,
      serviceState,
      serviceEnabled,
      serviceEnabledState,
      serviceActiveState: values.serviceActiveState || '',
      serviceSubState: values.serviceSubState || '',
      serviceResult: values.serviceResult || '',
      servicePid: Number.isFinite(servicePid) ? servicePid : 0,
      serviceMainStatus: values.serviceMainStatus || '',
      serviceRestartCount: Number.isFinite(serviceRestartCount) ? serviceRestartCount : 0,
      clientRunning,
      clientProcesses,
      processPattern: RASPBERRY_PI_ROOM_AUDIO_PATTERN,
      bluetoothActive,
      bluetoothState,
      bluealsaActive,
      bluealsaState,
      powerconfMac: values.powerconfMac || RASPBERRY_PI_POWERCONF_MAC,
      powerconfConnected,
      powerconfState: values.powerconfState || '',
      roomAudioServerOk,
      roomAudioServerUrl: values.roomAudioServerUrl || RASPBERRY_PI_ROOM_AUDIO_SERVER_URL,
      roomAudioServerStatus: values.roomAudioServerStatus || '',
      checkedAt,
      durationMs: Date.now() - startedMs,
      error: ok ? '' : issues.slice(0, 3).join(' · '),
      issues
    };
  } catch (error) {
    const message = String(error.stderr || '').trim()
      || String(error.stdout || '').trim()
      || (error.killed ? 'Raspberry Pi ping timed out' : error.message)
      || 'Raspberry Pi ping failed';
    return {
      ok: false,
      reachable: false,
      status: 'offline',
      label: 'OFFLINE',
      host: sshTarget,
      hostname: '',
      uptimeSeconds: 0,
      loadAverage: '',
      serviceName: RASPBERRY_PI_ROOM_AUDIO_SERVICE,
      serviceRunning: false,
      serviceActive: false,
      serviceState: 'unknown',
      serviceEnabled: false,
      serviceEnabledState: 'unknown',
      serviceActiveState: '',
      serviceSubState: '',
      serviceResult: '',
      servicePid: 0,
      serviceMainStatus: '',
      serviceRestartCount: 0,
      clientRunning: false,
      clientProcesses: 0,
      processPattern: RASPBERRY_PI_ROOM_AUDIO_PATTERN,
      bluetoothActive: false,
      bluetoothState: 'unknown',
      bluealsaActive: false,
      bluealsaState: 'unknown',
      powerconfMac: RASPBERRY_PI_POWERCONF_MAC,
      powerconfConnected: false,
      powerconfState: 'unknown',
      roomAudioServerOk: false,
      roomAudioServerUrl: RASPBERRY_PI_ROOM_AUDIO_SERVER_URL,
      roomAudioServerStatus: 'unknown',
      checkedAt,
      durationMs: Date.now() - startedMs,
      error: message.split(/\r?\n/).slice(0, 3).join(' · '),
      issues: [message.split(/\r?\n/)[0] || 'Raspberry Pi ping failed']
    };
  }
}

async function toggleRaspberryPiRoomAudioService() {
  const checkedAt = new Date().toISOString();
  const startedMs = Date.now();
  if (!RASPBERRY_PI_SSH_HOST) {
    const status = await readRaspberryPiStatus();
    const message = 'Raspberry Pi SSH host is not configured';
    return {
      ...status,
      toggle: {
        ok: false,
        action: 'toggle',
        host: '',
        checkedAt,
        durationMs: Date.now() - startedMs,
        readinessPolls: 0,
        ready: false,
        error: message
      },
      error: message,
      issues: [message]
    };
  }
  const { sshTarget, sshArgs } = buildRaspberryPiSshArgs(buildRaspberryPiToggleServiceScript());
  let action = 'toggle';
  let toggleOk = false;
  let toggleError = '';

  try {
    const { stdout } = await execFileAsync('ssh', sshArgs, {
      timeout: Math.max(RASPBERRY_PI_TIMEOUT_MS, 9000),
      maxBuffer: 64 * 1024
    });
    const values = parseKeyValueLines(stdout);
    action = values.action || action;
    toggleOk = values.toggleOk === 'true';
  } catch (error) {
    const message = String(error.stderr || '').trim()
      || String(error.stdout || '').trim()
      || (error.killed ? 'Raspberry Pi service toggle timed out' : error.message)
      || 'Raspberry Pi service toggle failed';
    toggleError = message.split(/\r?\n/).slice(0, 3).join(' · ');
  }

  let status = await readRaspberryPiStatus();
  let readinessPolls = 1;
  if (toggleOk && !toggleError) {
    const deadline = Date.now() + (action === 'start' ? 14_000 : 6_000);
    while (Date.now() < deadline) {
      const ready = action === 'start'
        ? Boolean(status.ok)
        : status.serviceRunning === false;
      if (ready) break;
      await waitMs(action === 'start' ? 1_500 : 800);
      status = await readRaspberryPiStatus();
      readinessPolls += 1;
    }
  }
  return {
    ...status,
    toggle: {
      ok: toggleOk && !toggleError,
      action,
      host: sshTarget,
      checkedAt,
      durationMs: Date.now() - startedMs,
      readinessPolls,
      ready: action === 'start' ? Boolean(status.ok) : status.serviceRunning === false,
      error: toggleError
    },
    error: toggleError || status.error,
    issues: toggleError ? [toggleError, ...(status.issues || [])] : status.issues
  };
}

async function handleRaspberryPiRequest(req, res) {
  const requestUrl = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
  if (requestUrl.pathname === '/api/jarvis/raspberry-pi/service/toggle') {
    if (req.method !== 'POST') {
      json(res, 405, { ok: false, error: 'Method not allowed. Use POST.' });
      return;
    }
    json(res, 200, await toggleRaspberryPiRoomAudioService());
    return;
  }

  if (requestUrl.pathname === '/api/jarvis/raspberry-pi/ping' || requestUrl.pathname === '/api/jarvis/raspberry-pi') {
    if (!['GET', 'POST'].includes(req.method || 'GET')) {
      json(res, 405, { ok: false, error: 'Method not allowed' });
      return;
    }
    json(res, 200, await readRaspberryPiStatus());
    return;
  }

  json(res, 404, { ok: false, error: 'Unknown Raspberry Pi endpoint' });
}

function buildPhoneAdbScript() {
  const adb = PHONE_ADB_PATH.includes('$HOME')
    ? PHONE_ADB_PATH
    : shellQuote(PHONE_ADB_PATH);
  const serial = shellQuote(PHONE_ADB_SERIAL);
  return [
    'set -u',
    `ADB=${adb}`,
    `SERIAL=${serial}`,
    'if [ ! -x "$ADB" ]; then echo "state=missing-adb"; echo "error=ADB binary not found or not executable"; exit 12; fi',
    '"$ADB" start-server >/dev/null 2>&1 || true',
    'state="$("$ADB" -s "$SERIAL" get-state 2>/dev/null || true)"',
    'echo "state=${state:-missing}"',
    'if [ "$state" != "device" ]; then "$ADB" devices -l 2>&1 | sed "s/^/devices=/"; exit 13; fi',
    'model="$("$ADB" -s "$SERIAL" shell getprop ro.product.model 2>/dev/null | tr -d "\\r" || true)"',
    'android="$("$ADB" -s "$SERIAL" shell getprop ro.build.version.release 2>/dev/null | tr -d "\\r" || true)"',
    'product="$("$ADB" -s "$SERIAL" shell getprop ro.product.name 2>/dev/null | tr -d "\\r" || true)"',
    'echo "model=$model"',
    'echo "android=$android"',
    'echo "product=$product"',
    'echo "serial=$SERIAL"'
  ].join('; ');
}

async function readPhoneAdbStatus() {
  const checkedAt = new Date().toISOString();
  const startedMs = Date.now();
  const missingConfig = !PHONE_ADB_SSH_HOST
    ? 'Phone ADB SSH host is not configured'
    : (!PHONE_ADB_SERIAL ? 'Phone ADB serial is not configured' : '');
  if (missingConfig) {
    return {
      ok: false,
      status: 'offline',
      label: 'NOT CONFIGURED',
      serial: PHONE_ADB_SERIAL,
      model: '',
      android: '',
      product: '',
      state: 'unknown',
      host: '',
      checkedAt,
      durationMs: Date.now() - startedMs,
      error: missingConfig
    };
  }
  const script = buildPhoneAdbScript();
  const sshTarget = PHONE_ADB_SSH_USER
    ? `${PHONE_ADB_SSH_USER}@${PHONE_ADB_SSH_HOST}`
    : PHONE_ADB_SSH_HOST;
  const sshArgs = [
    '-i', expandHome(PHONE_ADB_SSH_KEY),
    '-o', 'IdentitiesOnly=yes',
    '-o', 'BatchMode=yes',
    '-o', 'ConnectTimeout=3',
    sshTarget,
    script
  ];

  try {
    const { stdout, stderr } = await execFileAsync('ssh', sshArgs, {
      timeout: PHONE_ADB_TIMEOUT_MS,
      maxBuffer: 256 * 1024
    });
    const values = parseKeyValueLines(stdout);
    const ok = values.state === 'device';
    return {
      ok,
      status: ok ? 'online' : 'offline',
      label: ok ? 'CONNECTED' : 'OFFLINE',
      serial: values.serial || PHONE_ADB_SERIAL,
      model: values.model || '',
      android: values.android || '',
      product: values.product || '',
      state: values.state || 'unknown',
      host: sshTarget,
      checkedAt,
      durationMs: Date.now() - startedMs,
      error: ok ? '' : (values.error || stderr.trim() || 'ADB target not connected')
    };
  } catch (error) {
    const values = parseKeyValueLines(error.stdout || '');
    const message = values.error
      || String(error.stderr || '').trim()
      || String(error.stdout || '').trim()
      || (error.killed ? 'ADB ping timed out' : error.message)
      || 'ADB ping failed';
    return {
      ok: false,
      status: 'offline',
      label: 'OFFLINE',
      serial: values.serial || PHONE_ADB_SERIAL,
      model: values.model || '',
      android: values.android || '',
      product: values.product || '',
      state: values.state || 'unknown',
      host: sshTarget,
      checkedAt,
      durationMs: Date.now() - startedMs,
      error: message.split(/\r?\n/).slice(0, 3).join(' · ')
    };
  }
}

async function handlePhoneAdbPing(req, res) {
  if (!['GET', 'POST'].includes(req.method || 'GET')) {
    json(res, 405, { ok: false, error: 'Method not allowed' });
    return;
  }
  json(res, 200, await readPhoneAdbStatus());
}

function dashboardVoiceRoomHeaders(extra = {}) {
  const headers = {
    accept: 'application/json',
    ...extra
  };
  if (DASHBOARD_VOICE_ROOM_AUDIO_TOKEN) headers['x-jarvis-room-token'] = DASHBOARD_VOICE_ROOM_AUDIO_TOKEN;
  return headers;
}

async function postJsonWithTimeout(url, payload, { timeoutMs = DASHBOARD_VOICE_TIMEOUT_MS, headers = {} } = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), Math.max(1_000, Number(timeoutMs) || DASHBOARD_VOICE_TIMEOUT_MS));
  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        ...headers
      },
      body: JSON.stringify(payload),
      signal: controller.signal
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(body.error || `HTTP ${response.status}`);
      error.statusCode = response.status;
      error.payload = body;
      throw error;
    }
    return body;
  } finally {
    clearTimeout(timeout);
  }
}

async function readDashboardVoiceStatus() {
  const checkedAt = new Date().toISOString();
  const startedMs = Date.now();
  if (!DASHBOARD_VOICE_ROOM_AUDIO_URL) {
    return {
      ok: false,
      status: 'offline',
      label: 'NOT CONFIGURED',
      roomAudioUrl: '',
      checkedAt,
      durationMs: Date.now() - startedMs,
      error: 'Dashboard voice room-audio URL is not configured.'
    };
  }
  try {
    const health = await fetchJsonWithTimeout(`${DASHBOARD_VOICE_ROOM_AUDIO_URL}/health`, {
      timeoutMs: Math.min(DASHBOARD_VOICE_TIMEOUT_MS, 3000),
      headers: dashboardVoiceRoomHeaders()
    });
    return {
      ok: Boolean(health.ok),
      status: health.ok ? 'online' : 'offline',
      label: health.ok ? 'ONLINE' : 'OFFLINE',
      roomAudioUrl: DASHBOARD_VOICE_ROOM_AUDIO_URL,
      service: health.service || 'operation-jarvis-room-audio',
      asyncAckSupported: Boolean(health.asyncAckSupported),
      processingAckEnabled: Boolean(health.processingAckEnabled),
      processingAckText: health.processingAckText || '',
      model: health.model || '',
      thinking: health.thinking || '',
      checkedAt,
      durationMs: Date.now() - startedMs,
      error: health.ok ? '' : (health.error || 'Room-audio service is not healthy.')
    };
  } catch (error) {
    return {
      ok: false,
      status: 'offline',
      label: 'OFFLINE',
      roomAudioUrl: DASHBOARD_VOICE_ROOM_AUDIO_URL,
      checkedAt,
      durationMs: Date.now() - startedMs,
      error: error?.message || 'Dashboard voice room-audio service is unavailable.'
    };
  }
}

async function handleDashboardVoiceRequest(req, res) {
  const requestUrl = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
  const pathname = requestUrl.pathname.replace(/\/+$/, '') || '/';

  if (pathname === '/api/jarvis/dashboard-voice/status' || pathname === '/api/jarvis/dashboard-voice') {
    if (!['GET', 'POST'].includes(req.method || 'GET')) {
      json(res, 405, { ok: false, error: 'Method not allowed' });
      return;
    }
    json(res, 200, await readDashboardVoiceStatus());
    return;
  }

  if (pathname === '/api/jarvis/dashboard-voice/client-event') {
    if (req.method !== 'POST') {
      json(res, 405, { ok: false, error: 'Method not allowed. Use POST.' });
      return;
    }
    try {
      const payload = await readJsonBody(req, 8 * 1024);
      const level = payload.level === 'error' ? 'error' : 'warn';
      const message = String(payload.message || payload.error || '').replace(/\s+/g, ' ').trim().slice(0, 240);
      const detail = String(payload.detail || '').replace(/\s+/g, ' ').trim().slice(0, 240);
      const state = String(payload.state || '').replace(/\s+/g, ' ').trim().slice(0, 40);
      const userAgent = String(req.headers['user-agent'] || '').slice(0, 180);
      console[level](`[dashboard-voice-client] state=${state || 'unknown'} message=${message || 'unknown'} detail=${detail || '-'} ua=${userAgent}`);
      json(res, 200, { ok: true });
    } catch (error) {
      json(res, 400, { ok: false, error: error?.message || 'Invalid client event.' });
    }
    return;
  }

  if (pathname === '/api/jarvis/dashboard-voice/turn-result') {
    if (req.method !== 'GET') {
      json(res, 405, { ok: false, error: 'Method not allowed. Use GET.' });
      return;
    }
    const turnId = String(requestUrl.searchParams.get('id') || '').trim();
    if (!turnId) {
      json(res, 400, { ok: false, error: 'id is required' });
      return;
    }
    try {
      const payload = await fetchJsonWithTimeout(`${DASHBOARD_VOICE_ROOM_AUDIO_URL}/turn-result?id=${encodeURIComponent(turnId)}`, {
        timeoutMs: DASHBOARD_VOICE_TIMEOUT_MS,
        headers: dashboardVoiceRoomHeaders()
      });
      json(res, payload.ok === false ? 502 : 200, {
        ...payload,
        source: 'dashboard-phone',
        outputTarget: 'phone'
      });
    } catch (error) {
      json(res, error.statusCode || 502, { ok: false, turnId, error: error?.message || 'Failed to poll dashboard voice turn.' });
    }
    return;
  }

  if (pathname === '/api/jarvis/dashboard-voice/turn') {
    if (req.method !== 'POST') {
      json(res, 405, { ok: false, error: 'Method not allowed. Use POST.' });
      return;
    }
    let body;
    try {
      body = await readBufferBody(req, DASHBOARD_VOICE_MAX_BYTES);
    } catch (error) {
      json(res, error.statusCode || 400, { ok: false, error: error.message });
      return;
    }
    if (!body || body.length < 44) {
      json(res, 400, { ok: false, error: 'Dashboard voice upload was empty or too small.' });
      return;
    }
    const mime = String(req.headers['content-type'] || 'audio/wav').split(';')[0].trim().toLowerCase();
    if (mime && mime !== 'audio/wav' && mime !== 'audio/x-wav' && mime !== 'application/octet-stream') {
      json(res, 415, { ok: false, error: `Unsupported dashboard voice content-type: ${mime}. Send audio/wav.` });
      return;
    }
    try {
      const wakeScore = Number.parseFloat(String(req.headers['x-jarvis-dashboard-voice-wake-score'] || '0')) || 0;
      const durationMs = Number.parseInt(String(req.headers['x-jarvis-dashboard-voice-duration-ms'] || '0'), 10) || 0;
      const payload = await postJsonWithTimeout(`${DASHBOARD_VOICE_ROOM_AUDIO_URL}/turn`, {
        audioWavBase64: body.toString('base64'),
        requireWakeWord: false,
        asyncAck: true,
        source: 'dashboard-phone',
        outputTarget: 'phone',
        durationMs,
        wakeScore
      }, {
        timeoutMs: DASHBOARD_VOICE_TIMEOUT_MS,
        headers: dashboardVoiceRoomHeaders()
      });
      const statusCode = payload.ok === false ? 502 : 200;
      json(res, statusCode, {
        ...payload,
        source: 'dashboard-phone',
        outputTarget: 'phone',
        proxiedBy: 'operation-jarvis-dashboard'
      });
    } catch (error) {
      json(res, error.statusCode || 502, {
        ok: false,
        error: error?.message || 'Dashboard voice turn failed.',
        roomAudioUrl: DASHBOARD_VOICE_ROOM_AUDIO_URL
      });
    }
    return;
  }

  json(res, 404, { ok: false, error: 'Unknown dashboard voice endpoint' });
}

let cachedSmartPlugConfig = null;
let cachedSmartPlugConfigAt = 0;
let cachedSmartPlugStatuses = null;
let cachedSmartPlugStatusesAt = 0;
let pendingSmartPlugStatuses = null;

function normalizeSmartPlugKey(value = '') {
  return String(value || '').trim().toLowerCase().replace(/[_\s]+/g, '-');
}

async function readSmartPlugConfig() {
  const now = Date.now();
  if (cachedSmartPlugConfig && now - cachedSmartPlugConfigAt < 10_000) return cachedSmartPlugConfig;
  const raw = await readFile(SMART_PLUG_CONFIG, 'utf8');
  const payload = JSON.parse(raw);
  const plugs = Object.entries(payload.plugs || {}).map(([name, plug = {}]) => ({
    name,
    label: plug.alias || titleFromName(name),
    host: plug.host || '',
    model: plug.model || '',
    hardware: plug.hardware || '',
    mac: plug.mac || '',
    aliases: Array.isArray(plug.aliases) ? plug.aliases : []
  }));
  cachedSmartPlugConfig = { ok: true, config: SMART_PLUG_CONFIG, plugs };
  cachedSmartPlugConfigAt = now;
  return cachedSmartPlugConfig;
}

async function resolveSmartPlugName(value) {
  const key = normalizeSmartPlugKey(value);
  const config = await readSmartPlugConfig();
  const plug = (config.plugs || []).find((candidate) => {
    if (normalizeSmartPlugKey(candidate.name) === key) return true;
    if (normalizeSmartPlugKey(candidate.label) === key) return true;
    return (candidate.aliases || []).some((alias) => normalizeSmartPlugKey(alias) === key);
  });
  if (!plug) throw new Error(`Unknown smart plug: ${value}`);
  return plug.name;
}

function configForSmartPlug(config, name) {
  const key = normalizeSmartPlugKey(name);
  return (config?.plugs || []).find((plug) => normalizeSmartPlugKey(plug.name) === key) || null;
}

async function runSmartPlugCtl(commandArgs, { timeoutMs = SMART_PLUG_TIMEOUT_MS } = {}) {
  const executable = await pathExists(SMART_PLUG_CLI) ? SMART_PLUG_CLI : 'plugctl';
  try {
    const { stdout, stderr } = await execFileAsync(executable, ['--config', SMART_PLUG_CONFIG, '--json', ...commandArgs], {
      cwd: SMART_PLUG_ROOT,
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' },
      timeout: Math.max(1000, Number(timeoutMs) || SMART_PLUG_TIMEOUT_MS),
      maxBuffer: 256 * 1024
    });
    const payload = parseJsonMaybe(stdout) || {};
    if (stderr?.trim()) payload.stderr = stderr.trim();
    return payload;
  } catch (error) {
    const payload = parseJsonMaybe(error.stdout || '') || parseJsonMaybe(error.stderr || '') || {};
    const message = payload.error
      || String(error.stderr || '').trim()
      || String(error.stdout || '').trim()
      || (error.killed ? 'Smart plug command timed out' : error.message)
      || 'Smart plug command failed';
    const wrapped = new Error(message.split(/\r?\n/).slice(0, 3).join(' · '));
    wrapped.payload = payload;
    throw wrapped;
  }
}

function normalizeSmartPlugStatus(rawStatus = {}, configPlug = null, startedMs = Date.now(), checkedAt = new Date().toISOString()) {
  const isOn = rawStatus.is_on === true ? true : (rawStatus.is_on === false ? false : null);
  const status = isOn === true ? 'on' : (isOn === false ? 'off' : 'unknown');
  const name = rawStatus.name || configPlug?.name || '';
  return {
    ok: isOn !== null,
    name,
    label: configPlug?.label || rawStatus.alias || titleFromName(name),
    host: rawStatus.host || configPlug?.host || '',
    alias: rawStatus.alias || configPlug?.label || '',
    model: rawStatus.model || configPlug?.model || '',
    mac: rawStatus.mac || configPlug?.mac || '',
    rssi: rawStatus.rssi ?? null,
    isOn,
    is_on: isOn,
    status,
    checkedAt,
    durationMs: Date.now() - startedMs
  };
}

async function readSmartPlugStatus(name, config = null) {
  const checkedAt = new Date().toISOString();
  const startedMs = Date.now();
  const plugConfig = configForSmartPlug(config, name) || { name, label: titleFromName(name) };
  try {
    const payload = await runSmartPlugCtl(['status', name]);
    return normalizeSmartPlugStatus(payload, plugConfig, startedMs, checkedAt);
  } catch (error) {
    return {
      ok: false,
      name: plugConfig.name || name,
      label: plugConfig.label || titleFromName(name),
      host: plugConfig.host || '',
      alias: plugConfig.label || '',
      model: plugConfig.model || '',
      mac: plugConfig.mac || '',
      rssi: null,
      isOn: null,
      is_on: null,
      status: 'error',
      checkedAt,
      durationMs: Date.now() - startedMs,
      error: error?.message || 'Smart plug status failed'
    };
  }
}

async function readSmartPlugStatuses({ force = false } = {}) {
  const now = Date.now();
  const cacheMs = Math.max(0, Number(SMART_PLUG_STATUS_CACHE_MS) || 0);
  if (!force && cachedSmartPlugStatuses && cacheMs > 0 && now - cachedSmartPlugStatusesAt < cacheMs) return cachedSmartPlugStatuses;
  if (!force && pendingSmartPlugStatuses) return pendingSmartPlugStatuses;

  pendingSmartPlugStatuses = (async () => {
    const checkedAt = new Date().toISOString();
    try {
      const config = await readSmartPlugConfig();
      const plugs = await Promise.all((config.plugs || []).map((plug) => readSmartPlugStatus(plug.name, config)));
      return {
        ok: plugs.every((plug) => plug.ok),
        status: plugs.every((plug) => plug.ok) ? 'online' : 'degraded',
        checkedAt,
        count: plugs.length,
        config: config.config,
        plugs
      };
    } catch (error) {
      return {
        ok: false,
        status: 'error',
        checkedAt,
        count: 0,
        config: SMART_PLUG_CONFIG,
        plugs: [],
        error: error?.message || 'Smart plug status failed'
      };
    }
  })();

  try {
    cachedSmartPlugStatuses = await pendingSmartPlugStatuses;
    cachedSmartPlugStatusesAt = Date.now();
    return cachedSmartPlugStatuses;
  } finally {
    pendingSmartPlugStatuses = null;
  }
}

async function toggleSmartPlug(name) {
  const resolvedName = await resolveSmartPlugName(name);
  const config = await readSmartPlugConfig();
  const plugConfig = configForSmartPlug(config, resolvedName);
  const checkedAt = new Date().toISOString();
  const startedMs = Date.now();
  const payload = await runSmartPlugCtl(['toggle', resolvedName], { timeoutMs: Math.max(SMART_PLUG_TIMEOUT_MS, 10_000) });
  cachedSmartPlugStatuses = null;
  return normalizeSmartPlugStatus(payload, plugConfig, startedMs, checkedAt);
}

async function handleSmartPlugRequest(req, res) {
  const requestUrl = new URL(req.url, `http://${req.headers.host || 'localhost'}`);

  if (requestUrl.pathname === '/api/jarvis/smart-plugs/toggle') {
    if (req.method !== 'POST') {
      json(res, 405, { ok: false, error: 'Method not allowed. Use POST.' });
      return;
    }
    try {
      let plug = requestUrl.searchParams.get('plug') || '';
      if (!plug) {
        const body = await readJsonBody(req).catch(() => ({}));
        plug = body.plug || body.name || '';
      }
      if (!plug) throw new Error('Missing smart plug name.');
      const status = await toggleSmartPlug(plug);
      json(res, 200, { ok: status.ok, action: 'toggle', plug: status });
    } catch (error) {
      json(res, 400, { ok: false, action: 'toggle', error: error?.message || 'Smart plug toggle failed' });
    }
    return;
  }

  if (requestUrl.pathname === '/api/jarvis/smart-plugs/status' || requestUrl.pathname === '/api/jarvis/smart-plugs') {
    if (!['GET', 'POST'].includes(req.method || 'GET')) {
      json(res, 405, { ok: false, error: 'Method not allowed' });
      return;
    }
    const force = requestUrl.searchParams.get('force') === '1' || req.method === 'POST';
    json(res, 200, await readSmartPlugStatuses({ force }));
    return;
  }

  json(res, 404, { ok: false, error: 'Unknown smart plug endpoint' });
}

const weatherCodeLabels = new Map([
  [0, 'Clear'],
  [1, 'Mainly clear'],
  [2, 'Partly cloudy'],
  [3, 'Cloudy'],
  [45, 'Fog'],
  [48, 'Rime fog'],
  [51, 'Light drizzle'],
  [53, 'Drizzle'],
  [55, 'Heavy drizzle'],
  [56, 'Freezing drizzle'],
  [57, 'Freezing drizzle'],
  [61, 'Light rain'],
  [63, 'Rain'],
  [65, 'Heavy rain'],
  [66, 'Freezing rain'],
  [67, 'Freezing rain'],
  [71, 'Light snow'],
  [73, 'Snow'],
  [75, 'Heavy snow'],
  [77, 'Snow grains'],
  [80, 'Rain showers'],
  [81, 'Rain showers'],
  [82, 'Heavy showers'],
  [85, 'Snow showers'],
  [86, 'Heavy snow showers'],
  [95, 'Thunderstorm'],
  [96, 'Thunderstorm hail'],
  [99, 'Thunderstorm hail']
]);

let cachedWeatherStatus = null;
let cachedWeatherStatusAt = 0;
let pendingWeatherStatus = null;

function weatherNeedsAttention(code, precipitationMm, windKph) {
  return code >= 45 || Number(precipitationMm) > 0 || Number(windKph) >= 40;
}

function formatWeatherSummary(current = {}) {
  const code = Number(current.weather_code);
  const condition = weatherCodeLabels.get(code) || 'Conditions';
  const feelsLike = Math.round(Number(current.apparent_temperature));
  const wind = Math.round(Number(current.wind_speed_10m));
  const pieces = [condition];
  if (Number.isFinite(feelsLike)) pieces.push(`feels ${feelsLike}°`);
  if (Number.isFinite(wind) && wind > 0) pieces.push(`wind ${wind} km/h`);
  return pieces.join(' · ');
}

async function readWeatherStatus() {
  const now = Date.now();
  const cacheMs = cachedWeatherStatus?.ok ? WEATHER_STATUS_CACHE_MS : WEATHER_STATUS_ERROR_CACHE_MS;
  if (cachedWeatherStatus && now - cachedWeatherStatusAt < cacheMs) return cachedWeatherStatus;
  if (pendingWeatherStatus) return pendingWeatherStatus;

  pendingWeatherStatus = (async () => {
    const checkedAt = new Date().toISOString();
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), WEATHER_STATUS_TIMEOUT_MS);
    const url = new URL('https://api.open-meteo.com/v1/forecast');
    url.search = new URLSearchParams({
      latitude: String(WEATHER_LATITUDE),
      longitude: String(WEATHER_LONGITUDE),
      current: 'temperature_2m,apparent_temperature,weather_code,precipitation,rain,showers,snowfall,wind_speed_10m,wind_gusts_10m',
      temperature_unit: 'celsius',
      wind_speed_unit: 'kmh',
      precipitation_unit: 'mm',
      timezone: 'America/Toronto'
    }).toString();

    try {
      const response = await fetch(url, {
        method: 'GET',
        headers: { accept: 'application/json' },
        signal: controller.signal
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const body = await response.json().catch(() => ({}));
      const current = body.current || {};
      const code = Number(current.weather_code);
      const precipitationMm = Number(current.precipitation ?? 0);
      const windKph = Number(current.wind_speed_10m ?? 0);
      const temperatureC = Number(current.temperature_2m);
      const feelsLikeC = Number(current.apparent_temperature);

      if (!Number.isFinite(temperatureC)) throw new Error('Missing temperature');

      return {
        ok: true,
        status: 'online',
        location: WEATHER_LOCATION,
        latitude: WEATHER_LATITUDE,
        longitude: WEATHER_LONGITUDE,
        temperatureC,
        feelsLikeC: Number.isFinite(feelsLikeC) ? feelsLikeC : null,
        condition: weatherCodeLabels.get(code) || 'Conditions',
        weatherCode: Number.isFinite(code) ? code : null,
        precipitationMm: Number.isFinite(precipitationMm) ? precipitationMm : 0,
        rainMm: Number(current.rain || 0),
        snowfallCm: Number(current.snowfall || 0),
        windKph: Number.isFinite(windKph) ? windKph : null,
        windGustKph: Number.isFinite(Number(current.wind_gusts_10m)) ? Number(current.wind_gusts_10m) : null,
        summary: formatWeatherSummary(current),
        attention: weatherNeedsAttention(code, precipitationMm, windKph),
        observedAt: current.time || null,
        updatedAt: checkedAt,
        source: 'Open-Meteo'
      };
    } catch (error) {
      if (cachedWeatherStatus?.ok) {
        return {
          ...cachedWeatherStatus,
          ok: true,
          status: 'stale',
          error: error?.name === 'AbortError' ? 'Weather timed out' : (error?.message || 'Weather unavailable'),
          stale: true,
          checkedAt
        };
      }
      return {
        ok: false,
        status: 'offline',
        location: WEATHER_LOCATION,
        error: error?.name === 'AbortError' ? 'Weather timed out' : (error?.message || 'Weather unavailable'),
        updatedAt: checkedAt,
        source: 'Open-Meteo'
      };
    } finally {
      clearTimeout(timeout);
    }
  })();

  try {
    cachedWeatherStatus = await pendingWeatherStatus;
    cachedWeatherStatusAt = Date.now();
    return cachedWeatherStatus;
  } finally {
    pendingWeatherStatus = null;
  }
}

async function handleJarvisDisplay(_req, res) {
  const jarvisPayload = await getJarvisLocalStatus({
    timeoutMs: JARVIS_DISPLAY_LOCAL_STATUS_TIMEOUT_MS,
    cacheMs: JARVIS_LOCAL_STATUS_CACHE_MS,
    allowStale: true
  });
  const local = jarvisPayload.local || {};
  const state = deriveRoomDisplayState(jarvisPayload);
  const [piSessions, omlx16, omlx64, weather, piCost, discordBot] = await Promise.all([
    readPiSessionStatus(),
    readOmlxStatus('16', { force: true }),
    readOmlxStatus('64', { force: true }),
    readWeatherStatus(),
    readPiSessionCostStatus(),
    readDiscordBotStatus()
  ]);
  const events = local.recentEvents || [];
  const lastEvent = events.find((event) => event.eventType !== 'action.start') || events[0] || null;
  const criticalMissing = Object.entries(local.exists || {})
    .filter(([, exists]) => !exists)
    .map(([name]) => name);

  const cameraStatus = getDashboardCameraStatus();

  const errorBanner = criticalMissing.length > 0
    ? `Missing local paths: ${criticalMissing.join(', ')}`
    : (!jarvisPayload.ok ? (jarvisPayload.error || 'Operation JARVIS status check failed') : '');

  json(res, 200, {
    ok: jarvisPayload.ok,
    generatedAt: new Date().toISOString(),
    server: {
      name: os.hostname(),
      uptimeSeconds: Math.round(process.uptime()),
      lanUrls: getLanAddresses().map(({ address }) => `http://${address}:${PORT}`)
    },
    state,
    piSessions,
    piCost,
    discordBot,
    omlx: omlx16,
    omlxServers: {
      '16': omlx16,
      '64': omlx64
    },
    weather,
    camera: cameraStatus,
    last: lastEvent ? {
      action: lastEvent.action || lastEvent.eventType || 'event',
      summary: lastEvent.summary || lastEvent.error || 'Operation JARVIS update',
      ok: lastEvent.ok,
      at: lastEvent.at
    } : {
      action: 'status',
      summary: jarvisPayload.status?.summary || jarvisPayload.error || 'No dashboard events yet.',
      ok: jarvisPayload.ok,
      at: jarvisPayload.generatedAt || null
    },
    output: latestRoomOutput(events),
    errorBanner,
    recentEvents: events.slice(0, 5)
  });
}

async function handleJarvisEvent(req, res) {
  if (!clientHasWriteToken(req)) {
    json(res, 401, { ok: false, error: 'Missing or invalid JARVIS dashboard token.' });
    return;
  }

  const payload = await readJsonBody(req);
  const event = {
    id: payload.id || randomUUID(),
    source: payload.source || 'operation-jarvis',
    eventType: payload.eventType || payload.type || 'event',
    action: payload.action || null,
    ok: payload.ok,
    summary: payload.summary || payload.error || '',
    error: payload.error || null,
    artifacts: Array.isArray(payload.artifacts) ? payload.artifacts.slice(0, 20) : [],
    data: payload.data || null,
    at: payload.at || new Date().toISOString()
  };
  broadcastJarvisEvent(event);
  json(res, 200, { ok: true, event });
}

async function handleJarvisAction(req, res) {
  if (!ENABLE_DASHBOARD_COMMANDS) {
    json(res, 403, {
      ok: false,
      error: 'Dashboard commands are disabled. Set JARVIS_ENABLE_DASHBOARD_COMMANDS=true and JARVIS_DASHBOARD_WRITE_TOKEN to enable allowlisted actions.'
    });
    return;
  }
  if (!DASHBOARD_WRITE_TOKEN) {
    json(res, 403, {
      ok: false,
      error: 'Dashboard commands require JARVIS_DASHBOARD_WRITE_TOKEN before they can be armed.'
    });
    return;
  }
  if (!clientHasWriteToken(req)) {
    json(res, 401, { ok: false, error: 'Missing or invalid JARVIS dashboard token.' });
    return;
  }

  try {
    const payload = await readJsonBody(req);
    const action = String(payload.action || '').trim();
    const commandArgs = buildJarvisActionArgs(action, payload.args || {});
    const result = await runJarvisCli(commandArgs);
    json(res, 200, { ok: true, action, result });
  } catch (error) {
    json(res, error.statusCode || 400, { ok: false, error: error.message, payload: error.payload || null });
  }
}

function artifactKind(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  if (['.jpg', '.jpeg', '.png', '.webp', '.gif'].includes(ext)) return 'image';
  if (['.mp4', '.mov', '.m4v', '.webm'].includes(ext)) return 'video';
  if (['.mp3', '.m4a', '.wav', '.aiff'].includes(ext)) return 'audio';
  if (['.jsonl', '.json'].includes(ext)) return 'analysis';
  return 'file';
}

async function collectJarvisArtifacts() {
  const roots = [operationMediaDir, operationDataDir];
  const ignored = new Set(['.DS_Store']);
  const artifacts = [];

  async function walk(dir, depth = 0) {
    if (depth > 4) return;
    let entries = [];
    try {
      entries = await readdir(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      if (ignored.has(entry.name)) continue;
      const entryPath = path.join(dir, entry.name);
      let entryStat;
      try {
        entryStat = await stat(entryPath);
      } catch {
        continue;
      }
      if (entry.isDirectory()) {
        await walk(entryPath, depth + 1);
      } else if (entry.isFile()) {
        const relative = path.relative(operationRoot, entryPath);
        artifacts.push({
          id: Buffer.from(relative).toString('base64url'),
          name: entry.name,
          relativePath: relative,
          path: entryPath,
          kind: artifactKind(entryPath),
          sizeBytes: entryStat.size,
          modifiedAt: entryStat.mtime.toISOString(),
          url: `/api/jarvis/artifacts/file?path=${encodeURIComponent(relative)}`
        });
      }
    }
  }

  for (const root of roots) await walk(root);
  return artifacts
    .sort((a, b) => b.modifiedAt.localeCompare(a.modifiedAt))
    .slice(0, latestArtifactLimit);
}

async function handleJarvisArtifacts(_req, res) {
  const artifacts = await collectJarvisArtifacts();
  json(res, 200, { ok: true, operationRoot, count: artifacts.length, artifacts });
}

async function handleJarvisArtifactFile(req, res) {
  const requestUrl = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
  const relative = requestUrl.searchParams.get('path') || '';
  const filePath = path.resolve(operationRoot, relative);
  const allowed = [operationMediaDir, operationDataDir].some((root) => filePath.startsWith(path.resolve(root) + path.sep));
  if (!allowed) {
    json(res, 403, { ok: false, error: 'Artifact path is outside allowed Operation JARVIS directories.' });
    return;
  }

  try {
    const fileStat = await stat(filePath);
    if (!fileStat.isFile()) throw new Error('Not a file');
    const ext = path.extname(filePath).toLowerCase();
    res.writeHead(200, dashboardHeaders({
      'content-type': contentTypes.get(ext) || 'application/octet-stream',
      'cache-control': 'no-store',
      'content-length': fileStat.size
    }));
    createReadStream(filePath).pipe(res);
  } catch {
    json(res, 404, { ok: false, error: 'Artifact not found.' });
  }
}

async function pathExists(candidate) {
  try {
    await stat(candidate);
    return true;
  } catch {
    return false;
  }
}

const eventClients = new Set();
const wsClients = new Set();
let reloadSequence = 0;
let liveSequence = 0;

function broadcastEvent(eventName, data) {
  const payload = `event: ${eventName}\ndata: ${JSON.stringify(data)}\n\n`;
  for (const client of eventClients) {
    client.write(payload);
  }
}

function encodeWebSocketFrame(text) {
  const payload = Buffer.from(text);
  const length = payload.length;
  let header;

  if (length < 126) {
    header = Buffer.from([0x81, length]);
  } else if (length < 65536) {
    header = Buffer.alloc(4);
    header[0] = 0x81;
    header[1] = 126;
    header.writeUInt16BE(length, 2);
  } else {
    header = Buffer.alloc(10);
    header[0] = 0x81;
    header[1] = 127;
    header.writeBigUInt64BE(BigInt(length), 2);
  }

  return Buffer.concat([header, payload]);
}

function sendWebSocket(socket, data) {
  if (socket.destroyed) return;
  socket.write(encodeWebSocketFrame(JSON.stringify(data)));
}

function broadcastWebSocket(data) {
  for (const socket of wsClients) {
    sendWebSocket(socket, data);
  }
}

function openEventStream(req, res) {
  res.writeHead(200, dashboardHeaders({
    'content-type': 'text/event-stream; charset=utf-8',
    'cache-control': 'no-store, no-transform',
    connection: 'keep-alive',
    'x-accel-buffering': 'no'
  }));
  res.write(`event: hello\ndata: ${JSON.stringify({ ok: true, reloadSequence })}\n\n`);
  eventClients.add(res);

  const heartbeat = setInterval(() => {
    res.write(`event: heartbeat\ndata: ${JSON.stringify({ now: new Date().toISOString() })}\n\n`);
  }, 25_000);

  req.on('close', () => {
    clearInterval(heartbeat);
    eventClients.delete(res);
  });
}

function triggerClientRefresh(reason = 'manual') {
  reloadSequence += 1;
  const event = {
    ok: true,
    reason,
    reloadSequence,
    clients: eventClients.size + wsClients.size,
    at: new Date().toISOString()
  };
  broadcastEvent('refresh', event);
  broadcastWebSocket({ type: 'refresh', ...event });
  return event;
}

const liveTones = ['cyan', 'green', 'violet', 'pink', 'amber', 'orange', 'blue', 'indigo', 'silver'];
const liveMessages = [
  'Neural route recalibrated',
  'Project telemetry pulse',
  'Workspace scan complete',
  'Subsystem handshake verified',
  'Command surface synchronized',
  'Local network signal confirmed'
];

const pendingCameraCommands = new Map();
const recentCameraCaptures = [];
function triggerLiveAnimation(reason = 'random-test') {
  liveSequence += 1;
  const event = {
    type: 'pulse',
    ok: true,
    reason,
    liveSequence,
    tone: liveTones[Math.floor(Math.random() * liveTones.length)],
    message: liveMessages[Math.floor(Math.random() * liveMessages.length)],
    intensity: Number((0.45 + Math.random() * 0.55).toFixed(2)),
    at: new Date().toISOString(),
    clients: wsClients.size
  };
  broadcastWebSocket(event);
  broadcastEvent('live-pulse', event);
  return event;
}

function cameraMimeBase(value = '') {
  return String(value || '').split(';')[0].trim().toLowerCase();
}

function cameraExtensionForMime(mime = '') {
  const base = cameraMimeBase(mime);
  if (base === 'image/png') return '.png';
  if (base === 'image/webp') return '.webp';
  if (base === 'video/mp4') return '.mp4';
  if (base === 'video/quicktime') return '.mov';
  if (base === 'video/webm') return '.webm';
  if (base.startsWith('image/')) return '.jpg';
  if (base.startsWith('video/')) return '.webm';
  return '.bin';
}

function clampNumber(value, min, max, fallback) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return fallback;
  return Math.min(max, Math.max(min, numeric));
}

function dashboardCameraArtifact(filePath, uploadedAt, sizeBytes) {
  const relativePath = path.relative(operationRoot, filePath);
  return {
    id: Buffer.from(relativePath).toString('base64url'),
    name: path.basename(filePath),
    relativePath,
    path: filePath,
    kind: artifactKind(filePath),
    sizeBytes,
    modifiedAt: uploadedAt,
    url: `/api/jarvis/artifacts/file?path=${encodeURIComponent(relativePath)}`
  };
}

function rememberCameraCapture(capture) {
  recentCameraCaptures.unshift(capture);
  recentCameraCaptures.splice(30);
}

function getDashboardCameraStatus() {
  return {
    ok: DASHBOARD_CAMERA_CLIENT_ENABLED && wsClients.size > 0,
    status: DASHBOARD_CAMERA_CLIENT_ENABLED ? (wsClients.size > 0 ? 'ready' : 'offline') : 'disabled',
    websocketClients: wsClients.size,
    pendingRequests: pendingCameraCommands.size,
    recentCaptures: recentCameraCaptures.slice(0, 8),
    mediaDir: dashboardCameraMediaDir,
    endpoints: {
      status: '/api/jarvis/camera/status',
      snapshot: '/api/jarvis/camera/snapshot',
      record: '/api/jarvis/camera/record'
    }
  };
}

function createPendingCameraCommand(kind, options = {}) {
  const requestId = randomUUID();
  const uploadToken = randomUUID();
  const durationMs = kind === 'record' ? Number(options.durationMs || 0) : 0;
  const timeoutMs = Math.max(5_000, durationMs + CAMERA_COMMAND_TIMEOUT_MS);
  const createdAt = new Date().toISOString();
  const pending = {
    requestId,
    uploadToken,
    kind,
    options,
    createdAt,
    timeoutMs,
    promise: null,
    resolve: null,
    reject: null,
    timer: null
  };

  pending.promise = new Promise((resolve, reject) => {
    pending.resolve = resolve;
    pending.reject = reject;
  });

  pending.timer = setTimeout(() => {
    pendingCameraCommands.delete(requestId);
    const error = new Error(`Dashboard camera ${kind} command timed out after ${Math.round(timeoutMs / 1000)}s.`);
    error.statusCode = 504;
    pending.reject(error);
  }, timeoutMs);
  pending.timer.unref?.();
  pendingCameraCommands.set(requestId, pending);
  return pending;
}

function settlePendingCameraCommand(requestId, result) {
  const pending = pendingCameraCommands.get(requestId);
  if (!pending) return false;
  pendingCameraCommands.delete(requestId);
  clearTimeout(pending.timer);
  pending.resolve(result);
  return true;
}

function buildCameraCommandMessage(pending) {
  return {
    type: 'camera-command',
    command: pending.kind,
    requestId: pending.requestId,
    uploadToken: pending.uploadToken,
    uploadUrl: `/api/jarvis/camera/upload?requestId=${encodeURIComponent(pending.requestId)}`,
    resultUrl: `/api/jarvis/camera/result?requestId=${encodeURIComponent(pending.requestId)}`,
    options: pending.options,
    createdAt: pending.createdAt,
    timeoutMs: pending.timeoutMs
  };
}

async function handleCameraCommandRequest(req, res, kind) {
  if (req.method !== 'POST') {
    json(res, 405, { ok: false, error: 'Method not allowed. Use POST.' });
    return;
  }
  if (!DASHBOARD_CAMERA_CLIENT_ENABLED) {
    json(res, 410, { ok: false, error: 'Dashboard camera client is disabled on the active HUD.' });
    return;
  }
  if (!clientCanUseDebugEndpoint(req)) {
    json(res, 403, { ok: false, error: 'Camera commands are limited to localhost unless debug endpoints are enabled or authenticated.' });
    return;
  }
  if (wsClients.size < 1) {
    json(res, 503, { ok: false, error: 'No dashboard WebSocket clients are connected; open the phone dashboard first.' });
    return;
  }

  let payload = {};
  try {
    payload = await readJsonBody(req);
  } catch (error) {
    json(res, error.statusCode || 400, { ok: false, error: error.message });
    return;
  }

  const options = kind === 'record'
    ? {
        durationMs: Math.round(clampNumber(payload.durationMs ?? Number(payload.durationSeconds || 5) * 1000, 250, CAMERA_RECORD_MAX_DURATION_MS, 5_000)),
        mime: String(payload.mime || ''),
        preferAudio: Boolean(payload.audio)
      }
    : {
        mime: String(payload.mime || 'image/jpeg'),
        quality: clampNumber(payload.quality, 0.1, 1, 0.86)
      };

  const pending = createPendingCameraCommand(kind, options);
  broadcastWebSocket(buildCameraCommandMessage(pending));
  broadcastEvent('camera-command', {
    ok: true,
    requestId: pending.requestId,
    command: pending.kind,
    options,
    at: pending.createdAt,
    clients: wsClients.size
  });

  try {
    const result = await pending.promise;
    json(res, result.ok === false ? 502 : 200, result);
  } catch (error) {
    json(res, error.statusCode || 500, {
      ok: false,
      requestId: pending.requestId,
      command: kind,
      error: error.message,
      clients: wsClients.size
    });
  }
}

async function handleCameraUpload(req, res) {
  if (!['POST', 'PUT'].includes(req.method || '')) {
    json(res, 405, { ok: false, error: 'Method not allowed. Use POST or PUT.' });
    return;
  }

  const requestUrl = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
  const requestId = requestUrl.searchParams.get('requestId') || '';
  const pending = pendingCameraCommands.get(requestId);
  const providedToken = req.headers['x-jarvis-camera-token'] || requestUrl.searchParams.get('token') || '';

  if (!pending) {
    json(res, 404, { ok: false, error: 'Camera command request was not found or already completed.' });
    return;
  }
  if (providedToken !== pending.uploadToken) {
    json(res, 401, { ok: false, error: 'Invalid camera upload token.' });
    return;
  }

  let body;
  try {
    body = await readBufferBody(req, CAMERA_UPLOAD_MAX_BYTES);
  } catch (error) {
    json(res, error.statusCode || 400, { ok: false, requestId, error: error.message });
    return;
  }
  if (!body || body.length < 1) {
    json(res, 400, { ok: false, requestId, error: 'Camera upload was empty.' });
    return;
  }

  const uploadedAt = new Date().toISOString();
  const mime = cameraMimeBase(req.headers['content-type'] || requestUrl.searchParams.get('mime') || pending.options.mime || 'application/octet-stream');
  const mediaKind = pending.kind === 'record' ? 'video' : 'snapshot';
  const ext = cameraExtensionForMime(mime);
  const dayDir = path.join(dashboardCameraMediaDir, uploadedAt.slice(0, 10));
  const safeStamp = uploadedAt.replace(/[:.]/g, '-');
  const filePath = path.join(dayDir, `${mediaKind}-${safeStamp}-${requestId.slice(0, 8)}${ext}`);

  try {
    await mkdir(dayDir, { recursive: true });
    await writeFile(filePath, body);
  } catch (error) {
    json(res, 500, { ok: false, requestId, error: `Failed to save camera upload: ${error.message}` });
    return;
  }

  const artifact = dashboardCameraArtifact(filePath, uploadedAt, body.length);
  const result = {
    ok: true,
    requestId,
    command: pending.kind,
    mediaKind,
    mime,
    sizeBytes: body.length,
    path: filePath,
    relativePath: artifact.relativePath,
    url: artifact.url,
    durationMs: Number(requestUrl.searchParams.get('durationMs') || pending.options.durationMs || 0) || null,
    width: Number(requestUrl.searchParams.get('width') || 0) || null,
    height: Number(requestUrl.searchParams.get('height') || 0) || null,
    uploadedAt,
    artifact
  };

  try {
    await writeFile(`${filePath}.json`, `${JSON.stringify({ ...result, uploadToken: undefined }, null, 2)}\n`);
  } catch {
    // Sidecar metadata is useful but not required.
  }

  rememberCameraCapture(result);
  settlePendingCameraCommand(requestId, result);
  broadcastJarvisEvent({
    id: `camera-${requestId}`,
    source: 'operation-jarvis-dashboard',
    eventType: 'action.complete',
    action: `camera-${pending.kind}`,
    ok: true,
    summary: pending.kind === 'record'
      ? `Recorded dashboard camera video: ${artifact.relativePath}`
      : `Captured dashboard camera photo: ${artifact.relativePath}`,
    artifacts: [artifact],
    data: { requestId, mediaKind, mime, sizeBytes: body.length, durationMs: result.durationMs },
    at: uploadedAt
  });
  json(res, 200, result);
}

async function handleCameraResult(req, res) {
  if (req.method !== 'POST') {
    json(res, 405, { ok: false, error: 'Method not allowed. Use POST.' });
    return;
  }

  const requestUrl = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
  const requestId = requestUrl.searchParams.get('requestId') || '';
  const pending = pendingCameraCommands.get(requestId);
  if (!pending) {
    json(res, 404, { ok: false, error: 'Camera command request was not found or already completed.' });
    return;
  }

  let payload = {};
  try {
    payload = await readJsonBody(req);
  } catch (error) {
    json(res, error.statusCode || 400, { ok: false, error: error.message });
    return;
  }

  const providedToken = req.headers['x-jarvis-camera-token'] || payload.uploadToken || requestUrl.searchParams.get('token') || '';
  if (providedToken !== pending.uploadToken) {
    json(res, 401, { ok: false, error: 'Invalid camera result token.' });
    return;
  }

  const result = {
    ok: Boolean(payload.ok),
    requestId,
    command: pending.kind,
    error: payload.error || (payload.ok ? null : 'Camera command failed.'),
    detail: payload.detail || null,
    at: new Date().toISOString()
  };
  settlePendingCameraCommand(requestId, result);
  json(res, 200, result);
}

async function handleCameraStatus(_req, res) {
  json(res, 200, getDashboardCameraStatus());
}

function scheduleRandomLivePulse() {
  const delay = 4_000 + Math.floor(Math.random() * 8_000);
  setTimeout(() => {
    triggerLiveAnimation('random-interval-test');
    scheduleRandomLivePulse();
  }, delay).unref?.();
}

async function serveStatic(req, res) {
  const requestUrl = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
  let pathname = decodeURIComponent(requestUrl.pathname);

  if (pathname === '/') pathname = '/index.html';

  const unsafePath = path.normalize(pathname).replace(/^\.\.(\/|\\|$)/, '');
  let filePath = path.resolve(publicDir, `.${unsafePath}`);

  const relativePath = path.relative(publicDir, filePath);
  if (relativePath.startsWith('..') || path.isAbsolute(relativePath)) {
    json(res, 403, { error: 'Forbidden' });
    return;
  }

  try {
    const fileStat = await stat(filePath);
    if (fileStat.isDirectory()) {
      filePath = path.join(filePath, 'index.html');
    }

    const ext = path.extname(filePath).toLowerCase();
    const cacheableVendorAsset = pathname.startsWith('/vendor/onnxruntime-web/') || ext === '.onnx' || ext === '.wasm';
    const cacheHeaders = cacheableVendorAsset
      ? { 'cache-control': 'public, max-age=31536000, immutable' }
      : {
          'cache-control': 'no-store, no-cache, must-revalidate, proxy-revalidate',
          pragma: 'no-cache',
          expires: '0'
        };
    res.writeHead(200, dashboardHeaders({
      'content-type': contentTypes.get(ext) || 'application/octet-stream',
      ...cacheHeaders
    }));
    createReadStream(filePath).pipe(res);
  } catch {
    res.writeHead(404, dashboardHeaders({
      'content-type': 'text/plain; charset=utf-8',
      'cache-control': 'no-store'
    }));
    res.end('Not found');
  }
}

const startedAt = new Date();

const server = createServer(async (req, res) => {
  try {
    if (req.url?.startsWith('/api/jarvis/display')) {
      await handleJarvisDisplay(req, res);
      return;
    }

    if (req.url?.startsWith('/api/jarvis/phone-adb')) {
      await handlePhoneAdbPing(req, res);
      return;
    }

    if (req.url?.startsWith('/api/jarvis/dashboard-voice')) {
      await handleDashboardVoiceRequest(req, res);
      return;
    }

    if (req.url?.startsWith('/api/jarvis/omlx')) {
      await handleOmlxRequest(req, res);
      return;
    }

    if (req.url?.startsWith('/api/jarvis/raspberry-pi')) {
      await handleRaspberryPiRequest(req, res);
      return;
    }

    if (req.url?.startsWith('/api/jarvis/smart-plugs')) {
      await handleSmartPlugRequest(req, res);
      return;
    }

    if (req.url?.startsWith('/api/jarvis/status')) {
      await handleJarvisStatus(req, res);
      return;
    }

    if (req.url?.startsWith('/api/jarvis/events')) {
      if (req.method !== 'POST') {
        json(res, 405, { ok: false, error: 'Method not allowed' });
        return;
      }
      await handleJarvisEvent(req, res);
      return;
    }

    if (req.url?.startsWith('/api/jarvis/actions')) {
      if (req.method !== 'POST') {
        json(res, 405, { ok: false, error: 'Method not allowed' });
        return;
      }
      await handleJarvisAction(req, res);
      return;
    }

    if (req.url?.startsWith('/api/jarvis/camera/snapshot')) {
      await handleCameraCommandRequest(req, res, 'snapshot');
      return;
    }

    if (req.url?.startsWith('/api/jarvis/camera/record')) {
      await handleCameraCommandRequest(req, res, 'record');
      return;
    }

    if (req.url?.startsWith('/api/jarvis/camera/upload')) {
      await handleCameraUpload(req, res);
      return;
    }

    if (req.url?.startsWith('/api/jarvis/camera/result')) {
      await handleCameraResult(req, res);
      return;
    }

    const requestPath = new URL(req.url || '/', `http://${req.headers.host || 'localhost'}`).pathname;
    if (requestPath === '/api/jarvis/camera' || requestPath === '/api/jarvis/camera/status') {
      await handleCameraStatus(req, res);
      return;
    }

    if (req.url?.startsWith('/api/jarvis/artifacts/file')) {
      await handleJarvisArtifactFile(req, res);
      return;
    }

    if (req.url?.startsWith('/api/jarvis/artifacts')) {
      await handleJarvisArtifacts(req, res);
      return;
    }

    if (req.url?.startsWith('/api/status')) {
      const lanAddresses = getLanAddresses();
      json(res, 200, {
        ok: true,
        name: 'operation-jarvis-dashboard',
        startedAt: startedAt.toISOString(),
        uptimeSeconds: Math.round(process.uptime()),
        host: HOST,
        port: PORT,
        hostname: os.hostname(),
        platform: `${os.type()} ${os.release()}`,
        node: process.version,
        commandsEnabled: ENABLE_DASHBOARD_COMMANDS && Boolean(DASHBOARD_WRITE_TOKEN),
        debugEndpointsEnabled: ENABLE_DEBUG_ENDPOINTS,
        ambientPulsesEnabled: ENABLE_AMBIENT_PULSES,
        camera: getDashboardCameraStatus(),
        dashboardVoice: await readDashboardVoiceStatus(),
        lanUrls: lanAddresses.map(({ address }) => `http://${address}:${PORT}`),
        lanAddresses
      });
      return;
    }

    if (req.url?.startsWith('/api/projects')) {
      const projects = await getProjects();
      json(res, 200, {
        ok: true,
        workspace: workspaceRoot,
        count: projects.length,
        generatedAt: new Date().toISOString(),
        projects
      });
      return;
    }

    if (req.url?.startsWith('/api/events')) {
      openEventStream(req, res);
      return;
    }

    if (req.url?.startsWith('/api/refresh') || req.url?.startsWith('/api/reload')) {
      if (req.method !== 'POST') {
        json(res, 405, { ok: false, error: 'Method not allowed. Use POST.' });
        return;
      }
      if (!clientCanUseDebugEndpoint(req)) {
        json(res, 403, { ok: false, error: 'Debug refresh endpoint is limited to localhost unless explicitly enabled or authenticated.' });
        return;
      }
      const requestUrl = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
      const reason = requestUrl.searchParams.get('reason') || 'manual';
      json(res, 200, triggerClientRefresh(reason));
      return;
    }

    if (req.url?.startsWith('/api/pulse')) {
      if (req.method !== 'POST') {
        json(res, 405, { ok: false, error: 'Method not allowed. Use POST.' });
        return;
      }
      if (!clientCanUseDebugEndpoint(req)) {
        json(res, 403, { ok: false, error: 'Debug pulse endpoint is limited to localhost unless explicitly enabled or authenticated.' });
        return;
      }
      const requestUrl = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
      const reason = requestUrl.searchParams.get('reason') || 'manual-test';
      json(res, 200, triggerLiveAnimation(reason));
      return;
    }

    if (req.url?.startsWith('/api/live')) {
      json(res, 200, {
        ok: true,
        websocketClients: wsClients.size,
        eventClients: eventClients.size,
        liveSequence,
        reloadSequence,
        debugEndpointsEnabled: ENABLE_DEBUG_ENDPOINTS,
        ambientPulsesEnabled: ENABLE_AMBIENT_PULSES,
        pulseEndpoint: '/api/pulse',
        websocketEndpoint: '/ws'
      });
      return;
    }

    await serveStatic(req, res);
  } catch (error) {
    console.error(`[operation-jarvis-dashboard] request failed: ${error.stack || error.message}`);
    json(res, 500, { ok: false, error: 'Internal server error' });
  }
});

server.on('upgrade', (req, socket) => {
  const requestUrl = new URL(req.url || '/', `http://${req.headers.host || 'localhost'}`);
  if (requestUrl.pathname !== '/ws') {
    socket.write('HTTP/1.1 404 Not Found\r\n\r\n');
    socket.destroy();
    return;
  }

  const key = req.headers['sec-websocket-key'];
  if (!key) {
    socket.write('HTTP/1.1 400 Bad Request\r\n\r\n');
    socket.destroy();
    return;
  }

  const accept = createHash('sha1')
    .update(`${key}258EAFA5-E914-47DA-95CA-C5AB0DC85B11`)
    .digest('base64');

  socket.write([
    'HTTP/1.1 101 Switching Protocols',
    'Upgrade: websocket',
    'Connection: Upgrade',
    `Sec-WebSocket-Accept: ${accept}`,
    '\r\n'
  ].join('\r\n'));

  socket.id = randomUUID();
  wsClients.add(socket);
  sendWebSocket(socket, {
    type: 'hello',
    ok: true,
    clientId: socket.id,
    liveSequence,
    reloadSequence,
    clients: wsClients.size,
    at: new Date().toISOString()
  });
  broadcastWebSocket({ type: 'clients', clients: wsClients.size, at: new Date().toISOString() });

  socket.on('data', (buffer) => {
    // Minimal frame handling: respond to browser close/ping frames, ignore client messages otherwise.
    const opcode = buffer[0] & 0x0f;
    if (opcode === 0x8) {
      if (!socket.destroyed) socket.write(Buffer.from([0x88, 0x00]));
      socket.end();
    } else if (opcode === 0x9) {
      if (!socket.destroyed) socket.write(Buffer.from([0x8a, 0x00]));
    }
  });

  socket.on('close', () => {
    wsClients.delete(socket);
    broadcastWebSocket({ type: 'clients', clients: wsClients.size, at: new Date().toISOString() });
  });

  socket.on('error', () => {
    wsClients.delete(socket);
  });
});

server.on('error', (error) => {
  console.error(`[operation-jarvis-dashboard] failed to start: ${error.message}`);
  if (error.code === 'EADDRINUSE') {
    console.error(`[operation-jarvis-dashboard] port ${PORT} is already in use. Try PORT=8788 npm start`);
  }
  process.exit(1);
});

if (ENABLE_AMBIENT_PULSES) {
  scheduleRandomLivePulse();
}

startPiSessionStatusWatcher().catch((error) => {
  console.error(`[operation-jarvis-dashboard] failed to start Pi session watcher: ${error.message}`);
});

server.listen(PORT, HOST, () => {
  const lanUrls = getLanAddresses().map(({ address }) => `http://${address}:${PORT}`);
  console.log(`[operation-jarvis-dashboard] listening on http://${HOST}:${PORT}`);
  if (lanUrls.length > 0) {
    console.log('[operation-jarvis-dashboard] LAN URLs:');
    for (const url of lanUrls) console.log(`  ${url}`);
  } else {
    console.log('[operation-jarvis-dashboard] no non-internal IPv4 LAN addresses detected yet');
  }
});
