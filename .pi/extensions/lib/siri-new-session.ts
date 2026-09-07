import { randomBytes } from "node:crypto";
import { chmod, lstat, mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { createServer, type Socket } from "node:net";
import { join } from "node:path";

export function hasConversation(entries: readonly any[]): boolean {
  return entries.some(e => e?.type === "compaction" || e?.type === "branch_summary" ||
    (e?.type === "message" && ["user", "assistant"].includes(e.message?.role)));
}

export const requestIDPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
export function validPrompt(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0 && Buffer.byteLength(value) <= 4096 &&
    !/[\x00-\x1f\x7f-\x9f]/u.test(value);
}

type Outcome = "sent" | "unavailable" | "unconfirmed";

/** Admission is on Pi's own event loop, not a stale heartbeat followed by PTY input.
 * Once dispatch starts, an uncertain result never releases the slot in this runtime.
 */
export class SiriNewSessionGate {
  private consumed = false;
  private inputPending = false;
  private closed = false;
  private claim?: { prompt: string; admitted: boolean; finish: (state: Outcome) => void };
  constructor(
    private readonly ready: () => boolean,
    private readonly send: (prompt: string) => void,
    private readonly reservationChanged: (pending: boolean) => void = () => {},
  ) {}
  available(): boolean {
    try { return !this.closed && !this.consumed && !this.inputPending && this.ready(); }
    catch { return false; }
  }
  submit(prompt: string, timeoutMS = 1800): Promise<Outcome> {
    if (!validPrompt(prompt) || !this.available()) return Promise.resolve("unavailable");
    this.consumed = true; // synchronous single-flight claim, before any await or dispatch
    this.reservationChanged(true);
    return new Promise(resolve => {
      const timer = setTimeout(() => { this.closed = true; finish("unconfirmed"); }, timeoutMS);
      const finish = (state: Outcome) => { clearTimeout(timer); resolve(state); };
      this.claim = { prompt, admitted: false, finish };
      try { this.send(prompt); } catch { finish("unconfirmed"); }
    });
  }
  input(event: { source: string; text: string }): boolean {
    if (this.claim) {
      const own = !this.closed && !this.claim.admitted && event.source === "extension" && event.text === this.claim.prompt;
      if (own) {
        try {
          if (this.ready()) { this.claim.admitted = true; return true; }
        } catch { /* fail closed */ }
        this.claim.finish("unconfirmed");
      }
      return false;
    }
    // An ordinary input already entering Pi must win over a later Siri request.
    this.inputPending = true;
    return true;
  }
  message(message: any) {
    if (!["user", "assistant"].includes(message?.role)) return;
    this.consumed = true;
    if (this.claim) {
      const text = Array.isArray(message.content)
        ? message.content.filter((p: any) => p.type === "text").map((p: any) => p.text).join("\n") : message.content;
      if (message.role === "user" && this.claim.admitted && text === this.claim.prompt) {
        this.claim.finish("sent");
        this.claim = undefined;
        this.reservationChanged(false);
      } else {
        this.closed = true; // unexpected conversation evidence must not release a delayed dispatch
        this.claim.finish("unconfirmed");
      }
    }
  }
  close() { this.closed = true; this.claim?.finish("unconfirmed"); this.reservationChanged(false); }
}

/** Private, bounded local IPC. Descriptor/generation are checked again at admission. */
export async function startSiriNewSessionServer(runtime: string, slot: number, gate: SiriNewSessionGate, identityCheck: () => Promise<boolean> = async () => true) {
  const generation = randomBytes(16).toString("hex");
  await mkdir(runtime, { recursive: true, mode: 0o700 });
  const directory = await lstat(runtime);
  if (!directory.isDirectory() || directory.isSymbolicLink() || directory.uid !== process.getuid?.()) throw new Error("Unsafe Siri runtime directory");
  await chmod(runtime, 0o700);
  const socketPath = join(runtime, `siri-${process.pid}-${generation.slice(0, 8)}.sock`);
  if (Buffer.byteLength(socketPath) > 100) throw new Error("Siri socket path too long");
  const descriptorPath = join(runtime, `slot-${slot}.json`);
  const clients = new Set<Socket>();
  const server = createServer(socket => {
    if (clients.size >= 4) { socket.destroy(); return; }
    clients.add(socket);
    socket.on("close", () => clients.delete(socket));
    socket.on("error", () => {});
    socket.setTimeout(2500, () => socket.destroy());
    let buffer = Buffer.alloc(0), handled = false;
    socket.on("data", chunk => {
      if (handled) { socket.destroy(); return; }
      buffer = Buffer.concat([buffer, chunk]);
      if (buffer.length > 16 * 1024) { socket.destroy(); return; }
      if (!buffer.includes(10)) return;
      handled = true;
      void (async () => {
        try {
          const request = JSON.parse(buffer.toString("utf8"));
          if (request.version !== 1 || request.generation !== generation || !(await identityCheck())) throw new Error("identity");
          if (socket.destroyed) return;
          if (request.operation === "probe") {
            socket.end(JSON.stringify({ version: 1, generation, sessionID: slot, available: gate.available() }) + "\n");
          } else if (request.operation === "submit" && requestIDPattern.test(request.requestID) && validPrompt(request.prompt)) {
            const state = await gate.submit(request.prompt);
            socket.end(JSON.stringify({ version: 1, generation, sessionID: slot, requestID: request.requestID, state }) + "\n");
          } else throw new Error("request");
        } catch { socket.destroy(); } // never expose prompt, exception, path, or credentials
      })();
    });
  });
  server.on("error", () => gate.close());
  try {
    await new Promise<void>((resolve, reject) => { server.once("error", reject); server.listen(socketPath, resolve); });
    await chmod(socketPath, 0o600);
    const temp = descriptorPath + `.${generation}.tmp`;
    await writeFile(temp, JSON.stringify({ version: 1, pid: process.pid, sessionID: slot, generation, socketPath }), { mode: 0o600, flag: "wx" });
    await rename(temp, descriptorPath);
  } catch (error) { server.close(); await rm(socketPath, { force: true }); throw error; }
  return async () => {
    gate.close();
    for (const client of clients) client.destroy();
    await new Promise<void>(resolve => server.close(() => resolve()));
    try {
      const current = JSON.parse(await readFile(descriptorPath, "utf8"));
      if (current.generation === generation) await rm(descriptorPath, { force: true });
    } catch { /* a replacement owns its own descriptor */ }
    await rm(socketPath, { force: true });
  };
}
