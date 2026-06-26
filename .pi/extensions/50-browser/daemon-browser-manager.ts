import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

type BrowserLaunchMode = "managed" | "cdp";

export type BrowserStatus = {
  launchMode: BrowserLaunchMode;
  running: boolean;
  connected: boolean;
  port?: number;
  profileDir: string;
  profileDirectory?: string;
  cdpUrl?: string;
  daemon?: {
    host: string;
    port: number;
    tokenFile: string;
    connectedAt: string | null;
    lastError: string;
    connecting: boolean;
  };
  activeIndex: number;
  pages: Array<{ index: number; url: string; title: string }>;
};

export type ScreenshotResult = {
  data: string;
  mimeType: "image/png";
  width?: number;
  height?: number;
  url: string;
  title: string;
};

let projectEnvCache: Record<string, string> | null = null;

function projectEnv(): Record<string, string> {
  if (projectEnvCache) return projectEnvCache;
  projectEnvCache = {};
  const envPath = join(process.cwd(), ".env");
  if (!existsSync(envPath)) return projectEnvCache;
  for (const line of readFileSync(envPath, "utf8").split(/\r?\n/)) {
    const match = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/);
    if (!match || match[1].startsWith("#")) continue;
    let value = match[2];
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) value = value.slice(1, -1);
    projectEnvCache[match[1]] = value;
  }
  return projectEnvCache;
}

function envValue(name: string, fallback?: string): string | undefined {
  return process.env[name]?.trim() || projectEnv()[name]?.trim() || fallback;
}

function defaultProfileDir(): string {
  return envValue("PI_BROWSER_PROFILE_DIR", join(homedir(), "Library", "Application Support", "Google", "Chrome"))!;
}

function defaultProfileDirectory(): string | undefined {
  return envValue("PI_BROWSER_PROFILE_DIRECTORY");
}

function defaultDaemonUrl(): string {
  return envValue("PI_BROWSER_DAEMON_URL", "http://127.0.0.1:17322")!;
}

function defaultTokenFile(): string {
  return envValue("PI_BROWSER_DAEMON_TOKEN_FILE", join(homedir(), ".jarvis", "chrome-bridge.token"))!;
}

export class DaemonBrowserManager {
  readonly profileDir: string;
  readonly profileDirectory?: string;
  readonly cdpUrl: string;
  readonly daemonUrl: string;
  private readonly tokenFile: string;

  constructor(daemonUrl = defaultDaemonUrl(), tokenFile = defaultTokenFile(), profileDir = defaultProfileDir(), profileDirectory = defaultProfileDirectory()) {
    this.daemonUrl = daemonUrl.replace(/\/+$/, "");
    this.tokenFile = tokenFile;
    this.profileDir = profileDir;
    this.profileDirectory = profileDirectory;
    this.cdpUrl = this.daemonUrl;
  }

  get currentLaunchMode(): BrowserLaunchMode {
    return "cdp";
  }

  private token(): string {
    try {
      return readFileSync(this.tokenFile, "utf8").trim();
    } catch (error) {
      throw new Error(`Chrome bridge token not found at ${this.tokenFile}. Start the daemon first with: npm --prefix .pi/extensions/50-browser run daemon`, { cause: error });
    }
  }

  private async request<T>(path: string, options: { method?: "GET" | "POST"; body?: unknown } = {}): Promise<T> {
    const response = await fetch(`${this.daemonUrl}${path}`, {
      method: options.method ?? "GET",
      headers: {
        authorization: `Bearer ${this.token()}`,
        ...(options.body === undefined ? {} : { "content-type": "application/json" }),
      },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    }).catch((error) => {
      throw new Error(`Chrome bridge daemon is not reachable at ${this.daemonUrl}. Start it with: npm --prefix .pi/extensions/50-browser run daemon`, { cause: error });
    });

    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload?.ok === false) throw new Error(payload?.error || `Chrome bridge request failed: HTTP ${response.status}`);
    return payload.result as T;
  }

  async open(url: string, newTab = false): Promise<{ url: string; title: string; index: number }> {
    return this.request("/open", { method: "POST", body: { url, newTab } });
  }

  async screenshot(options: { fullPage?: boolean; selector?: string; attachImage?: boolean }): Promise<ScreenshotResult> {
    return this.request("/screenshot", { method: "POST", body: options });
  }

  async extract(params: { selector?: string; maxText?: number; includeLinks?: boolean }): Promise<{ url: string; title: string; text: string; links?: Array<{ text: string; href: string }> }> {
    return this.request("/extract", { method: "POST", body: params });
  }

  async tabs(action: "list" | "switch" | "close", index?: number): Promise<BrowserStatus> {
    return this.request("/tabs", { method: "POST", body: { action, index } });
  }

  async status(): Promise<BrowserStatus> {
    return this.request("/status");
  }

  async close(all = true): Promise<void> {
    await this.request("/close", { method: "POST", body: { all } });
  }

  async click(params: { x?: number; y?: number; selector?: string; text?: string; exact?: boolean; button?: "left" | "right" | "middle"; clicks?: number }): Promise<{ x: number; y: number; url: string; title: string }> {
    return this.request("/click", { method: "POST", body: params });
  }

  async type(params: { selector?: string; text: string; clear?: boolean; delayMs?: number }): Promise<{ url: string; title: string; typedCharacters: number }> {
    return this.request("/type", { method: "POST", body: params });
  }

  async upload(params: { selector?: string; text?: string; exact?: boolean; path?: string; paths?: string[]; timeoutMs?: number }): Promise<{ url: string; title: string; files: string[]; method: "input" | "filechooser" }> {
    return this.request("/upload", { method: "POST", body: params });
  }

  async key(key: string): Promise<{ url: string; title: string }> {
    return this.request("/key", { method: "POST", body: { key } });
  }

  async scroll(params: { direction?: "up" | "down" | "left" | "right"; amount?: number; x?: number; y?: number }): Promise<{ url: string; title: string; amount: number; direction: string }> {
    return this.request("/scroll", { method: "POST", body: params });
  }

  async wait(params: { ms?: number; selector?: string; text?: string; loadState?: "load" | "domcontentloaded" | "networkidle"; timeoutMs?: number }): Promise<{ url: string; title: string }> {
    return this.request("/wait", { method: "POST", body: params });
  }
}
