import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { existsSync, mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";
import { setTimeout as sleep } from "node:timers/promises";
import { createServer } from "node:net";

import { chromium, type Browser, type BrowserContext, type Locator, type Page } from "playwright-core";

import { STEALTH_INIT_SCRIPT } from "./stealth-patches";

export type BrowserStatus = {
  running: boolean;
  connected: boolean;
  port?: number;
  profileDir: string;
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

const DEFAULT_CHROME_PATHS = [
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",
  "/Applications/Chromium.app/Contents/MacOS/Chromium",
  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium-browser",
  "/usr/bin/chromium",
];

function chromePath(): string {
  const configured = process.env.PI_BROWSER_CHROME_PATH?.trim();
  if (configured && existsSync(configured)) return configured;
  const found = DEFAULT_CHROME_PATHS.find((path) => existsSync(path));
  if (!found) throw new Error(`Chrome executable not found. Set PI_BROWSER_CHROME_PATH to your Chrome/Chromium binary.`);
  return found;
}

async function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : undefined;
      server.close(() => (port ? resolve(port) : reject(new Error("Could not allocate browser debug port"))));
    });
  });
}

function randomInt(min: number, max: number): number {
  return Math.floor(min + Math.random() * (max - min + 1));
}

function defaultProfileDir(): string {
  return process.env.PI_BROWSER_PROFILE_DIR?.trim() || join(homedir(), ".pi", "agent", "browser-profile");
}

async function waitForCdp(port: number, timeoutMs: number): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let lastError: unknown;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/version`);
      if (response.ok) return;
    } catch (error) {
      lastError = error;
    }
    await sleep(150);
  }
  throw new Error(`Timed out waiting for Chrome CDP on port ${port}${lastError instanceof Error ? `: ${lastError.message}` : ""}`);
}

async function titleOf(page: Page): Promise<string> {
  try {
    return await page.title();
  } catch {
    return "";
  }
}

async function viewportSize(page: Page): Promise<{ width?: number; height?: number }> {
  try {
    const size = page.viewportSize();
    if (size) return size;
    const value = await page.evaluate(() => ({ width: window.innerWidth, height: window.innerHeight }));
    return value;
  } catch {
    return {};
  }
}

async function firstVisibleLocator(locator: Locator, limit = 50): Promise<Locator | null> {
  const count = Math.min(await locator.count().catch(() => 0), limit);
  for (let i = 0; i < count; i++) {
    const candidate = locator.nth(i);
    const visible = await candidate.isVisible({ timeout: 250 }).catch(() => false);
    if (!visible) continue;
    const box = await candidate.boundingBox({ timeout: 500 }).catch(() => null);
    if (box && box.width > 0 && box.height > 0) return candidate;
  }
  return null;
}

async function locatorFor(page: Page, params: { selector?: string; text?: string; exact?: boolean }): Promise<Locator> {
  if (params.selector) {
    const locator = page.locator(params.selector);
    return (await firstVisibleLocator(locator)) ?? locator.first();
  }
  if (params.text) {
    const exact = Boolean(params.exact);
    const candidates: Locator[] = [
      page.getByRole("link", { name: params.text, exact }),
      page.getByRole("button", { name: params.text, exact }),
      page.getByLabel(params.text, { exact }),
      page.getByPlaceholder(params.text, { exact }),
      page.getByText(params.text, { exact }),
    ];
    for (const candidate of candidates) {
      const visible = await firstVisibleLocator(candidate);
      if (visible) return visible;
    }
    return page.getByText(params.text, { exact }).first();
  }
  throw new Error("selector or text is required");
}

async function locatorCenter(page: Page, locator: Locator): Promise<{ x: number; y: number }> {
  await locator.scrollIntoViewIfNeeded({ timeout: 5000 });
  await locator
    .evaluate((el) => el.scrollIntoView({ block: "center", inline: "center", behavior: "auto" }))
    .catch(() => undefined);
  await sleep(100);

  const box = await locator.boundingBox({ timeout: 5000 });
  if (!box) throw new Error("Target element has no visible bounding box");

  const size = await viewportSize(page);
  const viewport = {
    width: size.width ?? 0,
    height: size.height ?? 0,
  };
  if (!viewport.width || !viewport.height) throw new Error("Could not determine browser viewport size");

  const x = box.x + box.width / 2 + randomInt(-2, 2);
  const y = box.y + box.height / 2 + randomInt(-2, 2);
  assertViewportPoint(page, x, y, viewport);
  return { x, y };
}

function assertViewportPoint(page: Page, x: number, y: number, viewport?: { width?: number; height?: number }): void {
  const width = viewport?.width ?? page.viewportSize()?.width;
  const height = viewport?.height ?? page.viewportSize()?.height;
  if (!width || !height) return;
  if (x < 0 || y < 0 || x > width || y > height) {
    throw new Error(`Target resolved offscreen at ${Math.round(x)},${Math.round(y)} for viewport ${width}x${height}; click/type aborted`);
  }
}

async function activeElementEditable(page: Page): Promise<boolean> {
  return page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null;
    if (!el) return false;
    if (el.isContentEditable) return true;
    const tag = el.tagName.toLowerCase();
    if (tag === "textarea") return !(el as HTMLTextAreaElement).disabled && !(el as HTMLTextAreaElement).readOnly;
    if (tag === "input") {
      const input = el as HTMLInputElement;
      const nonTextTypes = new Set(["button", "checkbox", "color", "file", "hidden", "image", "radio", "range", "reset", "submit"]);
      return !input.disabled && !input.readOnly && !nonTextTypes.has((input.type || "text").toLowerCase());
    }
    if (tag === "select") return !(el as HTMLSelectElement).disabled;
    return false;
  });
}

export class BrowserManager {
  private browser: Browser | null = null;
  private context: BrowserContext | null = null;
  private chrome: ChildProcessWithoutNullStreams | null = null;
  private activePage: Page | null = null;
  private port: number | undefined;
  private launchPromise: Promise<void> | null = null;
  readonly profileDir: string;

  constructor(profileDir = defaultProfileDir()) {
    this.profileDir = profileDir;
  }

  async ensureStarted(): Promise<Page> {
    if (this.context && this.browser?.isConnected()) return this.page();
    if (!this.launchPromise) this.launchPromise = this.start();
    try {
      await this.launchPromise;
    } finally {
      this.launchPromise = null;
    }
    return this.page();
  }

  private async start(): Promise<void> {
    mkdirSync(this.profileDir, { recursive: true });
    const port = await freePort();
    this.port = port;
    const width = randomInt(1280, 1512);
    const height = randomInt(820, 982);
    const args = [
      `--remote-debugging-address=127.0.0.1`,
      `--remote-debugging-port=${port}`,
      `--user-data-dir=${this.profileDir}`,
      `--window-size=${width},${height}`,
      "--no-first-run",
      "--no-default-browser-check",
      "--disable-blink-features=AutomationControlled",
      "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
      "about:blank",
    ];

    this.chrome = spawn(chromePath(), args, {
      stdio: ["ignore", "pipe", "pipe"],
      detached: false,
      env: process.env,
    });

    this.chrome.on("exit", () => {
      this.browser = null;
      this.context = null;
      this.activePage = null;
      this.chrome = null;
    });

    await waitForCdp(port, 12000);
    this.browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`);
    this.context = this.browser.contexts()[0] ?? await this.browser.newContext();
    await this.context.addInitScript(STEALTH_INIT_SCRIPT);
    for (const page of this.context.pages()) await this.patchPage(page);
    this.context.on("page", (page) => {
      void this.patchPage(page);
      this.activePage = page;
    });
    this.activePage = this.context.pages()[0] ?? await this.context.newPage();
  }

  private async patchPage(page: Page): Promise<void> {
    try {
      await page.addInitScript(STEALTH_INIT_SCRIPT);
    } catch {}
  }

  private pages(): Page[] {
    return this.context?.pages().filter((page) => !page.isClosed()) ?? [];
  }

  async page(): Promise<Page> {
    if (!this.context) throw new Error("Browser is not started");
    if (this.activePage && !this.activePage.isClosed()) return this.activePage;
    this.activePage = this.pages()[0] ?? await this.context.newPage();
    return this.activePage;
  }

  async open(url: string, newTab = false): Promise<{ url: string; title: string; index: number }> {
    await this.ensureStarted();
    if (!/^https?:\/\//i.test(url) && !/^file:\/\//i.test(url) && !/^about:/i.test(url)) url = `https://${url}`;
    const page = newTab && this.context ? await this.context.newPage() : await this.page();
    this.activePage = page;
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 45000 });
    await page.waitForLoadState("networkidle", { timeout: 5000 }).catch(() => undefined);
    return { url: page.url(), title: await titleOf(page), index: this.pages().indexOf(page) };
  }

  async screenshot(options: { fullPage?: boolean; selector?: string; attachImage?: boolean }): Promise<ScreenshotResult> {
    const page = await this.ensureStarted();
    let buffer: Buffer;
    if (options.selector) {
      const locator = page.locator(options.selector).first();
      await locator.scrollIntoViewIfNeeded({ timeout: 5000 });
      buffer = await locator.screenshot({ type: "png", timeout: 15000 });
    } else {
      buffer = await page.screenshot({ fullPage: Boolean(options.fullPage), type: "png", timeout: 15000 });
    }
    const size = await viewportSize(page);
    return {
      data: buffer.toString("base64"),
      mimeType: "image/png",
      width: size.width,
      height: size.height,
      url: page.url(),
      title: await titleOf(page),
    };
  }

  async click(params: { x?: number; y?: number; selector?: string; text?: string; exact?: boolean; button?: "left" | "right" | "middle"; clicks?: number }): Promise<{ x: number; y: number; url: string; title: string }> {
    const page = await this.ensureStarted();
    const beforeUrl = page.url();
    let x = params.x;
    let y = params.y;
    if (x === undefined || y === undefined) {
      const locator = await locatorFor(page, params);
      const center = await locatorCenter(page, locator);
      x = center.x;
      y = center.y;
    } else {
      assertViewportPoint(page, x, y);
    }
    await this.humanMove(page, x, y);
    await sleep(randomInt(80, 260));
    await page.mouse.down({ button: params.button ?? "left" });
    await sleep(randomInt(45, 145));
    await page.mouse.up({ button: params.button ?? "left", clickCount: Math.max(1, Math.min(params.clicks ?? 1, 3)) });
    await this.settleAfterClick(page, beforeUrl);
    return { x, y, url: page.url(), title: await titleOf(page) };
  }

  async type(params: { selector?: string; text: string; clear?: boolean; delayMs?: number }): Promise<{ url: string; title: string; typedCharacters: number }> {
    const page = await this.ensureStarted();
    if (params.selector) {
      const locator = await locatorFor(page, { selector: params.selector });
      const center = await locatorCenter(page, locator);
      await this.humanMove(page, center.x, center.y);
      await locator.click({ timeout: 5000 });
    }

    if (!(await activeElementEditable(page))) {
      throw new Error("No editable element is focused. Provide a selector to browser_type, or click/focus an input before typing.");
    }

    if (params.clear) {
      const modifier = process.platform === "darwin" ? "Meta" : "Control";
      await page.keyboard.press(`${modifier}+A`);
      await page.keyboard.press("Backspace");
      await sleep(randomInt(80, 220));
    }
    await page.keyboard.type(params.text, { delay: params.delayMs ?? randomInt(35, 95) });
    return { url: page.url(), title: await titleOf(page), typedCharacters: params.text.length };
  }

  async upload(params: { selector?: string; text?: string; exact?: boolean; path?: string; paths?: string[]; timeoutMs?: number }): Promise<{ url: string; title: string; files: string[]; method: "input" | "filechooser" }> {
    const page = await this.ensureStarted();
    const requestedFiles = [...(params.paths ?? []), ...(params.path ? [params.path] : [])].map((filePath) => resolve(filePath));
    if (!requestedFiles.length) throw new Error("Provide path or paths for browser_upload.");
    for (const filePath of requestedFiles) {
      if (!existsSync(filePath)) throw new Error(`Upload file does not exist: ${filePath}`);
    }

    const timeout = Math.max(500, Math.min(params.timeoutMs ?? 10000, 60000));
    let method: "input" | "filechooser" = "input";

    if (params.selector || params.text) {
      const target = await locatorFor(page, { selector: params.selector, text: params.text, exact: params.exact });
      const isFileInput = await target
        .evaluate((el) => el instanceof HTMLInputElement && (el.type || "").toLowerCase() === "file")
        .catch(() => false);

      if (isFileInput) {
        await target.setInputFiles(requestedFiles, { timeout });
      } else {
        method = "filechooser";
        const chooserPromise = page.waitForEvent("filechooser", { timeout });
        await target.click({ timeout });
        const chooser = await chooserPromise;
        await chooser.setFiles(requestedFiles);
      }
    } else {
      const input = page.locator('input[type="file"]').first();
      const count = await page.locator('input[type="file"]').count().catch(() => 0);
      if (!count) throw new Error("No input[type=file] found. Provide selector/text for the upload control.");
      await input.setInputFiles(requestedFiles, { timeout });
    }

    await page.waitForLoadState("domcontentloaded", { timeout: 3000 }).catch(() => undefined);
    return { url: page.url(), title: await titleOf(page), files: requestedFiles, method };
  }

  async key(key: string): Promise<{ url: string; title: string }> {
    const page = await this.ensureStarted();
    const normalized = key.replace(/\s+/g, "").toLowerCase();

    // Playwright sends keyboard events to the web page, not always to Chrome's UI.
    // Emulate the most common browser-tab shortcuts so tool results match user expectations.
    if (normalized === "meta+t" || normalized === "control+t") {
      if (!this.context) throw new Error("Browser is not started");
      const newPage = await this.context.newPage();
      this.activePage = newPage;
      await newPage.goto("about:blank", { waitUntil: "domcontentloaded", timeout: 5000 }).catch(() => undefined);
      return { url: newPage.url(), title: await titleOf(newPage) };
    }
    if (normalized === "meta+w" || normalized === "control+w") {
      await page.close();
      this.activePage = this.pages()[0] ?? null;
      const nextPage = await this.page();
      return { url: nextPage.url(), title: await titleOf(nextPage) };
    }

    await page.keyboard.press(key);
    await page.waitForLoadState("domcontentloaded", { timeout: 3000 }).catch(() => undefined);
    return { url: page.url(), title: await titleOf(page) };
  }

  async scroll(params: { direction?: "up" | "down" | "left" | "right"; amount?: number; x?: number; y?: number }): Promise<{ url: string; title: string; amount: number; direction: string }> {
    const page = await this.ensureStarted();
    const direction = params.direction ?? "down";
    const amount = Math.max(50, Math.min(params.amount ?? 700, 3000));
    if (params.x !== undefined && params.y !== undefined) await this.humanMove(page, params.x, params.y);
    const dx = direction === "left" ? -amount : direction === "right" ? amount : 0;
    const dy = direction === "up" ? -amount : direction === "down" ? amount : 0;
    const chunks = randomInt(3, 6);
    for (let i = 0; i < chunks; i++) {
      await page.mouse.wheel(dx / chunks, dy / chunks);
      await sleep(randomInt(80, 220));
    }
    return { url: page.url(), title: await titleOf(page), amount, direction };
  }

  async wait(params: { ms?: number; selector?: string; text?: string; loadState?: "load" | "domcontentloaded" | "networkidle"; timeoutMs?: number }): Promise<{ url: string; title: string }> {
    const page = await this.ensureStarted();
    const timeout = Math.max(250, Math.min(params.timeoutMs ?? 10000, 60000));
    if (params.ms) await sleep(Math.max(0, Math.min(params.ms, 60000)));
    if (params.selector) await page.locator(params.selector).first().waitFor({ state: "visible", timeout });
    if (params.text) await page.getByText(params.text).first().waitFor({ state: "visible", timeout });
    if (params.loadState) await page.waitForLoadState(params.loadState, { timeout });
    return { url: page.url(), title: await titleOf(page) };
  }

  async extract(params: { selector?: string; maxText?: number; includeLinks?: boolean }): Promise<{ url: string; title: string; text: string; links?: Array<{ text: string; href: string }> }> {
    const page = await this.ensureStarted();
    const maxText = Math.max(500, Math.min(params.maxText ?? 12000, 50000));
    const text = params.selector
      ? await page.locator(params.selector).first().innerText({ timeout: 5000 })
      : await page.locator("body").innerText({ timeout: 5000 }).catch(() => "");
    const result: { url: string; title: string; text: string; links?: Array<{ text: string; href: string }> } = {
      url: page.url(),
      title: await titleOf(page),
      text: text.length > maxText ? `${text.slice(0, maxText)}\n… truncated …` : text,
    };
    if (params.includeLinks) {
      result.links = await page.evaluate(() => Array.from(document.querySelectorAll("a[href]")).slice(0, 120).map((a) => ({
        text: (a.textContent || "").trim().replace(/\s+/g, " ").slice(0, 160),
        href: (a as HTMLAnchorElement).href,
      })));
    }
    return result;
  }

  async tabs(action: "list" | "switch" | "close", index?: number): Promise<BrowserStatus> {
    await this.ensureStarted();
    const pages = this.pages();
    if (action === "switch") {
      if (index === undefined || !pages[index]) throw new Error(`Tab index ${index} is not open`);
      this.activePage = pages[index];
      await this.activePage.bringToFront();
    } else if (action === "close") {
      if (index === undefined || !pages[index]) throw new Error(`Tab index ${index} is not open`);
      await pages[index].close();
      this.activePage = this.pages()[0] ?? null;
    }
    return this.status();
  }

  async status(): Promise<BrowserStatus> {
    const pages = await Promise.all(this.pages().map(async (page, index) => ({ index, url: page.url(), title: await titleOf(page) })));
    return {
      running: Boolean(this.chrome),
      connected: Boolean(this.context && this.browser?.isConnected()),
      port: this.port,
      profileDir: this.profileDir,
      activeIndex: this.activePage ? this.pages().indexOf(this.activePage) : -1,
      pages,
    };
  }

  async close(all = true): Promise<void> {
    if (all) {
      await this.context?.close().catch(() => undefined);
      await this.browser?.close().catch(() => undefined);
      this.chrome?.kill("SIGTERM");
      this.browser = null;
      this.context = null;
      this.activePage = null;
      this.chrome = null;
      return;
    }
    const page = await this.page();
    await page.close();
    this.activePage = this.pages()[0] ?? null;
  }

  private async settleAfterClick(page: Page, beforeUrl: string): Promise<void> {
    const timeoutMs = Math.max(0, Math.min(Number(process.env.PI_BROWSER_CLICK_NAV_WAIT_MS || 1500), 10000));
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (page.isClosed()) return;
      if (page.url() !== beforeUrl) {
        await page.waitForLoadState("domcontentloaded", { timeout: 5000 }).catch(() => undefined);
        await page.waitForLoadState("networkidle", { timeout: 2000 }).catch(() => undefined);
        return;
      }
      await sleep(100);
    }
    await page.waitForLoadState("domcontentloaded", { timeout: 750 }).catch(() => undefined);
  }

  private async humanMove(page: Page, x: number, y: number): Promise<void> {
    const steps = randomInt(12, 28);
    await page.mouse.move(x + randomInt(-3, 3), y + randomInt(-3, 3), { steps });
  }
}
