const timeEl = document.querySelector('#display-time');
const periodEl = document.querySelector('#display-period');
const dateEl = document.querySelector('#display-date');
const alarmDateLine = document.querySelector('#alarm-date-line');
const errorEl = document.querySelector('#display-error');
const jarvisBrand = document.querySelector('#jarvis-brand');
const jarvisBrandIndicator = document.querySelector('#jarvis-brand-indicator');
const cameraPanel = document.querySelector('#camera-test-panel');
const cameraPreview = document.querySelector('#camera-preview');
const cameraStatus = document.querySelector('#camera-status');
const cameraCard = document.querySelector('#camera-card');
const reloadButton = document.querySelector('#display-reload-button');
const raspberryPiButton = document.querySelector('#right-reserved-card-2');
const raspberryPiIconEl = document.querySelector('#display-raspberry-pi-icon');
const raspberryPiDetailEl = document.querySelector('#display-raspberry-pi-detail');
const phoneAdbButton = document.querySelector('#right-reserved-card-3');
const phoneAdbIconEl = document.querySelector('#display-phone-adb-icon');
const phoneAdbDetailEl = document.querySelector('#display-phone-adb-detail');
const stateCard = document.querySelector('#state-card');
const stateLabel = document.querySelector('#display-state-label');
const stateDetail = document.querySelector('#display-state-detail');
const uptimeEl = document.querySelector('#display-dashboard-uptime');
const weatherCard = document.querySelector('#weather-card');
const weatherTempEl = document.querySelector('#display-weather-temp');
const weatherDetailEl = document.querySelector('#display-weather-detail');
const headerWeatherEl = document.querySelector('#display-header-weather');
const headerPiSessionsEl = document.querySelector('#display-header-pi-sessions');
const activeModelsCard = document.querySelector('#active-models-card');
const activeModelsSummaryEl = document.querySelector('#active-models-summary');
const activeModelsStatusEl = document.querySelector('#active-models-status');
const activeModelsMemoryFillEl = document.querySelector('#active-models-memory-fill');
const activeModelsMemoryTextEl = document.querySelector('#active-models-memory-text');
const activeModelsListEl = document.querySelector('#active-models-list');
const activeModelsFooterEl = document.querySelector('#active-models-footer');
const omlxButtons = Array.from(document.querySelectorAll('[data-omlx-server]'));
const omlxControlById = new Map(omlxButtons.map((button) => {
  const serverId = normalizeOmlxClientServerId(button.dataset.omlxServer);
  return [serverId, {
    button,
    labelEl: button.querySelector('.omlx-label, .eyebrow'),
    iconEl: button.querySelector('.omlx-status-icon'),
    detailEl: button.querySelector('.omlx-detail, .hud-mini-detail')
  }];
}));
const smartPlugGrid = document.querySelector('#smart-plug-grid');
let smartPlugButtons = Array.from(document.querySelectorAll('[data-smart-plug]'));
const smartPlugButtonByName = new Map(smartPlugButtons.map((button) => [button.dataset.smartPlug, button]));
const serverEl = document.querySelector('#display-server');
const refreshEl = document.querySelector('#display-refresh');

const toneClasses = ['tone-cyan', 'tone-green', 'tone-violet', 'tone-pink', 'tone-amber', 'tone-orange', 'tone-blue', 'tone-indigo', 'tone-silver'];
const INDICATOR_REFRESH_INTERVAL_MS = 30_000;
const ACTIVE_MODELS_REFRESH_INTERVAL_MS = 1_000;
let latestDisplayPayload = null;
let dashboardUptimeBaseSeconds = 0;
let dashboardUptimeSyncedAt = Date.now();
let cameraStream = null;
let cameraStartPromise = null;
let cameraAspectRatio = 4 / 3;
let cameraPositionFrame = 0;
const omlxPingInFlight = new Map();
const omlxToggleInFlight = new Map();
const latestOmlxStatuses = new Map();
let activeModelsUsageInFlight = null;
let raspberryPiPingInFlight = null;
let raspberryPiToggleInFlight = null;
let latestRaspberryPiStatus = null;
let phoneAdbPingInFlight = null;
let smartPlugStatusInFlight = null;
const smartPlugToggleInFlight = new Map();
const latestSmartPlugStatuses = new Map();
let lastClockDisplay = '';
let lastPeriodDisplay = '';
let lastHeaderDateDisplay = '';
let lastAlarmDateDisplay = '';

function updateClock() {
  const now = new Date();
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/Toronto',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true
  }).formatToParts(now);
  const hour = parts.find((part) => part.type === 'hour')?.value || '--';
  const minute = parts.find((part) => part.type === 'minute')?.value || '--';
  const period = parts.find((part) => part.type === 'dayPeriod')?.value || '';

  const clockDisplay = `${hour}:${minute}`;
  const periodDisplay = period.toUpperCase();
  if (clockDisplay !== lastClockDisplay) {
    timeEl.textContent = clockDisplay;
    lastClockDisplay = clockDisplay;
  }
  if (periodDisplay !== lastPeriodDisplay) {
    periodEl.textContent = periodDisplay;
    lastPeriodDisplay = periodDisplay;
  }

  const headerDateDisplay = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/Toronto',
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    timeZoneName: 'short'
  }).format(now);
  if (headerDateDisplay !== lastHeaderDateDisplay) {
    dateEl.textContent = headerDateDisplay;
    lastHeaderDateDisplay = headerDateDisplay;
  }

  const alarmDateDisplay = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/Toronto',
    weekday: 'long',
    month: 'long',
    day: 'numeric'
  }).format(now);
  if (alarmDateDisplay !== lastAlarmDateDisplay) {
    alarmDateLine.textContent = alarmDateDisplay;
    lastAlarmDateDisplay = alarmDateDisplay;
    queueCameraPanelPosition();
  }
}

function formatRelative(iso) {
  if (!iso) return '—';
  const ms = Date.now() - Date.parse(iso);
  if (!Number.isFinite(ms)) return '—';
  const seconds = Math.max(0, Math.round(ms / 1000));
  if (seconds < 10) return 'just now';
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  return `${hours}h ago`;
}

function finiteDashboardNumber(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatDashboardBytes(value) {
  const bytes = finiteDashboardNumber(value);
  if (bytes === null) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let scaled = Math.abs(bytes);
  let unitIndex = 0;
  while (scaled >= 1024 && unitIndex < units.length - 1) {
    scaled /= 1024;
    unitIndex += 1;
  }
  const signed = bytes < 0 ? -scaled : scaled;
  const digits = unitIndex >= 3 ? 2 : (unitIndex === 0 ? 0 : 1);
  return `${signed.toFixed(digits)} ${units[unitIndex]}`;
}

function formatDashboardBytesCompact(value) {
  return formatDashboardBytes(value).replace(/\s+/g, '');
}

function formatCompactDashboardNumber(value) {
  const parsed = finiteDashboardNumber(value);
  if (parsed === null) return '—';
  try {
    return new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(parsed);
  } catch {
    return parsed.toLocaleString();
  }
}

function shortDashboardModelName(raw = '') {
  const value = String(raw || '').split('/').filter(Boolean).pop() || String(raw || 'Model');
  return value.length > 34 ? `${value.slice(0, 31)}…` : value;
}

function compactDashboardModelName(raw = '') {
  const value = shortDashboardModelName(raw)
    .replace(/[-_](instruct|chat|mlx|gguf|awq|gptq|q\d+(_k_m)?|\d+bit|fp16|bf16)$/i, '')
    .replace(/[-_](instruct|chat|mlx|gguf|awq|gptq|q\d+(_k_m)?|\d+bit|fp16|bf16)$/i, '');
  const size = value.match(/(?:^|[-_])(\d+(?:\.\d+)?B)(?:[-_]|$)/i)?.[1]?.toUpperCase();
  if (/qwen/i.test(value) && size) return `Q${size}`;
  if (/llama/i.test(value) && size) return `L${size}`;
  if (/mistral/i.test(value) && size) return `M${size}`;
  if (/mixtral/i.test(value) && size) return `Mix${size}`;
  if (/gemma/i.test(value) && size) return `G${size}`;
  if (/deepseek/i.test(value) && size) return `DS${size}`;
  if (/phi/i.test(value) && size) return `Phi${size}`;
  return value.length > 10 ? `${value.slice(0, 9)}…` : value;
}

function compactOmlxServerLabel(server = {}) {
  const serverId = String(server.serverId || '').trim();
  if (serverId) return serverId.replace(/^omlx[-_]?/i, '');
  return String(server.name || 'OMLX').replace(/^OMLX[-_]?/i, '') || 'OMLX';
}

function clearActiveModelsList() {
  if (!activeModelsListEl) return;
  while (activeModelsListEl.firstChild) activeModelsListEl.removeChild(activeModelsListEl.firstChild);
}

function makeActiveModelsNode(tag, className = '', text = '') {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== '') node.textContent = text;
  return node;
}

function appendActiveModelsEmpty(server, container) {
  const empty = makeActiveModelsNode('div', 'active-models-empty');
  empty.textContent = server.ok ? 'idle' : (server.error ? 'offline' : 'offline');
  container.appendChild(empty);
}

function formatDashboardSeconds(value, compact = false) {
  const seconds = finiteDashboardNumber(value);
  if (seconds === null) return '';
  if (seconds < 1) return compact ? '<1s' : 'under 1s';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  const remaining = Math.round(seconds % 60);
  if (minutes < 60) return compact ? `${minutes}m` : `${minutes}m ${remaining}s`;
  const hours = Math.floor(minutes / 60);
  return compact ? `${hours}h` : `${hours}h ${minutes % 60}m`;
}

function formatDashboardTps(value) {
  const tps = finiteDashboardNumber(value);
  if (tps === null || tps <= 0) return '';
  return `${tps >= 100 ? Math.round(tps) : tps.toFixed(1)}t/s`;
}

function shortDashboardRequestId(value = '') {
  const raw = String(value || '').trim();
  if (!raw) return 'request';
  return (raw.split('-')[0] || raw).slice(0, 8);
}

function activeModelRequestCounts(model = {}) {
  const prefilling = Array.isArray(model.prefilling) ? model.prefilling.length : 0;
  const generating = Array.isArray(model.generating) ? model.generating.length : 0;
  const activities = Array.isArray(model.activities) ? model.activities.length : 0;
  const waiting = Array.isArray(model.waiting) ? model.waiting.length : 0;
  return {
    active: Math.max(Number(model.activeRequests || 0), prefilling + generating + activities),
    waiting: Math.max(Number(model.waitingRequests || 0), waiting),
    prefilling,
    generating,
    activities
  };
}

function activeModelRailPriority(model = {}) {
  const counts = activeModelRequestCounts(model);
  return (counts.active * 1000) + (counts.waiting * 100) + (model.isLoading ? 20 : 0) + (model.loaded ? 10 : 0) + (model.pinned ? 1 : 0);
}

function appendActiveModelLiveLine(container, phase, title, detail = '', options = {}) {
  const line = makeActiveModelsNode('div', 'active-model-live-line');
  line.dataset.phase = phase;
  const titleEl = makeActiveModelsNode('strong', '', title);
  line.appendChild(titleEl);
  const progress = finiteDashboardNumber(options.progressPercent);
  if (progress !== null) {
    const track = makeActiveModelsNode('span', 'active-model-progress-track');
    const fill = makeActiveModelsNode('i');
    fill.style.width = `${Math.max(0, Math.min(100, progress))}%`;
    track.appendChild(fill);
    line.appendChild(track);
    line.appendChild(makeActiveModelsNode('span', 'active-model-live-pct', `${Math.round(progress)}%`));
  }
  if (detail) line.appendChild(makeActiveModelsNode('span', 'active-model-live-detail', detail));
  if (options.subdetail) line.appendChild(makeActiveModelsNode('span', 'active-model-live-subdetail', options.subdetail));
  container.appendChild(line);
}

function appendActiveModelLiveRows(row, model = {}) {
  const live = makeActiveModelsNode('div', 'active-model-live');
  const prefilling = Array.isArray(model.prefilling) ? model.prefilling : [];
  const generating = Array.isArray(model.generating) ? model.generating : [];
  const waiting = Array.isArray(model.waiting) ? model.waiting : [];
  const activities = Array.isArray(model.activities) ? model.activities : [];
  let shown = 0;

  for (const item of prefilling) {
    if (shown >= 2) break;
    const processed = finiteDashboardNumber(item.processed);
    const total = finiteDashboardNumber(item.total);
    const pct = processed !== null && total && total > 0 ? Math.max(0, Math.min(99, (processed / total) * 100)) : null;
    const title = 'PF';
    const details = [];
    if (processed !== null && total) details.push(`${formatCompactDashboardNumber(processed)}/${formatCompactDashboardNumber(total)}`);
    const elapsed = formatDashboardSeconds(item.elapsed, true);
    if (elapsed) details.push(elapsed);
    const tps = formatDashboardTps(item.speed);
    const eta = formatDashboardSeconds(item.eta, true);
    const perf = [tps, eta ? `${eta}` : ''].filter(Boolean).join(' · ');
    appendActiveModelLiveLine(live, 'prefill', title, details.join(' · '), {
      progressPercent: pct,
      subdetail: perf
    });
    shown += 1;
  }

  for (const item of generating) {
    if (shown >= 2) break;
    const title = 'GEN';
    const details = [];
    if (finiteDashboardNumber(item.generatedTokens) !== null) details.push(`${formatCompactDashboardNumber(item.generatedTokens)}`);
    const tps = formatDashboardTps(item.tokensPerSecond);
    if (tps) details.push(tps);
    const elapsed = formatDashboardSeconds(item.elapsedSeconds, true);
    if (elapsed) details.push(elapsed);
    appendActiveModelLiveLine(live, 'generate', title, details.join(' · '));
    shown += 1;
  }

  for (const item of waiting) {
    if (shown >= 2) break;
    const position = finiteDashboardNumber(item.queuePosition);
    const title = `queue${position ? ` #${position}` : ''}`;
    const details = [];
    if (finiteDashboardNumber(item.promptTokens) !== null) details.push(`${formatCompactDashboardNumber(item.promptTokens)} tok`);
    const elapsed = formatDashboardSeconds(item.elapsedSeconds, true);
    if (elapsed) details.push(`${elapsed} wait`);
    appendActiveModelLiveLine(live, 'queued', title, details.join(' · '));
    shown += 1;
  }

  for (const item of activities) {
    if (shown >= 2) break;
    appendActiveModelLiveLine(live, 'activity', item.kind || 'activity');
    shown += 1;
  }

  const remaining = prefilling.length + generating.length + waiting.length + activities.length - shown;
  if (remaining > 0) appendActiveModelLiveLine(live, 'more', `+${remaining} more`);
  if (shown > 0 || remaining > 0) row.appendChild(live);
}

function activeModelsServerRequestTotal(server = {}) {
  return Number(server.activeRequests || 0) + Number(server.waitingRequests || 0);
}

function activeModelsServerUiState(server = {}) {
  if (!server.ok) return 'offline';
  if (activeModelsServerRequestTotal(server) > 0) return 'active';
  if ((Array.isArray(server.models) ? server.models : []).some((model) => model.isLoading)) return 'loading';
  return 'online';
}

function activeModelsModelRequestTotal(model = {}) {
  const counts = activeModelRequestCounts(model);
  return counts.active + counts.waiting;
}

function primaryActiveModelsModel(server = {}) {
  const models = Array.isArray(server.models) ? server.models : [];
  return [...models].sort((a, b) => activeModelRailPriority(b) - activeModelRailPriority(a))[0] || null;
}

function selectActiveModelsFocus(servers = []) {
  const candidates = [];
  const serverBias = (server = {}) => String(server.serverId || '') === '64' ? 2 : (String(server.serverId || '') === '16' ? 1 : 0);
  const addCandidate = (rank, server, model = null, kind = 'idle', item = null) => {
    candidates.push({ rank: rank + serverBias(server), server, model, kind, item });
  };

  for (const server of servers) {
    const models = Array.isArray(server.models) ? [...server.models].sort((a, b) => activeModelRailPriority(b) - activeModelRailPriority(a)) : [];
    for (const model of models) {
      const counts = activeModelRequestCounts(model);
      const prefilling = Array.isArray(model.prefilling) ? model.prefilling : [];
      const generating = Array.isArray(model.generating) ? model.generating : [];
      const waiting = Array.isArray(model.waiting) ? model.waiting : [];
      if (prefilling.length) addCandidate(6000, server, model, 'prefill', prefilling[0]);
      if (generating.length) addCandidate(5000, server, model, 'generate', generating[0]);
      if (waiting.length) addCandidate(4000, server, model, 'queued', waiting[0]);
      else if (counts.waiting > 0) addCandidate(3900, server, model, 'queued', null);
      if (counts.active > 0) addCandidate(3000, server, model, 'active', null);
      if (model.isLoading) addCandidate(2000, server, model, 'loading', null);
      if (model.loaded) addCandidate(1000, server, model, 'ready', null);
    }
    if (!models.length) addCandidate(server.ok ? 20 : 10, server, null, server.ok ? 'idle' : 'offline', null);
  }

  return candidates.sort((a, b) => b.rank - a.rank)[0] || null;
}

function appendActiveModelsFocusProgress(container, percent) {
  const progress = finiteDashboardNumber(percent);
  if (progress === null) return;
  const clamped = Math.max(0, Math.min(100, progress));
  const track = makeActiveModelsNode('div', 'active-models-focus-progress');
  const fill = makeActiveModelsNode('i');
  fill.style.width = `${clamped}%`;
  track.appendChild(fill);
  container.appendChild(track);
}

function appendActiveModelsFocusDetail(container, text, className = '') {
  if (!text) return;
  container.appendChild(makeActiveModelsNode('div', `active-models-focus-detail${className ? ` ${className}` : ''}`, text));
}

function appendActiveModelsFocusPeers(container, focus, servers = []) {
  const peers = servers.filter((server) => server !== focus?.server);
  if (!peers.length) return;
  const peerBox = makeActiveModelsNode('div', 'active-models-focus-peers');
  for (const server of peers) {
    const peer = makeActiveModelsNode('div', 'active-models-focus-peer');
    peer.dataset.state = activeModelsServerUiState(server);
    const dot = makeActiveModelsNode('span', 'active-models-focus-dot');
    dot.setAttribute('aria-hidden', 'true');
    const label = makeActiveModelsNode('strong', '', compactOmlxServerLabel(server));
    peer.append(dot, label);
    const requests = activeModelsServerRequestTotal(server);
    if (requests > 0) peer.appendChild(makeActiveModelsNode('span', '', `${requests}R`));
    else if (!server.ok) peer.appendChild(makeActiveModelsNode('span', '', 'OFF'));
    peerBox.appendChild(peer);
  }
  container.appendChild(peerBox);
}

function appendActiveModelsFocus(container, focus, servers = []) {
  const focusNode = makeActiveModelsNode('section', 'active-models-focus');
  focusNode.dataset.kind = focus?.kind || 'idle';
  focusNode.dataset.state = activeModelsServerUiState(focus?.server || {});

  const server = focus?.server || servers[0] || { ok: false, serverId: '—', name: 'OMLX', models: [] };
  const model = focus?.model || primaryActiveModelsModel(server);
  const modelRequests = model ? activeModelsModelRequestTotal(model) : 0;
  const serverRequests = activeModelsServerRequestTotal(server);

  const serverLine = makeActiveModelsNode('div', 'active-models-focus-server');
  const dot = makeActiveModelsNode('span', 'active-models-focus-dot');
  dot.setAttribute('aria-hidden', 'true');
  const serverLabel = makeActiveModelsNode('strong', '', compactOmlxServerLabel(server));
  serverLabel.title = server.name || `OMLX-${server.serverId || ''}`;
  serverLine.append(dot, serverLabel);
  if (!server.ok) serverLine.appendChild(makeActiveModelsNode('span', 'active-models-focus-pill', 'OFF'));
  focusNode.appendChild(serverLine);

  if (model) {
    const modelBlock = makeActiveModelsNode('div', 'active-models-focus-model-block');
    const modelTitle = makeActiveModelsNode('strong', 'active-models-focus-model', compactDashboardModelName(model.id));
    modelTitle.title = model.id || '';
    modelBlock.appendChild(modelTitle);
    const chipText = modelRequests > 0
      ? `${modelRequests} REQ`
      : (model.isLoading ? 'LOAD' : (model.loaded ? 'RDY' : (model.pinned ? 'PIN' : '')));
    if (chipText) modelBlock.appendChild(makeActiveModelsNode('span', 'active-models-focus-chip', chipText));
    focusNode.appendChild(modelBlock);
  }

  const phase = makeActiveModelsNode('div', 'active-models-focus-phase');
  const kind = focus?.kind || (model ? 'ready' : (server.ok ? 'idle' : 'offline'));
  const item = focus?.item || {};

  if (kind === 'prefill') {
    const processed = finiteDashboardNumber(item.processed);
    const total = finiteDashboardNumber(item.total);
    const pct = processed !== null && total && total > 0 ? Math.max(0, Math.min(100, (processed / total) * 100)) : null;
    phase.textContent = 'PREFILL';
    focusNode.appendChild(phase);
    focusNode.appendChild(makeActiveModelsNode('div', 'active-models-focus-percent', pct !== null ? `${Math.round(pct)}%` : 'PF'));
    appendActiveModelsFocusProgress(focusNode, pct);
    appendActiveModelsFocusDetail(focusNode, formatDashboardTps(item.speed), 'accent');
  } else if (kind === 'generate') {
    phase.textContent = 'GEN';
    focusNode.appendChild(phase);
    appendActiveModelsFocusDetail(focusNode, formatDashboardTps(item.tokensPerSecond), 'accent');
  } else if (kind === 'queued') {
    const position = finiteDashboardNumber(item.queuePosition);
    phase.textContent = 'QUEUE';
    focusNode.appendChild(phase);
    focusNode.appendChild(makeActiveModelsNode('div', 'active-models-focus-metric', position ? `#${position}` : `${modelRequests || serverRequests || 1} REQ`));
    appendActiveModelsFocusDetail(focusNode, formatDashboardSeconds(item.elapsedSeconds, true), 'accent');
  } else if (kind === 'active') {
    phase.textContent = 'ACTIVE';
    focusNode.appendChild(phase);
    focusNode.appendChild(makeActiveModelsNode('div', 'active-models-focus-metric', `${modelRequests || serverRequests || 1} REQ`));
  } else if (kind === 'loading') {
    phase.textContent = 'LOADING';
    focusNode.appendChild(phase);
  } else if (kind === 'ready') {
    // Per-model RDY chip already communicates readiness; keep the focus rail uncluttered.
  } else {
    focusNode.appendChild(makeActiveModelsNode('div', 'active-models-focus-metric', server.ok ? 'IDLE' : 'OFF'));
  }

  const spacer = makeActiveModelsNode('div', 'active-models-focus-spacer');
  focusNode.appendChild(spacer);
  appendActiveModelsFocusPeers(focusNode, focus, servers);
  container.appendChild(focusNode);
}

function updateActiveModelsChrome(payload = {}, servers = []) {
  const activeRequests = servers.reduce((sum, server) => sum + Number(server.activeRequests || 0), 0);
  const waitingRequests = servers.reduce((sum, server) => sum + Number(server.waitingRequests || 0), 0);
  const loadedModels = servers.reduce((sum, server) => sum + server.models.filter((model) => model.loaded).length, 0);
  const totals = payload.totals || {};
  const memoryUsed = finiteDashboardNumber(totals.memoryUsed) ?? servers.reduce((sum, server) => sum + (finiteDashboardNumber(server.memoryUsed) ?? 0), 0);
  const memoryMax = finiteDashboardNumber(totals.memoryMax) ?? servers.reduce((sum, server) => sum + (finiteDashboardNumber(server.memoryMax) ?? 0), 0);
  const memoryPct = memoryMax > 0 ? Math.max(0, Math.min(100, (memoryUsed / memoryMax) * 100)) : 0;

  const totalRequests = activeRequests + waitingRequests;
  const onlineServers = servers.filter((server) => server.ok).length;
  if (activeModelsSummaryEl) activeModelsSummaryEl.textContent = 'OMLX';
  if (activeModelsStatusEl) {
    activeModelsStatusEl.textContent = totalRequests > 0
      ? `${totalRequests} REQ`
      : (loadedModels > 0 ? `${loadedModels} RDY` : (onlineServers > 0 ? 'IDLE' : 'OFF'));
  }
  if (activeModelsMemoryFillEl) activeModelsMemoryFillEl.style.width = `${memoryPct}%`;
  if (activeModelsMemoryTextEl) {
    activeModelsMemoryTextEl.textContent = memoryMax > 0
      ? `${formatDashboardBytesCompact(memoryUsed)} / ${formatDashboardBytesCompact(memoryMax)} cap`
      : 'Memory pending';
  }
  if (activeModelsFooterEl) {
    activeModelsFooterEl.textContent = totalRequests > 0
      ? `A ${activeRequests}${waitingRequests ? ` · Q ${waitingRequests}` : ''}`
      : `${onlineServers}/${servers.length || 2} ONLINE`;
  }
}

function renderActiveModelsUsage(payload = {}) {
  if (!activeModelsCard || !activeModelsListEl) return;
  const rawServers = Array.isArray(payload.servers) ? payload.servers : [];
  const fallbackServers = [
    { ok: false, serverId: '64', name: 'OMLX-64', error: 'Checking…', models: [] },
    { ok: false, serverId: '16', name: 'OMLX-16', error: 'Checking…', models: [] }
  ];
  const servers = (rawServers.length ? rawServers : fallbackServers)
    .map((server) => ({
      ...server,
      models: Array.isArray(server.models) ? server.models.filter((model) => {
        const counts = activeModelRequestCounts(model);
        return model.loaded || model.isLoading || counts.active > 0 || counts.waiting > 0;
      }) : []
    }))
    .sort((a, b) => {
      const rank = (server) => String(server.serverId || '') === '64' ? 0 : (String(server.serverId || '') === '16' ? 1 : 2);
      return rank(a) - rank(b);
    });
  const activeRequests = servers.reduce((sum, server) => sum + Number(server.activeRequests || 0), 0);
  const loadedModels = servers.reduce((sum, server) => sum + server.models.filter((model) => model.loaded).length, 0);
  const onlineServers = servers.filter((server) => server.ok).length;
  const pressureLevels = servers.map((server) => String(server.memoryPressure?.pressureLevel || '').toLowerCase());
  const memoryPressure = pressureLevels.some((level) => /critical|hard/.test(level))
    ? 'critical'
    : (pressureLevels.some((level) => /warn|soft|pressure|high/.test(level)) ? 'warm' : '');

  updateActiveModelsChrome(payload, servers);
  activeModelsCard.dataset.pressure = memoryPressure || (activeRequests > 0 ? 'active' : (onlineServers > 0 || loadedModels > 0 ? 'idle' : 'offline'));
  activeModelsCard.hidden = false;
  clearActiveModelsList();

  appendActiveModelsFocus(activeModelsListEl, selectActiveModelsFocus(servers), servers);
}

async function refreshActiveModelsUsage() {
  if (!activeModelsCard) return null;
  if (activeModelsUsageInFlight) return activeModelsUsageInFlight;
  activeModelsUsageInFlight = (async () => {
    try {
      const response = await fetch('/api/jarvis/omlx/usage', { method: 'GET', cache: 'no-store' });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
      renderActiveModelsUsage(payload);
      return payload;
    } catch (error) {
      renderActiveModelsUsage({
        ok: false,
        generatedAt: new Date().toISOString(),
        totals: { activeRequests: 0, waitingRequests: 0, loadedModels: 0, memoryUsed: 0, memoryMax: 0 },
        servers: [
          { ok: false, serverId: '64', name: 'OMLX-64', error: error?.message || 'Usage unavailable', models: [] },
          { ok: false, serverId: '16', name: 'OMLX-16', error: error?.message || 'Usage unavailable', models: [] }
        ]
      });
      return null;
    } finally {
      activeModelsUsageInFlight = null;
    }
  })();
  return activeModelsUsageInFlight;
}

function summarizeRaspberryPiIssue(status = {}) {
  if (status.serviceRunning === false) {
    return status.serviceState && status.serviceState !== 'unknown'
      ? `Service ${status.serviceState}`
      : 'Service stopped';
  }
  if (status.serviceEnabled === false) return 'Service not enabled';
  if (status.clientRunning === false) return 'Client missing';
  if (status.bluetoothActive === false) return 'Bluetooth offline';
  if (status.bluealsaActive === false) return 'BlueALSA offline';
  if (status.powerconfConnected === false) return 'PowerConf offline';
  if (status.roomAudioServerOk === false) return 'Room server offline';
  return status.error || 'Room audio degraded';
}

function renderRaspberryPiStatus(status = {}) {
  if (!raspberryPiButton) return;
  if (!status.checking && !status.toggling && status.state !== 'idle') latestRaspberryPiStatus = status;
  const state = status.state || (status.checking || status.toggling ? 'checking' : (status.ok ? 'online' : (status.reachable ? 'degraded' : 'offline')));
  const checking = state === 'checking';
  const toggling = Boolean(status.toggling);
  const toggleFailed = Boolean(status.toggle?.error);
  const idle = state === 'idle';
  const online = Boolean(status.ok) && !checking && !idle && !toggleFailed;
  const degraded = !online && !checking && !idle && (toggleFailed || state === 'degraded' || Boolean(status.reachable));
  const issue = status.toggle?.error || summarizeRaspberryPiIssue(status);
  const actionLabel = status.action === 'stop' ? 'Stopping…' : (status.action === 'start' ? 'Starting…' : 'Toggling…');
  const detail = toggling
    ? actionLabel
    : (checking
      ? 'Pinging…'
      : (idle ? 'Tap to toggle' : (online ? 'Room audio online' : (degraded ? issue : (status.error || 'Pi offline')))));
  const checkedText = status.checkedAt ? ` · checked ${formatRelative(status.checkedAt)}` : '';
  const healthDetails = [
    status.serviceRunning === true ? 'service running' : (status.serviceRunning === false ? 'service not running' : ''),
    status.clientRunning === true ? 'client running' : (status.clientRunning === false ? 'client missing' : ''),
    status.powerconfConnected === true ? 'PowerConf connected' : (status.powerconfConnected === false ? 'PowerConf disconnected' : ''),
    status.roomAudioServerOk === true ? 'room server healthy' : (status.roomAudioServerOk === false ? 'room server unavailable' : '')
  ].filter(Boolean).join(' · ');
  const title = toggling
    ? `${actionLabel.replace('…', '')} Raspberry Pi room audio service`
    : (idle
      ? 'Tap to toggle Raspberry Pi room audio service'
      : (online
        ? `Raspberry Pi room audio online${status.hostname ? ` · ${status.hostname}` : ''}${status.uptimeSeconds ? ` · ${formatCompactDuration(status.uptimeSeconds)} uptime` : ''}${healthDetails ? ` · ${healthDetails}` : ''}${checkedText}`
        : (degraded
          ? `Raspberry Pi reachable but room audio degraded: ${issue}${healthDetails ? ` · ${healthDetails}` : ''}${checkedText}`
          : `Raspberry Pi unavailable${status.error ? `: ${status.error}` : ''}${checkedText}`)));

  raspberryPiButton.classList.remove(...toneClasses);
  raspberryPiButton.classList.add(online ? 'tone-blue' : ((checking || degraded) ? 'tone-amber' : 'tone-silver'));
  raspberryPiButton.dataset.state = idle ? 'idle' : (checking ? 'checking' : (online ? 'online' : (degraded ? 'degraded' : 'offline')));
  raspberryPiButton.title = title;
  raspberryPiButton.setAttribute('aria-label', title);
  raspberryPiButton.setAttribute('aria-busy', checking ? 'true' : 'false');

  if (raspberryPiIconEl) raspberryPiIconEl.setAttribute('aria-label', title);
  if (raspberryPiDetailEl) raspberryPiDetailEl.textContent = detail;
}

async function pingRaspberryPi() {
  if (raspberryPiPingInFlight) return raspberryPiPingInFlight;
  if (raspberryPiToggleInFlight) return raspberryPiToggleInFlight;
  renderRaspberryPiStatus({ checking: true, state: 'checking' });
  raspberryPiPingInFlight = (async () => {
    try {
      const response = await fetch('/api/jarvis/raspberry-pi/ping', {
        method: 'POST',
        cache: 'no-store'
      });
      const status = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(status.error || `HTTP ${response.status}`);
      renderRaspberryPiStatus(status);
      return status;
    } catch (error) {
      const status = {
        ok: false,
        reachable: false,
        status: 'offline',
        state: 'offline',
        error: error?.message || 'Raspberry Pi ping failed',
        checkedAt: new Date().toISOString()
      };
      renderRaspberryPiStatus(status);
      return status;
    } finally {
      raspberryPiPingInFlight = null;
    }
  })();
  return raspberryPiPingInFlight;
}

async function toggleRaspberryPiService() {
  if (raspberryPiToggleInFlight) return raspberryPiToggleInFlight;
  if (raspberryPiPingInFlight) return raspberryPiPingInFlight;
  const action = latestRaspberryPiStatus?.serviceRunning === true ? 'stop' : (latestRaspberryPiStatus?.serviceRunning === false ? 'start' : 'toggle');
  renderRaspberryPiStatus({ toggling: true, state: 'checking', action });
  raspberryPiToggleInFlight = (async () => {
    try {
      const response = await fetch('/api/jarvis/raspberry-pi/service/toggle', {
        method: 'POST',
        cache: 'no-store'
      });
      const status = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(status.error || `HTTP ${response.status}`);
      renderRaspberryPiStatus(status);
      return status;
    } catch (error) {
      const status = {
        ok: false,
        reachable: false,
        status: 'offline',
        state: 'offline',
        error: error?.message || 'Raspberry Pi service toggle failed',
        checkedAt: new Date().toISOString()
      };
      renderRaspberryPiStatus(status);
      return status;
    } finally {
      raspberryPiToggleInFlight = null;
    }
  })();
  return raspberryPiToggleInFlight;
}

function renderPhoneAdbStatus(status = {}) {
  if (!phoneAdbButton) return;
  const state = status.state || (status.checking ? 'checking' : (status.ok ? 'online' : 'offline'));
  const checking = state === 'checking';
  const online = Boolean(status.ok) && !checking;
  const idle = state === 'idle';
  const detail = checking
    ? 'Pinging…'
    : (idle ? 'Tap to ping' : (online ? (status.model || 'Connected') : (status.error || 'No ADB link')));
  const checkedText = status.checkedAt ? ` · checked ${formatRelative(status.checkedAt)}` : '';
  const title = idle
    ? 'Tap to ping phone ADB'
    : (online
      ? `Phone ADB connected${status.model ? ` to ${status.model}` : ''}${status.android ? ` · Android ${status.android}` : ''}${checkedText}`
      : `Phone ADB unavailable${status.error ? `: ${status.error}` : ''}${checkedText}`);

  phoneAdbButton.classList.remove(...toneClasses);
  phoneAdbButton.classList.add(online ? 'tone-blue' : (checking ? 'tone-amber' : 'tone-silver'));
  phoneAdbButton.dataset.state = idle ? 'idle' : (checking ? 'checking' : (online ? 'online' : 'offline'));
  phoneAdbButton.title = title;
  phoneAdbButton.setAttribute('aria-label', title);
  phoneAdbButton.setAttribute('aria-busy', checking ? 'true' : 'false');

  if (phoneAdbIconEl) phoneAdbIconEl.setAttribute('aria-label', title);
  if (phoneAdbDetailEl) phoneAdbDetailEl.textContent = detail;
}

async function pingPhoneAdb() {
  if (phoneAdbPingInFlight) return phoneAdbPingInFlight;
  renderPhoneAdbStatus({ checking: true, state: 'checking' });
  phoneAdbPingInFlight = (async () => {
    try {
      const response = await fetch('/api/jarvis/phone-adb/ping', {
        method: 'POST',
        cache: 'no-store'
      });
      const status = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(status.error || `HTTP ${response.status}`);
      renderPhoneAdbStatus(status);
      return status;
    } catch (error) {
      const status = {
        ok: false,
        status: 'offline',
        state: 'offline',
        error: error?.message || 'ADB ping failed',
        checkedAt: new Date().toISOString()
      };
      renderPhoneAdbStatus(status);
      return status;
    } finally {
      phoneAdbPingInFlight = null;
    }
  })();
  return phoneAdbPingInFlight;
}


function addSmartPlugClickHandler(button) {
  if (!button || button.dataset.smartPlugHandlerAttached === 'true') return;
  button.dataset.smartPlugHandlerAttached = 'true';
  button.addEventListener('click', () => {
    toggleSmartPlug(button.dataset.smartPlug);
  });
}

function ensureSmartPlugButton(name, label = name) {
  if (!name) return null;
  const existing = smartPlugButtonByName.get(name);
  if (existing) return existing;
  if (!smartPlugGrid) return null;

  const button = document.createElement('button');
  button.id = `smart-plug-${name.replace(/[^a-z0-9_-]+/gi, '-')}`;
  button.className = 'hud-mini-card glass-panel tone-silver smart-plug-card';
  button.type = 'button';
  button.role = 'switch';
  button.dataset.state = 'checking';
  button.dataset.smartPlug = name;
  button.setAttribute('aria-live', 'polite');
  button.setAttribute('aria-checked', 'false');
  button.setAttribute('aria-busy', 'true');
  button.setAttribute('aria-label', `Toggle ${label}`);
  button.title = `Toggle ${label}`;
  button.innerHTML = [
    `<p class="eyebrow smart-plug-label"></p>`,
    `<span class="omlx-status-icon smart-plug-status-icon" role="img"></span>`,
    `<p class="hud-mini-detail smart-plug-detail">Checking…</p>`
  ].join('');
  button.querySelector('.smart-plug-label').textContent = label;
  button.querySelector('.smart-plug-status-icon').setAttribute('aria-label', `${label} status checking`);
  smartPlugGrid.appendChild(button);
  smartPlugButtons.push(button);
  smartPlugButtonByName.set(name, button);
  addSmartPlugClickHandler(button);
  return button;
}

function smartPlugTitle(status = {}) {
  const label = status.label || status.name || 'Smart plug';
  const checkedText = status.checkedAt ? ` · checked ${formatRelative(status.checkedAt)}` : '';
  if (status.toggling) return `Toggling ${label}`;
  if (status.checking) return `Checking ${label}`;
  if (status.ok === false || status.status === 'error') return `${label} unavailable${status.error ? `: ${status.error}` : ''}${checkedText}`;
  const isOn = status.isOn === true || status.is_on === true || status.status === 'on';
  const isOff = status.isOn === false || status.is_on === false || status.status === 'off';
  const stateText = isOn ? 'on' : (isOff ? 'off' : 'unknown');
  return `${label} is ${stateText}${checkedText}`;
}

function renderSmartPlugStatus(status = {}) {
  const name = status.name || status.plug || '';
  const label = status.label || smartPlugButtonByName.get(name)?.querySelector('.smart-plug-label')?.textContent || name;
  const button = ensureSmartPlugButton(name, label);
  if (!button) return;
  const isOn = status.isOn === true || status.is_on === true || status.status === 'on';
  const isOff = status.isOn === false || status.is_on === false || status.status === 'off';
  const checking = Boolean(status.checking);
  const toggling = Boolean(status.toggling);
  const error = status.ok === false || status.status === 'error';
  const state = (checking || toggling)
    ? 'checking'
    : (error ? 'error' : (isOn ? 'on' : (isOff ? 'off' : 'unknown')));
  const detail = toggling
    ? 'Toggling…'
    : (checking
      ? 'Checking…'
      : (error ? (status.error || 'Unavailable') : (isOn ? 'On' : (isOff ? 'Off' : 'Unknown'))));
  const title = smartPlugTitle({ ...status, label, checking, toggling });

  latestSmartPlugStatuses.set(name, { ...status, label, state });
  button.classList.remove(...toneClasses);
  button.classList.add(state === 'on' ? 'tone-blue' : (state === 'error' ? 'tone-orange' : (state === 'checking' ? 'tone-amber' : 'tone-silver')));
  button.dataset.state = state;
  button.title = title;
  button.setAttribute('aria-label', `Toggle ${label}. ${title}`);
  button.setAttribute('aria-checked', isOn ? 'true' : 'false');
  button.setAttribute('aria-busy', (checking || toggling) ? 'true' : 'false');

  const labelEl = button.querySelector('.smart-plug-label');
  const iconEl = button.querySelector('.smart-plug-status-icon');
  const detailEl = button.querySelector('.smart-plug-detail');
  if (labelEl) labelEl.textContent = label;
  if (iconEl) iconEl.setAttribute('aria-label', title);
  if (detailEl) detailEl.textContent = detail;
}

function renderAllSmartPlugsChecking() {
  for (const button of smartPlugButtons) {
    const name = button.dataset.smartPlug;
    const label = button.querySelector('.smart-plug-label')?.textContent || name;
    if (!latestSmartPlugStatuses.has(name)) renderSmartPlugStatus({ name, label, checking: true, state: 'checking' });
  }
}

async function refreshSmartPlugStatuses({ silent = false, force = false } = {}) {
  if (smartPlugStatusInFlight) return smartPlugStatusInFlight;
  if (!silent) renderAllSmartPlugsChecking();
  const query = force ? '?force=1' : '';
  smartPlugStatusInFlight = (async () => {
    try {
      const response = await fetch(`/api/jarvis/smart-plugs/status${query}`, { cache: 'no-store' });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || (payload.ok === false && (!Array.isArray(payload.plugs) || payload.plugs.length === 0))) {
        throw new Error(payload.error || `HTTP ${response.status}`);
      }
      for (const plug of payload.plugs || []) renderSmartPlugStatus(plug);
      return payload;
    } catch (error) {
      for (const button of smartPlugButtons) {
        const name = button.dataset.smartPlug;
        const current = latestSmartPlugStatuses.get(name) || { name, label: button.querySelector('.smart-plug-label')?.textContent || name };
        renderSmartPlugStatus({ ...current, ok: false, status: 'error', error: error?.message || 'Smart plug status failed', checkedAt: new Date().toISOString() });
      }
      return { ok: false, error: error?.message || 'Smart plug status failed' };
    } finally {
      smartPlugStatusInFlight = null;
    }
  })();
  return smartPlugStatusInFlight;
}

async function toggleSmartPlug(name) {
  if (!name) return null;
  if (smartPlugToggleInFlight.has(name)) return smartPlugToggleInFlight.get(name);
  const current = latestSmartPlugStatuses.get(name) || { name, label: smartPlugButtonByName.get(name)?.querySelector('.smart-plug-label')?.textContent || name };
  renderSmartPlugStatus({ ...current, toggling: true, state: 'checking' });
  const request = (async () => {
    try {
      const response = await fetch(`/api/jarvis/smart-plugs/toggle?plug=${encodeURIComponent(name)}`, {
        method: 'POST',
        cache: 'no-store'
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || payload.ok === false) throw new Error(payload.error || `HTTP ${response.status}`);
      if (payload.plug) renderSmartPlugStatus(payload.plug);
      window.setTimeout(() => refreshSmartPlugStatuses({ silent: true, force: true }), 650);
      return payload;
    } catch (error) {
      renderSmartPlugStatus({ ...current, ok: false, status: 'error', error: error?.message || 'Smart plug toggle failed', checkedAt: new Date().toISOString() });
      window.setTimeout(() => refreshSmartPlugStatuses({ silent: true, force: true }), 1200);
      return { ok: false, error: error?.message || 'Smart plug toggle failed' };
    } finally {
      smartPlugToggleInFlight.delete(name);
    }
  })();
  smartPlugToggleInFlight.set(name, request);
  return request;
}

function formatUptime(seconds = 0) {
  const mins = Math.floor(seconds / 60);
  const hrs = Math.floor(mins / 60);
  const days = Math.floor(hrs / 24);
  if (days > 0) return `${days}d ${hrs % 24}h uptime`;
  if (hrs > 0) return `${hrs}h ${mins % 60}m uptime`;
  if (mins > 0) return `${mins}m uptime`;
  return `${seconds}s uptime`;
}

function formatCompactDuration(seconds = 0) {
  const safeSeconds = Math.max(0, Math.floor(Number(seconds) || 0));
  const mins = Math.floor(safeSeconds / 60);
  const hrs = Math.floor(mins / 60);
  const days = Math.floor(hrs / 24);
  if (days > 0) return `${days}d ${hrs % 24}h`;
  if (hrs > 0) return `${hrs}h ${mins % 60}m`;
  if (mins > 0) return `${mins}m`;
  return `${safeSeconds}s`;
}

function syncDashboardUptime(server = {}) {
  const incoming = Number(server.uptimeSeconds || 0);
  const now = Date.now();
  const currentEstimate = dashboardUptimeBaseSeconds + Math.floor((now - dashboardUptimeSyncedAt) / 1000);
  // Pi-session websocket updates reuse the last full display payload; avoid
  // resetting the uptime tile backwards between 10-second API refreshes.
  if (incoming >= currentEstimate || currentEstimate - incoming > 15) {
    dashboardUptimeBaseSeconds = incoming;
    dashboardUptimeSyncedAt = now;
  }
  updateDashboardUptime();
}

function updateDashboardUptime() {
  if (!uptimeEl) return;
  const elapsed = Math.floor((Date.now() - dashboardUptimeSyncedAt) / 1000);
  uptimeEl.textContent = formatCompactDuration(dashboardUptimeBaseSeconds + elapsed);
}

function getWeatherEmoji(weather = {}) {
  if (!weather.ok) return '⚠️';
  const code = Number(weather.weatherCode);
  if (Number.isFinite(code)) {
    if (code === 0) return '☀️';
    if (code === 1) return '🌤️';
    if (code === 2) return '⛅';
    if (code === 3) return '☁️';
    if (code === 45 || code === 48) return '🌫️';
    if (code >= 51 && code <= 57) return '🌦️';
    if ((code >= 61 && code <= 67) || (code >= 80 && code <= 82)) return '🌧️';
    if ((code >= 71 && code <= 77) || (code >= 85 && code <= 86)) return '❄️';
    if (code >= 95) return '⛈️';
  }

  const description = `${weather.condition || ''} ${weather.summary || ''}`.toLowerCase();
  if (/thunder|storm/.test(description)) return '⛈️';
  if (/snow|flurr/.test(description)) return '❄️';
  if (/rain|shower|drizzle/.test(description)) return '🌧️';
  if (/fog|mist|haze/.test(description)) return '🌫️';
  if (/cloud|overcast/.test(description)) return '☁️';
  if (/clear|sun/.test(description)) return '☀️';
  return '🌡️';
}

function renderDiscordBotStatus(discordBot = {}) {
  const running = discordBot.running === true;
  const verified = discordBot.ok !== false;
  const state = verified ? (running ? 'online' : 'offline') : 'unknown';
  const label = verified
    ? (running ? `Discord bot online${discordBot.pid ? ` · PID ${discordBot.pid}` : ''}` : 'Discord bot offline')
    : `Discord bot status unknown${discordBot.error ? ` · ${discordBot.error}` : ''}`;

  if (jarvisBrand) {
    jarvisBrand.dataset.discordBot = state;
    jarvisBrand.dataset.discordLabel = running ? 'BOT ONLINE' : (state === 'offline' ? 'BOT OFFLINE' : 'BOT UNKNOWN');
    jarvisBrand.title = label;
    jarvisBrand.setAttribute('aria-label', `JARVIS alarm clock display · ${label}`);
  }
  if (jarvisBrandIndicator) {
    jarvisBrandIndicator.setAttribute('aria-label', label);
  }
}

function renderWeather(weather = {}) {
  const temp = Number(weather.temperatureC);
  const detail = weather.ok
    ? (weather.summary || weather.condition || 'Conditions updated')
    : (weather.error || 'Weather unavailable');
  const weatherTitle = weather.updatedAt
    ? `${weather.location || 'Weather'} · ${detail} · updated ${formatRelative(weather.updatedAt)}`
    : detail;

  if (headerWeatherEl) {
    const emoji = getWeatherEmoji(weather);
    const temperatureText = Number.isFinite(temp) ? `${Math.round(temp)}°` : '--°';
    headerWeatherEl.textContent = `${emoji} ${temperatureText}`;
    headerWeatherEl.dataset.state = weather.ok ? 'online' : 'offline';
    headerWeatherEl.title = weatherTitle;
    headerWeatherEl.setAttribute('aria-label', `Weather ${temperatureText} · ${detail}`);
  }

  if (!weatherCard) return;
  weatherCard.classList.remove(...toneClasses);
  const tone = !weather.ok
    ? 'orange'
    : (weather.attention ? 'amber' : 'blue');
  weatherCard.classList.add(`tone-${tone}`);
  weatherCard.dataset.state = weather.ok ? 'online' : 'offline';
  weatherCard.title = weatherTitle;
  if (weatherTempEl) weatherTempEl.textContent = Number.isFinite(temp) ? `${Math.round(temp)}°` : '--°';
  if (weatherDetailEl) weatherDetailEl.textContent = detail;
}

function normalizeOmlxClientServerId(raw = '16') {
  return String(raw || '').trim().replace(/^omlx[-_]?/i, '') === '64' ? '64' : '16';
}

function defaultOmlxName(serverId = '16') {
  return normalizeOmlxClientServerId(serverId) === '64' ? 'OMLX-64' : 'OMLX-16';
}

function getOmlxControl(serverId = '16') {
  const normalized = normalizeOmlxClientServerId(serverId);
  return omlxControlById.get(normalized) || omlxControlById.get('16') || null;
}

function renderOmlxStatus(serverOrStatus = '16', maybeStatus = {}) {
  const statusOnly = serverOrStatus && typeof serverOrStatus === 'object' && !Array.isArray(serverOrStatus);
  const serverId = normalizeOmlxClientServerId(statusOnly ? (serverOrStatus.serverId || serverOrStatus.server || '16') : serverOrStatus);
  const omlx = statusOnly ? serverOrStatus : (maybeStatus || {});
  const control = getOmlxControl(serverId);
  if (!control) return;

  if (!omlx.checking && !omlx.toggling && omlx.state !== 'idle') latestOmlxStatuses.set(serverId, omlx);
  const name = omlx.displayName || omlx.name || defaultOmlxName(serverId);
  const state = omlx.state || (omlx.checking || omlx.toggling ? 'checking' : (omlx.ok ? 'online' : 'offline'));
  const checking = state === 'checking';
  const toggling = Boolean(omlx.toggling);
  const idle = state === 'idle';
  const online = Boolean(omlx.ok) && !checking && !idle;
  const actionLabel = omlx.action === 'stop' ? 'Stopping…' : (omlx.action === 'start' ? 'Starting…' : 'Switching…');
  const modelText = Number.isFinite(omlx.modelCount)
    ? `${omlx.modelCount} model${omlx.modelCount === 1 ? '' : 's'}`
    : 'Online';
  const loadedText = Number.isFinite(omlx.loadedCount)
    ? ` · ${omlx.loadedCount} loaded`
    : '';
  const detail = toggling
    ? actionLabel
    : (checking
      ? 'Checking…'
      : (idle ? 'Tap to toggle' : (online ? modelText : 'Offline')));
  const checkedText = omlx.checkedAt ? ` · checked ${formatRelative(omlx.checkedAt)}` : '';
  const title = toggling
    ? `${actionLabel.replace('…', '')} ${name} server`
    : (idle
      ? `Tap to toggle ${name} server`
      : (online
        ? `${name} server online${Number.isFinite(omlx.modelCount) ? ` · ${modelText}${loadedText}` : ''}${omlx.defaultModel ? ` · default ${omlx.defaultModel}` : ''}${checkedText}`
        : `${name} server offline${omlx.error ? `: ${omlx.error}` : ''}${checkedText}`));

  control.button.classList.remove(...toneClasses);
  control.button.classList.add(online ? 'tone-blue' : (checking ? 'tone-amber' : 'tone-orange'));
  control.button.dataset.state = idle ? 'idle' : (checking ? 'checking' : (online ? 'online' : 'offline'));
  control.button.title = title;
  control.button.setAttribute('aria-label', title);
  control.button.setAttribute('aria-checked', online ? 'true' : 'false');
  control.button.setAttribute('aria-busy', checking ? 'true' : 'false');

  if (control.labelEl) control.labelEl.textContent = name;
  if (control.iconEl) {
    control.iconEl.textContent = '';
    control.iconEl.setAttribute('aria-label', title);
  }
  if (control.detailEl) control.detailEl.textContent = detail;
}

async function pingOmlxStatus(serverId = '16') {
  const normalized = normalizeOmlxClientServerId(serverId);
  if (omlxPingInFlight.has(normalized)) return omlxPingInFlight.get(normalized);
  if (omlxToggleInFlight.has(normalized)) return omlxToggleInFlight.get(normalized);
  renderOmlxStatus(normalized, { checking: true, state: 'checking' });
  const pending = (async () => {
    try {
      const response = await fetch(`/api/jarvis/omlx/${encodeURIComponent(normalized)}/status`, {
        method: 'POST',
        cache: 'no-store'
      });
      const status = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(status.error || `HTTP ${response.status}`);
      renderOmlxStatus(normalized, status);
      return status;
    } catch (error) {
      const status = {
        ok: false,
        status: 'offline',
        state: 'offline',
        serverId: normalized,
        name: defaultOmlxName(normalized),
        error: error?.message || `${defaultOmlxName(normalized)} status check failed`,
        checkedAt: new Date().toISOString()
      };
      renderOmlxStatus(normalized, status);
      return status;
    } finally {
      omlxPingInFlight.delete(normalized);
    }
  })();
  omlxPingInFlight.set(normalized, pending);
  return pending;
}

async function toggleOmlxServer(serverId = '16') {
  const normalized = normalizeOmlxClientServerId(serverId);
  if (omlxToggleInFlight.has(normalized)) return omlxToggleInFlight.get(normalized);
  if (omlxPingInFlight.has(normalized)) return omlxPingInFlight.get(normalized);
  const action = latestOmlxStatuses.get(normalized)?.ok ? 'stop' : 'start';
  renderOmlxStatus(normalized, { toggling: true, state: 'checking', action });
  const pending = (async () => {
    try {
      const response = await fetch(`/api/jarvis/omlx/${encodeURIComponent(normalized)}/server/toggle?action=${encodeURIComponent(action)}`, {
        method: 'POST',
        cache: 'no-store'
      });
      const status = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(status.error || `HTTP ${response.status}`);
      renderOmlxStatus(normalized, status);
      return status;
    } catch (error) {
      const status = {
        ok: false,
        status: 'offline',
        state: 'offline',
        serverId: normalized,
        name: defaultOmlxName(normalized),
        error: error?.message || `${defaultOmlxName(normalized)} server switch failed`,
        checkedAt: new Date().toISOString()
      };
      renderOmlxStatus(normalized, status);
      return status;
    } finally {
      omlxToggleInFlight.delete(normalized);
      window.setTimeout(() => pingOmlxStatus(normalized), 900);
    }
  })();
  omlxToggleInFlight.set(normalized, pending);
  return pending;
}

function renderDisplay(payload) {
  latestDisplayPayload = payload;
  const state = payload.state || {};
  const piSessions = payload.piSessions || {};
  const activeCount = Number(piSessions.activeCount ?? piSessions.totalSessions ?? piSessions.activeGenerating ?? 0);
  const localActive = Number(piSessions.localActive || 0);
  const discordGenerating = Number(piSessions.discordActiveGenerating || 0);
  const localOpen = Number(piSessions.localOpen || 0);
  const discordOpen = Number(piSessions.discordProcessOpen || 0);
  const isAttention = !payload.ok || state.key === 'error' || Boolean(payload.errorBanner);
  const tone = isAttention ? 'orange' : (activeCount > 0 ? 'green' : 'silver');
  document.documentElement.dataset.liveTone = tone;
  if (stateCard) {
    stateCard.classList.remove(...toneClasses);
    stateCard.classList.add(`tone-${tone}`);
    stateCard.dataset.state = activeCount > 0 ? 'active' : 'idle';
  }
  if (stateLabel) stateLabel.textContent = String(activeCount);
  const sessionDetail = activeCount === 0
    ? `No active Pi sessions · ${localOpen + discordOpen} open idle`
    : `${activeCount} active Pi session${activeCount === 1 ? '' : 's'} · ${localActive} local/direct · ${discordGenerating} Discord`;
  if (stateDetail) stateDetail.textContent = sessionDetail;
  if (headerPiSessionsEl) {
    headerPiSessionsEl.textContent = `Agents: ${activeCount}`;
    headerPiSessionsEl.dataset.state = activeCount > 0 ? 'active' : 'idle';
    headerPiSessionsEl.title = sessionDetail;
  }

  syncDashboardUptime(payload.server || {});
  renderWeather(payload.weather || {});
  renderDiscordBotStatus(payload.discordBot || {});
  const omlxServers = payload.omlxServers || {};
  renderOmlxStatus('16', omlxServers['16'] || payload.omlx || {});
  renderOmlxStatus('64', omlxServers['64'] || payload.omlx64 || {});

  if (payload.errorBanner) {
    errorEl.hidden = false;
    errorEl.textContent = payload.errorBanner;
  } else {
    errorEl.hidden = true;
    errorEl.textContent = '';
  }

  serverEl.textContent = `${payload.server?.name || 'JARVIS host'} · ${formatUptime(payload.server?.uptimeSeconds || 0)}`;
  refreshEl.textContent = `Updated ${formatRelative(payload.generatedAt)}`;
}

async function refreshDisplay() {
  try {
    const response = await fetch('/api/jarvis/display', { cache: 'no-store' });
    const payload = await response.json();
    renderDisplay(payload);
  } catch (error) {
    if (stateCard) {
      stateCard.classList.remove(...toneClasses);
      stateCard.classList.add('tone-orange');
      stateCard.dataset.state = 'error';
    }
    if (stateLabel) stateLabel.textContent = '0';
    if (stateDetail) stateDetail.textContent = `Pi session status unavailable: ${error.message}`;
    if (headerPiSessionsEl) {
      headerPiSessionsEl.textContent = 'Agents: 0';
      headerPiSessionsEl.dataset.state = 'idle';
      headerPiSessionsEl.title = `Pi session status unavailable: ${error.message}`;
    }
    renderDiscordBotStatus({ ok: false, running: false, error: error.message });
    for (const serverId of omlxControlById.keys()) {
      renderOmlxStatus(serverId, {
        ok: false,
        status: 'offline',
        state: 'offline',
        serverId,
        name: defaultOmlxName(serverId),
        error: `Dashboard status unavailable: ${error.message}`,
        checkedAt: new Date().toISOString()
      });
    }
    errorEl.hidden = false;
    errorEl.textContent = `Dashboard link failed: ${error.message}`;
  }
}

function connectWebSocket() {
  if (!('WebSocket' in window)) return;
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const socket = new WebSocket(`${protocol}//${window.location.host}/ws`);

  socket.addEventListener('open', () => {
    document.body.classList.add('ws-online');
    refreshDisplay();
  });

  socket.addEventListener('message', (event) => {
    let payload;
    try {
      payload = JSON.parse(event.data);
    } catch {
      return;
    }

    if (payload.type === 'camera-command') {
      postCameraCommandResult(payload, {
        ok: false,
        error: 'Dashboard camera client is disabled on this display.'
      }).catch(() => {});
      return;
    }

    if (payload.type === 'pi-sessions') {
      if (latestDisplayPayload) {
        latestDisplayPayload = {
          ...latestDisplayPayload,
          generatedAt: payload.at || new Date().toISOString(),
          piSessions: payload.piSessions || { activeGenerating: 0, sessions: [] }
        };
        renderDisplay(latestDisplayPayload);
      } else {
        refreshDisplay();
      }
      return;
    }

    if (['jarvis-event', 'pulse', 'clients', 'refresh'].includes(payload.type)) refreshDisplay();
  });

  socket.addEventListener('close', () => {
    document.body.classList.remove('ws-online');
    setTimeout(connectWebSocket, 2500);
  });
}

updateClock();
updateDashboardUptime();
setInterval(() => {
  updateClock();
  updateDashboardUptime();
}, 1000);

const urlParams = new URLSearchParams(window.location.search);
const autoStartCamera = false;

function clampClientNumber(value, min, max, fallback) {
  if (value === null || value === undefined || value === '') return fallback;
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return fallback;
  return Math.min(max, Math.max(min, numeric));
}

if ('serviceWorker' in navigator && ['https:', 'http:'].includes(window.location.protocol)) {
  navigator.serviceWorker.register('/sw.js').catch(() => {});
}

function updateCameraAspectRatio(source = {}) {
  let ratio = Number(source.aspectRatio);
  if (!Number.isFinite(ratio) || ratio <= 0) {
    const width = Number(source.width || cameraPreview?.videoWidth || 0);
    const height = Number(source.height || cameraPreview?.videoHeight || 0);
    if (width > 0 && height > 0) ratio = width / height;
  }
  if (Number.isFinite(ratio) && ratio > 0.4 && ratio < 3) {
    cameraAspectRatio = ratio;
    queueCameraPanelPosition();
  }
}

function positionCameraPanel() {
  cameraPositionFrame = 0;
  if (!cameraPanel) return;

  if (cameraPanel.closest('#camera-card')) {
    cameraPanel.style.width = '';
    cameraPanel.style.height = '';
    cameraPanel.style.left = '';
    cameraPanel.style.top = '';
    cameraPanel.style.right = '';
    cameraPanel.style.bottom = '';
    return;
  }

  const screen = document.querySelector('.display-screen');
  const clockCard = document.querySelector('.alarm-clock-card');
  const screenRect = (screen || document.body).getBoundingClientRect();
  const clockRect = clockCard?.getBoundingClientRect();
  const dateRect = alarmDateLine?.getBoundingClientRect();
  const edgeInset = 8;
  const gapAboveCamera = 8;
  const cameraBottom = clockRect
    ? Math.max(0, Math.min(screenRect.height, clockRect.bottom - screenRect.top))
    : screenRect.height;
  const ratio = Math.min(3, Math.max(0.4, cameraAspectRatio || (4 / 3)));
  const isShortLandscape = window.matchMedia('(orientation: landscape) and (max-height: 390px)').matches;
  const maxWidth = Math.max(96, screenRect.width - edgeInset * 2);
  const desiredWidth = Math.min(maxWidth, screenRect.width * (isShortLandscape ? 0.34 : 0.38));
  const clearTop = dateRect
    ? Math.max(0, dateRect.bottom - screenRect.top + gapAboveCamera)
    : Math.max(0, screenRect.height * 0.68);
  const availableHeight = Math.max(48, cameraBottom - clearTop);

  let width = desiredWidth;
  let height = width / ratio;
  if (height > availableHeight) {
    height = availableHeight;
    width = Math.min(maxWidth, height * ratio);
  }

  const left = (screenRect.width - width) / 2;

  cameraPanel.style.width = `${Math.round(width)}px`;
  cameraPanel.style.height = `${Math.round(height)}px`;
  cameraPanel.style.left = `${Math.round(left)}px`;
  cameraPanel.style.top = `${Math.round(cameraBottom - height)}px`;
  cameraPanel.style.right = 'auto';
  cameraPanel.style.bottom = 'auto';
}

function queueCameraPanelPosition() {
  if (!cameraPanel || cameraPositionFrame) return;
  cameraPositionFrame = window.requestAnimationFrame(positionCameraPanel);
}

function setCameraStatus(state, label, detail = '') {
  if (cameraCard) {
    cameraCard.dataset.state = state;
    cameraCard.title = detail || label || 'Dashboard camera';
  }
  if (cameraPanel) {
    cameraPanel.dataset.state = state;
    cameraPanel.hidden = false;
    cameraPanel.setAttribute('aria-pressed', cameraStream ? 'true' : 'false');
    cameraPanel.setAttribute('aria-label', cameraStream ? 'Stop camera preview' : 'Start camera preview');
    cameraPanel.title = detail || label || 'Toggle camera preview';
    queueCameraPanelPosition();
  }
  if (cameraStatus) {
    cameraStatus.textContent = label;
    cameraStatus.title = detail;
  }
}

function stopCameraTest() {
  if (cameraStream) {
    for (const track of cameraStream.getTracks()) track.stop();
    cameraStream = null;
  }
  if (cameraPreview) cameraPreview.srcObject = null;
  setCameraStatus('idle', 'Camera standby');
}

async function requestCameraStream() {
  const preferredConstraints = {
    audio: false,
    video: {
      facingMode: { ideal: 'user' },
      width: { ideal: 640 },
      height: { ideal: 360 }
    }
  };

  try {
    return await navigator.mediaDevices.getUserMedia(preferredConstraints);
  } catch (error) {
    if (['OverconstrainedError', 'ConstraintNotSatisfiedError', 'NotFoundError'].includes(error?.name)) {
      return navigator.mediaDevices.getUserMedia({ audio: false, video: true });
    }
    throw error;
  }
}

async function startCameraTest() {
  if (cameraStream) return cameraStream;
  if (cameraStartPromise) return cameraStartPromise;

  cameraStartPromise = (async () => {
    if (!window.isSecureContext) {
      setCameraStatus('error', 'Secure origin off', 'Camera access needs HTTPS or Chrome insecure-origin whitelist.');
      return null;
    }

    if (!navigator.mediaDevices?.getUserMedia) {
      setCameraStatus('error', 'Camera API unavailable', 'This browser does not expose navigator.mediaDevices.getUserMedia.');
      return null;
    }

    setCameraStatus('testing', 'Camera linking…');

    try {
      cameraStream = await requestCameraStream();
      const [videoTrack] = cameraStream.getVideoTracks();
      updateCameraAspectRatio(videoTrack?.getSettings?.() || {});
      if (cameraPreview) {
        cameraPreview.srcObject = cameraStream;
        await cameraPreview.play().catch(() => {});
        updateCameraAspectRatio();
      }
      setCameraStatus('online', 'Camera online', 'Tap preview to stop.');
      return cameraStream;
    } catch (error) {
      cameraStream = null;
      const denied = ['NotAllowedError', 'PermissionDeniedError', 'SecurityError'].includes(error?.name);
      setCameraStatus('error', denied ? 'Camera denied' : 'Camera error', error?.message || String(error));
      return null;
    } finally {
      cameraStartPromise = null;
    }
  })();

  return cameraStartPromise;
}

function toggleCameraTest() {
  if (cameraStream) {
    stopCameraTest();
  } else {
    startCameraTest();
  }
}

async function ensureCameraStream() {
  const stream = cameraStream || await startCameraTest();
  if (!stream) {
    throw new Error(cameraStatus?.textContent || 'Camera did not start.');
  }
  return stream;
}

function blobFromCanvas(canvas, mime = 'image/jpeg', quality = 0.86) {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) resolve(blob);
      else reject(new Error('Snapshot encoding failed.'));
    }, mime, quality);
  });
}

function pickRecordingMime(preferred = '') {
  if (!window.MediaRecorder) return '';
  const candidates = [
    preferred,
    'video/webm;codecs=vp9,opus',
    'video/webm;codecs=vp8,opus',
    'video/webm;codecs=vp8',
    'video/webm',
    'video/mp4'
  ].filter(Boolean);
  return candidates.find((mime) => MediaRecorder.isTypeSupported?.(mime)) || '';
}

async function uploadCameraBlob(command, blob, meta = {}) {
  const url = new URL(command.uploadUrl || '/api/jarvis/camera/upload', window.location.origin);
  url.searchParams.set('kind', meta.kind || command.command || 'snapshot');
  url.searchParams.set('mime', blob.type || meta.mime || 'application/octet-stream');
  if (meta.width) url.searchParams.set('width', String(meta.width));
  if (meta.height) url.searchParams.set('height', String(meta.height));
  if (meta.durationMs) url.searchParams.set('durationMs', String(meta.durationMs));

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'content-type': blob.type || meta.mime || 'application/octet-stream',
      'x-jarvis-camera-token': command.uploadToken || ''
    },
    body: blob
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || result.ok === false) {
    throw new Error(result.error || `Camera upload failed with HTTP ${response.status}`);
  }
  return result;
}

async function postCameraCommandResult(command, payload) {
  if (!command.resultUrl) return;
  await fetch(command.resultUrl, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'x-jarvis-camera-token': command.uploadToken || ''
    },
    body: JSON.stringify(payload)
  }).catch(() => {});
}

async function captureSnapshotCommand(command) {
  await ensureCameraStream();
  if (!cameraPreview) throw new Error('Camera preview element is missing.');
  const width = cameraPreview.videoWidth || cameraStream?.getVideoTracks?.()[0]?.getSettings?.().width || 640;
  const height = cameraPreview.videoHeight || cameraStream?.getVideoTracks?.()[0]?.getSettings?.().height || 480;
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext('2d');
  if (!context) throw new Error('Canvas capture is unavailable.');
  context.drawImage(cameraPreview, 0, 0, width, height);
  const mime = command.options?.mime || 'image/jpeg';
  const quality = Number(command.options?.quality ?? 0.86);
  const blob = await blobFromCanvas(canvas, mime, quality);
  return uploadCameraBlob(command, blob, { kind: 'snapshot', width, height });
}

async function recordVideoCommand(command) {
  const stream = await ensureCameraStream();
  if (!window.MediaRecorder) throw new Error('MediaRecorder is unavailable in this browser.');
  const durationMs = Math.max(250, Math.min(Number(command.options?.durationMs || 5000), 20000));
  const mimeType = pickRecordingMime(command.options?.mime || '');
  const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
  const chunks = [];

  await new Promise((resolve, reject) => {
    const stopTimer = window.setTimeout(() => {
      if (recorder.state !== 'inactive') recorder.stop();
    }, durationMs);
    recorder.addEventListener('dataavailable', (event) => {
      if (event.data?.size) chunks.push(event.data);
    });
    recorder.addEventListener('error', (event) => {
      window.clearTimeout(stopTimer);
      reject(event.error || new Error('Video recording failed.'));
    });
    recorder.addEventListener('stop', () => {
      window.clearTimeout(stopTimer);
      resolve();
    }, { once: true });
    recorder.start(250);
  });

  if (!chunks.length) throw new Error('Video recording produced no data.');
  const blob = new Blob(chunks, { type: recorder.mimeType || mimeType || 'video/webm' });
  const settings = stream.getVideoTracks?.()[0]?.getSettings?.() || {};
  return uploadCameraBlob(command, blob, {
    kind: 'record',
    durationMs,
    width: settings.width || cameraPreview?.videoWidth || undefined,
    height: settings.height || cameraPreview?.videoHeight || undefined
  });
}

async function handleCameraCommand(command) {
  if (!command?.requestId) return;
  const isRecord = command.command === 'record';
  setCameraStatus('testing', isRecord ? 'Recording…' : 'Capturing…');
  try {
    const result = isRecord ? await recordVideoCommand(command) : await captureSnapshotCommand(command);
    setCameraStatus('online', 'Camera online', 'Tap preview to stop.');
    return result;
  } catch (error) {
    const message = error?.message || String(error);
    setCameraStatus('error', isRecord ? 'Record failed' : 'Capture failed', message);
    await postCameraCommandResult(command, { ok: false, error: message });
    return null;
  }
}

cameraPanel?.addEventListener('click', toggleCameraTest);
cameraPreview?.addEventListener('loadedmetadata', () => updateCameraAspectRatio());
cameraPanel?.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    toggleCameraTest();
  }
});

for (const button of omlxButtons) {
  button.addEventListener('click', () => {
    toggleOmlxServer(button.dataset.omlxServer);
  });
}

raspberryPiButton?.addEventListener('click', () => {
  toggleRaspberryPiService();
});

phoneAdbButton?.addEventListener('click', () => {
  pingPhoneAdb();
});

for (const button of smartPlugButtons) {
  addSmartPlugClickHandler(button);
}

reloadButton?.addEventListener('click', () => {
  reloadButton.setAttribute('aria-busy', 'true');
  window.location.reload();
});

window.addEventListener('resize', queueCameraPanelPosition, { passive: true });
window.addEventListener('orientationchange', queueCameraPanelPosition, { passive: true });
document.addEventListener('visibilitychange', () => {
  if (document.hidden) return;
  if (cameraStream) queueCameraPanelPosition();
  refreshActiveModelsUsage();
  refreshSmartPlugStatuses({ silent: true, force: true });
});
if (document.fonts?.ready) {
  document.fonts.ready.then(queueCameraPanelPosition).catch(() => {});
}

for (const serverId of omlxControlById.keys()) renderOmlxStatus(serverId, { state: 'idle' });
renderRaspberryPiStatus({ state: 'idle' });
renderPhoneAdbStatus({ state: 'idle' });
renderActiveModelsUsage({
  ok: false,
  generatedAt: new Date().toISOString(),
  totals: { activeRequests: 0, waitingRequests: 0, loadedModels: 0, memoryUsed: 0, memoryMax: 0 },
  servers: []
});
renderAllSmartPlugsChecking();
setCameraStatus(window.isSecureContext ? 'idle' : 'error', window.isSecureContext ? 'Camera standby' : 'Secure origin off');
window.addEventListener('pagehide', stopCameraTest);
for (const [index, serverId] of Array.from(omlxControlById.keys()).entries()) {
  window.setTimeout(() => pingOmlxStatus(serverId), 500 + (index * 200));
}
window.setTimeout(pingRaspberryPi, 900);
if (phoneAdbButton) window.setTimeout(pingPhoneAdb, 1100);
window.setTimeout(refreshActiveModelsUsage, 1200);
window.setTimeout(() => refreshSmartPlugStatuses({ force: true }), 1300);

if (autoStartCamera) {
  window.setTimeout(startCameraTest, 650);
}

connectWebSocket();
refreshDisplay();
setInterval(refreshDisplay, 10_000);
setInterval(refreshActiveModelsUsage, ACTIVE_MODELS_REFRESH_INTERVAL_MS);
setInterval(() => {
  for (const [index, serverId] of Array.from(omlxControlById.keys()).entries()) {
    window.setTimeout(() => pingOmlxStatus(serverId), index * 200);
  }
  window.setTimeout(pingRaspberryPi, 700);
  if (phoneAdbButton) window.setTimeout(pingPhoneAdb, 1100);
}, INDICATOR_REFRESH_INTERVAL_MS);
setInterval(() => refreshSmartPlugStatuses({ silent: true }), 5_000);
