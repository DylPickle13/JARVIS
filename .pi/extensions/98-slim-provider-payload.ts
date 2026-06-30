import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

function toolName(tool: any): string | undefined {
  return typeof tool?.name === "string" ? tool.name : typeof tool?.function?.name === "string" ? tool.function.name : undefined;
}

function compactAvailableTools(_payload: any): string {
  return "";
}

function compactInstructions(instructions: string, payload: any): string {
  let text = instructions;

  text = text.replace(
    /Available tools:\n(?:- [^\n]*\n)+\nIn addition to the tools above, you may have access to other custom tools depending on the project\.\n\n?/,
    compactAvailableTools(payload),
  );

  text = text.replace(
    /Guidelines:\n(?:- [^\n]*\n)+(?:\n)/,
    [
      "Guidelines:",
      "- Coding: use bash/read/grep/find/ls/edit/write; exact unique edits, batch disjoint edits.",
      "- Ask one clarification only if required.",
      "- Memory: load `memory` first; stable facts only; no secrets/sensitive data.",
      "- Web: `web_search` discover, `fetch_content` text/pages, `get_search_content` stored; load `browser` for rendered/interactive/logged-in/forms/screenshots/open-use-check sites.",
      "- Optional groups require `load_tools`; cron/scheduled-job checks use `discord_cron` first unless OS cron/launchd is explicitly requested.",
      "- Be concise; show paths.",
      "",
    ].join("\n"),
  );

  text = text.replace(
    /Pi documentation \(read only[^\n]*\):\n- Main documentation: ([^\n]+)\n- Additional docs: ([^\n]+)\n- Examples: ([^\n]+)\n(?:- (?:When reading|When asked|When working|Always read)[^\n]*\n?)+/,
    "Pi docs only when relevant: README $1; docs $2; examples $3. Read relevant docs first.",
  );

  return text;
}

const TOOL_DESCRIPTION_OVERRIDES: Record<string, string> = {
  read: "Read a file/image; use offset/limit for large text.",
  bash: "Run a bash command in cwd; optional timeout.",
  edit: "Edit one file by exact unique text replacements.",
  write: "Write/overwrite a file, creating parent dirs.",
  grep: "Search file contents; supports path/glob/context/limit.",
  find: "Find files by glob; optional path/limit.",
  ls: "List a directory; optional path/limit.",
  ssh: "Run SSH command on trusted host.",
  memory: "Durable project memory: search/remember/update/forget/list/status. No secrets.",
  web_search: "Cited web search/research; discovery only. Do not use includeContent; batch selected URLs with fetch_content.",
  code_search: "Search external code/docs/API examples.",
  fetch_content: "Fetch/extract URL(s)/GitHub/YouTube/local video; batch selected research URLs in one urls array.",
  get_search_content: "Retrieve stored search/fetch content by responseId.",
  minecraft_jarvis: "Minecraft bot chat/control; use direct short plain messages; no SSH/shell/slash.",
  maps: "Ask Google Maps about places, addresses, coordinates, routes, travel time, or local searches.",
  load_tools: "Load optional groups incl browser=visible Chrome for rendered/interactive web; plus memory, code_docs, image, video, jarvis, phone, google, cron, discord, sessions, all.",
  agent_phone: "Android phone control via safe CLI-token args.",
  jarvis: "Operation JARVIS dashboard/camera/Cast/Spotify/air-purifier helper.",
  smart_plug: "Local smart-plug control.",
  google_workspace: "Google Workspace API for Drive/Gmail/Docs/Sheets/Calendar.",
  discord_cron: "Manage scheduled Pi/JARVIS jobs posted to Discord.",
  discord_ping: "Send immediate Discord ping/notification, optionally with attachments.",
  discord_send_file: "Upload a verified local file to the current Discord channel.",
  session_search: "Search prior Pi/JARVIS sessions.",
  browser_status: "Visible Chrome status, profile path, active tab, and open tabs.",
  browser_open: "Open/navigate real visible Chrome with persistent profile.",
  browser_screenshot: "Capture visible Chrome screenshot; returns PNG image for visual reasoning.",
  browser_click: "Click visible Chrome by x/y viewport coordinates, CSS selector, or visible text.",
  browser_type: "Type into visible Chrome focused element or CSS selector.",
  browser_upload: "Upload approved local file(s) through visible Chrome file inputs.",
  browser_key: "Press a key/shortcut in visible Chrome.",
  browser_scroll: "Scroll visible Chrome page.",
  browser_wait: "Wait for time, selector/text, or load state in visible Chrome.",
  browser_extract: "Extract readable text and optional links from current Chrome page.",
  browser_tabs: "List, switch, or close visible Chrome tabs.",
  browser_close: "Close active Chrome tab or entire browser.",
  github_cli: "Run official gh CLI with args; loads GitHub token from .env and redacts it.",
};

function stripNestedSchemaMetadata(value: any): any {
  if (Array.isArray(value)) return value.map(stripNestedSchemaMetadata);
  if (!value || typeof value !== "object") return value;

  const copy: any = {};
  for (const [key, child] of Object.entries(value)) {
    if (key === "description" || key === "title" || key === "$comment" || key === "examples" || key === "additionalProperties") continue;
    copy[key] = stripNestedSchemaMetadata(child);
  }
  return copy;
}

function stripEnumValue(value: any, enumValue: string): any {
  if (Array.isArray(value)) return value.map((child) => stripEnumValue(child, enumValue));
  if (!value || typeof value !== "object") return value;

  const copy: any = { ...value };
  if (Array.isArray(copy.enum)) {
    copy.enum = copy.enum.filter((item: unknown) => item !== enumValue);
  }
  for (const [key, child] of Object.entries(copy)) {
    if (key === "enum") continue;
    copy[key] = stripEnumValue(child, enumValue);
  }
  return copy;
}

const SCHEMA_STRIP_TOOLS = new Set([
  "read",
  "bash",
  "edit",
  "write",
  "grep",
  "find",
  "ls",
  "ssh",
  "ask_user",
  "memory",
  "web_search",
  "code_search",
  "fetch_content",
  "get_search_content",
  "load_tools",
  "minecraft_jarvis",
  "maps",
  // Optional lazy-loaded tools: preserve top-level descriptions, strip nested prose.
  "agent_phone",
  "jarvis",
  "smart_plug",
  "google_workspace",
  "discord_cron",
  "discord_ping",
  "discord_send_file",
  "session_search",
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
  "github_cli",
]);

function compactTool(tool: any): any {
  if (!tool || typeof tool !== "object") return tool;
  const name = toolName(tool);
  if (!name || !SCHEMA_STRIP_TOOLS.has(name)) return tool;

  const copy: any = { ...tool };

  // Preserve terse top-level descriptions; remove nested parameter prose/metadata.
  const override = TOOL_DESCRIPTION_OVERRIDES[name];
  if (override && typeof copy.description === "string") copy.description = override;

  if (copy.parameters) copy.parameters = stripNestedSchemaMetadata(copy.parameters);
  if (copy.input_schema) copy.input_schema = stripNestedSchemaMetadata(copy.input_schema);
  if (name === "web_search") {
    if (copy.parameters) copy.parameters = stripEnumValue(copy.parameters, "gemini");
    if (copy.input_schema) copy.input_schema = stripEnumValue(copy.input_schema, "gemini");
  }
  if (copy.function && typeof copy.function === "object") {
    copy.function = { ...copy.function };
    if (override && typeof copy.function.description === "string") copy.function.description = override;
    if (copy.function.strict === false) delete copy.function.strict;
    if (copy.function.parameters) copy.function.parameters = stripNestedSchemaMetadata(copy.function.parameters);
    if (name === "web_search" && copy.function.parameters) copy.function.parameters = stripEnumValue(copy.function.parameters, "gemini");
  }

  return copy;
}

export default function slimProviderPayload(pi: ExtensionAPI) {
  pi.on("before_agent_start", (event) => {
    const selectedTools = (event as any).systemPromptOptions?.selectedTools ?? pi.getActiveTools();
    const payloadLike = { tools: selectedTools.map((name: string) => ({ name })) };
    const systemPrompt = compactInstructions(event.systemPrompt, payloadLike);
    return systemPrompt === event.systemPrompt ? undefined : { systemPrompt };
  });

  pi.on("before_provider_request", (event) => {
    const payload: any = event.payload;
    return {
      ...payload,
      instructions: typeof payload.instructions === "string" ? compactInstructions(payload.instructions, payload) : payload.instructions,
      tools: Array.isArray(payload.tools) ? payload.tools.map(compactTool) : payload.tools,
    };
  });
}
