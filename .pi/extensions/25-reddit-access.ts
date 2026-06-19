import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { StringEnum } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
  DEFAULT_MAX_BYTES,
  DEFAULT_MAX_LINES,
  formatSize,
  truncateHead,
  withFileMutationQueue,
  type TruncationResult,
} from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "typebox";

import {
  fetchRedditSubredditPage,
  fetchRedditThread,
  isRedditSupportedUrl,
  isRedditThreadUrl,
  subredditPageToJsonObject,
  subredditPageToMarkdown,
  threadToJsonObject,
  threadToMarkdown,
  type NormalizedSubredditPage,
  type NormalizedThread,
} from "./lib/reddit-access.ts";

const FORMATS = ["markdown", "json"] as const;
const DEFAULT_MAX_POSTS = 25;
const DEFAULT_TIMEOUT_SEC = 75;
const MAX_TIMEOUT_SEC = 300;

interface RedditRunOptions {
  format?: "markdown" | "json";
  maxPosts?: number;
  timeoutSec?: number;
}

interface RedditRunDetails {
  ok: boolean;
  url: string;
  format: "markdown" | "json";
  implementation: "pi-extension-ts";
  kind?: "thread" | "subreddit";
  fetchedVia?: string;
  sourceUrl?: string;
  title?: string;
  subreddit?: string;
  sort?: string;
  time?: string;
  author?: string | null;
  reportedComments?: number | null;
  extractedComments?: number | null;
  postCount?: number | null;
  after?: string | null;
  fullOutputPath?: string;
  truncation?: TruncationResult;
  error?: string;
}

function clampInt(value: unknown, fallback: number, min: number, max: number): number {
  if (typeof value !== "number" || !Number.isFinite(value)) return fallback;
  return Math.max(min, Math.min(max, Math.floor(value)));
}

function normalizeFormat(value: unknown): "markdown" | "json" {
  return value === "json" ? "json" : "markdown";
}

function combineSignals(signal: AbortSignal | undefined, timeoutMs: number): AbortSignal {
  const timeoutSignal = AbortSignal.timeout(timeoutMs);
  if (!signal) return timeoutSignal;
  if (typeof AbortSignal.any === "function") return AbortSignal.any([signal, timeoutSignal]);

  const controller = new AbortController();
  const abort = () => controller.abort();
  signal.addEventListener("abort", abort, { once: true });
  timeoutSignal.addEventListener("abort", abort, { once: true });
  return controller.signal;
}

function fetchContentRedditUrls(input: unknown): string[] {
  if (!input || typeof input !== "object" || Array.isArray(input)) return [];
  const params = input as { url?: unknown; urls?: unknown; prompt?: unknown; timestamp?: unknown; frames?: unknown };
  if (params.prompt !== undefined || params.timestamp !== undefined || params.frames !== undefined) return [];

  if (typeof params.url === "string" && isRedditSupportedUrl(params.url)) return [params.url];
  if (Array.isArray(params.urls) && params.urls.length > 0 && params.urls.every((url) => typeof url === "string" && isRedditSupportedUrl(url))) {
    return params.urls as string[];
  }
  return [];
}

function detailsFromThread(thread: NormalizedThread, url: string, format: "markdown" | "json"): RedditRunDetails {
  return {
    ok: true,
    url,
    format,
    implementation: "pi-extension-ts",
    kind: "thread",
    fetchedVia: thread.fetchedVia,
    sourceUrl: thread.sourceUrl,
    title: thread.post.title,
    subreddit: thread.post.subreddit,
    author: thread.post.author,
    reportedComments: thread.post.commentCount ?? null,
    extractedComments: thread.commentCountExtracted,
  };
}

function detailsFromSubredditPage(page: NormalizedSubredditPage, url: string, format: "markdown" | "json"): RedditRunDetails {
  return {
    ok: true,
    url,
    format,
    implementation: "pi-extension-ts",
    kind: "subreddit",
    fetchedVia: page.fetchedVia,
    sourceUrl: page.sourceUrl,
    title: `r/${page.subreddit} — ${page.sort}${page.time ? ` (${page.time})` : ""}`,
    subreddit: page.subreddit,
    sort: page.sort,
    time: page.time,
    postCount: page.posts.length,
    after: page.after ?? null,
  };
}

async function truncateForTool(text: string): Promise<{ text: string; fullOutputPath?: string; truncation?: TruncationResult }> {
  const truncation = truncateHead(text, {
    maxBytes: DEFAULT_MAX_BYTES,
    maxLines: DEFAULT_MAX_LINES,
  });

  if (!truncation.truncated) return { text };

  const tempDir = await mkdtemp(join(tmpdir(), "pi-reddit-"));
  const fullOutputPath = join(tempDir, "reddit-output.txt");
  await withFileMutationQueue(fullOutputPath, async () => {
    await writeFile(fullOutputPath, text, "utf8");
  });

  const notice = [
    "",
    `[Output truncated: showing ${truncation.outputLines} of ${truncation.totalLines} lines`,
    `(${formatSize(truncation.outputBytes)} of ${formatSize(truncation.totalBytes)}).`,
    `Full output saved to: ${fullOutputPath}]`,
  ].join(" ");

  return {
    text: `${truncation.content}${notice}`,
    fullOutputPath,
    truncation,
  };
}

async function runRedditThread(
  url: string,
  options: RedditRunOptions,
  signal?: AbortSignal,
): Promise<{ content: Array<{ type: "text"; text: string }>; details: RedditRunDetails }> {
  const format = normalizeFormat(options.format);
  const maxPosts = clampInt(options.maxPosts, DEFAULT_MAX_POSTS, 1, 100);
  const timeoutSec = clampInt(options.timeoutSec, DEFAULT_TIMEOUT_SEC, 5, MAX_TIMEOUT_SEC);
  const combinedSignal = combineSignals(signal, timeoutSec * 1000);

  if (isRedditThreadUrl(url)) {
    const thread = await fetchRedditThread(url, { signal: combinedSignal });
    const raw = format === "json" ? `${JSON.stringify(threadToJsonObject(thread), null, 2)}\n` : threadToMarkdown(thread);
    if (!raw.trim()) throw new Error("Reddit extraction returned no output");

    const truncated = await truncateForTool(raw);
    return {
      content: [{ type: "text", text: truncated.text }],
      details: {
        ...detailsFromThread(thread, url, format),
        fullOutputPath: truncated.fullOutputPath,
        truncation: truncated.truncation,
      },
    };
  }

  const page = await fetchRedditSubredditPage(url, { signal: combinedSignal, limit: maxPosts });
  const raw = format === "json" ? `${JSON.stringify(subredditPageToJsonObject(page), null, 2)}\n` : subredditPageToMarkdown(page, maxPosts);
  if (!raw.trim()) throw new Error("Reddit extraction returned no output");

  const truncated = await truncateForTool(raw);
  return {
    content: [{ type: "text", text: truncated.text }],
    details: {
      ...detailsFromSubredditPage(page, url, format),
      fullOutputPath: truncated.fullOutputPath,
      truncation: truncated.truncation,
    },
  };
}

export default function registerRedditAccess(pi: ExtensionAPI) {
  pi.registerTool({
    name: "reddit_thread",
    label: "Reddit",
    description:
      "Fetch and parse a public Reddit comments thread or subreddit front page/listing without PRAW, OAuth, tokens, or any project-folder script. Native TypeScript Pi extension; tries Reddit public JSON first, then Redlib HTML fallback.",
    promptSnippet: "Fetch public Reddit thread comments or subreddit front-page listings without PRAW/OAuth; uses public JSON then Redlib fallback.",
    promptGuidelines: [
      "Use reddit_thread for Reddit post/comment threads and subreddit front-page/listing URLs instead of generic web_search/fetch_content when the user provides a Reddit URL.",
      "The reddit_thread tool is a standalone Pi extension and does not use PRAW, OAuth, Reddit credentials, or any external project-folder script.",
      "For subreddit URLs like https://www.reddit.com/r/subreddit/ or /new/top/rising, reddit_thread returns the listing posts; for comments URLs, it returns the post and comments.",
    ],
    parameters: Type.Object({
      url: Type.String({ description: "Reddit comments URL, subreddit listing URL, r/subreddit path, or bare post id. Examples: https://www.reddit.com/r/sub/comments/id/title/, https://redd.it/id, https://www.reddit.com/r/subreddit/" }),
      maxPosts: Type.Optional(Type.Integer({ minimum: 1, maximum: 100, description: "Max posts to fetch/show for subreddit listing URLs. Ignored for comments threads. Default 25." })),
      format: Type.Optional(StringEnum(FORMATS, { description: "Output format. Default markdown." })),
      timeoutSec: Type.Optional(Type.Integer({ minimum: 5, maximum: MAX_TIMEOUT_SEC, description: "Timeout in seconds. Default 75." })),
    }),
    async execute(_toolCallId, params, signal) {
      return runRedditThread(params.url, params, signal);
    },
    renderCall(args, theme) {
      const url = typeof args.url === "string" ? args.url : "";
      const display = url.length > 72 ? `${url.slice(0, 69)}...` : url;
      return new Text(theme.fg("toolTitle", theme.bold("reddit_thread ")) + theme.fg(url ? "accent" : "error", display || "(no URL)"), 0, 0);
    },
    renderResult(result, { expanded, isPartial }, theme) {
      const details = result.details as RedditRunDetails | undefined;
      if (isPartial) return new Text(theme.fg("accent", "fetching Reddit..."), 0, 0);
      if (details?.error || details?.ok === false) return new Text(theme.fg("error", details.error ?? "Reddit fetch failed"), 0, 0);

      const title = details?.title || (details?.kind === "subreddit" ? "Reddit subreddit" : "Reddit thread");
      let status = theme.fg("success", title);
      if (details?.kind === "subreddit") {
        status += theme.fg("muted", ` (${details.postCount ?? 0} posts)`);
      } else if (details?.extractedComments !== undefined && details?.extractedComments !== null) {
        status += theme.fg("muted", ` (${details.extractedComments} comments)`);
      }
      if (details?.fetchedVia) status += theme.fg("dim", ` via ${details.fetchedVia}`);
      if (details?.truncation?.truncated) status += theme.fg("warning", " [truncated]");
      if (!expanded) return new Text(status, 0, 0);

      const textContent = result.content.find((item) => item.type === "text")?.text ?? "";
      const preview = textContent.length > 900 ? `${textContent.slice(0, 900)}...` : textContent;
      return new Text(`${status}\n${theme.fg("dim", preview)}`, 0, 0);
    },
  });

  pi.on("tool_result", async (event, ctx) => {
    if (event.toolName !== "fetch_content") return undefined;
    const urls = fetchContentRedditUrls(event.input);
    if (urls.length === 0) return undefined;

    // If web-access already produced Reddit markdown, do not override it. This
    // keeps compatibility with any future native pi-web-access implementation.
    const existingText = event.content?.find((item: any) => item?.type === "text")?.text ?? "";
    if (
      urls.length === 1 &&
      typeof existingText === "string" &&
      /^# .+\n\n- Source: https:\/\/(www\.)?reddit\.com\//m.test(existingText) &&
      existingText.includes("- Fetched via: `")
    ) {
      return undefined;
    }

    const rendered: string[] = [];
    const replacements: RedditRunDetails[] = [];
    const errors: Array<{ url: string; error: string }> = [];

    for (const url of urls) {
      try {
        const replacement = await runRedditThread(
          url,
          { format: "markdown", maxPosts: DEFAULT_MAX_POSTS, timeoutSec: DEFAULT_TIMEOUT_SEC },
          ctx.signal,
        );
        const text = replacement.content.find((item) => item.type === "text")?.text ?? "";
        rendered.push(urls.length > 1 ? `<!-- reddit_thread: ${url} -->\n${text}` : text);
        replacements.push(replacement.details);
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        errors.push({ url, error: message });
        rendered.push(`## Reddit extraction failed\n\n- Source: ${url}\n- Error: ${message}`);
      }
    }

    const truncated = await truncateForTool(rendered.join("\n\n---\n\n"));

    if (urls.length === 1 && replacements.length === 1 && errors.length === 0) {
      return {
        content: [{ type: "text", text: truncated.text }],
        details: {
          ...replacements[0],
          fullOutputPath: truncated.fullOutputPath ?? replacements[0].fullOutputPath,
          truncation: truncated.truncation ?? replacements[0].truncation,
          replacedFetchContent: true,
          originalFetchContentDetails: event.details,
        },
        isError: false,
      };
    }

    return {
      content: [{ type: "text", text: truncated.text }],
      details: {
        ok: errors.length === 0,
        urls,
        format: "markdown",
        implementation: "pi-extension-ts",
        replacedFetchContent: true,
        originalFetchContentDetails: event.details,
        replacements,
        errors,
        fullOutputPath: truncated.fullOutputPath,
        truncation: truncated.truncation,
      },
      isError: errors.length > 0,
    };
  });
}
