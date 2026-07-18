import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

type CanonicalToolGroup =
  | "memory"
  | "code_docs"
  | "image"
  | "video"
  | "jarvis"
  | "minecraft_jarvis"
  | "phone"
  | "google"
  | "cron"
  | "discord"
  | "sessions"
  | "browser"
  | "reaper"
  | "gx10";
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
  video: ["generate_video"],
  jarvis: ["jarvis", "smart_plug"],
  minecraft_jarvis: ["minecraft_jarvis"],
  phone: ["agent_phone"],
  google: ["google_workspace"],
  cron: ["discord_cron"],
  discord: ["discord_ping", "discord_send_file"],
  sessions: ["session_search"],
  reaper: ["reaper_ping", "reaper_lua"],
  gx10: ["gx10_ping", "gx10_get", "gx10_find", "gx10_lua"],
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
  video: "generate_video for local LTX-2.3 Q8 MLX audio-video generation or image-to-audio-video clips",
  jarvis: "Operation JARVIS for dashboard phone camera vision, Google Cast speech/media, local smart plugs, and VeSync/Levoit air purifier control",
  minecraft_jarvis: "Minecraft jarvis bot chat/control through the in-game Qwen companion",
  phone: "agent_phone for safe LG-H933 Android phone control via ADB refs/screenshots",
  google: "google_workspace for Calendar/events, Gmail/mail, Drive/files/folders, Docs, and Sheets",
  cron: "discord_cron only: scheduled Pi/JARVIS jobs whose output posts to Discord",
  discord: "discord_ping for immediate Discord pings/notifications and attachments; discord_send_file for current-channel uploads when available",
  sessions: "session_search over prior Pi/JARVIS sessions",
  reaper: "reaper_ping/reaper_lua for the live REAPER session on mac-mini-16 via inline Lua bridge",
  gx10: "gx10_get/gx10_find semantic reads plus gx10_ping/gx10_lua for direct BOSS GX-10 CoreMIDI access",
  browser: "visible Chrome for rendered/interactive web: screenshots/clicks/typing/uploads/extract",
};

const GROUP_NAMES = Object.keys(TOOL_GROUPS) as ConcreteToolGroup[];
const GROUP_NAMES_WITH_ALL_TEXT = [...GROUP_NAMES, "all"].join(", ");
const LOADABLE_GROUPS_TEXT = `${GROUP_NAMES.map((name) => `${name}=${GROUP_SUMMARIES[name]}`).join("; ")}; all=all loadable groups`;
const BASELINE_TOOLS_TEXT = "coding, ssh, web_search/fetch_content/get_search_content, minecraft_jarvis, maps, github_cli";
const LOAD_TOOLS_DESCRIPTION = `Load optional tool schemas by exact group name. Always-on baseline: ${BASELINE_TOOLS_TEXT}. Available groups: ${LOADABLE_GROUPS_TEXT}. Optional schemas stay visible for this Pi session after loading; minecraft_jarvis is already always on.`;
const LOAD_TOOLS_PROMPT_SNIPPET = `Load optional tool groups by exact name: ${GROUP_NAMES_WITH_ALL_TEXT}.`;

const GROUP_GUIDANCE: Record<GuidanceGroup, { skill: string; lines: readonly string[] }> = {
  memory: {
    skill: "durable memory",
    lines: [
      "Use `memory` only for stable durable facts, preferences, lessons, project notes, or workflows that should survive future sessions. Memory is explicit-only; there is no automatic prompt-time recall.",
      "Never store secrets, credentials, tokens, private personal data, or transient one-off details.",
      "Prefer `action: \"search\"` before writing new memories; keep new entries concise and tagged when useful. `forget` permanently purges the memory and its event history.",
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
      "Use `generate_image` for local PNG image generation or guided image edits on mac-mini-64. It uses only the approved Qwen image model; do not offer or request alternate models for this tool.",
      "Default high-quality image profile is large 16:9, 30 steps. Keep prompts visually descriptive and change the aspect/size/steps only for an explicit speed, quality, or framing request.",
      "For guided edits, pass a local PNG/JPEG/WebP/BMP `inputImagePath`, describe the transformation, and use `imageStrength` around 0.4 by default; higher values preserve more source-image influence.",
      "Do not use shell, browser, ComfyUI, Draw Things, or alternate image generators unless explicitly requested.",
    ],
  },
  video: {
    skill: "video generation",
    lines: [
      "Use `generate_video` for local MP4 generation with synchronized audio or image-to-audio-video clips on mac-mini-64. It uses only the approved LTX-2.3 Q8 MLX model; do not offer or request alternate models for this tool.",
      "Default quality profile is standard 16:9, 4 seconds, 24 fps, two-stage pipeline, low-RAM streaming. Use `seconds`, not frames; the worker converts to 33/65/97/129-frame counts and caps output around 5.4 seconds at 24 fps.",
      "For image-to-audio-video, pass a local PNG/JPEG/WebP/BMP `inputImagePath` and describe camera/subject motion plus ambience, sound effects, and dialogue/audio cues.",
      "Large audio-video clips can take a long time; use `pipeline: \"distilled\"` and `size: \"small\"` for faster previews. Do not substitute browser, ComfyUI, shell, or manual worker calls unless debugging.",
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
      "For any home-control request (lights/plugs/switches/power, Cast/TV/speakers, camera/view, air purifier), first call `load_tools({ groups: [\"jarvis\"] })`; then use the exact unlocked `jarvis` or `smart_plug` tool. Do not read files, run shell/CLI, SSH, or guess commands unless the JARVIS tool fails.",
      "Safe checks: `jarvis({ action: \"help\" })`, `jarvis({ action: \"status\", noCast: true })`, `jarvis({ action: \"cast-status\", device: \"speakers\" })`, `smart_plug({ action: \"list\" })`, or `jarvis({ action: \"purifier-status\" })`.",
      "Dashboard camera actions: `jarvis({ action: \"look\" })`, `jarvis({ action: \"video\", duration: 5 })`, `jarvis({ action: \"video-until\", condition: \"a person is visible\", maxDuration: 60 })`, or `jarvis({ action: \"analyze-view\", question: \"What is visible?\" })`.",
      "Cast actions: `jarvis({ action: \"speak\", text: \"JARVIS online.\", device: \"speakers\" })`, `jarvis({ action: \"cast-status\", device: \"tv\" })`, `jarvis({ action: \"cast-volume\", level: 25 })`, `jarvis({ action: \"cast-youtube\", query: \"relaxing jazz\", device: \"tv\" })`, and related `cast-mute`, `cast-stop`, `cast-play-url` actions. `cast-stop` quits the Cast app by default.",
      "Spotify actions include `cast-spotify-devices`, play/resume with `cast-spotify`, pause/next/previous/volume, queue read/add, seek, shuffle, and repeat. Use `device: \"tv\"`/`\"speakers\"` for configured aliases or an exact `spotifyDeviceName`; prefer names over changing IDs and never expose credentials.",
      "Smart-plug/light phrases such as 'turn on/off the light/lamp/kettle/tv plug' go directly to the dedicated local-only tool: `smart_plug({ action: \"status\"|\"on\"|\"off\"|\"toggle\", plug: \"<configured-plug-name>\" })`. Run `smart_plug({ action: \"list\" })` only if the alias is unclear, and summarize the resulting state after writes.",
      "Air-purifier actions use exactly two `jarvis` actions: `jarvis({ action: \"purifier-status\" })` for read-only status/filter/air-quality info, and `jarvis({ action: \"purifier-set\", setting: \"mode\", value: \"auto\" })` for writes. Supported settings: power, mode, speed, display, child-lock, light-detection, auto-preference, timer. VeSync writes may take more than a minute; wait for the tool result before issuing another purifier command.",
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
      "Call `discord_ping` only after the requested goal or condition is verified complete. Keep messages concise and outcome-focused; do not send routine progress updates or speculative results.",
      "Verify every requested attachment before sending. After browser or file work, do not notify until the specifically requested result is actually ready.",
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
  reaper: {
    skill: "live REAPER inline Lua bridge",
    lines: [
      "Use `reaper_ping` and `reaper_lua` only after loading the `reaper` group; these tools talk to the live REAPER instance on mac-mini-16.",
      "Use `reaper_lua` for live-session inspection or edits by sending inline Lua only. Do not save temporary task scripts for REAPER work.",
      "For edits, write any desired `reaper.Undo_BeginBlock()` / `reaper.Undo_EndBlock()` directly in the Lua snippet; the bridge intentionally has no hardcoded action wrappers.",
      "Return JSON-safe Lua tables from `reaper_lua` so results are easy to inspect.",
      "Do not guess REAPER/ReaScript API signatures. Before using any unfamiliar REAPER API call, inspect official docs, local bridge examples, or known project examples.",
      "If a REAPER API call returns an unexpected value/type, stop immediately and look up the API before retrying. Do not make a second guessed attempt.",
      "Capture all return values for REAPER API functions unless the signature has been verified; many return multiple values. Use `reaper.APIExists(\"FunctionName\")` for common availability checks.",
      "Official ReaScript API reference: https://www.reaper.fm/sdk/reascript/reascripthelp.html",
    ],
  },
  gx10: {
    skill: "direct GX-10 semantic/CoreMIDI bridge",
    lines: [
      "Use `gx10_get`, `gx10_find`, `gx10_ping`, and `gx10_lua` only after loading the `gx10` group; these tools connect directly to the standard BOSS GX-10 CoreMIDI endpoint on mac-mini-16, not REAPER or DAW CTRL.",
      "For ordinary questions, use read-only `gx10_get` first (current live temp patch by default); `what=overview` reads the current patch, `assignments` preserves source/target labels, and `what=get` is only for exact low-level paths. Use `gx10_find` to resolve unfamiliar semantic names. Both preserve decoded labels/raw IDs and report ambiguity rather than guessing.",
      "Use `gx10_lua` only as the custom/planning/low-level escape hatch. Semantic Lua reads include `gx.current_patch()`, `gx.chain()`, `gx.effects()`, `gx.assignments()`, `gx.controls()`, `gx.semantic()`, `gx.find()`, and `gx.get_many()`; low-level reads remain `gx.get()`, `gx.get_block()`, `gx.rq1()`, and `gx.listen()`.",
      "For unfamiliar paths, use `gx10_find` or inspect with `gx.schema(query)` rather than guessing. API documentation is `/Users/dylanrapanan/gx10-bridge/README.md` on mac-mini-16.",
      "Keep `allowWrite:false` unless sir explicitly requested a GX-10 edit in the current conversation. For semantic edits, dry-run `gx.plan_edit(spec)`, show its exact plan ID (and every whole-block mirror for save=true), then stop for approval; regenerate with `expectedPlanId` and use `tx:apply_plan(plan)` inside a matching `gx.transaction`. Never blindly retry a failed write.",
      "Use `tx:set` for schema fields, `tx:set_machine` for exact stored values, and `tx:get_block`/`tx:set_block` for byte-exact moves or copies. Avoid raw `tx:write` unless a documented address was verified and no schema path exists.",
      "The bridge fails closed while Tone Studio is running, snapshots touched blocks, verifies readback, and rolls back on failure. IR transfer and firmware writes are intentionally unavailable.",
    ],
  },
  browser: {
    skill: "visible browser control",
    lines: [
      "`browser` is real visible persistent Chrome: status/open/screenshot/click/type/upload/key/scroll/wait/extract/tabs/close.",
      "Load it for open/use/check-site requests and rendered, interactive, logged-in, JavaScript, form, upload/download, screenshot, or web-app work; `web_search`/`fetch_content` remain text-only. Do not ask merely to load the group.",
      "Typical flow: open → viewport screenshot → act → screenshot or extract to verify. Check `browser_status` before opening many tabs; use full-page screenshots only when necessary.",
      "Prefer selectors or visible text when unambiguous. Coordinate clicks must use the latest viewport screenshot; re-screenshot after navigation or significant changes because coordinates can go stale.",
      "Use `browser_type` with a selector and `clear:true` when replacing field contents; use `browser_open` for URL navigation. Do not enter passwords or private data unless explicitly provided for that action.",
      "Upload only explicitly approved local files, prefer `input[type=file]`, and verify attachment with screenshot/extract before submitting.",
      "Use `browser_extract` for long DOM text, links, and forms. Ask before private/account/purchase/destructive/submit actions and stop for CAPTCHA.",
    ],
  },
};

const GroupName = Type.String();

let loadedGroups = new Set<ConcreteToolGroup>();

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

function loadedGroupsArray(): ConcreteToolGroup[] {
  return GROUP_NAMES.filter((group) => loadedGroups.has(group));
}

function mergeLoadedGroups(groups: readonly ConcreteToolGroup[]): ConcreteToolGroup[] {
  for (const group of groups) loadedGroups.add(group);
  return loadedGroupsArray();
}

function resetLoadedGroups(): void {
  loadedGroups.clear();
}

function loadedTools(pi: ExtensionAPI): string[] {
  return selectAvailableTools(pi, desiredToolsFor(loadedGroupsArray()));
}

function activateToolGroups(pi: ExtensionAPI, groups: readonly ConcreteToolGroup[]) {
  const allLoadedGroups = mergeLoadedGroups(groups);
  const requestedToolNames = unique(groups.flatMap((group) => TOOL_GROUPS[group]));
  const unlockedToolNames = selectAvailableTools(pi, requestedToolNames);
  const missingToolNames = requestedToolNames.filter((name) => !unlockedToolNames.includes(name));
  const activeBefore = pi.getActiveTools();
  const addedToolNames = unlockedToolNames.filter((name) => !activeBefore.includes(name));
  const activeTools = selectAvailableTools(pi, unique([...activeBefore, ...addedToolNames]));

  // Keep activation purely additive. Pi records addedToolNames on the load_tools
  // result and uses native deferred definitions on capable providers.
  pi.setActiveTools(activeTools);

  return {
    allLoadedGroups,
    requestedToolNames,
    unlockedToolNames,
    missingToolNames,
    addedToolNames,
    activeTools,
  };
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

export default function lazyTools(pi: ExtensionAPI) {
  pi.registerTool({
    name: "load_tools",
    label: "Load Tools",
    description: LOAD_TOOLS_DESCRIPTION,
    promptSnippet: LOAD_TOOLS_PROMPT_SNIPPET,
    promptGuidelines: [
      "Call load_tools before any optional group listed in its canonical description (" + GROUP_NAMES_WITH_ALL_TEXT + "). For live REAPER session work, load `reaper` then use `reaper_lua` with inline Lua only. For direct BOSS GX-10 work, load `gx10`, prefer `gx10_get`/`gx10_find` for reads, and retain `gx10_lua` for low-level/custom work. Home-control intents (lights/plugs/switches/power, Cast/TV/speakers, camera/view, purifier) => first load `jarvis`; for lights/plugs then call `smart_plug` directly. Do not inspect files or use shell/CLI unless the tool fails. GitHub/`gh` => always-on `github_cli`; never bash `gh`. Local `git` status/diff/add/commit/log/branch => bash. If `github_cli` unavailable, report tool failure. For Google intents, load `google`. Web/search/fetch, github_cli, minecraft_jarvis, maps, and ssh are always on; no removed-tool aliases.",
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
      const activation = activateToolGroups(pi, expandedGroups);
      const guidance = buildGuidanceSection(expandedGroups, "JARVIS loaded-tool guidance");
      return {
        content: [
          {
            type: "text",
            text: [
              `Loaded: ${summarizeGroups(expandedGroups)}.`,
              `Unlocked tools: ${activation.unlockedToolNames.length > 0 ? activation.unlockedToolNames.join(", ") : "(none)"}.`,
              activation.addedToolNames.length > 0 ? `Newly activated schemas: ${activation.addedToolNames.join(", ")}.` : "All available tools in the requested groups were already active.",
              activation.missingToolNames.length > 0 ? `Unavailable requested/context-specific tools: ${activation.missingToolNames.join(", ")}. Use only the unlocked tools above unless a later session registers the missing tool.` : undefined,
              "Use unlocked tools directly on the next step and later turns. Pi anchors newly activated schemas at this tool result on providers with native deferred loading. Optional schemas reset when the Pi session restarts or when /reset-tools is used.",
              guidance || undefined,
            ]
              .filter(Boolean)
              .join("\n\n"),
          },
        ],
        details: {
          groups: expandedGroups,
          loadedGroups: activation.allLoadedGroups,
          requestedToolNames: activation.requestedToolNames,
          unlockedToolNames: activation.unlockedToolNames,
          addedToolNames: activation.addedToolNames,
          activeTools: activation.activeTools,
          missingTools: activation.missingToolNames,
          guidance,
        },
      };
    },
  });

  pi.on("session_start", () => {
    resetLoadedGroups();
    applyBaselineToolSet(pi);
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
    if (groups.length === 0 || groups.some((group) => loadedGroups.has(group))) return;
    return {
      block: true,
      reason: `${event.toolName} is hidden until one of its optional groups is loaded. Call load_tools({ groups: ["${groups[0]}"] }) first, then retry with the exact unlocked tool. Valid group(s): ${groups.map((group) => `"${group}"`).join(", ")}.`,
    };
  });

  pi.registerCommand("lazy-tools", {
    description: "Show lazy tool groups, loaded groups, and the active tool set.",
    handler: async (_args, ctx) => {
      const activeTools = pi.getActiveTools();
      ctx.ui.notify(
        `Lazy tool groups: ${LOADABLE_GROUPS_TEXT}\nLoaded groups: ${summarizeGroups(loadedGroupsArray())}\nLoaded tools: ${loadedTools(pi).join(", ")}\nActive tools: ${activeTools.join(", ")}`,
        "info",
      );
    },
  });

  pi.registerCommand("load-tools", {
    description: `Load lazy tool groups for this Pi session: /load-tools ${GROUP_NAMES.join(",")},all`,
    handler: async (args, ctx) => {
      const requested = args
        .split(/[\s,]+/)
        .map((part) => part.trim().toLowerCase())
        .filter(Boolean);
      const invalid = requested.filter((group) => !isToolGroupName(group));
      const valid = requested.filter(isToolGroupName);
      if (invalid.length > 0 || valid.length === 0) {
        ctx.ui.notify(`Usage: /load-tools <group>[,<group>...]\nCanonical groups: ${LOADABLE_GROUPS_TEXT}.\nAlways-on baseline: ${BASELINE_TOOLS_TEXT}.\n${invalid.length > 0 ? `Invalid group(s): ${invalid.join(", ")}. No aliases are supported.` : ""}`, "warning");
        return;
      }
      const expandedGroups = expandGroups(valid);
      const activation = activateToolGroups(pi, expandedGroups);
      const guidance = buildGuidanceSection(expandedGroups, "JARVIS loaded-tool guidance");
      if (guidance) {
        pi.sendMessage({
          customType: "jarvis-loaded-tool-guidance",
          content: guidance,
          display: false,
          details: { groups: expandedGroups },
        }, { deliverAs: "nextTurn" });
      }
      ctx.ui.notify(
        `Loaded groups for this Pi session: ${summarizeGroups(activation.allLoadedGroups)}\nNewly active tools: ${activation.addedToolNames.join(", ") || "(none)"}\nActive tools: ${activation.activeTools.join(", ")}\nThe group playbook is queued for the next user turn. Note: slash-command activation has no tool-result anchor and may refresh the provider cache once; model-called load_tools uses native deferred loading where supported.`,
        "info",
      );
    },
  });

  pi.registerCommand("reset-tools", {
    description: "Reset active tools to the JARVIS lazy-tools baseline.",
    handler: async (_args, ctx) => {
      resetLoadedGroups();
      const selected = applyBaselineToolSet(pi);
      ctx.ui.notify(`Reset active tools: ${selected.join(", ")}`, "info");
    },
  });
}
