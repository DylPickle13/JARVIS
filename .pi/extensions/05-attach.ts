import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

import {
  AttachmentStore,
  buildAttachmentPromptBlock,
  formatAttachmentBytes,
  localAttachmentCandidates,
  type StagedAttachment,
} from "./lib/attach/core.ts";
import { prepareAttachmentImages } from "./lib/attach/images.ts";
import {
  looksLikeSshSession,
  requestSshAttachmentPicker,
  runNativeAttachmentPicker,
  sshAttachmentBridgeConfigured,
  type PickedAttachmentCandidates,
} from "./lib/attach/transport.ts";

const PROJECT_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const ATTACHMENTS_ROOT = join(PROJECT_ROOT, "attachments");
const NATIVE_PICKER = join(PROJECT_ROOT, ".pi", "scripts", "pi-attach-picker");
const WIDGET_KEY = "pi-attach";
const STATUS_KEY = "pi-attach";
const PLAIN_SSH_MESSAGE =
  "This SSH session cannot open a picker on your computer.\nReconnect using: jarvis-pi-ssh mac-mini-64";

function modelSupportsImages(ctx: ExtensionContext): boolean {
  return Array.isArray(ctx.model?.input) && ctx.model.input.includes("image");
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export default function registerAttachExtension(pi: ExtensionAPI) {
  let store: AttachmentStore | undefined;
  let staged: StagedAttachment[] = [];
  let activeSessionId = "";
  let pickerBusy = false;

  function bindStore(ctx: ExtensionContext): AttachmentStore {
    const sessionId = ctx.sessionManager.getSessionId() || `ephemeral-${process.pid}`;
    if (!store || activeSessionId !== sessionId) {
      activeSessionId = sessionId;
      store = new AttachmentStore(ATTACHMENTS_ROOT);
      staged = [];
    }
    return store;
  }

  function updateWidget(ctx: ExtensionContext): void {
    if (ctx.mode !== "tui") return;
    if (staged.length === 0) {
      ctx.ui.setWidget(WIDGET_KEY, undefined);
      return;
    }
    const visible = staged.slice(0, 8).map((item) => `  • ${item.displayName} (${formatAttachmentBytes(item.sizeBytes)})`);
    if (staged.length > visible.length) visible.push(`  • …and ${staged.length - visible.length} more`);
    ctx.ui.setWidget(
      WIDGET_KEY,
      [
        `📎 ${staged.length} attachment${staged.length === 1 ? "" : "s"} staged for the next message`,
        ...visible,
        "Run /attach to change this selection.",
      ],
      { placement: "aboveEditor" },
    );
  }

  async function reloadStaged(ctx: ExtensionContext): Promise<void> {
    const currentStore = bindStore(ctx);
    staged = await currentStore.load();
    updateWidget(ctx);
  }

  async function chooseCandidates(currentStore: AttachmentStore): Promise<PickedAttachmentCandidates> {
    const existing = staged.map((item) => ({ id: item.id, name: item.displayName, sizeBytes: item.sizeBytes }));
    if (sshAttachmentBridgeConfigured()) {
      return requestSshAttachmentPicker(existing, currentStore.limits);
    }
    if (looksLikeSshSession()) {
      throw new Error(PLAIN_SSH_MESSAGE);
    }
    const result = await runNativeAttachmentPicker(NATIVE_PICKER, existing, currentStore.limits);
    const uniquePaths = [...new Set(result.paths)];
    if (uniquePaths.length !== result.paths.length) {
      throw new Error("The attachment picker returned duplicate files.");
    }
    return {
      cancelled: result.cancelled,
      keepIds: result.keepIds,
      candidates: result.cancelled ? [] : await localAttachmentCandidates(uniquePaths),
      release: async () => undefined,
    };
  }

  async function pickAndStage(ctx: ExtensionContext): Promise<void> {
    if (pickerBusy) {
      ctx.ui.notify("The attachment picker is already open.", "warning");
      return;
    }
    pickerBusy = true;
    ctx.ui.setStatus(STATUS_KEY, "Opening attachment picker…");
    let picked: PickedAttachmentCandidates | undefined;
    try {
      const currentStore = bindStore(ctx);
      picked = await chooseCandidates(currentStore);
      if (picked.cancelled) {
        ctx.ui.notify("Attachment selection cancelled.", "info");
        return;
      }
      const beforeIds = staged.map((item) => item.id);
      staged = await currentStore.reconcile(picked.keepIds, picked.candidates);
      updateWidget(ctx);
      const unchanged =
        picked.candidates.length === 0 &&
        beforeIds.length === picked.keepIds.length &&
        beforeIds.every((id, index) => id === picked.keepIds[index]);
      if (unchanged) {
        ctx.ui.notify("Attachment selection unchanged.", "info");
      } else if (staged.length === 0) {
        ctx.ui.notify("Staged attachments cleared.", "info");
      } else {
        ctx.ui.notify(
          `${staged.length} file${staged.length === 1 ? "" : "s"} staged for the next message.`,
          "info",
        );
      }
    } finally {
      if (picked) await picked.release();
      pickerBusy = false;
      ctx.ui.setStatus(STATUS_KEY, undefined);
    }
  }

  pi.registerCommand("attach", {
    description: "Choose files to attach to the next message.",
    handler: async (args, ctx) => {
      if (args.trim()) {
        ctx.ui.notify("/attach takes no arguments.", "warning");
        return;
      }
      if (ctx.mode !== "tui" || !ctx.hasUI) {
        ctx.ui.notify("/attach requires an interactive Pi terminal.", "error");
        return;
      }
      try {
        await reloadStaged(ctx);
        await pickAndStage(ctx);
      } catch (error) {
        const message = errorMessage(error);
        ctx.ui.notify(message === PLAIN_SSH_MESSAGE ? message : `Could not attach files: ${message}`, "error");
      }
    },
  });

  pi.on("session_start", async (_event, ctx) => {
    if (ctx.mode === "tui") ctx.ui.setStatus(STATUS_KEY, undefined);
    try {
      await reloadStaged(ctx);
    } catch (error) {
      staged = [];
      updateWidget(ctx);
      ctx.ui.notify(`Could not initialize attachments: ${errorMessage(error)}`, "error");
    }
  });

  pi.on("input", async (event, ctx) => {
    if (event.source !== "interactive") return { action: "continue" as const };
    const currentStore = bindStore(ctx);
    if (staged.length === 0) {
      staged = await currentStore.load().catch(() => []);
      if (staged.length === 0) return { action: "continue" as const };
    }

    const snapshot = [...staged];
    const prepared = await prepareAttachmentImages(snapshot, modelSupportsImages(ctx));
    try {
      staged = await currentStore.consume(snapshot.map((item) => item.id));
    } catch (error) {
      ctx.ui.setEditorText(event.text);
      ctx.ui.notify(`Attachments were not sent: ${errorMessage(error)}`, "error");
      return { action: "handled" as const };
    }
    updateWidget(ctx);

    const attachmentBlock = buildAttachmentPromptBlock(snapshot, prepared.nativeImageIds);
    const text = event.text.trimEnd() ? `${event.text.trimEnd()}\n\n${attachmentBlock}` : attachmentBlock;
    const images = [...(event.images || []), ...prepared.images];
    return {
      action: "transform" as const,
      text,
      ...(images.length > 0 ? { images } : {}),
    };
  });

  pi.on("session_shutdown", async (_event, ctx) => {
    if (ctx.mode === "tui") {
      ctx.ui.setStatus(STATUS_KEY, undefined);
      ctx.ui.setWidget(WIDGET_KEY, undefined);
    }
    store = undefined;
    staged = [];
    activeSessionId = "";
  });
}
