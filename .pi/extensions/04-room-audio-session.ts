import { chmod, lstat, mkdir, rename, unlink, writeFile } from 'node:fs/promises';
import { createServer, type Socket } from 'node:net';
import { join } from 'node:path';
import { randomBytes } from 'node:crypto';
import type { ExtensionAPI, ExtensionContext } from '@earendil-works/pi-coding-agent';
import { exactMobileTmuxIdentity } from './lib/attach/mobile-server.ts';
import { RoomSessionGate } from './lib/room-session.ts';

/** Only loaded into the separately provisioned Room Audio pane; never reloads 1–9. */
export default function(pi: ExtensionAPI) {
  let ctx: ExtensionContext | undefined;
  let gate: RoomSessionGate | undefined;
  let close: (() => Promise<void>) | undefined;
  let publish: (() => Promise<void>) | undefined;
  pi.on('session_start', async (_event, context) => {
    if ((await exactMobileTmuxIdentity())?.slot !== 10) return;
    ctx = context;
    pi.setSessionName('Room Audio');
    if (gate) { await publish?.(); return; }
    const directory = join(context.cwd, '.pi/runtime/room-audio-session');
    await mkdir(directory, { recursive: true, mode: 0o700 });
    const info = await lstat(directory);
    if (!info.isDirectory() || info.isSymbolicLink() || info.uid !== process.getuid?.() || (info.mode & 0o777) !== 0o700)
      throw new Error('Private room session directory unavailable');
    const generation = randomBytes(12).toString('hex');
    const socketPath = join(directory, `room-${process.pid}.sock`);
    const descriptor = join(directory, 'owner.json');
    gate = new RoomSessionGate({
      ready: () => !!ctx?.hasUI && ctx.isIdle() && !ctx.hasPendingMessages() && ctx.ui.getEditorText().length === 0,
      send: text => pi.sendUserMessage(text),
      abort: async () => { await ctx?.abort(); },
    });
    const sockets = new Set<Socket>();
    const server = createServer(socket => {
      if (sockets.size >= 8) { socket.destroy(); return; }
      sockets.add(socket); socket.on('close', () => sockets.delete(socket)); socket.on('error', () => {});
      let raw = Buffer.alloc(0), read = false;
      socket.setTimeout(5000, () => socket.destroy());
      socket.on('data', async chunk => {
        if (read) { socket.destroy(); return; }
        raw = Buffer.concat([raw, chunk]);
        if (raw.length > 40000) { socket.destroy(); return; }
        if (!raw.includes(10)) return;
        read = true; socket.setTimeout(0);
        try {
          if (raw.indexOf(10) !== raw.length - 1) throw new Error();
          if ((await exactMobileTmuxIdentity())?.slot !== 10) throw new Error();
          const request = JSON.parse(raw.toString('utf8'));
          if (request.generation !== generation || request.version !== 1) throw new Error();
          let result: object;
          if (request.action === 'status' && Object.keys(request).length === 3) result = gate!.status();
          else if (request.action === 'prompt' && Object.keys(request).length === 5)
            result = await gate!.prompt(request.id, request.text);
          else if (request.action === 'abort' && Object.keys(request).length === 4 && typeof request.id === 'string')
            result = await gate!.abort(request.id);
          else throw new Error();
          socket.end(JSON.stringify(result) + '\n');
        } catch { socket.end(JSON.stringify({ ok: false, error: 'room-session-unavailable; never replay' }) + '\n'); }
      });
    });
    await new Promise<void>((resolve, reject) => { server.once('error', reject); server.listen(socketPath, resolve); });
    await chmod(socketPath, 0o600);
    publish = async () => {
      const temporary = descriptor + '.' + randomBytes(8).toString('hex');
      await writeFile(temporary, JSON.stringify({ version: 1, sessionID: 10, pid: process.pid,
        generation, socketPath, sessionFile: ctx?.sessionManager.getSessionFile() }), { mode: 0o600, flag: 'wx' });
      await rename(temporary, descriptor);
    };
    await publish();
    close = async () => { gate?.close(); for (const socket of sockets) socket.destroy();
      await new Promise<void>(resolve => server.close(() => resolve())); await unlink(socketPath).catch(() => {}); };
  });
  pi.on('input', (event, context) => {
    if (!gate || gate.input(event.source, event.text)) return { action: 'continue' as const };
    if (event.source === 'interactive') {
      context.ui.setEditorText(event.text);
      context.ui.notify('Room audio is using Session 10. Stop it before sending; your draft was retained.', 'warning');
    }
    return { action: 'handled' as const };
  });
  pi.on('agent_start', (_event, context) => { ctx = context; gate?.started(); });
  pi.on('agent_settled', async (_event, context) => {
    ctx = context;
    if (!gate || !context.isIdle()) return;
    const entry = [...context.sessionManager.getBranch()].reverse().find((e: any) => e.type === 'message' && e.message?.role === 'assistant') as any;
    const message = entry?.message;
    const text = (message?.content ?? []).filter((p: any) => p.type === 'text').map((p: any) => p.text).join('\n');
    gate.settled(text, !message || ['error', 'aborted'].includes(message.stopReason));
    await publish?.();
  });
  pi.on('session_before_switch', async () => {
    if (gate?.status().requestID) return { cancel: true };
  });
  pi.on('session_before_fork', async () => {
    if (gate?.status().requestID) return { cancel: true };
  });
  pi.on('session_shutdown', async () => { await close?.(); });
}
