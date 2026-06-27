import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

type CanonicalToolGroup =
  | "memory"
  | "code_docs"
  | "image"
  | "jarvis"
  | "minecraft_jarvis"
  | "phone"
  | "google"
  | "cron"
  | "discord"
  | "sessions"
  | "browser";
type ToolGroup = CanonicalToolGroup | "all";
type ConcreteToolGroup = CanonicalToolGroup;
type GuidanceGroup = ConcreteToolGroup;

const ALWAYS_ON_TOOLS = [
  "read",
  "bash",
  "edit",
  "write",
  "grep",
  "find",
  "ls",
  "ssh",
  "web_search",
  "fetch_content",
  "get_search_content",
  "minecraft_jarvis",
  "maps",
  "github_cli",
  "load_tools",
] as const;

const TOOL_GROUPS: Record<ConcreteToolGroup, readonly string[]> = {
  memory: ["memory"],
  code_docs: ["code_search"],
  image: ["generate_image"],
  jarvis: ["jarvis", "smart_plug"],
  minecraft_jarvis: ["minecraft_jarvis"],
  phone: ["agent_phone"],
  google: ["google_workspace"],
  cron: ["discord_cron"],
  discord: ["discord_ping", "discord_send_file"],
  sessions: ["session_search"],
  browser: [
    "browser_status",
    "browser_open",
    "browser_screenshot",
    "browser_click",
    "browser_type",
    "browser_upload",
    "browser_key",
    "browser_scroll",
    "browser_wait",
    "browser_extract",
    "browser_tabs",
    "browser_close",
  ],
};

const GROUP_SUMMARIES: Record<ConcreteToolGroup, string> = {
  memory: "memory for durable project/local facts/preferences/workflows; never store secrets",
  code_docs: "code_search for external code/docs/API examples",
  image: "generate_image for local Qwen image generation or guided edits",
  jarvis: "Operation JARVIS for dashboard phone camera vision, Google Cast speech/media, and local smart plugs",
  minecraft_jarvis: "Minecraft jarvis bot chat/control through the in-game Qwen companion",
  phone: "agent_phone for safe LG-H933 Android phone control via ADB refs/screenshots",
  google: "google_workspace for Calendar/events, Gmail/mail, Drive/files/folders, Docs, and Sheets",
  cron: "discord_cron only: scheduled Pi/JARVIS jobs whose output posts to Discord",
  discord: "discord_ping for immediate Discord pings/notifications and attachments; discord_send_file for current-channel uploads when available",
  sessions: "session_search over prior Pi/JARVIS sessions",
  browser: "visible Chrome for rendered/interactive web: screenshots/clicks/typing/uploads/extract",
};

const GROUP_NAMES = Object.keys(TOOL_GROUPS) as ConcreteToolGroup[];
const LOADABLE_GROUPS_TEXT = `${GROUP_NAMES.map((name) => `${name}=${GROUP_SUMMARIES[name]}`).join("; ")}; all=all loadable groups`;

const GROUP_GUIDANCE: Record<GuidanceGroup, { skill: string; lines: readonly string[] }> = {
  memory: {
    skill: "durable memory",
    lines: [
      "Use `memory` only for stable durable facts, preferences, lessons, project notes, or workflows that should survive future sessions.",
      "Never store secrets, credentials, tokens, private personal data, or transient one-off details.",
      "Prefer `action: \"search\"` before writing new memories; keep new entries concise and tagged when useful.",
    ],
  },
  code_docs: {
    skill: "code/docs search",
    lines: [
      "Use `code_search` for external programming docs, API examples, library usage, and implementation patterns.",
      "For local repository search, use baseline `grep`, `find`, `ls`, and `read` first instead of external code search.",
    ],
  },
  image: {
    skill: "image generation",
    lines: [
      "Use `generate_image` for local PNG image generation or guided image edits on mac-mini-64.",
      "Provide a detailed visual prompt; for guided edits, pass a local inputImagePath and use imageStrength around 0.4 by default.",
      "Do not use shell, browser, ComfyUI, Draw Things, or alternate image generators unless explicitly requested.",
    ],
  },
  phone: {
    skill: "agent-phone Android control",
    lines: [
      "Use `agent_phone` for the dedicated LG-H933 Android phone; do not run raw ADB or `agent-phone` through `bash` unless debugging the adapter or explicitly asked for a shell workflow.",
      "Call shape: `agent_phone({ args: [\"snapshot\", \"-i\"] })`; `args` are CLI tokens after the `agent-phone` binary, never including `agent-phone` itself.",
      "Typical flow: `status` → `snapshot -i` → interact with current `@refs` using `tap @ref`, `type`, `press BACK/HOME/ENTER`, or `swipe` → re-run `snapshot -i` after every screen change because refs can go stale.",
      "Prefer `tap @ref` over raw coordinates; use `tap-text TEXT` only when text/description/resource-id matching is obvious. Use `wait --text TEXT` after navigation or app launch.",
      "Use `snapshot -i --image`, `screenshot --image`, or `attachImage: true` only when pixel-level vision is needed; ordinary phone control should use the text refs from `snapshot -i`.",
      "Phone-sensitive actions — SMS/calls, purchases, account/security changes, deleting data, private content, or APK installs — require explicit user confirmation and may need a new adapter command rather than raw shell.",
    ],
  },
  google: {
    skill: "google-access",
    lines: [
      "Use `google_workspace` for Workspace intents: Calendar/events/schedule, Gmail/email/mail, Drive/files/folders, Docs, and Sheets; do not guess shell commands like `gdrive`, `gapi`, or `gsutil`.",
      "Actions: `calendar_events` for Calendar, `drive_download_folder` for recursive Drive folders, generic `call` with `path` for Workspace APIs, `status`/`services`/`help`/`schema` for discovery, and `auth`/`raw` only when needed.",
      "Examples: Calendar `google_workspace({ action: \"calendar_events\", calendarId: \"primary\", when: \"upcoming\", maxResults: 10, pretty: true })`; Drive list `path:[\"drive\",\"files\",\"list\"]`; Gmail list `path:[\"gmail\",\"users\",\"messages\",\"list\"], params:{ userId:\"me\", maxResults:10 }`; Docs/Sheets use `call` plus `help`/`schema`.",
      "Drive folder download: use `action: \"drive_download_folder\"`, prefer `folderId` (exact unique `folderName` also works), keep `destination` under cwd, use `dryRun: true` to count without writes, and only use `overwrite: true` with explicit intent. Supports subfolders, Google editor exports, JSON media, and manifests.",
      "Workspace writes/destructive calls require explicit user intent; include IDs, request body under `json`/`body`, and verify with a read/list call when feasible. Never pass API keys/secrets in params.",
    ],
  },
  jarvis: {
    skill: "operation-jarvis",
    lines: [
      "Use `load_tools({ groups: [\"jarvis\"] })` before using Operation JARVIS, dashboard camera, Cast actions, or smart-plug control; then call the unlocked `jarvis` or `smart_plug` tool directly.",
      "Safe checks: `jarvis({ action: \"help\" })`, `jarvis({ action: \"status\", noCast: true })`, `jarvis({ action: \"cast-status\", device: \"speakers\" })`, or `smart_plug({ action: \"list\" })`.",
      "Dashboard camera actions: `jarvis({ action: \"look\" })`, `jarvis({ action: \"video\", duration: 5 })`, `jarvis({ action: \"video-until\", condition: \"a person is visible\", maxDuration: 60 })`, or `jarvis({ action: \"analyze-view\", question: \"What is visible?\" })`.",
      "Cast actions: `jarvis({ action: \"speak\", text: \"JARVIS online.\", device: \"speakers\" })`, `jarvis({ action: \"cast-status\", device: \"tv\" })`, `jarvis({ action: \"cast-volume\", level: 25 })`, `jarvis({ action: \"cast-youtube\", query: \"relaxing jazz\", device: \"tv\" })`, and related `cast-mute`, `cast-stop`, `cast-play-url` actions.",
      "Smart-plug actions use the dedicated local-only tool: `smart_plug({ action: \"status\", plug: \"<configured-plug-name>\" })`, `smart_plug({ action: \"on\", plug: \"<configured-plug-name>\" })`, `smart_plug({ action: \"off\", plug: \"<configured-plug-name>\" })`, or `smart_plug({ action: \"toggle\", plug: \"<configured-plug-name>\" })`. Run `smart_plug({ action: \"list\" })` to see local aliases.",
      "Always keep camera recording bounded. For spoken output, keep text short and keep full details in Discord.",
    ],
  },
  minecraft_jarvis: {
    skill: "minecraft-jarvis",
    lines: [
      "Use `minecraft_jarvis({ message })` directly for Minecraft bot chat/control; always on, no `load_tools` needed.",
      "Do not substitute SSH/shell/slash commands; keep messages short, plain-language, and non-destructive.",
    ],
  },
  cron: {
    skill: "scheduled-discord-jobs",
    lines: [
      "Use `discord_cron` only for Pi/JARVIS scheduled jobs whose output posts to Discord, including questions like 'what cron jobs are running?', 'what scheduled jobs exist?', or 'is there a briefing cron job?'.",
      "For existence checks by job name, call `discord_cron({ action: \"list\" })` and filter the returned jobs; do not grep the repository or inspect OS crontab unless the user explicitly asks for OS cron/launchd.",
      "This is not an immediate notification tool or file-upload tool. For immediate Discord pings, notifications, or file delivery, load the `discord` group and use `discord_ping` or `discord_send_file` as appropriate.",
      "Do not fall back to shell/system crontab inspection unless the user explicitly asks for OS-level cron/launchd jobs; these Discord-backed jobs are managed by `discord_cron`.",
      "Do not start/restart the main JARVIS Discord bot unless the user explicitly asks.",
      "Common actions: `status`, `list`, `add`, `remove`, `enable`, `disable`, `run`, `runs`, `output`, `setup`, `install_cron`, and `uninstall_cron`.",
      "Adding a job requires `schedule` and `prompt`; schedules can be relative (`+5m`), interval-like (`5m interval`), cron, or ISO depending on the runner.",
      "`run` starts a detached manual run and posts output to the job's Discord thread; inspect history with `runs` and a specific run with `output`.",
      "Treat remove/disable/uninstall/setup changes as mutating operations: require clear user intent and summarize what changed.",
    ],
  },
  discord: {
    skill: "immediate Discord pings and file delivery",
    lines: [
      "Use `load_tools({ groups: [\"discord\"] })` before immediate Discord notifications or file delivery; then call the unlocked `discord_ping` or `discord_send_file` directly.",
      "Use `discord_ping` when the user clearly asks to be pinged/notified on Discord, says 'ping me', or asks to send files/results to them by Discord; include `attachmentPath` or `attachmentPaths` when files are part of the request.",
      "Use `discord_send_file` only to upload a verified local file to the current Discord channel when running inside a Discord session and the tool is available.",
      "If the user asks 'ping me/send me these files', prefer `discord_ping` with attachments; do not require a current-channel context.",
      "Use `discord_cron` only for scheduled or recurring jobs whose output posts to Discord.",
      "Verify requested files or conditions before sending; keep Discord messages concise and outcome-focused.",
      "If `discord_send_file` is unavailable, do not substitute it for current-channel uploads; report the unavailable context unless a user-facing ping with attachments satisfies the request.",
    ],
  },
  sessions: {
    skill: "session-search",
    lines: [
      "Use `session_search` before scanning raw old session files when the user asks about prior Pi/JARVIS work, decisions, logs, or memories from previous sessions.",
      "Start with `action: \"search\"`, a natural-language `query`, and a small `limit`; set `includeText: true` only when snippets are insufficient.",
      "Use `action: \"status\"` to check freshness. Use `action: \"index\"` only when requested or when status/search results indicate the index is stale.",
      "Search results cite session files/chunks; use them to answer concisely or decide which raw session file to inspect next.",
    ],
  },
  browser: {
    skill: "visible browser control",
    lines: [
      "`browser` = real visible persistent Chrome: open/screenshot/click/type/scroll/key/extract/tabs/upload.",
      "Load for open/use/check sites, rendered/interactive/logged-in/JS/forms/upload/download/screenshot/web-app tasks; web_search/fetch_content=text-only; don't ask just to load.",
      "Flow: open→screenshot→act→screenshot/extract. Prefer selector/text; coords from latest screenshot. Ask before private/account/purchase/destructive/submit; stop for CAPTCHA.",
    ],
  },
};

const GroupName = Type.String();

let providerVisibleGroups = new Set<ConcreteToolGroup>();

function unique(names: Iterable<string>): string[] {
  return [...new Set(names)];
}

function canonicalGroup(group: ToolGroup): ConcreteToolGroup | undefined {
  if (group === "all") return undefined;
  return GROUP_NAMES.includes(group as ConcreteToolGroup) ? (group as ConcreteToolGroup) : undefined;
}

function isToolGroupName(value: string): value is ToolGroup {
  return value === "all" || GROUP_NAMES.includes(value as ConcreteToolGroup);
}

function expandGroups(groups: readonly ToolGroup[]): ConcreteToolGroup[] {
  if (groups.includes("all")) return [...GROUP_NAMES];
  return unique(groups.map(canonicalGroup).filter((group): group is ConcreteToolGroup => Boolean(group))) as ConcreteToolGroup[];
}

function allLazyToolNames(): string[] {
  return unique([
    ...ALWAYS_ON_TOOLS,
    ...GROUP_NAMES.flatMap((group) => TOOL_GROUPS[group]),
  ]);
}

function desiredToolsFor(groups: readonly ConcreteToolGroup[] = []): string[] {
  return unique([
    ...ALWAYS_ON_TOOLS,
    ...groups.flatMap((group) => TOOL_GROUPS[group]),
  ]);
}

function existingToolNames(pi: ExtensionAPI): Set<string> {
  return new Set(pi.getAllTools().map((tool) => tool.name));
}

function selectAvailableTools(pi: ExtensionAPI, names: readonly string[]): string[] {
  const available = existingToolNames(pi);
  return unique(names).filter((name) => available.has(name));
}

function applyBaselineToolSet(pi: ExtensionAPI): string[] {
  const selected = selectAvailableTools(pi, ALWAYS_ON_TOOLS);
  pi.setActiveTools(selected);
  return selected;
}

function primeExecutionToolSet(pi: ExtensionAPI): string[] {
  // Pi snapshots executable tools at the start of an agent run. Keep every lazy
  // integration in that execution snapshot, then filter provider-visible schemas
  // in before_provider_request until load_tools reveals a group.
  const selected = selectAvailableTools(pi, allLazyToolNames());
  pi.setActiveTools(selected);
  return selected;
}

function providerVisibleGroupsArray(): ConcreteToolGroup[] {
  return GROUP_NAMES.filter((group) => providerVisibleGroups.has(group));
}

function mergeProviderVisibleGroups(groups: readonly ConcreteToolGroup[]): ConcreteToolGroup[] {
  for (const group of groups) providerVisibleGroups.add(group);
  return providerVisibleGroupsArray();
}

function replaceProviderVisibleGroups(groups: readonly ConcreteToolGroup[]): ConcreteToolGroup[] {
  providerVisibleGroups = new Set(groups);
  return providerVisibleGroupsArray();
}

function resetProviderVisibleGroups(): void {
  providerVisibleGroups.clear();
}

function providerVisibleTools(pi: ExtensionAPI): string[] {
  return selectAvailableTools(pi, desiredToolsFor(providerVisibleGroupsArray()));
}

function summarizeGroups(groups: readonly ConcreteToolGroup[]): string {
  if (groups.length === 0) return "baseline";
  return groups.map((group) => `${group} (${TOOL_GROUPS[group].join(", ")})`).join("; ");
}

function isAlwaysOnToolName(toolName: string): boolean {
  return (ALWAYS_ON_TOOLS as readonly string[]).includes(toolName);
}

function groupsForToolName(toolName: string): ConcreteToolGroup[] {
  return GROUP_NAMES.filter((group) => TOOL_GROUPS[group].includes(toolName));
}

function buildGuidanceSection(groups: readonly GuidanceGroup[], heading = "JARVIS unlocked-tool guidance"): string {
  if (groups.length === 0) return "";
  const sections = groups.map((group) => {
    const guidance = GROUP_GUIDANCE[group];
    const label = group === "jarvis" ? "jarvis group" : `${group} group`;
    return [`### ${label} — ${guidance.skill} playbook`, ...guidance.lines.map((line) => `- ${line}`)].join("\n");
  });
  return [
    `## ${heading}`,
    "Use listed tools directly; do not guess external command names.",
    "If an unlocked tool is missing from callable schema, report schema refresh failure.",
    ...sections,
  ].join("\n");
}

function buildCompactLoadGuidance(groups: readonly GuidanceGroup[]): string {
  if (groups.length === 0) return "";
  const lines: Record<GuidanceGroup, string> = {
    memory: "memory: use `memory` only for stable durable facts/preferences/lessons/workflows; never store secrets or sensitive personal data.",
    code_docs: "code_docs: use `code_search` for external programming docs/API examples; use local grep/find/read for repo files first.",
    image: "image: use `generate_image` for local Qwen image generation/editing; provide detailed prompts and local inputImagePath for guided edits.",
    phone: "phone: use `agent_phone` directly; args are CLI tokens excluding the binary; start with `snapshot -i`, interact via `@refs`, and confirm sensitive actions.",
    google: "google: use `google_workspace` for Calendar/events, Gmail/mail, Drive files/folders, Docs, and Sheets; use `calendar_events`, `drive_download_folder`, or generic `call` with help/schema; writes need explicit intent.",
    jarvis: "jarvis: use `jarvis` for camera/Cast and `smart_plug` for plugs; keep recordings bounded and speech short.",
    minecraft_jarvis: "minecraft_jarvis: use `minecraft_jarvis({ message })` for the Minecraft bot; do not substitute SSH, shell, or slash-command shortcuts.",
    cron: "cron: use `discord_cron` only for Discord-posted scheduled jobs; OS cron/launchd only if explicitly requested.",
    discord: "discord: use `discord_ping` for immediate Discord pings/notifications, with attachments when requested; use `discord_send_file` only for current-channel uploads when available.",
    sessions: "sessions: use `session_search` search first; status for freshness; index only if requested/stale.",
    browser: "browser: load for rendered/interactive/logged-in/forms/screenshots/open-use-check; web=text; verify; ask before sensitive."
  };
  return ["Compact playbook:", ...groups.map((group) => `- ${lines[group]}`)].join("\n");
}

function providerToolName(tool: any): string | undefined {
  if (typeof tool?.name === "string") return tool.name;
  if (typeof tool?.function?.name === "string") return tool.function.name;
  if (typeof tool?.toolSpec?.name === "string") return tool.toolSpec.name;
  return undefined;
}

function providerToolNames(tools: any[] | undefined): string[] {
  if (!Array.isArray(tools)) return [];
  const names: string[] = [];
  for (const tool of tools) {
    if (Array.isArray(tool?.functionDeclarations)) {
      for (const declaration of tool.functionDeclarations) {
        if (typeof declaration?.name === "string") names.push(declaration.name);
      }
      continue;
    }
    const name = providerToolName(tool);
    if (name) names.push(name);
  }
  return unique(names);
}

function filterProviderTools(tools: any[] | undefined, visible: Set<string>): any[] | undefined {
  if (!Array.isArray(tools)) return tools;
  const filtered = tools
    .map((tool) => {
      if (Array.isArray(tool?.functionDeclarations)) {
        const declarations = tool.functionDeclarations.filter((declaration: any) => typeof declaration?.name !== "string" || visible.has(declaration.name));
        return declarations.length > 0 ? { ...tool, functionDeclarations: declarations } : undefined;
      }
      const name = providerToolName(tool);
      return !name || visible.has(name) ? tool : undefined;
    })
    .filter((tool) => tool !== undefined);
  return filtered;
}

function rewriteAvailableToolsText(text: string, visibleToolNames: readonly string[]): string {
  const line = `Available tools: ${visibleToolNames.join(", ")}.\n`;
  let rewritten = text.replace(
    /Available tools:\n(?:- [^\n]*\n)+(?:\nIn addition to the tools above, you may have access to other custom tools depending on the project\.\n)?/,
    `${line}\n`,
  );
  rewritten = rewritten.replace(/Available tools(?: are provided in the tool schema list|: [^\n]*)\.\n/, line);
  return rewritten;
}

function rewritePayloadTextFields(payload: any, visibleToolNames: readonly string[]): any {
  let next = payload;
  const update = (text: string) => rewriteAvailableToolsText(text, visibleToolNames);

  if (typeof next?.instructions === "string") {
    const instructions = update(next.instructions);
    if (instructions !== next.instructions) next = { ...next, instructions };
  }

  if (typeof next?.system === "string") {
    const system = update(next.system);
    if (system !== next.system) next = { ...next, system };
  } else if (Array.isArray(next?.system)) {
    const system = next.system.map((block: any) =>
      typeof block?.text === "string" ? { ...block, text: update(block.text) } : block,
    );
    next = { ...next, system };
  }

  if (next?.systemInstruction && Array.isArray(next.systemInstruction.parts)) {
    const parts = next.systemInstruction.parts.map((part: any) =>
      typeof part?.text === "string" ? { ...part, text: update(part.text) } : part,
    );
    next = { ...next, systemInstruction: { ...next.systemInstruction, parts } };
  }

  return next;
}

function filterProviderPayload(payload: any, visibleToolNames: readonly string[]): any {
  if (!payload || typeof payload !== "object") return payload;
  const visible = new Set(visibleToolNames);
  let next = payload;

  if (Array.isArray(next.tools)) {
    const tools = filterProviderTools(next.tools, visible);
    next = { ...next, tools };
  }

  if (Array.isArray(next.toolConfig?.tools)) {
    const tools = filterProviderTools(next.toolConfig.tools, visible);
    next = { ...next, toolConfig: { ...next.toolConfig, tools } };
  }

  const namesFromPayload = unique([
    ...providerToolNames(next.tools),
    ...providerToolNames(next.toolConfig?.tools),
  ]);
  return rewritePayloadTextFields(next, namesFromPayload.length > 0 ? namesFromPayload : visibleToolNames);
}

export default function lazyTools(pi: ExtensionAPI) {
  pi.registerTool({
    name: "load_tools",
    label: "Load Tools",
    description: 'Load optional schemas. Baseline: coding, ssh, web_search/fetch_content/get_search_content, minecraft_jarvis, maps, github_cli. Groups: memory, code_docs, image, jarvis, phone, google, cron, discord, sessions, browser=visible Chrome, all. No aliases; minecraft_jarvis is already on.',
    promptSnippet: "Load optional groups. Baseline: coding, ssh, web_search/fetch_content/get_search_content, minecraft_jarvis, maps, github_cli. Common: memory, code_docs, image, google, phone, cron, discord, browser=visible Chrome.",
    promptGuidelines: [
      "Call load_tools before optional groups: memory, code_docs, image, jarvis, phone, google, cron, discord, sessions, browser. GitHub/`gh` => always-on `github_cli`; never bash `gh`. Local `git` status/diff/add/commit/log/branch => bash. If `github_cli` unavailable, report tool failure. For Google intents, load `google`. Web/search/fetch, github_cli, minecraft_jarvis, maps, and ssh are always on; no removed-tool aliases.",
      "If the user asks whether a cron/scheduled job exists, or asks to list/check scheduled jobs, load the `cron` group and call `discord_cron` first; do not search files or inspect OS crontab unless the user explicitly says OS cron/launchd.",
      "Discord map: `discord_cron` manages scheduled jobs that post to Discord; the `discord` group exposes immediate Discord delivery tools: `discord_ping` for user pings/notifications including attachments, and `discord_send_file` for current-channel uploads only when that context/tool is available.",
      "Web: `web_search`=discover (`provider: \"youtube\"` for YouTube), `fetch_content`=static, `get_search_content`=stored. Load `browser` without asking for open/use/check, rendered/interactive/logged-in/JS/forms/uploads/downloads/screenshots/web-apps; ask before private/account/purchase/destructive/submit.",
      "After load_tools succeeds, use the exact unlocked tool and returned playbook. If a required tool is unavailable, say so; if a tool was listed as unlocked but is not callable, report schema refresh failure rather than substituting another tool.",
    ],
    parameters: Type.Object({
      groups: Type.Array(GroupName, {
        minItems: 1,
        description: `Tool groups to load for this Pi session: ${LOADABLE_GROUPS_TEXT}.`,
      }),
    }),
    executionMode: "sequential",
    async execute(_toolCallId, params) {
      const requestedGroups = Array.isArray(params.groups)
        ? (params.groups as unknown[]).map((group) => String(group).trim().toLowerCase()).filter(Boolean)
        : [];
      const invalidGroups = requestedGroups.filter((group) => !isToolGroupName(group));
      if (invalidGroups.length > 0) {
        const validGroupNames = [...GROUP_NAMES, "all"].join(", ");
        return {
          content: [
            {
              type: "text",
              text: `Invalid tool group(s): ${invalidGroups.join(", ")}. Valid groups: ${validGroupNames}. No aliases are supported.`,
            },
          ],
          details: {
            invalidGroups,
            validGroups: validGroupNames,
          },
        };
      }
      const groups = requestedGroups as ToolGroup[];
      const expandedGroups = expandGroups(groups);
      const visibleGroups = mergeProviderVisibleGroups(expandedGroups);
      const executionTools = primeExecutionToolSet(pi);
      const visibleTools = providerVisibleTools(pi);
      const requestedToolNames = unique(expandedGroups.flatMap((group) => TOOL_GROUPS[group]));
      const unlockedToolNames = selectAvailableTools(pi, requestedToolNames);
      const missingUnlockedTools = requestedToolNames.filter((name) => !unlockedToolNames.includes(name));
      const guidance = buildCompactLoadGuidance(expandedGroups);
      return {
        content: [
          {
            type: "text",
            text: [
              `Loaded: ${summarizeGroups(expandedGroups)}.`,
              `Unlocked tools: ${unlockedToolNames.length > 0 ? unlockedToolNames.join(", ") : "(none)"}.`,
              missingUnlockedTools.length > 0 ? `Unavailable requested/context-specific tools: ${missingUnlockedTools.join(", ")}. Use only the unlocked tools above unless a later session registers the missing tool.` : undefined,
              "Use unlocked tools directly on the next step and later turns; their schemas are now provider-visible for this Pi session. If an unlocked tool is not callable, report schema refresh failure. Optional schemas reset when the Pi session restarts or when /reset-tools is used.",
              guidance || undefined,
            ]
              .filter(Boolean)
              .join("\n\n"),
          },
        ],
        details: {
          groups: expandedGroups,
          providerVisibleGroups: visibleGroups,
          providerVisibleTools: visibleTools,
          executionTools,
          requestedToolNames,
          unlockedToolNames,
          missingTools: missingUnlockedTools,
          guidance,
        },
      };
    },
  });

  pi.on("session_start", () => {
    resetProviderVisibleGroups();
    applyBaselineToolSet(pi);
  });

  pi.on("before_agent_start", async (event) => {
    // Prime every lazy tool for execution before Pi snapshots tools for this run.
    // Provider payloads remain baseline-only until load_tools updates providerVisibleGroups.
    // Always return the pre-prime prompt so enabling the execution registry does
    // not leak every optional tool's prompt snippets/guidelines into the model.
    primeExecutionToolSet(pi);
    const guidanceGroups = unique(["minecraft_jarvis", ...providerVisibleGroupsArray()]) as GuidanceGroup[];
    const guidance = buildGuidanceSection(guidanceGroups, "JARVIS active tool guidance");
    return {
      systemPrompt: guidance ? `${event.systemPrompt}\n\n${guidance}` : event.systemPrompt,
    };
  });

  pi.on("before_provider_request", (event) => {
    return filterProviderPayload((event as any).payload, providerVisibleTools(pi));
  });

  pi.on("tool_call", (event) => {
    const removedMapsToolName = ["google", "maps"].join("_");
    if (event.toolName === removedMapsToolName) {
      return {
        block: true,
        reason: "This removed location-grounding tool is disabled in this JARVIS Pi configuration. Use web_search/fetch_content with official sources, or a browser/manual route link when needed.",
      };
    }

    if (isAlwaysOnToolName(event.toolName)) return;
    const groups = groupsForToolName(event.toolName);
    if (groups.length === 0 || groups.some((group) => providerVisibleGroups.has(group))) return;
    return {
      block: true,
      reason: `${event.toolName} is hidden until one of its optional groups is loaded. Call load_tools({ groups: ["${groups[0]}"] }) first, then retry with the exact unlocked tool. Valid group(s): ${groups.map((group) => `"${group}"`).join(", ")}.`,
    };
  });

  pi.on("agent_end", () => {
    // Keep provider-visible groups across turns in the same Pi session.
    // The execution registry is slimmed back to baseline between turns and
    // re-primed at before_agent_start, while provider visibility resets only
    // on session_start or via /reset-tools.
    applyBaselineToolSet(pi);
  });

  pi.registerCommand("lazy-tools", {
    description: "Show lazy tool groups, provider-visible tools, and the execution tool set.",
    handler: async (_args, ctx) => {
      const visibleTools = providerVisibleTools(pi);
      const executionTools = pi.getActiveTools();
      ctx.ui.notify(
        `Lazy tool groups: ${LOADABLE_GROUPS_TEXT}\nProvider-visible groups: ${summarizeGroups(providerVisibleGroupsArray())}\nProvider-visible tools: ${visibleTools.join(", ")}\nExecution tools: ${executionTools.join(", ")}`,
        "info",
      );
    },
  });

  pi.registerCommand("load-tools", {
    description: "Load lazy tool groups for this Pi session: /load-tools memory,code_docs,image,jarvis,minecraft_jarvis,phone,google,cron,discord,sessions,browser,all",
    handler: async (args, ctx) => {
      const requested = args
        .split(/[\s,]+/)
        .map((part) => part.trim().toLowerCase())
        .filter(Boolean);
      const invalid = requested.filter((group) => !isToolGroupName(group));
      const valid = requested.filter(isToolGroupName);
      if (invalid.length > 0 || valid.length === 0) {
        ctx.ui.notify(`Usage: /load-tools <group>[,<group>...]\nGroups: ${LOADABLE_GROUPS_TEXT}\nCommon choices: code_docs=code_search; image=generate_image; memory=durable memory; phone=LG-H933 Android control; cron=scheduled Discord jobs; discord=immediate Discord pings/file delivery; browser=visible Chrome control. Web tools (web_search/fetch_content/get_search_content) and github_cli are always on.\n${invalid.length > 0 ? `Invalid group(s): ${invalid.join(", ")}. No aliases are supported.` : ""}`, "warning");
        return;
      }
      const expandedGroups = expandGroups(valid);
      const visibleGroups = replaceProviderVisibleGroups(expandedGroups);
      const executionTools = selectAvailableTools(pi, allLazyToolNames());
      const visibleTools = providerVisibleTools(pi);
      applyBaselineToolSet(pi);
      ctx.ui.notify(
        `Loaded groups for this Pi session: ${summarizeGroups(visibleGroups)}\nProvider-visible tools for future turns: ${visibleTools.join(", ")}\nExecution tools will be primed at run start: ${executionTools.join(", ")}`,
        "info",
      );
    },
  });

  pi.registerCommand("reset-tools", {
    description: "Reset provider-visible tools to the JARVIS lazy-tools baseline.",
    handler: async (_args, ctx) => {
      resetProviderVisibleGroups();
      const selected = applyBaselineToolSet(pi);
      ctx.ui.notify(`Reset provider-visible/active tools: ${selected.join(", ")}`, "info");
    },
  });
}
