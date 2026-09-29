import { randomBytes } from 'node:crypto';

export type RoomHooks = { ready(): boolean; send(text: string): void; abort(): Promise<void> | void };
export type RoomCandidateEvent =
  | { type: 'candidate_start' | 'candidate_invalidate'; candidate: number }
  | { type: 'candidate_delta'; candidate: number; delta: string }
  | { type: 'candidate_end'; candidate: number; text: string };
/** One owner/event-loop for both microphones and interactive Session 10. No queue. */
export class RoomSessionGate {
  private active?: { id: string; finish?: (value: object) => void; cancelled: boolean; text?: string; admitted?: boolean;
    emit?: (event: RoomCandidateEvent) => void; candidate?: number; candidateOpen?: boolean };
  private inputPending = false;
  private consumed = new Set<string>();
  private closed = false;
  private hooks: RoomHooks;
  constructor(hooks: RoomHooks) { this.hooks = hooks; }
  status() { return { ok: !this.closed, sessionID: 10, requestID: this.active?.id ?? null,
    busy: !!this.active || this.inputPending || !this.hooks.ready() }; }
  prompt(id: string, text: string, emit?: (event: RoomCandidateEvent) => void): Promise<object> {
    if (!/^[0-9a-f]{32}$/.test(id) || typeof text !== 'string' || !text.trim() || Buffer.byteLength(text) > 32768)
      return Promise.resolve({ ok: false, error: 'invalid' });
    if (this.closed || this.active || this.inputPending || !this.hooks.ready() || this.consumed.has(id) || this.consumed.size >= 4096)
      return Promise.resolve({ ok: false, error: 'busy-or-consumed; never replay automatically' });
    this.consumed.add(id);
    return new Promise(finish => {
      this.active = { id, finish, cancelled: false, text, emit };
      try { this.hooks.send(text); }
      catch { this.active = undefined; finish({ ok: false, error: 'delivery-unknown' }); }
    });
  }
  input(source: string, text: string): boolean {
    if (this.active?.finish) {
      if (source === 'extension' && text === this.active.text && !this.active.admitted) {
        this.active.admitted = true; return true;
      }
      return false;
    }
    this.inputPending = true; return true;
  }
  started() {
    this.inputPending = false;
    if (!this.active && !this.closed) this.active = { id: randomBytes(16).toString('hex'), cancelled: false };
  }
  private candidateEvent(event: RoomCandidateEvent) {
    const active = this.active;
    if (!active?.finish || !active.admitted || active.cancelled) return;
    // A failed/slow candidate channel must never interrupt the actual agent.
    try { active.emit?.(event); } catch { active.emit = undefined; }
  }
  candidateStarted() {
    const active = this.active;
    if (!active?.finish || !active.admitted || active.cancelled) return;
    active.candidate = (active.candidate ?? 0) + 1; active.candidateOpen = true;
    this.candidateEvent({ type: 'candidate_start', candidate: active.candidate });
  }
  candidateDelta(delta: string) {
    const active = this.active;
    if (active?.candidateOpen && delta)
      this.candidateEvent({ type: 'candidate_delta', candidate: active.candidate!, delta });
  }
  candidateInvalidated() {
    const active = this.active;
    if (!active?.candidateOpen) return;
    active.candidateOpen = false;
    this.candidateEvent({ type: 'candidate_invalidate', candidate: active.candidate! });
  }
  candidateEnded(text: string, failed = false) {
    if (failed) { this.candidateInvalidated(); return; }
    const active = this.active;
    if (active?.candidateOpen)
      this.candidateEvent({ type: 'candidate_end', candidate: active.candidate!, text });
  }
  settled(text: string, failed = false) {
    const active = this.active; this.active = undefined; this.inputPending = false;
    active?.finish?.({ ok: !failed && !active.cancelled, requestID: active.id,
      text: !failed && !active.cancelled ? text : '', error: failed || active.cancelled ? 'cancelled-or-failed' : undefined });
  }
  async abort(id: string) {
    if (!this.active || this.active.id !== id) return { ok: false, error: 'turn-changed' };
    this.active.cancelled = true;
    await this.hooks.abort();
    return { ok: true, requestID: id };
  }
  close() { this.closed = true; this.settled('', true); }
}
