import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

import { truncate } from "../lib/text";
import type { DaemonBrowserManager as BrowserManager } from "./daemon-browser-manager";

const MouseButton = ["left", "right", "middle"] as const;
const ScrollDirection = ["up", "down", "left", "right"] as const;
const LoadState = ["load", "domcontentloaded", "networkidle"] as const;
const TabsAction = ["list", "switch", "close"] as const;

function stringEnum(values: readonly string[], options?: Record<string, unknown>) {
  return Type.Union(values.map((value) => Type.Literal(value)) as any, options as any);
}

let lastBrowserActionAt = 0;

async function pace(): Promise<void> {
  const minGap = Number(process.env.PI_BROWSER_MIN_ACTION_GAP_MS || 275);
  const elapsed = Date.now() - lastBrowserActionAt;
  if (elapsed < minGap) await new Promise((resolve) => setTimeout(resolve, minGap - elapsed));
  lastBrowserActionAt = Date.now();
}

function compactJson(value: unknown): string {
  return truncate(JSON.stringify(value, null, 2));
}

export function registerBrowserTools(pi: ExtensionAPI, getBrowser: () => BrowserManager) {
  pi.registerTool({
    name: "browser_status",
    label: "Browser Status",
    description: "Return status for the lazy visible Chrome browser: launch/attach mode, running state, profile/CDP path, active tab, and open tabs.",
    parameters: Type.Object({}),
    async execute() {
      const status = await getBrowser().status();
      return { content: [{ type: "text", text: compactJson(status) }], details: status };
    },
  });

  pi.registerTool({
    name: "browser_open",
    label: "Browser Open",
    description: "Open a URL in the visible Chrome browser through the persistent local Chrome bridge daemon.",
    parameters: Type.Object({
      url: Type.String({ description: "URL or domain to open. Domains without a scheme are treated as https://." }),
      newTab: Type.Optional(Type.Boolean({ description: "Open in a new tab instead of reusing the active tab." })),
    }),
    async execute(_id, params, signal, onUpdate) {
      if (signal?.aborted) throw new Error("browser_open cancelled");
      onUpdate?.({ content: [{ type: "text", text: `Opening ${params.url} in visible Chrome...` }] });
      await pace();
      const result = await getBrowser().open(String(params.url), Boolean(params.newTab));
      return {
        content: [{ type: "text", text: `Opened tab ${result.index}: ${result.title || "(untitled)"}\n${result.url}` }],
        details: result,
      };
    },
  });

  pi.registerTool({
    name: "browser_screenshot",
    label: "Browser Screenshot",
    description: "Capture the current visible browser page as a PNG image for visual reasoning. Supports viewport, full-page, or element screenshots.",
    parameters: Type.Object({
      fullPage: Type.Optional(Type.Boolean({ description: "Capture the full scrollable page instead of just the viewport." })),
      selector: Type.Optional(Type.String({ description: "Optional CSS selector for an element-only screenshot." })),
      attachImage: Type.Optional(Type.Boolean({ description: "Attach image data. Defaults to true; false returns only metadata." })),
    }),
    async execute(_id, params, signal, onUpdate) {
      if (signal?.aborted) throw new Error("browser_screenshot cancelled");
      onUpdate?.({ content: [{ type: "text", text: "Capturing browser screenshot..." }] });
      const result = await getBrowser().screenshot({ fullPage: params.fullPage, selector: params.selector, attachImage: params.attachImage });
      const text = [`Screenshot: ${result.title || "(untitled)"}`, result.url, result.width && result.height ? `Viewport: ${result.width}x${result.height}` : undefined].filter(Boolean).join("\n");
      const content: Array<{ type: "text"; text: string } | { type: "image"; data: string; mimeType: string }> = [{ type: "text", text }];
      if (params.attachImage !== false) content.push({ type: "image", data: result.data, mimeType: result.mimeType });
      return { content, details: { ...result, data: params.attachImage === false ? undefined : "[base64 png attached]" } };
    },
  });

  pi.registerTool({
    name: "browser_click",
    label: "Browser Click",
    description: "Click the visible browser page by viewport coordinates, CSS selector, or visible text. Coordinates should come from the latest screenshot.",
    parameters: Type.Object({
      x: Type.Optional(Type.Number({ description: "Viewport x coordinate in pixels from the latest screenshot." })),
      y: Type.Optional(Type.Number({ description: "Viewport y coordinate in pixels from the latest screenshot." })),
      selector: Type.Optional(Type.String({ description: "CSS selector to click instead of coordinates." })),
      text: Type.Optional(Type.String({ description: "Visible text to click instead of coordinates/selector." })),
      exact: Type.Optional(Type.Boolean({ description: "When using text, require exact text match." })),
      button: Type.Optional(stringEnum(MouseButton, { description: "Mouse button. Defaults to left." })),
      clicks: Type.Optional(Type.Number({ description: "Click count, 1-3. Defaults to 1." })),
    }),
    async execute(_id, params, signal, onUpdate) {
      if (signal?.aborted) throw new Error("browser_click cancelled");
      if ((params.x === undefined || params.y === undefined) && !params.selector && !params.text) throw new Error("Provide x/y, selector, or text.");
      onUpdate?.({ content: [{ type: "text", text: "Clicking browser target..." }] });
      await pace();
      const result = await getBrowser().click(params as any);
      return { content: [{ type: "text", text: `Clicked at ${Math.round(result.x)},${Math.round(result.y)}\n${result.title || "(untitled)"}\n${result.url}` }], details: result };
    },
  });

  pi.registerTool({
    name: "browser_type",
    label: "Browser Type",
    description: "Type text into the focused editable web-page element, or first focus a CSS selector. Fails if no editable element is focused. Supports clearing the field first. For URL navigation, use browser_open instead of typing into the browser address bar.",
    parameters: Type.Object({
      text: Type.String({ description: "Text to type." }),
      selector: Type.Optional(Type.String({ description: "Optional CSS selector to focus before typing." })),
      clear: Type.Optional(Type.Boolean({ description: "Select all and clear current field contents before typing." })),
      delayMs: Type.Optional(Type.Number({ description: "Per-character typing delay in ms. Defaults to a human-like random delay." })),
    }),
    async execute(_id, params, signal, onUpdate) {
      if (signal?.aborted) throw new Error("browser_type cancelled");
      onUpdate?.({ content: [{ type: "text", text: `Typing ${String(params.text).length} characters...` }] });
      await pace();
      const result = await getBrowser().type(params as any);
      return { content: [{ type: "text", text: `Typed ${result.typedCharacters} characters.\n${result.title || "(untitled)"}\n${result.url}` }], details: result };
    },
  });

  pi.registerTool({
    name: "browser_upload",
    label: "Browser Upload",
    description: "Upload one or more explicitly approved local files through the visible browser, using an input[type=file] selector or a visible upload control that opens a file chooser.",
    parameters: Type.Object({
      path: Type.Optional(Type.String({ description: "Single local file path to upload. Use an absolute path when possible." })),
      paths: Type.Optional(Type.Array(Type.String({ description: "Local file path to upload." }), { description: "Multiple local file paths to upload." })),
      selector: Type.Optional(Type.String({ description: "CSS selector for input[type=file] or an upload control that opens a file chooser. Defaults to first input[type=file]." })),
      text: Type.Optional(Type.String({ description: "Visible text for an upload control that opens a file chooser, e.g. Upload Resume." })),
      exact: Type.Optional(Type.Boolean({ description: "When using text, require exact text match." })),
      timeoutMs: Type.Optional(Type.Number({ description: "Timeout for locating/uploading, default 10000, max 60000." })),
    }),
    async execute(_id, params, signal, onUpdate) {
      if (signal?.aborted) throw new Error("browser_upload cancelled");
      const count = [params.path, ...(params.paths ?? [])].filter(Boolean).length;
      onUpdate?.({ content: [{ type: "text", text: `Uploading ${count} file${count === 1 ? "" : "s"} through browser...` }] });
      await pace();
      const result = await getBrowser().upload(params as any);
      return {
        content: [{ type: "text", text: `Uploaded ${result.files.length} file${result.files.length === 1 ? "" : "s"} via ${result.method}.\n${result.title || "(untitled)"}\n${result.url}` }],
        details: result,
      };
    },
  });

  pi.registerTool({
    name: "browser_key",
    label: "Browser Key",
    description: "Press a keyboard key or shortcut in the active web page, e.g. Enter, Escape, Tab, ArrowDown, Control+A. Meta+T/Control+T and Meta+W/Control+W are emulated as tab open/close actions. For URL navigation, use browser_open instead of address-bar shortcuts.",
    parameters: Type.Object({ key: Type.String({ description: "Playwright key name or shortcut, e.g. Enter, Escape, Tab, ArrowDown, Control+A." }) }),
    async execute(_id, params, signal) {
      if (signal?.aborted) throw new Error("browser_key cancelled");
      await pace();
      const result = await getBrowser().key(String(params.key));
      return { content: [{ type: "text", text: `Pressed ${params.key}.\n${result.title || "(untitled)"}\n${result.url}` }], details: result };
    },
  });

  pi.registerTool({
    name: "browser_scroll",
    label: "Browser Scroll",
    description: "Scroll the current browser page with mouse-wheel-like movement.",
    parameters: Type.Object({
      direction: Type.Optional(stringEnum(ScrollDirection, { description: "Scroll direction. Defaults to down." })),
      amount: Type.Optional(Type.Number({ description: "Scroll amount in pixels. Defaults to 700; max 3000." })),
      x: Type.Optional(Type.Number({ description: "Optional x coordinate to move mouse to before scrolling." })),
      y: Type.Optional(Type.Number({ description: "Optional y coordinate to move mouse to before scrolling." })),
    }),
    async execute(_id, params, signal) {
      if (signal?.aborted) throw new Error("browser_scroll cancelled");
      await pace();
      const result = await getBrowser().scroll(params as any);
      return { content: [{ type: "text", text: `Scrolled ${result.direction} ${result.amount}px.\n${result.title || "(untitled)"}\n${result.url}` }], details: result };
    },
  });

  pi.registerTool({
    name: "browser_wait",
    label: "Browser Wait",
    description: "Wait for time, visible selector/text, or page load state in the browser.",
    parameters: Type.Object({
      ms: Type.Optional(Type.Number({ description: "Milliseconds to wait, max 60000." })),
      selector: Type.Optional(Type.String({ description: "CSS selector that must become visible." })),
      text: Type.Optional(Type.String({ description: "Visible text that must appear." })),
      loadState: Type.Optional(stringEnum(LoadState, { description: "Page load state to wait for." })),
      timeoutMs: Type.Optional(Type.Number({ description: "Timeout for selector/text/load waits. Defaults to 10000; max 60000." })),
    }),
    async execute(_id, params, signal) {
      if (signal?.aborted) throw new Error("browser_wait cancelled");
      const result = await getBrowser().wait(params as any);
      return { content: [{ type: "text", text: `Browser wait complete.\n${result.title || "(untitled)"}\n${result.url}` }], details: result };
    },
  });

  pi.registerTool({
    name: "browser_extract",
    label: "Browser Extract",
    description: "Extract readable text and optional links from the current browser page or a CSS selector. Safer than arbitrary page evaluation.",
    parameters: Type.Object({
      selector: Type.Optional(Type.String({ description: "Optional CSS selector whose text should be extracted." })),
      maxText: Type.Optional(Type.Number({ description: "Maximum text characters, 500-50000. Defaults to 12000." })),
      includeLinks: Type.Optional(Type.Boolean({ description: "Include up to 120 page links." })),
    }),
    async execute(_id, params, signal) {
      if (signal?.aborted) throw new Error("browser_extract cancelled");
      const result = await getBrowser().extract(params as any);
      return { content: [{ type: "text", text: compactJson(result) }], details: result };
    },
  });

  pi.registerTool({
    name: "browser_tabs",
    label: "Browser Tabs",
    description: "List, switch, or close tabs in the visible browser.",
    parameters: Type.Object({
      action: stringEnum(TabsAction, { description: "Tab action: list, switch, or close." }),
      index: Type.Optional(Type.Number({ description: "Tab index for switch/close." })),
    }),
    async execute(_id, params, signal) {
      if (signal?.aborted) throw new Error("browser_tabs cancelled");
      const result = await getBrowser().tabs(params.action as any, params.index);
      return { content: [{ type: "text", text: compactJson(result) }], details: result };
    },
  });

  pi.registerTool({
    name: "browser_close",
    label: "Browser Close",
    description: "Close the active tab, or release this tool handle while keeping the persistent Chrome bridge alive.",
    parameters: Type.Object({ all: Type.Optional(Type.Boolean({ description: "Close entire browser. Defaults to true. false closes active tab only." })) }),
    async execute(_id, params, signal) {
      if (signal?.aborted) throw new Error("browser_close cancelled");
      const browser = getBrowser();
      await browser.close(params.all !== false);
      const closedAll = params.all !== false;
      return {
        content: [{ type: "text", text: params.all === false ? "Closed active browser tab." : "Browser bridge remains connected." }],
        details: { closedAll, bridgeKeptAlive: closedAll },
      };
    },
  });
}
