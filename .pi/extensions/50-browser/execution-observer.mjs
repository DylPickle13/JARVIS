// Private, same-process hooks for the version-pinned runner/relay. Never exposed
// through HTTP or a browser_* argument. Receipts contain no page/body contents.
export const OBSERVER_KEY = Symbol.for('jarvis.browser.execution-observer.v1');
const registrations = new Map();
let active = null;
const commands = new Map();
// Private diagnostics only: never retain expressions, selectors, input or URLs.
const COMMAND_NAMES = new Set(['Runtime.callFunctionOn','Runtime.evaluate',
  'Input.dispatchMouseEvent','Input.dispatchKeyEvent','Input.insertText',
  'DOM.scrollIntoViewIfNeeded','DOM.getContentQuads','Page.getLayoutMetrics',
  'chrome.tabs.update','chrome.tabs.get','chrome.tabs.query']);
function commandName(method, params) {
  const name = method === 'chrome.debugger.sendCommand' && Array.isArray(params) ? params[1] : method;
  return COMMAND_NAMES.has(name) ? name : 'other';
}

function changed(record) {
  record.revision++;
  try { Promise.resolve(record.onChange?.(snapshot(record))).catch(() => { record.unknown = true; }); }
  catch { record.unknown = true; }
}
function snapshot(r) {
  return Object.freeze({id:r.id, revision:r.revision, requestEntered:r.requestEntered,
    requestTerminal:r.requestTerminal, snippetEntered:r.snippetEntered,
    snippetTerminal:r.snippetTerminal, outcome:r.outcome, valueVerified:r.valueVerified,
    resultTabId:r.resultTabId, pending:r.pending, unknown:r.unknown,
    quiescent:r.requestTerminal && r.snippetTerminal && r.pending === 0 && !r.unknown});
}

const hooks = Object.freeze({
  async request(code, invoke) {
    const r = registrations.get(code);
    if (!r) return invoke();
    if (r.requestEntered) throw new Error('Duplicate observed browser request refused');
    r.requestEntered = true; changed(r);
    try { return await invoke(); }
    finally { r.requestTerminal = true; changed(r); }
  },
  async snippet(code, invoke) {
    const r = registrations.get(code);
    if (!r) return invoke();
    if (r.snippetEntered) throw new Error('Duplicate observed browser execution refused');
    r.snippetEntered = true; changed(r);
    try {
      const result = await invoke();
      r.outcome = 'completed';
      r.valueVerified = result?.valueVerified === true;
      r.resultTabId = Number.isSafeInteger(result?.tabId) ? result.tabId : null;
      return result;
    } catch (error) { r.outcome = 'failed'; throw error; }
    finally { r.snippetTerminal = true; changed(r); }
  },
  command(connection, method, params) {
    if (!active) return null;
    const r = active;
    // A changed relay while this execution is alive is never silent proof.
    if (r.connection && r.connection !== connection) r.unknown = true;
    r.connection = connection;
    const token = Object.freeze({});
    commands.set(token, {record:r, name:commandName(method, params), started:performance.now()});
    r.pending++; changed(r);
    return token;
  },
  acknowledge(token) {
    const r = commands.get(token)?.record;
    if (!r) return; // Duplicate/foreign acknowledgement cannot alter proof.
    commands.delete(token); r.pending--; changed(r);
  },
  unknown(token) {
    const r = commands.get(token)?.record;
    if (!r) return;
    commands.delete(token); r.pending--; r.unknown = true; changed(r);
  },
});

export function installExecutionObserver() {
  const prior = globalThis[OBSERVER_KEY];
  if (prior && prior !== hooks) throw new Error('Conflicting browser execution observer');
  if (!prior) Object.defineProperty(globalThis, OBSERVER_KEY, {value:hooks});
  return hooks;
}

export function registerExecution(code, {id, onChange} = {}) {
  installExecutionObserver();
  if (active || registrations.has(code)) throw new Error('Unresolved browser execution prevents dispatch');
  const record = {id, onChange, revision:0, requestEntered:false, requestTerminal:false,
    snippetEntered:false, snippetTerminal:false, outcome:'pending', valueVerified:false,
    resultTabId:null, pending:0, unknown:false, connection:null};
  active = record; registrations.set(code, record);
  return Object.freeze({
    snapshot:() => snapshot(record),
    diagnostics() {
      const now = performance.now(), pendingCommands = [];
      for (const command of commands.values()) {
        if (command.record === record && pendingCommands.length < 32)
          pendingCommands.push({name:command.name, ageMs:Math.max(0, Math.floor(now-command.started))});
      }
      return {requestTerminal:record.requestTerminal, snippetTerminal:record.snippetTerminal,
        pending:record.pending, unknown:record.unknown, pendingCommands};
    },
    // No force-reset API: a running/ambiguous operation cannot be forgotten.
    retire() {
      if (!snapshot(record).quiescent) throw new Error('Execution proof missing; cannot retire observer');
      if (active === record) active = null;
      registrations.delete(code);
    },
  });
}
