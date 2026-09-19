import { randomBytes } from 'node:crypto';

export type RoomHooks = { ready(): boolean; send(text: string): void; abort(): Promise<void> | void };
/** One owner/event-loop for both microphones and interactive Session 10. No queue. */
export class RoomSessionGate {
  private active?: { id: string; finish?: (value: object) => void; cancelled: boolean; text?: string; admitted?: boolean };
  private inputPending = false;
  private consumed = new Set<string>();
  private closed = false;
  private hooks: RoomHooks;
  constructor(hooks: RoomHooks) { this.hooks = hooks; }
  status() { return { ok: !this.closed, sessionID: 10, requestID: this.active?.id ?? null,
    busy: !!this.active || this.inputPending || !this.hooks.ready() }; }
  prompt(id: string, text: string): Promise<object> {
    if (!/^[0-9a-f]{32}$/.test(id) || typeof text !== 'string' || !text.trim() || Buffer.byteLength(text) > 32768)
      return Promise.resolve({ ok: false, error: 'invalid' });
    if (this.closed || this.active || this.inputPending || !this.hooks.ready() || this.consumed.has(id) || this.consumed.size >= 4096)
      return Promise.resolve({ ok: false, error: 'busy-or-consumed; never replay automatically' });
    this.consumed.add(id);
    return new Promise(finish => {
      this.active = { id, finish, cancelled: false, text };
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
