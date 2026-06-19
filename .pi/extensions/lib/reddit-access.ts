export type RedditFetchMethod = "public-json" | "redlib";
export type RedditListingSort = "hot" | "new" | "top" | "rising" | "controversial";

export interface ThreadRef {
  originalUrl: string;
  postId: string;
  subreddit?: string;
  slug?: string;
}

export interface SubredditRef {
  originalUrl: string;
  subreddit: string;
  sort: RedditListingSort;
  time?: string;
  after?: string;
  before?: string;
}

export interface NormalizedPost {
  id: string;
  subreddit?: string;
  author?: string | null;
  title: string;
  body: string;
  score?: number | null;
  upvoteRatio?: number | null;
  createdUtc?: number | null;
  createdIso?: string | null;
  createdLabel?: string | null;
  createdTitle?: string | null;
  commentCount?: number | null;
  permalink: string;
  url?: string | null;
}

export interface NormalizedComment {
  id?: string | null;
  author?: string | null;
  body: string;
  score?: number | null;
  createdUtc?: number | null;
  createdIso?: string | null;
  createdLabel?: string | null;
  createdTitle?: string | null;
  permalink?: string | null;
  depth: number;
  replies: NormalizedComment[];
}

export interface NormalizedThread {
  fetchedAt: string;
  fetchedVia: "reddit_public_json" | "redlib_html";
  sourceUrl: string;
  post: NormalizedPost;
  comments: NormalizedComment[];
  commentCountExtracted: number;
  notes: string[];
}

export interface NormalizedListingPost {
  id: string;
  subreddit?: string;
  author?: string | null;
  title: string;
  body?: string;
  score?: number | null;
  upvoteRatio?: number | null;
  createdUtc?: number | null;
  createdIso?: string | null;
  createdLabel?: string | null;
  createdTitle?: string | null;
  commentCount?: number | null;
  permalink: string;
  url?: string | null;
  domain?: string | null;
  flair?: string | null;
  isSelf?: boolean | null;
  over18?: boolean | null;
  stickied?: boolean | null;
}

export interface NormalizedSubredditPage {
  fetchedAt: string;
  fetchedVia: "reddit_public_json" | "redlib_html";
  sourceUrl: string;
  subreddit: string;
  sort: RedditListingSort;
  time?: string;
  after?: string | null;
  before?: string | null;
  posts: NormalizedListingPost[];
  notes: string[];
}

interface FetchRedditThreadOptions {
  methods?: RedditFetchMethod[];
  signal?: AbortSignal;
}

interface FetchRedditSubredditPageOptions {
  methods?: RedditFetchMethod[];
  signal?: AbortSignal;
  limit?: number;
}

type DomChild = DomNode | string;

interface DomNode {
  tag: string;
  attrs: Record<string, string>;
  children: DomChild[];
  parent?: DomNode;
}

const DEFAULT_USER_AGENT = "JARVISRedditAccess/0.4 pi-extension (thread/listing reader; no PRAW/OAuth)";
const DEFAULT_REDLIB_INSTANCES = [
  "https://redlib.privadency.com",
  "https://redlib.privacyredirect.com",
  "https://redlib.perennialte.ch",
];
const LISTING_SORTS: readonly RedditListingSort[] = ["hot", "new", "top", "rising", "controversial"];
const LISTING_SORT_SET = new Set<string>(LISTING_SORTS);
const REQUEST_TIMEOUT_MS = 25_000;
const VOID_TAGS = new Set([
  "area",
  "base",
  "br",
  "col",
  "embed",
  "hr",
  "img",
  "input",
  "link",
  "meta",
  "param",
  "source",
  "track",
  "wbr",
]);
const BLOCK_TAGS = new Set([
  "article",
  "blockquote",
  "br",
  "dd",
  "div",
  "dl",
  "dt",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "li",
  "ol",
  "p",
  "pre",
  "section",
  "table",
  "td",
  "th",
  "tr",
  "ul",
]);
const HTML_ENTITIES: Record<string, string> = {
  amp: "&",
  lt: "<",
  gt: ">",
  quot: '"',
  apos: "'",
  nbsp: " ",
  ndash: "–",
  mdash: "—",
  hellip: "…",
  rsquo: "’",
  lsquo: "‘",
  rdquo: "”",
  ldquo: "“",
};

function decodeHtmlEntities(value: string): string {
  return value.replace(/&(#x?[0-9a-fA-F]+|[a-zA-Z][a-zA-Z0-9]+);/g, (raw, entity: string) => {
    if (entity.startsWith("#x") || entity.startsWith("#X")) {
      const code = Number.parseInt(entity.slice(2), 16);
      return Number.isFinite(code) ? String.fromCodePoint(code) : raw;
    }
    if (entity.startsWith("#")) {
      const code = Number.parseInt(entity.slice(1), 10);
      return Number.isFinite(code) ? String.fromCodePoint(code) : raw;
    }
    return HTML_ENTITIES[entity] ?? raw;
  });
}

function composeSignal(signal?: AbortSignal, timeoutMs = REQUEST_TIMEOUT_MS): AbortSignal {
  const timeoutSignal = AbortSignal.timeout(timeoutMs);
  if (!signal) return timeoutSignal;
  if (typeof AbortSignal.any === "function") return AbortSignal.any([signal, timeoutSignal]);

  const controller = new AbortController();
  const abort = () => controller.abort();
  signal.addEventListener("abort", abort, { once: true });
  timeoutSignal.addEventListener("abort", abort, { once: true });
  return controller.signal;
}

function normalizeId(value: string): string {
  return value.replace(/^t3_/i, "").toLowerCase();
}

export function parseThreadRef(value: string): ThreadRef | null {
  const trimmed = value.trim();
  if (/^[a-z0-9]{5,12}$/i.test(trimmed)) return { originalUrl: value, postId: normalizeId(trimmed) };

  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    return null;
  }

  const host = parsed.hostname.toLowerCase();
  const isRedditHost = host === "reddit.com" || host.endsWith(".reddit.com");
  const isShortHost = host === "redd.it";
  const parts = parsed.pathname.split("/").filter(Boolean).map(stripJsonSuffix);

  if (isShortHost && parts[0]) {
    return { originalUrl: value, postId: normalizeId(parts[0]) };
  }

  if (!isRedditHost) return null;

  if (parts.length >= 4 && parts[0]?.toLowerCase() === "r" && parts[2]?.toLowerCase() === "comments") {
    return {
      originalUrl: value,
      subreddit: parts[1],
      postId: normalizeId(parts[3]),
      slug: parts[4] ?? "",
    };
  }

  if (parts.length >= 2 && parts[0]?.toLowerCase() === "comments") {
    return {
      originalUrl: value,
      postId: normalizeId(parts[1]),
      slug: parts[2] ?? "",
    };
  }

  return null;
}

function stripJsonSuffix(value: string): string {
  return value.replace(/\.json$/i, "");
}

function normalizeListingSort(value: string | null | undefined): RedditListingSort | null {
  const normalized = stripJsonSuffix(value ?? "").toLowerCase();
  return LISTING_SORT_SET.has(normalized) ? (normalized as RedditListingSort) : null;
}

export function parseSubredditRef(value: string): SubredditRef | null {
  const trimmed = value.trim();
  const bareMatch = trimmed.match(/^\/?r\/([A-Za-z0-9_][A-Za-z0-9_]{1,20})(?:\/([A-Za-z]+))?\/?$/i);
  if (bareMatch) {
    const pathSort = normalizeListingSort(bareMatch[2]);
    if (bareMatch[2] && !pathSort) return null;
    return { originalUrl: value, subreddit: bareMatch[1], sort: pathSort ?? "hot" };
  }

  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    return null;
  }

  const host = parsed.hostname.toLowerCase();
  const isRedditHost = host === "reddit.com" || host.endsWith(".reddit.com");
  if (!isRedditHost) return null;

  const parts = parsed.pathname.split("/").filter(Boolean).map(stripJsonSuffix);
  if (parts[0]?.toLowerCase() !== "r" || !parts[1]) return null;
  if (parts[2]?.toLowerCase() === "comments") return null;

  const subreddit = parts[1];
  const pathSort = normalizeListingSort(parts[2]);
  const querySort = normalizeListingSort(parsed.searchParams.get("sort"));
  const sort = pathSort ?? querySort ?? "hot";

  // Only accept subreddit front-page/listing paths. Other subreddit URLs such as
  // /about, /wiki, /search, and /comments should be handled by other tools.
  if (parts.length > 2 && !pathSort) return null;
  if (parts.length > 3) return null;

  const time = parsed.searchParams.get("t") || undefined;
  const after = parsed.searchParams.get("after") || undefined;
  const before = parsed.searchParams.get("before") || undefined;
  return { originalUrl: value, subreddit, sort, time, after, before };
}

export function isRedditThreadUrl(value: string): boolean {
  return parseThreadRef(value) !== null;
}

export function isRedditSubredditUrl(value: string): boolean {
  return parseSubredditRef(value) !== null;
}

export function isRedditSupportedUrl(value: string): boolean {
  return isRedditThreadUrl(value) || isRedditSubredditUrl(value);
}

function redditJsonUrls(ref: ThreadRef): string[] {
  const query = new URLSearchParams({ raw_json: "1", limit: "500" }).toString();
  const urls: string[] = [];
  if (ref.subreddit) {
    const slug = ref.slug ? `/${ref.slug}` : "";
    urls.push(`https://www.reddit.com/r/${ref.subreddit}/comments/${ref.postId}${slug}.json?${query}`);
    urls.push(`https://api.reddit.com/r/${ref.subreddit}/comments/${ref.postId}${slug}?${query}`);
  }
  urls.push(`https://www.reddit.com/comments/${ref.postId}.json?${query}`);
  urls.push(`https://api.reddit.com/comments/${ref.postId}?${query}`);
  return urls;
}

function redditListingJsonUrls(ref: SubredditRef, limit: number): string[] {
  const safeLimit = Number.isFinite(limit) ? limit : 25;
  const query = new URLSearchParams({ raw_json: "1", limit: String(Math.max(1, Math.min(100, Math.floor(safeLimit)))) });
  if (ref.time && (ref.sort === "top" || ref.sort === "controversial")) query.set("t", ref.time);
  if (ref.after) query.set("after", ref.after);
  if (ref.before) query.set("before", ref.before);

  const sortPath = ref.sort === "hot" ? "" : `/${ref.sort}`;
  const queryText = query.toString();
  return [
    `https://www.reddit.com/r/${ref.subreddit}${sortPath}.json?${queryText}`,
    `https://api.reddit.com/r/${ref.subreddit}${sortPath}?${queryText}`,
  ];
}

async function fetchText(url: string, signal?: AbortSignal, accept = "application/json,text/html;q=0.9,*/*;q=0.8"): Promise<string> {
  const response = await fetch(url, {
    signal: composeSignal(signal),
    headers: {
      "User-Agent": process.env.REDDIT_USER_AGENT || DEFAULT_USER_AGENT,
      Accept: accept,
      "Accept-Language": "en-US,en;q=0.9",
    },
  });
  const text = await response.text();
  if (!response.ok) throw new Error(`HTTP ${response.status} for ${url}: ${text.slice(0, 300).trim()}`);
  return text;
}

function isoFromUtc(timestamp: unknown): string | null {
  if (typeof timestamp !== "number" || !Number.isFinite(timestamp)) return null;
  return new Date(timestamp * 1000).toISOString();
}

async function fetchRedditPublicJson(ref: ThreadRef, signal?: AbortSignal): Promise<NormalizedThread> {
  const errors: string[] = [];
  for (const url of redditJsonUrls(ref)) {
    try {
      const text = await fetchText(url, signal, "application/json");
      return normalizeRedditJson(JSON.parse(text), ref, url);
    } catch (err) {
      errors.push(err instanceof Error ? err.message : String(err));
    }
  }
  throw new Error(errors.join("; "));
}

async function fetchRedditListingPublicJson(ref: SubredditRef, limit: number, signal?: AbortSignal): Promise<NormalizedSubredditPage> {
  const errors: string[] = [];
  for (const url of redditListingJsonUrls(ref, limit)) {
    try {
      const text = await fetchText(url, signal, "application/json");
      return normalizeRedditListingJson(JSON.parse(text), ref, url);
    } catch (err) {
      errors.push(err instanceof Error ? err.message : String(err));
    }
  }
  throw new Error(errors.join("; "));
}

function normalizeRedditJson(data: unknown, ref: ThreadRef, sourceUrl: string): NormalizedThread {
  if (!Array.isArray(data) || data.length < 1) throw new Error("Reddit JSON did not contain listing array");
  const postListing = (data[0] as any)?.data;
  const commentsListing = (data[1] as any)?.data;
  const postData = postListing?.children?.[0]?.data;
  if (!postData) throw new Error("Reddit JSON did not contain post data");

  const comments: NormalizedComment[] = [];
  for (const child of commentsListing?.children ?? []) {
    const comment = normalizeRedditComment(child, 0);
    if (comment) comments.push(comment);
  }

  const createdUtc = typeof postData.created_utc === "number" ? postData.created_utc : null;
  const permalink = postData.permalink ? `https://www.reddit.com${postData.permalink}` : ref.originalUrl;

  return {
    fetchedAt: new Date().toISOString(),
    fetchedVia: "reddit_public_json",
    sourceUrl,
    post: {
      id: postData.id ?? ref.postId,
      subreddit: postData.subreddit ?? ref.subreddit,
      author: postData.author ?? null,
      title: postData.title ?? "",
      body: postData.selftext ?? "",
      score: typeof postData.score === "number" ? postData.score : null,
      upvoteRatio: typeof postData.upvote_ratio === "number" ? postData.upvote_ratio : null,
      createdUtc,
      createdIso: isoFromUtc(createdUtc),
      commentCount: typeof postData.num_comments === "number" ? postData.num_comments : null,
      permalink,
      url: postData.url ?? permalink,
    },
    comments,
    commentCountExtracted: countComments(comments),
    notes: [],
  };
}

function normalizeRedditListingJson(data: unknown, ref: SubredditRef, sourceUrl: string): NormalizedSubredditPage {
  const listing = (data as any)?.data;
  if (!listing || !Array.isArray(listing.children)) throw new Error("Reddit JSON did not contain subreddit listing data");

  const posts: NormalizedListingPost[] = [];
  for (const child of listing.children) {
    const post = normalizeRedditListingPost(child, ref.subreddit);
    if (post) posts.push(post);
  }

  return {
    fetchedAt: new Date().toISOString(),
    fetchedVia: "reddit_public_json",
    sourceUrl,
    subreddit: ref.subreddit,
    sort: ref.sort,
    time: ref.time,
    after: typeof listing.after === "string" ? listing.after : null,
    before: typeof listing.before === "string" ? listing.before : null,
    posts,
    notes: [],
  };
}

function normalizeRedditListingPost(child: any, fallbackSubreddit: string): NormalizedListingPost | null {
  if (child?.kind !== "t3") return null;
  const data = child.data ?? {};
  const id = typeof data.id === "string" ? data.id : "";
  const createdUtc = typeof data.created_utc === "number" ? data.created_utc : null;
  const permalink = data.permalink ? `https://www.reddit.com${data.permalink}` : `https://www.reddit.com/r/${data.subreddit ?? fallbackSubreddit}/comments/${id}/`;

  return {
    id,
    subreddit: data.subreddit ?? fallbackSubreddit,
    author: data.author ?? null,
    title: data.title ?? "",
    body: typeof data.selftext === "string" ? data.selftext : "",
    score: typeof data.score === "number" ? data.score : null,
    upvoteRatio: typeof data.upvote_ratio === "number" ? data.upvote_ratio : null,
    createdUtc,
    createdIso: isoFromUtc(createdUtc),
    commentCount: typeof data.num_comments === "number" ? data.num_comments : null,
    permalink,
    url: data.url ?? permalink,
    domain: data.domain ?? null,
    flair: data.link_flair_text ?? null,
    isSelf: typeof data.is_self === "boolean" ? data.is_self : null,
    over18: typeof data.over_18 === "boolean" ? data.over_18 : null,
    stickied: typeof data.stickied === "boolean" ? data.stickied : null,
  };
}

function normalizeRedditComment(child: any, depth: number): NormalizedComment | null {
  if (child?.kind !== "t1") return null;
  const data = child.data ?? {};
  const replies: NormalizedComment[] = [];
  if (data.replies && typeof data.replies === "object") {
    for (const replyChild of data.replies?.data?.children ?? []) {
      const reply = normalizeRedditComment(replyChild, depth + 1);
      if (reply) replies.push(reply);
    }
  }

  const createdUtc = typeof data.created_utc === "number" ? data.created_utc : null;
  return {
    id: data.id ?? null,
    author: data.author ?? null,
    body: data.body ?? "",
    score: typeof data.score === "number" ? data.score : null,
    createdUtc,
    createdIso: isoFromUtc(createdUtc),
    permalink: data.permalink ? `https://www.reddit.com${data.permalink}` : null,
    depth,
    replies,
  };
}

function redlibInstances(): string[] {
  const raw = process.env.REDLIB_INSTANCES || process.env.REDLIB_INSTANCE || "";
  if (raw.trim()) return raw.split(",").map((item) => item.trim().replace(/\/$/, "")).filter(Boolean);
  return DEFAULT_REDLIB_INSTANCES;
}

function redlibUrls(ref: ThreadRef, instance: string): string[] {
  const base = instance.replace(/\/$/, "");
  if (ref.subreddit) {
    const slug = ref.slug ? `/${ref.slug}` : "";
    return [`${base}/r/${ref.subreddit}/comments/${ref.postId}${slug}/`, `${base}/comments/${ref.postId}/`, `${base}/${ref.postId}`];
  }
  return [`${base}/comments/${ref.postId}/`, `${base}/${ref.postId}`];
}

async function fetchRedlibHtml(ref: ThreadRef, signal?: AbortSignal): Promise<NormalizedThread> {
  const errors: string[] = [];
  for (const instance of redlibInstances()) {
    for (const url of redlibUrls(ref, instance)) {
      try {
        const html = await fetchText(url, signal, "text/html");
        if (/You've been blocked|whoa there, pardner/i.test(html)) throw new Error("Redlib returned a Reddit block page");
        return normalizeRedlibHtml(html, ref, url);
      } catch (err) {
        errors.push(`${url}: ${err instanceof Error ? err.message : String(err)}`);
      }
    }
  }
  throw new Error(errors.join("; "));
}

function redlibListingUrls(ref: SubredditRef, instance: string): string[] {
  const base = instance.replace(/\/$/, "");
  const sortPath = ref.sort === "hot" ? "" : `/${ref.sort}`;
  const query = new URLSearchParams();
  if (ref.time && (ref.sort === "top" || ref.sort === "controversial")) query.set("t", ref.time);
  if (ref.after) query.set("after", ref.after);
  if (ref.before) query.set("before", ref.before);
  const queryText = query.toString();
  return [`${base}/r/${ref.subreddit}${sortPath}/${queryText ? `?${queryText}` : ""}`];
}

async function fetchRedlibListingHtml(ref: SubredditRef, signal?: AbortSignal): Promise<NormalizedSubredditPage> {
  const errors: string[] = [];
  for (const instance of redlibInstances()) {
    for (const url of redlibListingUrls(ref, instance)) {
      try {
        const html = await fetchText(url, signal, "text/html");
        if (/You've been blocked|whoa there, pardner/i.test(html)) throw new Error("Redlib returned a Reddit block page");
        return normalizeRedlibListingHtml(html, ref, url);
      } catch (err) {
        errors.push(`${url}: ${err instanceof Error ? err.message : String(err)}`);
      }
    }
  }
  throw new Error(errors.join("; "));
}

function parseAttrs(raw: string): Record<string, string> {
  const attrs: Record<string, string> = {};
  const attrPattern = /([^\s"'<>\/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?/g;
  let match: RegExpExecArray | null;
  while ((match = attrPattern.exec(raw))) {
    const name = match[1]?.toLowerCase();
    if (!name) continue;
    attrs[name] = decodeHtmlEntities(match[2] ?? match[3] ?? match[4] ?? "");
  }
  return attrs;
}

function parseHtml(html: string): DomNode {
  const root: DomNode = { tag: "document", attrs: {}, children: [] };
  const stack: DomNode[] = [root];
  const tokenPattern = /<!--[\s\S]*?-->|<![^>]*>|<\/?[^>]+>|[^<]+/g;
  let match: RegExpExecArray | null;

  while ((match = tokenPattern.exec(html))) {
    const token = match[0];
    const parent = stack[stack.length - 1];
    if (!parent) continue;

    if (token.startsWith("<!--") || token.startsWith("<!")) continue;

    if (token.startsWith("</")) {
      const tag = token.slice(2, -1).trim().split(/\s+/, 1)[0]?.toLowerCase();
      if (!tag) continue;
      for (let index = stack.length - 1; index > 0; index -= 1) {
        if (stack[index]?.tag === tag) {
          stack.length = index;
          break;
        }
      }
      continue;
    }

    if (token.startsWith("<")) {
      const selfClosing = /\/\s*>$/.test(token);
      const inside = token.slice(1, token.length - (selfClosing ? 2 : 1)).trim();
      const tagMatch = inside.match(/^([^\s/>]+)/);
      const tag = tagMatch?.[1]?.toLowerCase();
      if (!tag) continue;
      const attrRaw = inside.slice(tagMatch[0].length);
      const node: DomNode = { tag, attrs: parseAttrs(attrRaw), children: [], parent };
      parent.children.push(node);
      if (!selfClosing && !VOID_TAGS.has(tag)) stack.push(node);
      continue;
    }

    if (token) parent.children.push(decodeHtmlEntities(token));
  }

  return root;
}

function hasClass(node: DomNode, className: string): boolean {
  return (node.attrs.class ?? "").split(/\s+/).includes(className);
}

function* iterNodes(node: DomNode): Iterable<DomNode> {
  for (const child of node.children) {
    if (typeof child !== "string") {
      yield child;
      yield* iterNodes(child);
    }
  }
}

function findFirst(node: DomNode | null | undefined, predicate: (node: DomNode) => boolean): DomNode | null {
  if (!node) return null;
  for (const child of iterNodes(node)) {
    if (predicate(child)) return child;
  }
  return null;
}

function findAll(node: DomNode | null | undefined, predicate: (node: DomNode) => boolean): DomNode[] {
  if (!node) return [];
  return Array.from(iterNodes(node)).filter(predicate);
}

function elementChildren(node: DomNode | null | undefined, predicate?: (node: DomNode) => boolean): DomNode[] {
  if (!node) return [];
  const children = node.children.filter((child): child is DomNode => typeof child !== "string");
  return predicate ? children.filter(predicate) : children;
}

function directChild(node: DomNode | null | undefined, tag: string, className?: string): DomNode | null {
  return elementChildren(node, (child) => child.tag === tag && (!className || hasClass(child, className)))[0] ?? null;
}

function textOf(node: DomNode | null | undefined): string {
  if (!node) return "";
  const parts: string[] = [];

  function walk(item: DomChild): void {
    if (typeof item === "string") {
      parts.push(item);
      return;
    }
    if (item.tag === "br") {
      parts.push("\n");
      return;
    }
    if (item.tag === "li") parts.push("\n- ");
    else if (BLOCK_TAGS.has(item.tag) && parts.length > 0 && !parts[parts.length - 1]?.endsWith("\n")) parts.push("\n");
    for (const child of item.children) walk(child);
    if (BLOCK_TAGS.has(item.tag)) parts.push("\n");
  }

  walk(node);
  return cleanText(parts.join(""));
}

function cleanText(value: string): string {
  const lines = value.replace(/\u00a0/g, " ").split(/\r?\n/).map((line) => line.replace(/[ \t\f\v]+/g, " ").trim());
  const cleaned: string[] = [];
  let previousBlank = true;
  for (const line of lines) {
    if (line) {
      cleaned.push(line);
      previousBlank = false;
    } else if (!previousBlank) {
      cleaned.push("");
      previousBlank = true;
    }
  }
  return cleaned.join("\n").trim();
}

function attrInt(node: DomNode | null | undefined, name: string): number | null {
  const value = node?.attrs[name] ?? "";
  const match = value.replace(/,/g, "").match(/-?\d+/);
  return match ? Number(match[0]) : null;
}

function absoluteUrl(href: string, baseUrl?: string): string {
  if (!href) return href;
  if (!baseUrl) return href;
  try {
    return new URL(href, baseUrl).toString();
  } catch {
    return href;
  }
}

function markdownOf(node: DomNode | null | undefined, baseUrl?: string): string {
  if (!node) return "";

  function renderChildren(current: DomNode): string {
    return current.children.map(render).join("");
  }

  function block(value: string): string {
    const trimmed = value.trim();
    return trimmed ? `\n${trimmed}\n` : "";
  }

  function render(item: DomChild): string {
    if (typeof item === "string") return item;
    switch (item.tag) {
      case "br":
        return "\n";
      case "p":
      case "div":
      case "section":
      case "article":
      case "summary":
      case "details":
        return block(renderChildren(item));
      case "h1":
        return block(`# ${renderChildren(item).trim()}`);
      case "h2":
        return block(`## ${renderChildren(item).trim()}`);
      case "h3":
        return block(`### ${renderChildren(item).trim()}`);
      case "h4":
      case "h5":
      case "h6":
        return block(`#### ${renderChildren(item).trim()}`);
      case "li":
        return `\n- ${renderChildren(item).trim()}\n`;
      case "ul":
      case "ol":
        return block(renderChildren(item));
      case "blockquote": {
        const quoted = renderChildren(item).trim().split(/\r?\n/).map((line) => `> ${line}`.trimEnd()).join("\n");
        return block(quoted);
      }
      case "pre":
        return block(`\`\`\`\n${textOf(item)}\n\`\`\``);
      case "code": {
        if (item.parent?.tag === "pre") return textOf(item);
        const code = textOf(item).replace(/`/g, "\\`");
        return code ? `\`${code}\`` : "";
      }
      case "a": {
        const label = cleanInline(renderChildren(item)) || item.attrs.href || "";
        const href = absoluteUrl(item.attrs.href ?? "", baseUrl);
        if (!href || href === label) return label;
        return `[${label}](${href})`;
      }
      default:
        return renderChildren(item);
    }
  }

  return cleanMarkdown(render(node));
}

function cleanInline(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function cleanMarkdown(value: string): string {
  return value
    .replace(/\u00a0/g, " ")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n[ \t]+/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function redlibPostTitleContainer(postNode: DomNode): DomNode | null {
  return findFirst(postNode, (node) => hasClass(node, "post_title"));
}

function redlibPostTitleLink(postNode: DomNode): DomNode | null {
  const titleContainer = redlibPostTitleContainer(postNode);
  return (
    findFirst(titleContainer, (node) => node.tag === "a" && !hasClass(node, "post_flair") && /\/comments\//i.test(node.attrs.href ?? "")) ??
    findFirst(titleContainer, (node) => node.tag === "a" && !hasClass(node, "post_flair")) ??
    titleContainer
  );
}

function redlibPostTitleText(postNode: DomNode): string {
  const titleContainer = redlibPostTitleContainer(postNode);
  const titleNode = redlibPostTitleLink(postNode);
  if (titleNode && titleNode !== titleContainer) return textOf(titleNode);

  const title = textOf(titleContainer);
  const flairText = textOf(findFirst(titleContainer, (node) => hasClass(node, "post_flair")));
  return flairText && title.startsWith(flairText) ? cleanText(title.slice(flairText.length)) : title;
}

function normalizeRedlibHtml(html: string, ref: ThreadRef, sourceUrl: string): NormalizedThread {
  const root = parseHtml(html);
  const postNode =
    findFirst(root, (node) => node.tag === "div" && hasClass(node, "post") && hasClass(node, "highlighted")) ??
    findFirst(root, (node) => node.tag === "div" && hasClass(node, "post"));
  if (!postNode) throw new Error("Could not find Redlib post content");

  const threadNodes = findAll(root, (node) => node.tag === "div" && hasClass(node, "thread"));
  const seen = new Set<string>();
  const comments: NormalizedComment[] = [];
  for (const threadNode of threadNodes) {
    for (const commentNode of elementChildren(threadNode, (child) => child.tag === "div" && hasClass(child, "comment"))) {
      const id = commentNode.attrs.id ?? "";
      if (id && seen.has(id)) continue;
      if (id) seen.add(id);
      comments.push(parseRedlibComment(commentNode, 0, sourceUrl));
    }
  }

  const countText = textOf(findFirst(root, (node) => node.attrs.id === "comment_count"));
  const countMatch = countText.replace(/,/g, "").match(/\d+/);
  const subreddit = textOf(findFirst(postNode, (node) => node.tag === "a" && hasClass(node, "post_subreddit"))).replace(/^r\//, "") || ref.subreddit;
  const author = textOf(findFirst(postNode, (node) => node.tag === "a" && hasClass(node, "post_author"))).replace(/^u\//, "") || null;
  const title = redlibPostTitleText(postNode) || textOf(findFirst(root, (node) => node.tag === "title"));
  const createdNode = findFirst(postNode, (node) => hasClass(node, "created"));
  const bodyNode = findFirst(postNode, (node) => hasClass(node, "post_body"));
  const bodyMd = findFirst(bodyNode, (node) => hasClass(node, "md")) ?? bodyNode;
  const permalink = subreddit ? `https://www.reddit.com/r/${subreddit}/comments/${ref.postId}/${ref.slug ?? ""}/` : ref.originalUrl;

  return {
    fetchedAt: new Date().toISOString(),
    fetchedVia: "redlib_html",
    sourceUrl,
    post: {
      id: ref.postId,
      subreddit,
      author,
      title,
      body: markdownOf(bodyMd, sourceUrl),
      score: attrInt(findFirst(postNode, (node) => hasClass(node, "post_score")), "title"),
      upvoteRatio: null,
      createdUtc: null,
      createdIso: null,
      createdLabel: textOf(createdNode),
      createdTitle: createdNode?.attrs.title ?? null,
      commentCount: countMatch ? Number(countMatch[0]) : null,
      permalink,
      url: permalink,
    },
    comments,
    commentCountExtracted: countComments(comments),
    notes: ["Fetched from Redlib HTML fallback because Reddit public JSON may be blocked from this network."],
  };
}

function parseCountText(value: string): number | null {
  const match = value.replace(/,/g, "").match(/\d+/);
  return match ? Number(match[0]) : null;
}

function postIdFromPermalink(permalink: string): string {
  const match = permalink.match(/\/comments\/([a-z0-9]+)/i);
  return match?.[1]?.toLowerCase() ?? "";
}

function normalizeRedlibListingHtml(html: string, ref: SubredditRef, sourceUrl: string): NormalizedSubredditPage {
  const root = parseHtml(html);
  const postNodes = findAll(root, (node) => node.tag === "div" && hasClass(node, "post"));
  const posts = postNodes.map((node) => parseRedlibListingPost(node, ref, sourceUrl)).filter((post): post is NormalizedListingPost => Boolean(post));
  if (posts.length === 0) throw new Error("Could not find Redlib subreddit listing posts");

  return {
    fetchedAt: new Date().toISOString(),
    fetchedVia: "redlib_html",
    sourceUrl,
    subreddit: ref.subreddit,
    sort: ref.sort,
    time: ref.time,
    after: null,
    before: null,
    posts,
    notes: ["Fetched from Redlib HTML fallback because Reddit public JSON may be blocked from this network."],
  };
}

function parseRedlibListingPost(postNode: DomNode, ref: SubredditRef, sourceUrl: string): NormalizedListingPost | null {
  const titleNode = redlibPostTitleLink(postNode);
  const title = redlibPostTitleText(postNode);
  if (!title) return null;

  const rawPermalink = titleNode?.attrs.href || findFirst(postNode, (node) => node.tag === "a" && /\/comments\//i.test(node.attrs.href ?? ""))?.attrs.href || "";
  const permalink = rawPermalink ? absoluteUrl(rawPermalink, new URL(sourceUrl).origin).replace(/^https?:\/\/[^/]+/, "https://www.reddit.com") : `https://www.reddit.com/r/${ref.subreddit}/`;
  const createdNode = findFirst(postNode, (node) => hasClass(node, "created"));
  const bodyNode = findFirst(postNode, (node) => hasClass(node, "post_body"));
  const bodyMd = findFirst(bodyNode, (node) => hasClass(node, "md")) ?? bodyNode;
  const subreddit = textOf(findFirst(postNode, (node) => node.tag === "a" && hasClass(node, "post_subreddit"))).replace(/^r\//, "") || ref.subreddit;
  const author = textOf(findFirst(postNode, (node) => node.tag === "a" && hasClass(node, "post_author"))).replace(/^u\//, "") || null;
  const commentsNode = findFirst(postNode, (node) => hasClass(node, "post_comments")) ?? findFirst(postNode, (node) => node.tag === "a" && /comments?/i.test(textOf(node)));
  const domain = textOf(findFirst(postNode, (node) => hasClass(node, "post_domain"))) || null;

  return {
    id: postIdFromPermalink(permalink),
    subreddit,
    author,
    title,
    body: markdownOf(bodyMd, sourceUrl),
    score: attrInt(findFirst(postNode, (node) => hasClass(node, "post_score")), "title"),
    upvoteRatio: null,
    createdUtc: null,
    createdIso: null,
    createdLabel: textOf(createdNode),
    createdTitle: createdNode?.attrs.title ?? null,
    commentCount: parseCountText(textOf(commentsNode)),
    permalink,
    url: permalink,
    domain,
    flair: textOf(findFirst(postNode, (node) => hasClass(node, "post_flair"))) || null,
    isSelf: null,
    over18: hasClass(postNode, "nsfw") ? true : null,
    stickied: hasClass(postNode, "stickied") ? true : null,
  };
}

function parseRedlibComment(commentNode: DomNode, depth: number, sourceUrl: string): NormalizedComment {
  const detailsNode = directChild(commentNode, "details", "comment_right");
  const summaryNode = directChild(detailsNode, "summary", "comment_data");
  const bodyNode = directChild(detailsNode, "div", "comment_body");
  const repliesNode = directChild(detailsNode, "blockquote", "replies");
  const createdNode = findFirst(summaryNode, (node) => node.tag === "a" && hasClass(node, "created"));
  const mdNode = findFirst(bodyNode, (node) => hasClass(node, "md")) ?? bodyNode;

  const replies = elementChildren(repliesNode, (child) => child.tag === "div" && hasClass(child, "comment")).map((child) =>
    parseRedlibComment(child, depth + 1, sourceUrl),
  );

  return {
    id: commentNode.attrs.id ?? null,
    author: textOf(findFirst(summaryNode, (node) => node.tag === "a" && hasClass(node, "comment_author"))).replace(/^u\//, "") || null,
    body: markdownOf(mdNode, sourceUrl),
    score: attrInt(findFirst(commentNode, (node) => hasClass(node, "comment_score")), "title"),
    createdUtc: null,
    createdIso: null,
    createdLabel: textOf(createdNode),
    createdTitle: createdNode?.attrs.title ?? null,
    permalink: createdNode?.attrs.href ? absoluteUrl(createdNode.attrs.href, new URL(sourceUrl).origin) : null,
    depth,
    replies,
  };
}

function countComments(comments: NormalizedComment[]): number {
  return comments.reduce((sum, comment) => sum + 1 + countComments(comment.replies), 0);
}

export function flattenComments(comments: NormalizedComment[]): NormalizedComment[] {
  const flat: NormalizedComment[] = [];
  for (const comment of comments) {
    flat.push(comment);
    flat.push(...flattenComments(comment.replies));
  }
  return flat;
}

function truncateComment(text: string, width = 1200): string {
  const trimmed = text.trim();
  return trimmed.length <= width ? trimmed : `${trimmed.slice(0, width - 1).trim()}…`;
}

export function threadToMarkdown(thread: NormalizedThread): string {
  const post = thread.post;
  const shown = flattenComments(thread.comments);
  const lines = [
    `# ${post.title || "(untitled)"}`,
    "",
    `- Source: ${post.permalink || thread.sourceUrl}`,
    `- Fetched via: \`${thread.fetchedVia}\``,
    `- Subreddit: r/${post.subreddit ?? "?"}`,
    `- Author: u/${post.author ?? "?"}`,
    `- Score: ${post.score ?? "?"}`,
    `- Comments reported/extracted: ${post.commentCount ?? "?"} / ${thread.commentCountExtracted}`,
    "",
    "## Post body",
    "",
    post.body || "_(no body)_",
    "",
    "## Comments",
    "",
  ];

  if (shown.length === 0) {
    lines.push("_(no comments extracted)_", "");
  }

  for (const [index, comment] of shown.entries()) {
    const indent = "  ".repeat(comment.depth);
    const when = comment.createdIso ?? comment.createdLabel ?? "";
    lines.push(`${indent}${index + 1}. u/${comment.author ?? "?"} — score ${comment.score ?? "?"}${when ? ` — ${when}` : ""}`);
    lines.push("");
    const body = truncateComment(comment.body || "_(empty)_");
    for (const line of body.split("\n")) lines.push(`${indent}${line}`.trimEnd());
    lines.push("");
  }

  if (thread.notes.length > 0) {
    lines.push("## Notes", "", ...thread.notes.map((note) => `- ${note}`), "");
  }

  return `${lines.join("\n").trim()}\n`;
}

function subredditPageUrl(page: NormalizedSubredditPage): string {
  const sortPath = page.sort === "hot" ? "" : `${page.sort}/`;
  const url = new URL(`https://www.reddit.com/r/${page.subreddit}/${sortPath}`);
  if (page.time && (page.sort === "top" || page.sort === "controversial")) url.searchParams.set("t", page.time);
  return url.toString();
}

function truncateBodyPreview(text: string | undefined, width = 500): string {
  const trimmed = (text ?? "").trim();
  return trimmed.length <= width ? trimmed : `${trimmed.slice(0, width - 1).trim()}…`;
}

function markdownLink(label: string, href: string): string {
  const safeLabel = label.replace(/\[/g, "\\[").replace(/\]/g, "\\]");
  return `[${safeLabel}](${href})`;
}

export function subredditPageToMarkdown(page: NormalizedSubredditPage, maxPosts = 25): string {
  const limit = Math.max(0, Math.min(Number.isFinite(maxPosts) ? Math.floor(maxPosts) : 25, page.posts.length));
  const shown = page.posts.slice(0, limit);
  const sortLabel = `${page.sort}${page.time ? ` (${page.time})` : ""}`;
  const lines = [
    `# r/${page.subreddit} — ${sortLabel}`,
    "",
    `- Source: ${subredditPageUrl(page)}`,
    `- Fetched via: \`${page.fetchedVia}\``,
    `- Posts extracted: ${page.posts.length}`,
  ];
  if (page.after) lines.push(`- Next page token: \`${page.after}\``);
  lines.push("", "## Posts", "");

  if (shown.length === 0) {
    lines.push(page.posts.length > 0 ? `_(posts omitted; ${page.posts.length} extracted)_` : "_(no posts extracted)_", "");
  }

  for (const [index, post] of shown.entries()) {
    const when = post.createdIso ?? post.createdLabel ?? "";
    lines.push(`${index + 1}. ${markdownLink(post.title || "(untitled)", post.permalink)}`);
    lines.push(`   - Subreddit: r/${post.subreddit ?? page.subreddit}`);
    lines.push(`   - Author: u/${post.author ?? "?"}`);
    lines.push(`   - Score: ${post.score ?? "?"}`);
    lines.push(`   - Comments: ${post.commentCount ?? "?"}`);
    if (when) lines.push(`   - Created: ${when}`);
    if (post.flair) lines.push(`   - Flair: ${post.flair}`);
    if (post.domain) lines.push(`   - Domain: ${post.domain}`);
    if (post.url && post.url !== post.permalink) lines.push(`   - URL: ${post.url}`);
    const body = truncateBodyPreview(post.body);
    if (body) {
      lines.push("");
      for (const line of body.split("\n")) lines.push(`   ${line}`.trimEnd());
    }
    lines.push("");
  }

  if (shown.length < page.posts.length) {
    lines.push(`_(showing ${shown.length} of ${page.posts.length} extracted posts; raise maxPosts for more)_`, "");
  }

  if (page.notes.length > 0) {
    lines.push("## Notes", "", ...page.notes.map((note) => `- ${note}`), "");
  }

  return `${lines.join("\n").trim()}\n`;
}

export function threadToJsonObject(thread: NormalizedThread): unknown {
  return {
    fetched_at: thread.fetchedAt,
    fetched_via: thread.fetchedVia,
    source_url: thread.sourceUrl,
    post: {
      id: thread.post.id,
      subreddit: thread.post.subreddit ?? null,
      author: thread.post.author ?? null,
      title: thread.post.title,
      body: thread.post.body,
      score: thread.post.score ?? null,
      upvote_ratio: thread.post.upvoteRatio ?? null,
      created_utc: thread.post.createdUtc ?? null,
      created_iso: thread.post.createdIso ?? null,
      created_label: thread.post.createdLabel ?? null,
      created_title: thread.post.createdTitle ?? null,
      comment_count: thread.post.commentCount ?? null,
      permalink: thread.post.permalink,
      url: thread.post.url ?? thread.post.permalink,
    },
    comments: thread.comments.map(commentToJsonObject),
    comment_count_extracted: thread.commentCountExtracted,
    notes: thread.notes,
  };
}

export function subredditPageToJsonObject(page: NormalizedSubredditPage): unknown {
  return {
    fetched_at: page.fetchedAt,
    fetched_via: page.fetchedVia,
    source_url: page.sourceUrl,
    subreddit: page.subreddit,
    sort: page.sort,
    time: page.time ?? null,
    after: page.after ?? null,
    before: page.before ?? null,
    page_url: subredditPageUrl(page),
    posts: page.posts.map((post) => ({
      id: post.id,
      subreddit: post.subreddit ?? null,
      author: post.author ?? null,
      title: post.title,
      body: post.body ?? "",
      score: post.score ?? null,
      upvote_ratio: post.upvoteRatio ?? null,
      created_utc: post.createdUtc ?? null,
      created_iso: post.createdIso ?? null,
      created_label: post.createdLabel ?? null,
      created_title: post.createdTitle ?? null,
      comment_count: post.commentCount ?? null,
      permalink: post.permalink,
      url: post.url ?? post.permalink,
      domain: post.domain ?? null,
      flair: post.flair ?? null,
      is_self: post.isSelf ?? null,
      over_18: post.over18 ?? null,
      stickied: post.stickied ?? null,
    })),
    notes: page.notes,
  };
}

function commentToJsonObject(comment: NormalizedComment): unknown {
  return {
    id: comment.id ?? null,
    author: comment.author ?? null,
    body: comment.body,
    score: comment.score ?? null,
    created_utc: comment.createdUtc ?? null,
    created_iso: comment.createdIso ?? null,
    created_label: comment.createdLabel ?? null,
    created_title: comment.createdTitle ?? null,
    permalink: comment.permalink ?? null,
    depth: comment.depth,
    replies: comment.replies.map(commentToJsonObject),
  };
}

export async function fetchRedditSubredditPage(url: string, options: FetchRedditSubredditPageOptions = {}): Promise<NormalizedSubredditPage> {
  const ref = parseSubredditRef(url);
  if (!ref) throw new Error(`Not a Reddit subreddit front-page/listing URL: ${url}`);

  const methods = options.methods?.length ? options.methods : ["public-json", "redlib"];
  const rawLimit = typeof options.limit === "number" && Number.isFinite(options.limit) ? options.limit : 25;
  const limit = Math.max(1, Math.min(100, Math.floor(rawLimit)));
  const errors: string[] = [];

  if (methods.includes("public-json")) {
    try {
      return await fetchRedditListingPublicJson(ref, limit, options.signal);
    } catch (err) {
      errors.push(`public-json: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  if (methods.includes("redlib")) {
    try {
      const result = await fetchRedlibListingHtml(ref, options.signal);
      if (result.posts.length > limit) result.posts = result.posts.slice(0, limit);
      if (errors.length > 0) result.notes.push(`Earlier fetch attempts failed: ${errors.join(" | ")}`);
      return result;
    } catch (err) {
      errors.push(`redlib: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  throw new Error(`All Reddit subreddit listing fetch methods failed: ${errors.join(" | ")}`);
}

export async function fetchRedditThread(url: string, options: FetchRedditThreadOptions = {}): Promise<NormalizedThread> {
  const ref = parseThreadRef(url);
  if (!ref) throw new Error(`Not a Reddit comments URL or post id: ${url}`);

  const methods = options.methods?.length ? options.methods : ["public-json", "redlib"];
  const errors: string[] = [];

  if (methods.includes("public-json")) {
    try {
      return await fetchRedditPublicJson(ref, options.signal);
    } catch (err) {
      errors.push(`public-json: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  if (methods.includes("redlib")) {
    try {
      const result = await fetchRedlibHtml(ref, options.signal);
      if (errors.length > 0) result.notes.push(`Earlier fetch attempts failed: ${errors.join(" | ")}`);
      return result;
    } catch (err) {
      errors.push(`redlib: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  throw new Error(`All Reddit fetch methods failed: ${errors.join(" | ")}`);
}
