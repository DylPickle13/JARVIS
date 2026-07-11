import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Key } from "@earendil-works/pi-tui";

const MAX_DELAY_MS = 2_147_483_647;

function parseDelay(value: string): number | undefined {
  const match = value
    .trim()
    .toLowerCase()
    .match(/^(\d+(?:\.\d+)?)\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours)$/);
  if (!match) return undefined;

  const amount = Number(match[1]);
  const unit = match[2];
  const multiplier = unit.startsWith("s") ? 1_000 : unit.startsWith("m") ? 60_000 : 60 * 60_000;
  const delayMs = amount * multiplier;

  if (!Number.isFinite(delayMs) || delayMs <= 0 || delayMs > MAX_DELAY_MS) return undefined;
  return Math.round(delayMs);
}

function formatScheduledTime(timestamp: number): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Toronto",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(new Date(timestamp));
}

async function promptForDelay(ctx: ExtensionContext): Promise<number | undefined> {
  const custom = await ctx.ui.input("Send after", "Examples: 45m, 2h, 30s");
  if (custom === undefined) return undefined;

  const delayMs = parseDelay(custom);
  if (delayMs === undefined) {
    ctx.ui.notify("Enter a delay such as 45m, 2h, or 30s.", "warning");
    return undefined;
  }
  return delayMs;
}

export default function registerScheduledPrompts(pi: ExtensionAPI) {
  const timers = new Set<ReturnType<typeof setTimeout>>();
  let sessionActive = false;

  pi.on("session_start", async () => {
    sessionActive = true;
  });

  pi.on("session_shutdown", async () => {
    sessionActive = false;
    for (const timer of timers) clearTimeout(timer);
    timers.clear();
  });

  pi.registerShortcut(Key.alt("s"), {
    description: "Schedule the current prompt",
    handler: async (ctx) => {
      const prompt = ctx.ui.getEditorText().trim();
      if (!prompt) {
        ctx.ui.notify("Type a prompt before scheduling it.", "warning");
        return;
      }

      const delayMs = await promptForDelay(ctx);
      if (delayMs === undefined) return;

      const scheduledFor = Date.now() + delayMs;
      let timer: ReturnType<typeof setTimeout>;
      timer = setTimeout(() => {
        timers.delete(timer);
        if (!sessionActive) return;

        try {
          pi.sendUserMessage(prompt, { deliverAs: "followUp" });
          ctx.ui.notify("Scheduled prompt sent.", "info");
        } catch (error: any) {
          ctx.ui.notify(`Could not send scheduled prompt: ${error?.message ?? String(error)}`, "error");
        }
      }, delayMs);
      timer.unref?.();
      timers.add(timer);

      ctx.ui.setEditorText("");
      ctx.ui.notify(`Prompt scheduled for ${formatScheduledTime(scheduledFor)}.`, "info");
    },
  });
}
