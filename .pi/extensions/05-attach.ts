import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

import {
  AttachmentStore,
  buildAttachmentPromptBlock,
  formatAttachmentBytes,
  localAttachmentCandidates,
  type PreparedAttachment,
  type StagedAttachment,
} from "./lib/attach/core.ts";
import { prepareAttachmentImages } from "./lib/attach/images.ts";
import {
  MobileAttachmentServer,
  type MobileAttachmentSnapshot,
} from "./lib/attach/mobile-server.ts";
import {
  looksLikeSshSession,
  requestSshAttachmentPicker,
  runNativeAttachmentPicker,
  sshAttachmentBridgeConfigured,
  type PickedAttachmentCandidates,
} from "./lib/attach/transport.ts";

const PROJECT_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const ATTACHMENTS_ROOT = join(PROJECT_ROOT, "attachments");
const RUNTIME_ROOT = join(PROJECT_ROOT, ".pi", "runtime");
const NATIVE_PICKER = join(PROJECT_ROOT, ".pi", "scripts", "pi-attach-picker");
const WIDGET_KEY = "pi-attach";
const STATUS_KEY = "pi-attach";
const PLAIN_SSH_MESSAGE =
  "This SSH session cannot open a picker on your computer.\nReconnect using: jarvis-pi-ssh mac-mini-64";

class AttachmentMutationLock {
  private tail: Promise<void> = Promise.resolve();

  async run<T>(operation: () => Promise<T>): Promise<T> {
    let release: (() => void) | undefined;
    const next = new Promise<void>((resolvePromise) => {
      release = resolvePromise;
    });
    const previous = this.tail;
    this.tail = previous.then(() => next, () => next);
    await previous;
    try {
      return await operation();
    } finally {
      release?.();
    }
  }
}

function modelSupportsImages(ctx: ExtensionContext): boolean {
  return Array.isArray(ctx.model?.input) && ctx.model.input.includes("image");
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function attachmentSetsEqual(
  first: StagedAttachment[],
  second: StagedAttachment[],
): boolean {
  return (
    first.length === second.length &&
    first.every((item, index) => {
      const other = second[index];
      return (
        other?.id === item.id &&
        other.path === item.path &&
        other.sizeBytes === item.sizeBytes &&
        other.sha256 === item.sha256
      );
    })
  );
}

export default function registerAttachExtension(pi: ExtensionAPI) {
  let store: AttachmentStore | undefined;
  let staged: StagedAttachment[] = [];
  let activeSessionId = "";
  let activeContext: ExtensionContext | undefined;
  let pickerBusy = false;
  let revision = 0;
  let mobileServer: MobileAttachmentServer | undefined;
  const mutationLock = new AttachmentMutationLock();

  function bindStore(ctx: ExtensionContext): AttachmentStore {
    const sessionId = ctx.sessionManager.getSessionId() || `ephemeral-${process.pid}`;
    if (!store || activeSessionId !== sessionId) {
      activeSessionId = sessionId;
      store = new AttachmentStore(ATTACHMENTS_ROOT);
      staged = [];
      revision = 0;
    }
    return store;
  }

  function updateWidget(ctx: ExtensionContext): void {
    if (ctx.mode !== "tui") return;
    if (staged.length === 0) {
      ctx.ui.setWidget(WIDGET_KEY, undefined);
      return;
    }
    const visible = staged
      .slice(0, 8)
      .map(
        (item) =>
          `  • ${item.displayName} (${formatAttachmentBytes(item.sizeBytes)})`,
      );
    if (staged.length > visible.length) {
      visible.push(`  • …and ${staged.length - visible.length} more`);
    }
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

  async function loadCurrent(
    ctx: ExtensionContext,
    currentStore = bindStore(ctx),
  ): Promise<StagedAttachment[]> {
    const loaded = await currentStore.load();
    if (!attachmentSetsEqual(staged, loaded)) revision += 1;
    staged = loaded;
    updateWidget(ctx);
    return loaded;
  }

  function currentSnapshot(currentStore: AttachmentStore): MobileAttachmentSnapshot {
    return {
      revision,
      limits: currentStore.limits,
      staged: [...staged],
    };
  }

  async function chooseCandidates(
    currentStore: AttachmentStore,
    existing: StagedAttachment[],
  ): Promise<PickedAttachmentCandidates> {
    const pickerExisting = existing.map((item) => ({
      id: item.id,
      name: item.displayName,
      sizeBytes: item.sizeBytes,
    }));
    if (sshAttachmentBridgeConfigured()) {
      return requestSshAttachmentPicker(pickerExisting, currentStore.limits);
    }
    if (looksLikeSshSession()) throw new Error(PLAIN_SSH_MESSAGE);
    const result = await runNativeAttachmentPicker(
      NATIVE_PICKER,
      pickerExisting,
      currentStore.limits,
    );
    const uniquePaths = [...new Set(result.paths)];
    if (uniquePaths.length !== result.paths.length) {
      throw new Error("The attachment picker returned duplicate files.");
    }
    return {
      cancelled: result.cancelled,
      keepIds: result.keepIds,
      candidates: result.cancelled
        ? []
        : await localAttachmentCandidates(uniquePaths),
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
      const opening = await mutationLock.run(async () => {
        const currentStore = bindStore(ctx);
        const existing = await loadCurrent(ctx, currentStore);
        return { currentStore, existing: [...existing], revision };
      });
      picked = await chooseCandidates(opening.currentStore, opening.existing);
      if (picked.cancelled) {
        ctx.ui.notify("Attachment selection cancelled.", "info");
        return;
      }
      const beforeIds = opening.existing.map((item) => item.id);
      await mutationLock.run(async () => {
        if (store !== opening.currentStore || revision !== opening.revision) {
          throw new Error(
            "The staged attachments changed while the picker was open. Run /attach again.",
          );
        }
        const next = await opening.currentStore.reconcile(
          picked!.keepIds,
          picked!.candidates,
        );
        const unchanged =
          picked!.candidates.length === 0 &&
          beforeIds.length === picked!.keepIds.length &&
          beforeIds.every((id, index) => id === picked!.keepIds[index]);
        staged = next;
        if (!unchanged) revision += 1;
        updateWidget(ctx);
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
      });
    } finally {
      if (picked) await picked.release();
      pickerBusy = false;
      ctx.ui.setStatus(STATUS_KEY, undefined);
    }
  }

  async function startMobileServer(ctx: ExtensionContext): Promise<void> {
    const previousServer = mobileServer;
    mobileServer = undefined;
    await previousServer?.close();
    const serverStore = bindStore(ctx);
    const serverContext = ctx;
    mobileServer = await MobileAttachmentServer.start(
      {
        snapshot: () =>
          mutationLock.run(async () => {
            if (store !== serverStore || activeContext !== serverContext) {
              throw new Error("The live Pi attachment session changed.");
            }
            await loadCurrent(serverContext, serverStore);
            return currentSnapshot(serverStore);
          }),
        prepare: (candidates) => serverStore.prepareCandidates(candidates),
        commit: (expectedRevision, keepIds, prepared) =>
          mutationLock.run(async () => {
            if (store !== serverStore || activeContext !== serverContext) {
              await serverStore.discardPrepared(prepared);
              throw new Error("The live Pi attachment session changed.");
            }
            if (revision !== expectedRevision) {
              await serverStore.discardPrepared(prepared);
              throw new Error("The staged attachments changed. Refresh the selection.");
            }
            try {
              staged = await serverStore.reconcilePrepared(keepIds, prepared);
            } catch (error) {
              await serverStore.discardPrepared(prepared);
              throw error;
            }
            revision += 1;
            try {
              updateWidget(serverContext);
            } catch {
              // UI teardown cannot roll back an already committed queue mutation.
            }
            return currentSnapshot(serverStore);
          }),
        discard: (prepared: PreparedAttachment[]) =>
          serverStore.discardPrepared(prepared),
      },
      { runtimeDirectory: RUNTIME_ROOT },
    );
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
        await pickAndStage(ctx);
      } catch (error) {
        const message = errorMessage(error);
        ctx.ui.notify(
          message === PLAIN_SSH_MESSAGE
            ? message
            : `Could not attach files: ${message}`,
          "error",
        );
      }
    },
  });

  pi.on("session_start", async (_event, ctx) => {
    activeContext = ctx;
    if (ctx.mode === "tui") ctx.ui.setStatus(STATUS_KEY, undefined);
    try {
      await mutationLock.run(async () => {
        await loadCurrent(ctx);
      });
      await startMobileServer(ctx);
    } catch (error) {
      staged = [];
      updateWidget(ctx);
      ctx.ui.notify(
        `Could not initialize attachments: ${errorMessage(error)}`,
        "error",
      );
    }
  });

  pi.on("input", async (event, ctx) => {
    if (event.source !== "interactive") return { action: "continue" as const };
    return mutationLock.run(async () => {
      const currentStore = bindStore(ctx);
      if (staged.length === 0) {
        await loadCurrent(ctx, currentStore).catch(() => undefined);
        if (staged.length === 0) return { action: "continue" as const };
      }

      const snapshot = [...staged];
      const prepared = await prepareAttachmentImages(
        snapshot,
        modelSupportsImages(ctx),
      );
      try {
        staged = await currentStore.consume(snapshot.map((item) => item.id));
      } catch (error) {
        ctx.ui.setEditorText(event.text);
        ctx.ui.notify(
          `Attachments were not sent: ${errorMessage(error)}`,
          "error",
        );
        return { action: "handled" as const };
      }
      revision += 1;
      updateWidget(ctx);

      const attachmentBlock = buildAttachmentPromptBlock(
        snapshot,
        prepared.nativeImageIds,
      );
      const text = event.text.trimEnd()
        ? `${event.text.trimEnd()}\n\n${attachmentBlock}`
        : attachmentBlock;
      const images = [...(event.images || []), ...prepared.images];
      return {
        action: "transform" as const,
        text,
        ...(images.length > 0 ? { images } : {}),
      };
    });
  });

  pi.on("session_shutdown", async (_event, ctx) => {
    const closingServer = mobileServer;
    mobileServer = undefined;
    activeContext = undefined;
    await closingServer?.close();
    if (ctx.mode === "tui") {
      ctx.ui.setStatus(STATUS_KEY, undefined);
      ctx.ui.setWidget(WIDGET_KEY, undefined);
    }
    store = undefined;
    staged = [];
    activeSessionId = "";
    revision = 0;
  });
}
