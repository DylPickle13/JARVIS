import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { spawn } from "node:child_process";

const DEFAULT_HOST = "mac-mini-llm-16gb";
const DEFAULT_REMOTE_DIR = "/Users/dylanrapanan/gx10-bridge";
const DEFAULT_TIMEOUT_SECONDS = 15;
const DEFAULT_SEMANTIC_TIMEOUT_SECONDS = 30;
const MAX_TIMEOUT_SECONDS = 120;

const SEMANTIC_READS = [
  "overview",
  "memory",
  "chain",
  "effects",
  "effect",
  "assignments",
  "controls",
  "system",
  "midi",
  "io",
  "tuner",
  "global_eq",
  "ir_names",
  "memories",
  "program_map",
  "looper",
  "get",
] as const;

type RunResult = {
  code: number | null;
  signal: NodeJS.Signals | null;
  stdout: string;
  stderr: string;
};

function clampTimeoutSeconds(value: unknown): number {
  const number = typeof value === "number" && Number.isFinite(value) ? value : DEFAULT_TIMEOUT_SECONDS;
  return Math.max(1, Math.min(MAX_TIMEOUT_SECONDS, number));
}

function shellQuote(value: string): string {
  return `'${value.replace(/'/g, `'"'"'`)}'`;
}

function normalizeSshHost(value: string | undefined): string {
  const host = value?.trim() || DEFAULT_HOST;
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(host)) {
    throw new Error("GX-10 SSH host must be a configured host alias, hostname, or IPv4 address");
  }
  return host;
}

function parseJsonMaybe(text: string): unknown | undefined {
  const trimmed = text.trim();
  if (!trimmed) return undefined;
  try {
    return JSON.parse(trimmed);
  } catch {
    return undefined;
  }
}

function truncate(text: string, maximum = 60_000): string {
  if (text.length <= maximum) return text;
  return `${text.slice(0, maximum)}\n\n... [truncated ${text.length - maximum} chars]`;
}

function boundedJsonText(text: string, maximum = 60_000): string {
  const trimmed = text.trim() || "null";
  if (trimmed.length <= maximum) return trimmed;
  return JSON.stringify({
    outputTruncated: true,
    originalCharacters: trimmed.length,
    message: "GX-10 result exceeded the tool boundary; narrow the request, paginate it, or omit detail=true.",
  });
}

function luaString(value: string): string {
  let escaped = "";
  for (const character of value) {
    const code = character.codePointAt(0)!;
    if (character === "\\") escaped += "\\\\";
    else if (character === '"') escaped += '\\"';
    else if (character === "\n") escaped += "\\n";
    else if (character === "\r") escaped += "\\r";
    else if (character === "\t") escaped += "\\t";
    else if (code < 32 || code === 127) escaped += `\\${code.toString().padStart(3, "0")}`;
    else escaped += character;
  }
  return `"${escaped}"`;
}

function luaLiteral(value: unknown): string {
  if (value === undefined || value === null) return "nil";
  if (typeof value === "string") return luaString(value);
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new Error("GX-10 semantic options require finite numbers");
    return String(value);
  }
  if (Array.isArray(value)) return `{${value.map(luaLiteral).join(",")}}`;
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([, item]) => item !== undefined)
      .sort(([left], [right]) => left.localeCompare(right));
    return `{${entries.map(([key, item]) => `[${luaString(key)}]=${luaLiteral(item)}`).join(",")}}`;
  }
  throw new Error(`Unsupported GX-10 semantic option type: ${typeof value}`);
}

async function runSsh(params: {
  host: string;
  command: string;
  stdin?: string;
  timeoutSeconds: number;
  signal?: AbortSignal;
}): Promise<RunResult> {
  return await new Promise<RunResult>((resolve, reject) => {
    const child = spawn("ssh", [params.host, params.command], { stdio: ["pipe", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    let settled = false;

    const finish = (result: RunResult) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      params.signal?.removeEventListener("abort", onAbort);
      resolve(result);
    };
    const fail = (error: Error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      params.signal?.removeEventListener("abort", onAbort);
      reject(error);
    };
    const timer = setTimeout(() => {
      child.kill("SIGTERM");
      setTimeout(() => child.kill("SIGKILL"), 1_000).unref();
      fail(new Error(`Timed out after ${params.timeoutSeconds}s running GX-10 bridge over SSH`));
    }, params.timeoutSeconds * 1000);
    timer.unref();

    const onAbort = () => {
      child.kill("SIGTERM");
      fail(new Error("Cancelled"));
    };
    params.signal?.addEventListener("abort", onAbort, { once: true });

    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.on("error", fail);
    child.on("close", (code, signal) => finish({ code, signal, stdout, stderr }));
    if (params.stdin !== undefined) child.stdin.write(params.stdin);
    child.stdin.end();
  });
}

async function abortableDelay(milliseconds: number, signal?: AbortSignal): Promise<void> {
  if (signal?.aborted) throw new Error("Cancelled");
  await new Promise<void>((resolve, reject) => {
    const timer = setTimeout(done, milliseconds);
    function done() {
      signal?.removeEventListener("abort", cancelled);
      resolve();
    }
    function cancelled() {
      clearTimeout(timer);
      reject(new Error("Cancelled"));
    }
    signal?.addEventListener("abort", cancelled, { once: true });
  });
}

async function runBridge(params: {
  host?: string;
  remoteDir?: string;
  timeoutSeconds?: number;
  command: "doctor" | "run";
  code?: string;
  allowWrite?: boolean;
  signal?: AbortSignal;
}): Promise<RunResult> {
  const host = normalizeSshHost(params.host);
  const remoteDir = params.remoteDir?.trim() || DEFAULT_REMOTE_DIR;
  const timeoutSeconds = clampTimeoutSeconds(params.timeoutSeconds);
  const command = [
    `cd ${shellQuote(remoteDir)}`,
    "&&",
    "bin/gx10-bridge",
    "--timeout",
    String(timeoutSeconds),
    ...(params.allowWrite ? ["--allow-write"] : []),
    params.command,
    ...(params.command === "run" ? ["-"] : []),
  ].join(" ");
  const invocation = {
    host,
    command,
    stdin: params.code,
    timeoutSeconds: timeoutSeconds + 5,
    signal: params.signal,
  };
  let result = await runSsh(invocation);
  // CoreMIDI occasionally rejects a fresh command-line client while its prior
  // process is being reaped. This exact failure occurs before any MIDI request;
  // retry one new process only for read-only calls, never for write-enabled Lua.
  if (!params.allowWrite && result.code === 10 && /MIDIClientCreate failed/.test(result.stderr)) {
    await abortableDelay(1_500, params.signal);
    result = await runSsh(invocation);
  }
  if (result.code !== 0) {
    throw new Error([
      `GX-10 bridge failed with code ${result.code}${result.signal ? ` signal ${result.signal}` : ""}.`,
      result.stderr.trim() ? `stderr:\n${truncate(result.stderr.trim(), 20_000)}` : undefined,
      result.stdout.trim() ? `stdout:\n${truncate(result.stdout.trim(), 20_000)}` : undefined,
    ].filter(Boolean).join("\n\n"));
  }
  return result;
}

export default function gx10BridgeExtension(pi: ExtensionAPI) {
  pi.registerTool({
    name: "gx10_ping",
    label: "GX-10 Ping",
    description: "Connect directly to the BOSS GX-10 over CoreMIDI on mac-mini-16 and report bridge, identity, firmware, endpoint, and generated-schema status. Load with load_tools({ groups: [\"gx10\"] }) before use.",
    promptSnippet: "Ping the direct GX-10 Lua bridge and return hardware/schema status.",
    promptGuidelines: [
      "Use gx10_ping after loading the gx10 group when connection, firmware, endpoint, or schema health should be checked.",
      "The bridge uses only the standard GX-10 endpoint and fails closed while BOSS Tone Studio is running.",
    ],
    parameters: Type.Object({
      timeoutSeconds: Type.Optional(Type.Number({ description: "Overall timeout in seconds. Default 15, max 120." })),
      host: Type.Optional(Type.String({ description: `SSH host alias. Default ${DEFAULT_HOST}.` })),
      remoteDir: Type.Optional(Type.String({ description: `Remote gx10-bridge directory. Default ${DEFAULT_REMOTE_DIR}.` })),
    }),
    async execute(_id, params, signal) {
      const result = await runBridge({
        host: params.host,
        remoteDir: params.remoteDir,
        timeoutSeconds: params.timeoutSeconds,
        command: "doctor",
        signal,
      });
      const parsed = parseJsonMaybe(result.stdout);
      return {
        content: [{ type: "text", text: truncate(result.stdout.trim() || "{}") }],
        details: { parsed, stderr: result.stderr, host: params.host || DEFAULT_HOST },
      };
    },
  });

  pi.registerTool({
    name: "gx10_get",
    label: "GX-10 Semantic Read",
    description: "Read the live GX-10 through the generated semantic layer. One read-only call returns the current memory/patch overview, chain, effects, assignments, controls, system/MIDI/I/O/tuner/EQ settings, IR or memory names, program maps, looper, or schema paths with decoded labels and raw IDs. Defaults to the live temp patch and never enables DT1. Load with load_tools({ groups: [\"gx10\"] }) before use.",
    promptSnippet: "Read ordinary GX-10 questions semantically; defaults to the current live patch.",
    promptGuidelines: [
      "Use gx10_get after loading gx10 for ordinary read questions; prefer it over manually decoding gx10_lua IDs.",
      "gx10_get is always read-only, defaults to the live temp patch, batches bounded RQ1 reads conservatively, and reports ambiguity instead of guessing.",
      "Use what=overview for the current patch; assignments returns source/target labels including MIDI CC details; effect requires query when selecting one active effect.",
      "Use what=get with path or paths only for low-level schema paths. Raw values and paths remain present for auditing.",
    ],
    parameters: Type.Object({
      what: Type.Optional(Type.Union([
        Type.Literal("overview"), Type.Literal("memory"), Type.Literal("chain"),
        Type.Literal("effects"), Type.Literal("effect"), Type.Literal("assignments"),
        Type.Literal("controls"), Type.Literal("system"), Type.Literal("midi"),
        Type.Literal("io"), Type.Literal("tuner"), Type.Literal("global_eq"),
        Type.Literal("ir_names"), Type.Literal("memories"), Type.Literal("program_map"),
        Type.Literal("looper"), Type.Literal("get"),
      ], { description: `Semantic read to perform. Default overview. Choices: ${SEMANTIC_READS.join(", ")}.` })),
      query: Type.Optional(Type.String({ description: "Effect selector or optional semantic filter. Exact duplicates return ambiguity candidates." })),
      section: Type.Optional(Type.String({ description: "System section/path filter for what=system." })),
      path: Type.Optional(Type.String({ description: "One exact schema path for what=get." })),
      paths: Type.Optional(Type.Array(Type.String(), { maxItems: 100, description: "Exact schema paths for what=get." })),
      bank: Type.Optional(Type.Number({ description: "Program-map bank number for what=program_map." })),
      enabledOnly: Type.Optional(Type.Boolean({ description: "For assignments/overview, include only enabled assignments." })),
      detail: Type.Optional(Type.Boolean({ description: "Include full field/parameter metadata instead of compact semantic objects." })),
      includeAllSlots: Type.Optional(Type.Boolean({ description: "Include unused physical FX slots in chain output." })),
      compact: Type.Optional(Type.Boolean({ description: "Return compact field objects for what=get." })),
      limit: Type.Optional(Type.Number({ description: "Bounded result limit for paginated/list reads." })),
      offset: Type.Optional(Type.Number({ description: "Zero-based pagination offset where supported." })),
      timeoutSeconds: Type.Optional(Type.Number({ description: `Overall timeout in seconds. Default ${DEFAULT_SEMANTIC_TIMEOUT_SECONDS}, max ${MAX_TIMEOUT_SECONDS}.` })),
      host: Type.Optional(Type.String({ description: `SSH host alias. Default ${DEFAULT_HOST}.` })),
      remoteDir: Type.Optional(Type.String({ description: `Remote gx10-bridge directory. Default ${DEFAULT_REMOTE_DIR}.` })),
    }),
    async execute(_id, params, signal) {
      const what = params.what || "overview";
      if (what === "effect" && !params.query?.trim()) throw new Error("gx10_get what=effect requires query");
      if (what === "get" && !params.path?.trim() && (!params.paths || params.paths.length === 0)) {
        throw new Error("gx10_get what=get requires path or paths");
      }
      const options = {
        query: params.query?.trim() || undefined,
        effect: params.query?.trim() || undefined,
        section: params.section?.trim() || undefined,
        path: params.path?.trim() || undefined,
        paths: params.paths && params.paths.length > 0 ? params.paths : undefined,
        bank: params.bank,
        enabledOnly: params.enabledOnly,
        detail: params.detail,
        includeAllSlots: params.includeAllSlots,
        compact: params.compact,
        limit: params.limit,
        offset: params.offset,
      };
      const result = await runBridge({
        host: params.host,
        remoteDir: params.remoteDir,
        timeoutSeconds: params.timeoutSeconds ?? DEFAULT_SEMANTIC_TIMEOUT_SECONDS,
        command: "run",
        code: `return gx.semantic(${luaString(what)}, ${luaLiteral(options)})`,
        allowWrite: false,
        signal,
      });
      const parsed = parseJsonMaybe(result.stdout);
      return {
        content: [{ type: "text", text: boundedJsonText(result.stdout) }],
        details: { parsed, stderr: result.stderr, host: params.host || DEFAULT_HOST, semanticRead: what, readOnly: true },
      };
    },
  });

  pi.registerTool({
    name: "gx10_find",
    label: "GX-10 Semantic Find",
    description: "Search generated GX-10 blocks, fields, effect types/parameters, assignment targets, and assignment-source labels without guessing numeric IDs. Results are ranked, paginated, and contain authoritative paths/metadata. Load with load_tools({ groups: [\"gx10\"] }) before use.",
    promptSnippet: "Find GX-10 semantic paths, effects, parameters, targets, and source labels.",
    promptGuidelines: [
      "Use gx10_find after loading gx10 when a semantic name or schema path is unfamiliar; then use gx10_get for the live value.",
      "gx10_find is metadata-only and reports ranked candidates; do not choose an ambiguous candidate without relevant context.",
    ],
    parameters: Type.Object({
      query: Type.String({ minLength: 1, description: "Natural semantic search text, such as s-bend trigger or noise suppressor threshold." }),
      limit: Type.Optional(Type.Number({ description: "Results per page. Default 50, max 200." })),
      offset: Type.Optional(Type.Number({ description: "Zero-based pagination offset." })),
      timeoutSeconds: Type.Optional(Type.Number({ description: "Overall timeout in seconds. Default 15, max 120." })),
      host: Type.Optional(Type.String({ description: `SSH host alias. Default ${DEFAULT_HOST}.` })),
      remoteDir: Type.Optional(Type.String({ description: `Remote gx10-bridge directory. Default ${DEFAULT_REMOTE_DIR}.` })),
    }),
    async execute(_id, params, signal) {
      const query = params.query.trim();
      if (!query) throw new Error("gx10_find requires a non-empty query");
      const options = { limit: params.limit, offset: params.offset };
      const result = await runBridge({
        host: params.host,
        remoteDir: params.remoteDir,
        timeoutSeconds: params.timeoutSeconds,
        command: "run",
        code: `return gx.find(${luaString(query)}, ${luaLiteral(options)})`,
        allowWrite: false,
        signal,
      });
      const parsed = parseJsonMaybe(result.stdout);
      return {
        content: [{ type: "text", text: boundedJsonText(result.stdout) }],
        details: { parsed, stderr: result.stderr, host: params.host || DEFAULT_HOST, readOnly: true },
      };
    },
  });

  pi.registerTool({
    name: "gx10_lua",
    label: "GX-10 Lua",
    description: "Execute unsaved inline Lua against the live BOSS GX-10 through the direct CoreMIDI bridge on mac-mini-16. Use gx10_get/gx10_find for ordinary reads; gx10_lua supports custom reads, RQ1-only gx.plan_edit dry runs, and explicitly approved verified transactions. Load with load_tools({ groups: [\"gx10\"] }) before use.",
    promptSnippet: "Run inline Lua against the live GX-10; code is not saved.",
    promptGuidelines: [
      "Use gx10_lua only after loading the gx10 group. Prefer gx10_get/gx10_find for ordinary read questions; return JSON-safe Lua values here.",
      "Semantic Lua reads include gx.current_patch(), gx.current_memory(), gx.chain(), gx.effects(), gx.effect(query), gx.assignments(), gx.controls(), gx.overview(), gx.semantic(what,options), gx.find(query), and gx.get_many(paths). Low-level reads remain gx.get(), gx.get_block(), gx.rq1(), and gx.listen().",
      "For schema-expressible edits, first call gx.plan_edit(spec) with allowWrite=false, show the exact before/after bytes and plan ID, and stop for approval. For save=true, also inspect every whole-block user-memory mirror/diff. After approval, regenerate with expectedPlanId and call tx:apply_plan(plan) inside gx.transaction using the matching save option.",
      "Use schema paths such as system.common.currentPatchNum, temp.assign[1], temp.fxItem[1].trigger, user[1].common, or inspect paths with gx.schema(query).",
      "Do not save temporary task scripts; pass complete Lua inline.",
      "Keep allowWrite false unless sir explicitly requested a GX-10 change in the current conversation.",
      "Every write must be composed inside gx.transaction(options, function(tx) ... end). Prefer tx:apply_plan for approved semantic plans; tx:set, tx:set_machine, and tx:get_block/tx:set_block remain lower-level escape hatches.",
      "Inspect the affected fields/blocks first. Use save=true only when sir explicitly asks to persist the change; otherwise changes are temporary memory only.",
      "The transaction engine snapshots touched blocks, reads every write back, and rolls back on failure. Never bypass it or blindly retry a failed write.",
      "Avoid tx:write raw addresses unless the schema cannot express a verified operation and the exact documented writable address has been checked. IR and firmware ranges are unavailable.",
      "API documentation is `/Users/dylanrapanan/gx10-bridge/README.md` on mac-mini-16.",
    ],
    parameters: Type.Object({
      code: Type.String({ description: "Complete inline Lua. Return a JSON-safe table/string/number/boolean/nil." }),
      allowWrite: Type.Optional(Type.Boolean({ description: "Enable native DT1 for gx.transaction. Defaults false and may be true only for an explicitly requested hardware edit." })),
      timeoutSeconds: Type.Optional(Type.Number({ description: "Overall timeout in seconds. Default 15, max 120." })),
      host: Type.Optional(Type.String({ description: `SSH host alias. Default ${DEFAULT_HOST}.` })),
      remoteDir: Type.Optional(Type.String({ description: `Remote gx10-bridge directory. Default ${DEFAULT_REMOTE_DIR}.` })),
    }),
    async execute(_id, params, signal) {
      const result = await runBridge({
        host: params.host,
        remoteDir: params.remoteDir,
        timeoutSeconds: params.timeoutSeconds,
        command: "run",
        code: params.code,
        allowWrite: params.allowWrite === true,
        signal,
      });
      const parsed = parseJsonMaybe(result.stdout);
      return {
        content: [{ type: "text", text: boundedJsonText(result.stdout) }],
        details: {
          parsed,
          stderr: result.stderr,
          host: params.host || DEFAULT_HOST,
          allowWrite: params.allowWrite === true,
        },
      };
    },
  });
}
