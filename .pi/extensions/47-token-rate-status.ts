import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const STATUS_KEY = "token-rate";
const APPROX_CHARS_PER_TOKEN = 4;
const UPDATE_THROTTLE_MS = 500;

type RateSource = "actual" | "estimated" | "none";

type RateSnapshot = {
  rate: number | null;
  source: RateSource;
  elapsedMs: number | null;
  outputTokens: number | null;
  estimatedOutputTokens: number;
};

let streamStartedMs: number | null = null;
let firstTokenMs: number | null = null;
let outputCharacters = 0;
let outputTokens: number | null = null;
let lastStatusUpdateMs = 0;
let lastTurnSnapshot: RateSnapshot | null = null;

function resetRate() {
  streamStartedMs = null;
  firstTokenMs = null;
  outputCharacters = 0;
  outputTokens = null;
  lastStatusUpdateMs = 0;
}

function usageOutputTokens(value: unknown): number | null {
  if (!value || typeof value !== "object") return null;
  const usage = (value as { usage?: { output?: unknown } }).usage;
  const output = Number(usage?.output);
  return Number.isFinite(output) && output > 0 ? output : null;
}

function assistantDeltaText(event: unknown): string {
  if (!event || typeof event !== "object") return "";
  const typed = event as { type?: unknown; delta?: unknown };
  if (!["text_delta", "thinking_delta", "toolcall_delta"].includes(String(typed.type || ""))) return "";
  return typeof typed.delta === "string" ? typed.delta : "";
}

function noteActualOutputTokens(value: unknown) {
  const actual = usageOutputTokens(value);
  if (actual !== null) outputTokens = actual;
}

function snapshot(now = Date.now()): RateSnapshot {
  const estimatedOutputTokens = outputCharacters > 0
    ? Math.max(1, outputCharacters / APPROX_CHARS_PER_TOKEN)
    : 0;
  const source: RateSource = outputTokens && outputTokens > 0
    ? "actual"
    : (estimatedOutputTokens > 0 ? "estimated" : "none");
  const tokensForRate = source === "actual" ? Number(outputTokens) : estimatedOutputTokens;
  const startMs = firstTokenMs || streamStartedMs;
  const elapsedMs = startMs ? Math.max(1, now - startMs) : null;
  const rate = elapsedMs && tokensForRate > 0
    ? Math.round((tokensForRate / (elapsedMs / 1000)) * 10) / 10
    : null;

  return {
    rate,
    source,
    elapsedMs,
    outputTokens: outputTokens ? Math.round(outputTokens) : null,
    estimatedOutputTokens: Math.round(estimatedOutputTokens * 10) / 10,
  };
}

function formatRate(value: number): string {
  if (value >= 100) return String(Math.round(value));
  if (value >= 10) return value.toFixed(1);
  return value.toFixed(2);
}

function renderLastTurnAverage(ctx: ExtensionContext) {
  if (!ctx.hasUI) return;
  const theme = ctx.ui.theme;
  const current = lastTurnSnapshot;
  if (!current?.rate) {
    ctx.ui.setStatus(STATUS_KEY, undefined);
    return;
  }

  const prefix = current.source === "estimated" ? "≈" : "";
  const text = `⚡ avg ${prefix}${formatRate(current.rate)} t/s`;
  ctx.ui.setStatus(STATUS_KEY, theme.fg("dim", text));
}

function updateFromAssistantEvent(event: unknown): boolean {
  const now = Date.now();
  const typed = event && typeof event === "object"
    ? event as { type?: unknown; partial?: unknown; message?: unknown; error?: unknown }
    : {};
  if (!streamStartedMs) streamStartedMs = now;

  const delta = assistantDeltaText(typed);
  if (delta) {
    if (!firstTokenMs) firstTokenMs = now;
    outputCharacters += Array.from(delta).length;
  }

  if (typed.type === "done") noteActualOutputTokens(typed.message);
  else if (typed.type === "error") noteActualOutputTokens(typed.error);
  noteActualOutputTokens(typed.partial);

  if (!delta && typed.type !== "done" && typed.type !== "error") return false;
  if (typed.type !== "done" && typed.type !== "error" && now - lastStatusUpdateMs < UPDATE_THROTTLE_MS) return false;
  lastStatusUpdateMs = now;
  return true;
}

export default function registerTokenRateStatus(pi: ExtensionAPI) {
  pi.on("session_start", async (_event, ctx) => {
    resetRate();
    lastTurnSnapshot = null;
    if (ctx.hasUI) ctx.ui.setStatus(STATUS_KEY, undefined);
  });

  pi.on("agent_start", async () => {
    resetRate();
  });

  pi.on("message_start", async (event) => {
    if (event.message.role !== "assistant") return;
    resetRate();
    streamStartedMs = Date.now();
    lastStatusUpdateMs = streamStartedMs;
  });

  pi.on("message_update", async (event) => {
    if (event.message.role !== "assistant") return;
    updateFromAssistantEvent(event.assistantMessageEvent);
  });

  pi.on("message_end", async (event) => {
    if (event.message.role !== "assistant") return;
    noteActualOutputTokens(event.message);
    lastTurnSnapshot = snapshot();
  });

  pi.on("turn_end", async (event, ctx) => {
    if (event.message.role === "assistant") {
      noteActualOutputTokens(event.message);
      lastTurnSnapshot = snapshot();
    }
    renderLastTurnAverage(ctx);
  });

  pi.on("session_shutdown", async (_event, ctx) => {
    if (ctx.hasUI) ctx.ui.setStatus(STATUS_KEY, undefined);
  });
}
