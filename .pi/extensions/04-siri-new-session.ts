import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { exactMobileTmuxIdentity } from "./lib/attach/mobile-server.ts";
import { hasConversation, SiriNewSessionGate, startSiriNewSessionServer } from "./lib/siri-new-session.ts";

/** Optional ingress for the nine protected mobile panes only. Never creates,
 * switches, resumes, resets, or reloads a Pi session. Loaded before attachments
 * so an overlapping editor submit can be refused without consuming staged files.
 */
export function registerSiriNewSession(pi: ExtensionAPI, identityProbe = exactMobileTmuxIdentity) {
  let gate: SiriNewSessionGate | undefined;
  let stop: (() => Promise<void>) | undefined;
  let promptActive = false, compacting = false;
  pi.on("session_start", async (_event, ctx) => {
    await stop?.(); stop = undefined; gate = undefined;
    const identity = await identityProbe();
    if (!identity) return;
    promptActive = false; compacting = false;
    let root = resolve(ctx.cwd);
    while (!existsSync(join(root, ".pi")) || !existsSync(join(root, "projects"))) {
      const parent = dirname(root); if (parent === root) return; root = parent;
    }
    gate = new SiriNewSessionGate(() => {
      const entries = ctx.sessionManager.getEntries();
      return ctx.hasUI && ctx.isIdle() === true && ctx.hasPendingMessages() === false &&
        !promptActive && !compacting && ctx.ui.getEditorText().length === 0 &&
        Array.isArray(entries) && !hasConversation(entries);
    }, text => pi.sendUserMessage(text), pending => pi.events.emit("jarvis:siri-admission", { pending })); // literal user message, no template/command expansion or queue
    try { stop = await startSiriNewSessionServer(join(root, ".pi", "runtime", "siri-new"), identity.slot, gate, async () => (await identityProbe())?.slot === identity.slot); }
    catch { gate.close(); } // missing capability makes Siri refuse, never use the selected slot
  });
  pi.on("input", (event, ctx) => {
    if (!gate || gate.input(event)) return { action: "continue" as const };
    if (event.source === "interactive" && ctx.hasUI) {
      ctx.ui.setEditorText(event.text);
      ctx.ui.notify("Siri is claiming this unused session. Your draft was retained; wait before sending.", "warning");
    }
    return { action: "handled" as const };
  });
  pi.on("message_start", event => gate?.message(event.message));
  pi.on("ui_prompt_start", () => { promptActive = true; });
  pi.on("ui_prompt_end", () => { promptActive = false; });
  pi.on("session_before_compact", () => { compacting = true; });
  pi.on("session_compact", () => { compacting = false; });
  pi.on("session_compact_failed", () => { compacting = false; });
  pi.on("session_shutdown", async () => { gate?.close(); await stop?.(); stop = undefined; });
}

export default function(pi: ExtensionAPI) { registerSiriNewSession(pi); }
