import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

import { BrowserManager } from "./browser-manager";
import { registerBrowserTools } from "./tools";

export default function registerBrowser(pi: ExtensionAPI) {
  let browser: BrowserManager | null = null;

  const getBrowser = () => {
    if (!browser) browser = new BrowserManager();
    return browser;
  };

  registerBrowserTools(pi, getBrowser);

  pi.on("session_shutdown", async () => {
    if (process.env.PI_BROWSER_KEEP_OPEN_ON_SHUTDOWN === "1") return;
    await browser?.close(true).catch(() => undefined);
    browser = null;
  });

  pi.registerCommand("browser", {
    description: "Visible Chrome browser helper: /browser status | open <url> | close | profile",
    handler: async (args, ctx) => {
      const [action = "status", ...rest] = args.trim().split(/\s+/).filter(Boolean);
      if (action === "status") {
        const status = await getBrowser().status();
        ctx.ui.notify(JSON.stringify(status, null, 2), "info");
        return;
      }
      if (action === "open") {
        const url = rest.join(" ").trim() || "about:blank";
        const result = await getBrowser().open(url);
        ctx.ui.notify(`Opened ${result.title || result.url}`, "success");
        return;
      }
      if (action === "close") {
        await browser?.close(true);
        browser = null;
        ctx.ui.notify("Closed visible browser.", "success");
        return;
      }
      if (action === "profile") {
        const profileDir = getBrowser().profileDir;
        ctx.ui.notify(`Browser profile: ${profileDir}`, "info");
        return;
      }
      ctx.ui.notify("Usage: /browser status | open <url> | close | profile", "warning");
    },
  });
}
