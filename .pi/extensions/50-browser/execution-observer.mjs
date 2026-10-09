// Private, same-process hooks for the version-pinned runner/relay. Never exposed
// through HTTP or a browser_* argument. Receipts contain no page/body contents.
export const OBSERVER_KEY = Symbol.for('jarvis.browser.execution-observer.v1');
const registrations = new Map();
let active = null;
const commands = new Map();

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
  command(connection) {
    if (!active) return null;
    const r = active;
    // A changed relay while this execution is alive is never silent proof.
    if (r.connection && r.connection !== connection) r.unknown = true;
    r.connection = connection;
    const token = Object.freeze({});
    commands.set(token, r); r.pending++; changed(r);
    return token;
  },
  acknowledge(token) {
    const r = commands.get(token);
    if (!r) return; // Duplicate/foreign acknowledgement cannot alter proof.
    commands.delete(token); r.pending--; changed(r);
  },
  unknown(token) {
    const r = commands.get(token);
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
    // No force-reset API: a running/ambiguous operation cannot be forgotten.
    retire() {
      if (!snapshot(record).quiescent) throw new Error('Execution proof missing; cannot retire observer');
      if (active === record) active = null;
      registrations.delete(code);
    },
  });
}
