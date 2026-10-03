// Deadlines bound the client's wait, NOT execution cancellation. A deadline
// expiry must quarantine the shared bridge until supervised recovery; it must
// never release the queue to another tab while an old action may still execute.
export function actionDeadlineMs(path, body = {}) {
  if (path === '/scroll') return 15000;
  if (path === '/type' && body.clear && body.delayMs === 0) return 30000;
  return 150000;
}

export function isRequestDeadline(error) {
  return error?.code === -32001 || error?.outcomeUnknown === true || /(?:MCP error -32001|Request timed out)/i.test(String(error?.message || error));
}

export function isLocalActionFailure(path, message) {
  return ['/type','/click','/key','/scroll','/upload','/open'].includes(path) &&
    /TimeoutError|JARVIS_INPUT_UNCERTAIN/.test(message);
}

export function failureKind(error) {
  if (isRequestDeadline(error)) return 'unacknowledged-deadline';
  if (/JARVIS_INPUT_UNCERTAIN/.test(String(error?.message || error))) return 'input-verification';
  if (/TimeoutError/.test(String(error?.message || error))) return 'action-timeout';
  return 'action-or-preflight-error';
}
