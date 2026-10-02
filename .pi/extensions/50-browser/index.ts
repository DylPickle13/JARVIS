import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

import { DaemonBrowserManager } from "./daemon-browser-manager";
import { registerBrowserTools } from "./tools";

export default function registerBrowser(pi: ExtensionAPI) {
  const browsers = new Map<string, DaemonBrowserManager>();
  const key = (ctx: ExtensionContext) => ctx.sessionManager.getSessionId();
  const getBrowser = (ctx: ExtensionContext): DaemonBrowserManager => {
    const id = key(ctx);
    let browser = browsers.get(id);
    if (!browser) {
      browser = new DaemonBrowserManager();
      browsers.set(id, browser);
    }
    return browser;
  };

  registerBrowserTools(pi, getBrowser);

  const releaseAll = async () => {
    const handles = [...browsers.values()];
    browsers.clear();
    await Promise.allSettled(handles.map(browser => browser.close(true)));
  };
  // New/resumed/forked sessions must not inherit another conversation's target.
  pi.on("session_start", releaseAll);
  // Releasing leases never closes Chrome, regardless of KEEP_OPEN_ON_SHUTDOWN.
  pi.on("session_shutdown", releaseAll);

  pi.registerCommand("browser", {
    description: "Visible Chrome browser helper: /browser status | open <url> | close | profile",
    handler: async (args, ctx) => {
      const [action = "status", ...rest] = args.trim().split(/\s+/).filter(Boolean);
      if (action === "status") {
        const status = await getBrowser(ctx).status();
        ctx.ui.notify(JSON.stringify(status, null, 2), "info");
        return;
      }
      if (action === "open") {
        const url = rest.join(" ").trim() || "about:blank";
        const result = await getBrowser(ctx).open(url);
        ctx.ui.notify(`Opened ${result.title || result.url}`, "success");
        return;
      }
      if (action === "close") {
        await browsers.get(key(ctx))?.close(true);
        browsers.delete(key(ctx));
        ctx.ui.notify("Released this session's tab leases. Shared tabs and browser remain open.", "success");
        return;
      }
      if (action === "profile") {
        const current = getBrowser(ctx);
        const profile = `${current.profileDir}${current.profileDirectory ? ` (${current.profileDirectory})` : ""}`;
        ctx.ui.notify(`Browser daemon: ${current.daemonUrl}\nProfile: ${profile}`, "info");
        return;
      }
      ctx.ui.notify("Usage: /browser status | open <url> | close | profile", "warning");
    },
  });
}
