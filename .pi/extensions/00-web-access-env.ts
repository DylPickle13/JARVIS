import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const WEB_SEARCH_CONFIG_PATH = join(homedir(), ".pi", "web-search.json");
const FETCH_STATUS_RE = /^Content fetched for \d+\/\d+ URLs \[[^\]]+\]\. Full page content now available\.?$/i;
const WEB_RESEARCH_WORKFLOW_PROMPT = [
	"Web research workflow:",
	"- Use web_search for discovery/snippets only; do not set includeContent:true.",
	"- When full pages are needed, choose the best URLs and fetch them with one batched fetch_content({ urls: [...] }) call.",
	"- Wait for that fetch_content result before final answers/docs, and ignore any delayed web-search-content-ready status messages.",
].join("\n");

function findAncestorFilePath(startDir: string, fileName: string): string | undefined {
	let currentDir = resolve(startDir);
	while (true) {
		const candidate = join(currentDir, fileName);
		if (existsSync(candidate)) return candidate;

		const parentDir = dirname(currentDir);
		if (parentDir === currentDir) return undefined;
		currentDir = parentDir;
	}
}

function unquoteDotEnvValue(value: string): string {
	const trimmed = value.trim();
	if (trimmed.length >= 2 && trimmed.startsWith('"') && trimmed.endsWith('"')) {
		return trimmed
			.slice(1, -1)
			.replace(/\\n/g, "\n")
			.replace(/\\r/g, "\r")
			.replace(/\\t/g, "\t")
			.replace(/\\"/g, '"')
			.replace(/\\\\/g, "\\");
	}
	if (trimmed.length >= 2 && trimmed.startsWith("'") && trimmed.endsWith("'")) {
		return trimmed.slice(1, -1);
	}
	return trimmed.replace(/\s+#.*$/, "");
}

function parseDotEnvFile(envPath: string): Record<string, string> {
	const values: Record<string, string> = {};
	const content = readFileSync(envPath, "utf8");
	for (const rawLine of content.split(/\r?\n/)) {
		const line = rawLine.trim();
		if (!line || line.startsWith("#")) continue;

		const match = line.match(/^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/);
		if (!match) continue;
		values[match[1]] = unquoteDotEnvValue(match[2]);
	}
	return values;
}

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

function installWebAccessStatusSuppressor(pi: ExtensionAPI): void {
	const piAny = pi as any;
	if (piAny.__jarvisWebAccessStatusSuppressor || typeof piAny.sendMessage !== "function") return;

	const originalSendMessage = piAny.sendMessage.bind(pi);
	piAny.__jarvisWebAccessStatusSuppressor = true;
	piAny.sendMessage = (message: any, options?: any) => {
		const customType = message && typeof message === "object" ? message.customType : undefined;

		// pi-web-access stores fetched content before it emits this notification.
		// Dropping the notification prevents background includeContent jobs from
		// appearing as new user-like turns if any legacy/manual call still starts one.
		if (customType === "web-search-content-ready") return undefined;

		if (customType === "web-search-error") {
			return originalSendMessage(message, { ...options, triggerTurn: false });
		}

		return originalSendMessage(message, options);
	};
}

function configureWebAccess(cwd: string): { envPath?: string; model?: string; hasApiKey: boolean; hasYouTubeApiKey: boolean } {
	const envPath = findAncestorFilePath(cwd, ".env");
	const dotenvValues = envPath ? parseDotEnvFile(envPath) : {};

	const paidGeminiKey = (process.env.PAID_GEMINI_API_KEY || dotenvValues.PAID_GEMINI_API_KEY || "").trim();
	if (!process.env.GEMINI_API_KEY && paidGeminiKey) {
		process.env.GEMINI_API_KEY = paidGeminiKey;
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

	const dotenvMinimalModel = (dotenvValues.MINIMAL_MODEL || "").trim();
	if (!process.env.MINIMAL_MODEL && dotenvMinimalModel) {
		process.env.MINIMAL_MODEL = dotenvMinimalModel;
	}
	const model = (process.env.MINIMAL_MODEL || "").trim() || undefined;
	const existingConfig = loadExistingWebSearchConfig();
	const nextConfig: Record<string, unknown> = {
		...existingConfig,
		provider: "gemini",
		searchProvider: "gemini",
		workflow: "none",
		allowBrowserCookies: false,
	};
	if (model) {
		nextConfig.searchModel = model;
	} else {
		delete nextConfig.searchModel;
	}

	// Keep the paid key in the project .env. pi-web-access reads process.env.GEMINI_API_KEY,
	// so we deliberately do not duplicate geminiApiKey into ~/.pi/web-search.json.
	delete nextConfig.geminiApiKey;

	mkdirSync(dirname(WEB_SEARCH_CONFIG_PATH), { recursive: true });
	writeFileSync(WEB_SEARCH_CONFIG_PATH, JSON.stringify(nextConfig, null, 2) + "\n", { mode: 0o600 });

	return { envPath, model, hasApiKey: Boolean(process.env.GEMINI_API_KEY), hasYouTubeApiKey: Boolean(process.env.GOOGLE_API_KEY || process.env.YOUTUBE_API_KEY || process.env.YOUTUBE_DATA_API_KEY) };
}

export default function registerPiWebAccessEnv(pi: ExtensionAPI) {
	installWebAccessStatusSuppressor(pi);

	pi.on("session_start", async (_event, ctx) => {
		configureWebAccess(ctx.cwd);
	});

	pi.on("before_agent_start", (event) => {
		if (event.systemPrompt.includes(WEB_RESEARCH_WORKFLOW_PROMPT)) return undefined;
		return { systemPrompt: `${event.systemPrompt}\n\n${WEB_RESEARCH_WORKFLOW_PROMPT}` };
	});

	pi.on("input", (event) => {
		const text = (event.text ?? "").trim();
		if (FETCH_STATUS_RE.test(text)) return { action: "handled" as const };
		return undefined;
	});

	pi.on("tool_call", async (event) => {
		if (event.toolName !== "web_search") return;
		const input = event.input as Record<string, unknown> | undefined;
		if (!input || typeof input !== "object" || Array.isArray(input)) return;

		// pi-web-access opens the browser-backed curator whenever workflow is not exactly
		// "none". Force it off for every web_search call so model-supplied
		// workflow:"summary-review" or future config drift cannot pop open Chrome.
		input.workflow = "none";

		// Full-content search results are delivered by pi-web-access as separate
		// background fetch notifications. Prefer the deterministic workflow:
		// search snippets first, then one explicit batched fetch_content({ urls }) call.
		input.includeContent = false;
	});

	pi.registerCommand("web-access-config", {
		description: "Show pi-web-access Gemini search configuration status",
		handler: async (_args, ctx) => {
			const status = configureWebAccess(ctx.cwd);
			ctx.ui.notify(
				`pi-web-access: provider=gemini, MINIMAL_MODEL=${status.model ?? "missing"}, Gemini key=${status.hasApiKey ? "loaded" : "missing"}, YouTube key=${status.hasYouTubeApiKey ? "loaded" : "missing"}`,
				status.hasApiKey && status.model ? "success" : "warning",
			);
		},
	});
}
