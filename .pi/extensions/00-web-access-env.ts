import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

import { findAncestorFile as findAncestorFilePath, parseDotEnvFile } from "./lib/env";

const WEB_SEARCH_CONFIG_PATH = join(homedir(), ".pi", "web-search.json");
const FETCH_STATUS_RE = /^Content fetched for \d+\/\d+ URLs \[[^\]]+\]\. Full page content now available\.?$/i;
const WEB_RESEARCH_WORKFLOW_PROMPT = [
	"Web research workflow:",
	"- Use web_search for discovery/snippets only; do not set includeContent:true.",
	"- When full pages are needed, choose the best URLs and fetch them with one batched fetch_content({ urls: [...] }) call.",
	"- Wait for that fetch_content result before final answers/docs, and ignore any delayed web-search-content-ready status messages.",
].join("\n");
const GEMINI_DISABLED_PROMPT = [
	"Web access policy:",
	"- Gemini-backed web access is intentionally disabled in this project.",
	"- Do not ask for or suggest GEMINI_API_KEY, Gemini API setup, or signing into gemini.google.com.",
	"- Use Exa-backed web_search by default; use provider:'youtube' only for YouTube Data API metadata/search.",
].join("\n");
function loadExistingWebSearchConfig(): Record<string, unknown> {
	if (!existsSync(WEB_SEARCH_CONFIG_PATH)) return {};
	try {
		return JSON.parse(readFileSync(WEB_SEARCH_CONFIG_PATH, "utf8")) as Record<string, unknown>;
	} catch {
		return {};
	}
}

function firstNonEmptyLine(pathValue: string | undefined): string | undefined {
	if (!pathValue) return undefined;
	const path = resolve(pathValue.replace(/^~(?=\/|$)/, process.env.HOME ?? ""));
	if (!existsSync(path)) return undefined;
	for (const line of readFileSync(path, "utf8").split(/\r?\n/)) {
		const candidate = line.trim();
		if (candidate) return candidate;
	}
	return undefined;
}

type SanitizeResult<T> = { value: T; changed: boolean };

const WEB_ACCESS_WRAPPER_VERSION = 2;
const GEMINI_FALLBACK_LINE_RE = /^\s*(?:[-•]|\d+[.)])?\s*(?:Set\s+GEMINI_API_KEY\b.*|GEMINI_API_KEY\s+not\s+configured.*|Sign\s+into\s+(?:gemini\.google\.com|Google)\b.*|Gemini\s+search\s+unavailable.*|Gemini\s+(?:API|Web):.*|Full\s+video\s+understanding\s+requires\s+Gemini\s+access.*|Video\s+analysis\s+requires\s+Gemini\s+access.*|Could\s+not\s+extract\s+YouTube\s+video\s+content\.\s+Sign\s+into\s+Google.*|Unable\s+to\s+authenticate\s+with\s+Gemini\..*)\s*$/i;

function sanitizeGeminiFallbackText(text: string): SanitizeResult<string> {
	let output = text
		.replace(/Could not extract YouTube video content\. Sign into Google in Chrome for automatic access, or set GEMINI_API_KEY\.?/gi, "Could not extract YouTube video content with the non-Gemini fallbacks available.")
		.replace(/Full video understanding requires Gemini access\. Set GEMINI_API_KEY or sign into Google in Chrome\.?/gi, "Full video understanding is disabled in this JARVIS web-access setup.")
		.replace(/Video analysis requires Gemini access\. Either:/gi, "Video analysis is disabled in this JARVIS web-access setup.")
		.replace(/Gemini search unavailable\. Either:/gi, "Gemini search is disabled in this JARVIS web-access setup. Use provider:'exa'.")
		.replace(/No search provider available\. Either:/gi, "No search provider available. Zero-config Exa MCP is attempted automatically; if it fails, check network access to https://mcp.exa.ai/mcp. Optional fallbacks:");

	const filteredLines = output.split(/\r?\n/).filter((line) => !GEMINI_FALLBACK_LINE_RE.test(line));
	output = filteredLines.join("\n")
		.replace(/\n{3,}/g, "\n\n")
		.replace(/Fallback options:\s*\n\s*$/g, "Fallback options:\n  • Verify the URL/DNS and try again\n  • Use web_search with provider:'exa' to find content about this topic")
		.trimEnd();

	return { value: output, changed: output !== text };
}

function sanitizeWebAccessValue(value: unknown, seen = new WeakSet<object>()): SanitizeResult<unknown> {
	if (typeof value === "string") return sanitizeGeminiFallbackText(value);
	if (!value || typeof value !== "object") return { value, changed: false };
	if (seen.has(value)) return { value, changed: false };
	seen.add(value);

	if (Array.isArray(value)) {
		let changed = false;
		const sanitized = value.map((item) => {
			const result = sanitizeWebAccessValue(item, seen);
			changed ||= result.changed;
			return result.value;
		});
		return { value: changed ? sanitized : value, changed };
	}

	let changed = false;
	const source = value as Record<string, unknown>;
	const sanitized: Record<string, unknown> = {};
	for (const [key, item] of Object.entries(source)) {
		const result = sanitizeWebAccessValue(item, seen);
		changed ||= result.changed;
		sanitized[key] = result.value;
	}
	return { value: changed ? { ...source, ...sanitized } : value, changed };
}

function installWebAccessStatusSuppressor(pi: ExtensionAPI): void {
	const piAny = pi as any;
	if (piAny.__jarvisWebAccessStatusSuppressorVersion === WEB_ACCESS_WRAPPER_VERSION) return;
	piAny.__jarvisWebAccessStatusSuppressor = true;
	piAny.__jarvisWebAccessStatusSuppressorVersion = WEB_ACCESS_WRAPPER_VERSION;

	if (typeof piAny.sendMessage === "function") {
		const originalSendMessage = piAny.sendMessage.bind(pi);
		piAny.sendMessage = (message: any, options?: any) => {
			const customType = message && typeof message === "object" ? message.customType : undefined;

			// pi-web-access stores fetched content before it emits this notification.
			// Dropping the notification prevents background includeContent jobs from
			// appearing as new user-like turns if any legacy/manual call still starts one.
			if (customType === "web-search-content-ready") return undefined;

			const sanitizedMessage = sanitizeWebAccessValue(message).value;
			if (customType === "web-search-error") {
				return originalSendMessage(sanitizedMessage, { ...options, triggerTurn: false });
			}

			return originalSendMessage(sanitizedMessage, options);
		};
	}

	if (typeof piAny.appendEntry === "function") {
		const originalAppendEntry = piAny.appendEntry.bind(pi);
		piAny.appendEntry = (...args: any[]) => {
			const customType = typeof args[0] === "string" ? args[0] : undefined;
			if (customType === "web-search-results") {
				const sanitized = sanitizeWebAccessValue(args[1]);
				if (sanitized.changed) args[1] = sanitized.value;
			}
			return originalAppendEntry(...args);
		};
	}
}

function configureWebAccess(cwd: string): { envPath?: string; hasExaApiKey: boolean; hasYouTubeApiKey: boolean } {
	const envPath = findAncestorFilePath(cwd, ".env");
	const dotenvValues = envPath ? parseDotEnvFile(envPath) : {};

	// Gemini is intentionally disabled for this project. Do not load Gemini keys
	// from .env or ambient process state into pi-web-access.
	delete process.env.GEMINI_API_KEY;
	delete process.env.PAID_GEMINI_API_KEY;
	delete process.env.MINIMAL_MODEL;

	const exaApiKey = (process.env.EXA_API_KEY || dotenvValues.EXA_API_KEY || "").trim();
	if (!process.env.EXA_API_KEY && exaApiKey) {
		process.env.EXA_API_KEY = exaApiKey;
	}

	const perplexityApiKey = (process.env.PERPLEXITY_API_KEY || dotenvValues.PERPLEXITY_API_KEY || "").trim();
	if (!process.env.PERPLEXITY_API_KEY && perplexityApiKey) {
		process.env.PERPLEXITY_API_KEY = perplexityApiKey;
	}

	const youtubeApiKey = (process.env.YOUTUBE_API_KEY || process.env.YOUTUBE_DATA_API_KEY || dotenvValues.YOUTUBE_API_KEY || dotenvValues.YOUTUBE_DATA_API_KEY || "").trim();
	const googleApiKey = (process.env.GOOGLE_API_KEY || dotenvValues.GOOGLE_API_KEY || "").trim();
	const webAccessGoogleApiKey = youtubeApiKey || googleApiKey;
	if (webAccessGoogleApiKey) {
		if (!process.env.GOOGLE_API_KEY) process.env.GOOGLE_API_KEY = webAccessGoogleApiKey;
		if (!process.env.YOUTUBE_API_KEY && youtubeApiKey) process.env.YOUTUBE_API_KEY = youtubeApiKey;
	}
	if (!process.env.GOOGLE_API_KEY) {
		const apiKeyFile = (
			process.env.YOUTUBE_API_KEY_FILE ||
			process.env.YOUTUBE_API_KEY_PATH ||
			process.env.GOOGLE_API_KEY_FILE ||
			process.env.GOOGLE_API_KEY_PATH ||
			dotenvValues.YOUTUBE_API_KEY_FILE ||
			dotenvValues.YOUTUBE_API_KEY_PATH ||
			dotenvValues.GOOGLE_API_KEY_FILE ||
			dotenvValues.GOOGLE_API_KEY_PATH ||
			""
		).trim();
		const fileKey = firstNonEmptyLine(apiKeyFile);
		if (fileKey) process.env.GOOGLE_API_KEY = fileKey;
	}

	const existingConfig = loadExistingWebSearchConfig();
	const nextConfig: Record<string, unknown> = {
		...existingConfig,
		provider: "exa",
		searchProvider: "exa",
		workflow: "none",
		allowBrowserCookies: false,
	};

	// Remove all Gemini-specific pi-web-access configuration. Exa is the default
	// search provider; YouTube may still use GOOGLE_API_KEY/YOUTUBE_API_KEY.
	delete nextConfig.geminiApiKey;
	delete nextConfig.searchModel;

	mkdirSync(dirname(WEB_SEARCH_CONFIG_PATH), { recursive: true });
	writeFileSync(WEB_SEARCH_CONFIG_PATH, JSON.stringify(nextConfig, null, 2) + "\n", { mode: 0o600 });

	return {
		envPath,
		hasExaApiKey: Boolean(process.env.EXA_API_KEY || existingConfig.exaApiKey),
		hasYouTubeApiKey: Boolean(process.env.GOOGLE_API_KEY || process.env.YOUTUBE_API_KEY || process.env.YOUTUBE_DATA_API_KEY),
	};
}

export default function registerPiWebAccessEnv(pi: ExtensionAPI) {
	installWebAccessStatusSuppressor(pi);

	pi.on("session_start", async (_event, ctx) => {
		configureWebAccess(ctx.cwd);
	});

	pi.on("before_agent_start", (event) => {
		const additions = [WEB_RESEARCH_WORKFLOW_PROMPT, GEMINI_DISABLED_PROMPT]
			.filter((prompt) => !event.systemPrompt.includes(prompt));
		if (additions.length === 0) return undefined;
		return { systemPrompt: `${event.systemPrompt}\n\n${additions.join("\n\n")}` };
	});

	pi.on("input", (event) => {
		const text = (event.text ?? "").trim();
		if (FETCH_STATUS_RE.test(text)) return { action: "handled" as const };
		return undefined;
	});

	pi.on("tool_call", async (event) => {
		if (event.toolName !== "web_search" && event.toolName !== "fetch_content") return;
		const input = event.input as Record<string, unknown> | undefined;
		if (!input || typeof input !== "object" || Array.isArray(input)) return;

		if (event.toolName === "fetch_content") {
			// pi-web-access' model override is only for Gemini-backed video/URL paths.
			delete input.model;
			return;
		}

		// pi-web-access opens the browser-backed curator whenever workflow is not exactly
		// "none". Force it off for every web_search call so model-supplied
		// workflow:"summary-review" or future config drift cannot pop open Chrome.
		input.workflow = "none";

		// Never allow Gemini-backed search through pi-web-access. Use Exa by default
		// and avoid the extension's auto fallback chain reaching Gemini.
		const provider = typeof input.provider === "string" ? input.provider.trim().toLowerCase() : "";
		if (!provider || provider === "auto" || provider === "gemini") {
			input.provider = "exa";
		}

		// Full-content search results are delivered by pi-web-access as separate
		// background fetch notifications. Prefer the deterministic workflow:
		// search snippets first, then one explicit batched fetch_content({ urls }) call.
		input.includeContent = false;
	});

	pi.on("tool_result", (event) => {
		if (!["web_search", "fetch_content", "get_search_content"].includes(event.toolName)) return undefined;

		const content = sanitizeWebAccessValue(event.content);
		const details = sanitizeWebAccessValue(event.details);
		const patch: Record<string, unknown> = {};
		if (content.changed) patch.content = content.value;
		if (details.changed) patch.details = details.value;
		return Object.keys(patch).length > 0 ? patch : undefined;
	});

	pi.registerCommand("web-access-config", {
		description: "Show pi-web-access Exa search configuration status",
		handler: async (_args, ctx) => {
			const status = configureWebAccess(ctx.cwd);
			ctx.ui.notify(
				`pi-web-access: provider=exa, Gemini disabled, Exa key=${status.hasExaApiKey ? "configured" : "not configured; using zero-config Exa MCP fallback"}, YouTube key=${status.hasYouTubeApiKey ? "loaded" : "missing"}`,
				"success",
			);
		},
	});
}
