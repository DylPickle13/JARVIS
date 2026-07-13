import { chmodSync, mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import type { ExtensionAPI, ProviderConfig, ProviderModelConfig } from "@earendil-works/pi-coding-agent";

import { findAncestorFile, parseDotEnv } from "./lib/env";

const PROJECT_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const CONTEXT_WINDOW_CACHE_PATH = join(PROJECT_ROOT, ".pi", "runtime", "omlx-context-windows.json");
const CONTEXT_WINDOW_CACHE_VERSION = 1;
const BACKGROUND_DISCOVERY_DELAY_MS = 500;
const DEFAULT_TIMEOUT_MS = 2500;
const LOCAL_ZERO_COST = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } as const;

type ModelSeed = Omit<ProviderModelConfig, "contextWindow"> & {
	contextWindow: number;
};

type ProviderSeed = {
	provider: string;
	baseUrlEnvKeys: string[];
	defaultBaseUrl: string;
	models: ModelSeed[];
	compat?: ProviderConfig["compat"];
};

type CachedProviderContextWindows = {
	baseUrl: string;
	updatedAt: string;
	models: Record<string, number>;
};

type ContextWindowCache = {
	version: number;
	providers: Record<string, CachedProviderContextWindows>;
};

type ResolvedProvider = {
	seed: ProviderSeed;
	baseUrl: string;
	cachedContextByModel: Map<string, number>;
};

const OMLX_PROVIDER_SEEDS: ProviderSeed[] = [
	{
		provider: "omlx",
		baseUrlEnvKeys: ["OMLX_BASE_URL", "DISCORD_VOICE_BASE_URL"],
		defaultBaseUrl: "http://127.0.0.1:8000/v1",
		compat: {
			supportsDeveloperRole: false,
			supportsReasoningEffort: false,
		},
		models: [
			{
				id: "Qwen3.5-9B-4bit",
				name: "Qwen3.5-9B-4bit",
				reasoning: true,
				input: ["text", "image"],
				contextWindow: 65536,
				maxTokens: 32768,
				compat: { thinkingFormat: "qwen-chat-template" },
			},
		],
	},
	{
		provider: "omlx-64",
		baseUrlEnvKeys: ["OMLX_64_BASE_URL", "JARVIS_DASHBOARD_OMLX_64_BASE_URL"],
		defaultBaseUrl: "http://127.0.0.1:8000/v1",
		compat: {
			supportsDeveloperRole: false,
			supportsReasoningEffort: false,
		},
		models: [
			{
				id: "Qwen3.6-35B-A3B-6bit",
				name: "Qwen3.6-35B-A3B-6bit",
				reasoning: true,
				input: ["text", "image"],
				contextWindow: 131072,
				maxTokens: 32768,
				compat: { thinkingFormat: "qwen-chat-template" },
			},
			{
				id: "Qwen3.6-27B-6bit",
				name: "Qwen3.6-27B-6bit",
				reasoning: true,
				input: ["text", "image"],
				contextWindow: 131072,
				maxTokens: 32768,
				compat: { thinkingFormat: "qwen-chat-template" },
			},
		],
	},
];

function loadDotEnvValues(): Record<string, string> {
	return parseDotEnv(findAncestorFile(process.cwd(), ".env"));
}

function firstNonEmptyEnv(keys: string[], dotenvValues: Record<string, string>): string | undefined {
	for (const key of keys) {
		const value = process.env[key] || dotenvValues[key];
		if (typeof value === "string" && value.trim()) return value.trim();
	}
	return undefined;
}

function normalizeBaseUrl(raw: string): string {
	const normalized = raw.trim().replace(/\/+$/, "");
	return normalized.endsWith("/v1") ? normalized : `${normalized}/v1`;
}

function toPositiveInt(value: unknown): number | undefined {
	const numeric = Number(value);
	if (!Number.isFinite(numeric)) return undefined;
	const rounded = Math.floor(numeric);
	return rounded > 0 ? rounded : undefined;
}

function parseModelContextWindow(model: unknown): number | undefined {
	if (!model || typeof model !== "object") return undefined;
	const typed = model as Record<string, unknown>;

	const directKeys = [
		"max_model_len",
		"maxModelLen",
		"max_context_length",
		"maxContextLength",
		"context_length",
		"contextLength",
		"context_window",
		"contextWindow",
	];

	for (const key of directKeys) {
		const parsed = toPositiveInt(typed[key]);
		if (parsed !== undefined) return parsed;
	}

	const metadata = typed.metadata;
	if (metadata && typeof metadata === "object") {
		for (const key of directKeys) {
			const parsed = toPositiveInt((metadata as Record<string, unknown>)[key]);
			if (parsed !== undefined) return parsed;
		}
	}

	return undefined;
}

async function fetchJson(url: string): Promise<unknown> {
	const abortController = new AbortController();
	const timeout = setTimeout(() => abortController.abort(), DEFAULT_TIMEOUT_MS);
	try {
		const response = await fetch(url, {
			method: "GET",
			headers: { "content-type": "application/json" },
			signal: abortController.signal,
		});
		if (!response.ok) return undefined;
		return await response.json();
	} catch {
		return undefined;
	} finally {
		clearTimeout(timeout);
	}
}

async function fetchListedContextWindows(baseUrl: string): Promise<Map<string, number>> {
	const payload = await fetchJson(`${baseUrl}/models`) as { data?: unknown } | undefined;
	if (!Array.isArray(payload?.data)) return new Map();

	const contextByModel = new Map<string, number>();
	for (const entry of payload.data) {
		if (!entry || typeof entry !== "object") continue;
		const typed = entry as Record<string, unknown>;
		const modelId = typeof typed.id === "string" ? typed.id.trim() : "";
		if (!modelId) continue;
		const contextWindow = parseModelContextWindow(typed);
		if (contextWindow !== undefined) contextByModel.set(modelId, contextWindow);
	}

	return contextByModel;
}

function parseAdminModelSettingsContextWindow(model: unknown): number | undefined {
	if (!model || typeof model !== "object") return undefined;
	const settings = (model as Record<string, unknown>).settings;
	if (!settings || typeof settings !== "object") return undefined;
	return toPositiveInt((settings as Record<string, unknown>).max_context_window);
}

async function fetchAdminSettingsContextWindows(baseUrl: string, modelIds: string[]): Promise<Map<string, number>> {
	const rootUrl = baseUrl.replace(/\/v1$/, "");
	const contextByModel = new Map<string, number>();

	// These independent requests run together. Discovery happens after startup, but
	// keeping it bounded also prevents a sleeping oMLX host from leaving unnecessary
	// background work around for multiple timeout periods.
	const [adminModels, globalSettings] = await Promise.all([
		fetchJson(`${rootUrl}/admin/api/models`) as Promise<{ models?: unknown } | undefined>,
		fetchJson(`${rootUrl}/admin/api/global-settings`) as Promise<{ sampling?: unknown } | undefined>,
	]);

	// This is the oMLX server's active per-model setting — the value shown in the
	// admin UI and actually configured for the model. It can differ from both the
	// model metadata exposed by /v1/models (`max_model_len`) and the raw model
	// generation config default.
	if (Array.isArray(adminModels?.models)) {
		for (const entry of adminModels.models) {
			if (!entry || typeof entry !== "object") continue;
			const typed = entry as Record<string, unknown>;
			const modelId = typeof typed.id === "string" ? typed.id.trim() : "";
			if (!modelIds.includes(modelId)) continue;
			const contextWindow = parseAdminModelSettingsContextWindow(typed);
			if (contextWindow !== undefined) contextByModel.set(modelId, contextWindow);
		}
	}

	// If oMLX has no per-model setting for a model, fall back to the server's
	// global sampling setting before finally falling back to /v1/models metadata.
	if (contextByModel.size < modelIds.length) {
		const sampling = globalSettings?.sampling;
		const globalContextWindow = sampling && typeof sampling === "object"
			? toPositiveInt((sampling as Record<string, unknown>).max_context_window)
			: undefined;
		if (globalContextWindow !== undefined) {
			for (const modelId of modelIds) {
				if (!contextByModel.has(modelId)) contextByModel.set(modelId, globalContextWindow);
			}
		}
	}

	return contextByModel;
}

async function fetchContextWindows(baseUrl: string, modelIds: string[]): Promise<Map<string, number>> {
	const [contextByModel, adminContextByModel] = await Promise.all([
		fetchListedContextWindows(baseUrl),
		fetchAdminSettingsContextWindows(baseUrl, modelIds),
	]);
	for (const [modelId, contextWindow] of adminContextByModel) {
		contextByModel.set(modelId, contextWindow);
	}
	return contextByModel;
}

function mergedModels(seed: ProviderSeed, contextByModel: Map<string, number>): ProviderModelConfig[] {
	return seed.models.map((model) => ({
		...model,
		cost: model.cost ?? LOCAL_ZERO_COST,
		contextWindow: contextByModel.get(model.id) ?? model.contextWindow,
	}));
}

function emptyContextWindowCache(): ContextWindowCache {
	return { version: CONTEXT_WINDOW_CACHE_VERSION, providers: {} };
}

function loadContextWindowCache(): ContextWindowCache {
	try {
		const parsed = JSON.parse(readFileSync(CONTEXT_WINDOW_CACHE_PATH, "utf8")) as Record<string, unknown>;
		if (parsed.version !== CONTEXT_WINDOW_CACHE_VERSION || !parsed.providers || typeof parsed.providers !== "object") {
			return emptyContextWindowCache();
		}

		const providers: Record<string, CachedProviderContextWindows> = {};
		for (const [provider, rawEntry] of Object.entries(parsed.providers as Record<string, unknown>)) {
			if (!rawEntry || typeof rawEntry !== "object") continue;
			const entry = rawEntry as Record<string, unknown>;
			const baseUrl = typeof entry.baseUrl === "string" ? entry.baseUrl.trim() : "";
			if (!baseUrl || !entry.models || typeof entry.models !== "object") continue;

			const models: Record<string, number> = {};
			for (const [modelId, rawContextWindow] of Object.entries(entry.models as Record<string, unknown>)) {
				const contextWindow = toPositiveInt(rawContextWindow);
				if (modelId.trim() && contextWindow !== undefined) models[modelId] = contextWindow;
			}
			providers[provider] = {
				baseUrl,
				updatedAt: typeof entry.updatedAt === "string" ? entry.updatedAt : "",
				models,
			};
		}
		return { version: CONTEXT_WINDOW_CACHE_VERSION, providers };
	} catch {
		return emptyContextWindowCache();
	}
}

function cachedContextWindows(cache: ContextWindowCache, seed: ProviderSeed, baseUrl: string): Map<string, number> {
	const cached = cache.providers[seed.provider];
	if (!cached || cached.baseUrl !== baseUrl) return new Map();

	const contextByModel = new Map<string, number>();
	for (const model of seed.models) {
		const contextWindow = toPositiveInt(cached.models[model.id]);
		if (contextWindow !== undefined) contextByModel.set(model.id, contextWindow);
	}
	return contextByModel;
}

function persistContextWindowCache(cache: ContextWindowCache): void {
	const cacheDirectory = dirname(CONTEXT_WINDOW_CACHE_PATH);
	const temporaryPath = `${CONTEXT_WINDOW_CACHE_PATH}.${process.pid}.tmp`;
	try {
		mkdirSync(cacheDirectory, { recursive: true, mode: 0o700 });
		writeFileSync(temporaryPath, `${JSON.stringify(cache, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
		chmodSync(temporaryPath, 0o600);
		renameSync(temporaryPath, CONTEXT_WINDOW_CACHE_PATH);
		chmodSync(CONTEXT_WINDOW_CACHE_PATH, 0o600);
	} catch {
		try {
			rmSync(temporaryPath, { force: true });
		} catch {
			// Best-effort cache cleanup only.
		}
	}
}

function providerConfig(seed: ProviderSeed, baseUrl: string, apiKey: string, contextByModel: Map<string, number>): ProviderConfig {
	return {
		baseUrl,
		api: "openai-completions",
		apiKey,
		compat: seed.compat,
		models: mergedModels(seed, contextByModel),
	};
}

function registerResolvedProvider(pi: ExtensionAPI, item: ResolvedProvider, apiKey: string, contextByModel: Map<string, number>): void {
	pi.registerProvider(item.seed.provider, providerConfig(item.seed, item.baseUrl, apiKey, contextByModel));
}

function isPiOffline(): boolean {
	return /^(?:1|true|yes)$/i.test(process.env.PI_OFFLINE?.trim() ?? "");
}

async function refreshResolvedProviderContexts(
	pi: ExtensionAPI,
	resolved: ResolvedProvider[],
	apiKey: string,
	cache: ContextWindowCache,
): Promise<void> {
	const modelIdsByBaseUrl = new Map<string, Set<string>>();
	for (const item of resolved) {
		const modelIds = modelIdsByBaseUrl.get(item.baseUrl) ?? new Set<string>();
		for (const model of item.seed.models) modelIds.add(model.id);
		modelIdsByBaseUrl.set(item.baseUrl, modelIds);
	}

	const fetchedByBaseUrl = new Map<string, Map<string, number>>(
		await Promise.all(
			[...modelIdsByBaseUrl].map(async ([baseUrl, modelIds]) => [
				baseUrl,
				await fetchContextWindows(baseUrl, [...modelIds]),
			] as const),
		),
	);

	let cacheChanged = false;
	for (const item of resolved) {
		const fetched = fetchedByBaseUrl.get(item.baseUrl) ?? new Map<string, number>();
		const refreshed = new Map(item.cachedContextByModel);
		let discoveredCount = 0;
		for (const model of item.seed.models) {
			const contextWindow = fetched.get(model.id);
			if (contextWindow === undefined) continue;
			refreshed.set(model.id, contextWindow);
			discoveredCount += 1;
		}
		if (discoveredCount === 0) continue;

		// Dynamic provider registration takes effect immediately and Pi refreshes the
		// currently selected model from the registry, so this also updates the live
		// session without delaying its initial prompt.
		registerResolvedProvider(pi, item, apiKey, refreshed);
		item.cachedContextByModel = refreshed;
		cache.providers[item.seed.provider] = {
			baseUrl: item.baseUrl,
			updatedAt: new Date().toISOString(),
			models: Object.fromEntries(refreshed),
		};
		cacheChanged = true;
	}

	if (cacheChanged) persistContextWindowCache(cache);
}

const OMLX_PREFILL_MEMORY_GUARD_PATTERNS = [
	/oMLX prefill memory guard rejected/i,
	/Prefill would require ~?[\d.]+\s*(?:[KMGT]i?B|[KMGT]?B)? peak.*\bKV\+SDPA\b.*\bceiling\b/i,
	/Prefill would require .* but .* ceiling is .*reduce context length/i,
];

const OMLX_PROMPT_TOO_LONG_PATTERNS = [
	/Prompt too long:\s*[\d,]+\s+tokens\s+exceeds\s+max\s+context\s+window\s+of\s+[\d,]+\s+tokens/i,
	/Prompt too long:.*exceeds\s+max\s+context\s+window/i,
];

const OMLX_PREFILL_MEMORY_RECOVERY_PROMPT =
	"Continue the interrupted task from the compacted context. Do not redo completed searches or repeat already completed tool work unless necessary. Answer the original user request using the retained findings. If memory pressure still blocks more tool use, provide the best concise answer from the compacted context.";

const OMLX_PREFILL_MEMORY_COMPACTION_INSTRUCTIONS =
	"Recover from an oMLX prefill memory guard error. Summarize aggressively: preserve the active user request, key facts/findings, source URLs, decisions made, and exactly what remains to do. Drop verbose raw search/page content, repeated snippets, long product/job descriptions, and the memory guard error text itself.";

function isOmlxProvider(provider: unknown): boolean {
	return typeof provider === "string" && (provider === "omlx" || provider.startsWith("omlx-"));
}

function isOmlxPrefillMemoryGuardError(errorMessage: string): boolean {
	const normalized = errorMessage.replace(/\s+/g, " ").trim();
	return OMLX_PREFILL_MEMORY_GUARD_PATTERNS.some((pattern) => pattern.test(normalized));
}

function isOmlxPromptTooLongError(errorMessage: string): boolean {
	const normalized = errorMessage.replace(/\s+/g, " ").trim();
	return OMLX_PROMPT_TOO_LONG_PATTERNS.some((pattern) => pattern.test(normalized));
}

function parsePositiveIntEnv(name: string, fallback: number): number {
	const parsed = Number.parseInt(process.env[name] ?? "", 10);
	return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
}

function messageText(message: { content?: unknown }): string {
	const content = message.content;
	if (typeof content === "string") return content;
	if (!Array.isArray(content)) return "";
	return content
		.map((part) => {
			if (part && typeof part === "object" && (part as Record<string, unknown>).type === "text") {
				return String((part as Record<string, unknown>).text ?? "");
			}
			return "";
		})
		.join("");
}

type EmergencyMessage = {
	role?: string;
	content?: unknown;
	command?: unknown;
	output?: unknown;
	summary?: unknown;
	stopReason?: unknown;
	errorMessage?: unknown;
	provider?: unknown;
	model?: unknown;
};

type EmergencyPreparation = {
	messagesToSummarize: EmergencyMessage[];
	turnPrefixMessages: EmergencyMessage[];
	previousSummary?: string;
	firstKeptEntryId: string;
	tokensBefore: number;
	fileOps?: unknown;
};

type EmergencyCompactionDetails = {
	readFiles: string[];
	modifiedFiles: string[];
};

const OMLX_EMERGENCY_KEEP_NONE_ENTRY_ID = "__omlx_emergency_compaction_keep_no_prior_messages__";
const OMLX_EMERGENCY_URL_RE = /\bhttps?:\/\/[^\s<>"')\]]+/gi;

function normalizeSnippet(text: string): string {
	return text.replace(/\r/g, "").replace(/[ \t]+/g, " ").replace(/\n{3,}/g, "\n\n").trim();
}

function truncateSnippet(text: string, maxChars: number): string {
	const normalized = normalizeSnippet(text);
	if (normalized.length <= maxChars) return normalized;
	const keep = Math.max(0, maxChars - 40);
	return `${normalized.slice(0, keep).trimEnd()}\n… [truncated]`;
}

function contentToText(content: unknown, maxChars = 6000): string {
	if (typeof content === "string") return truncateSnippet(content, maxChars);
	if (!Array.isArray(content)) return "";

	const parts: string[] = [];
	for (const part of content) {
		if (!part || typeof part !== "object") continue;
		const typed = part as Record<string, unknown>;
		const type = String(typed.type ?? "");
		if (type === "text" && typeof typed.text === "string") {
			parts.push(typed.text);
		} else if (type === "toolCall") {
			const name = typeof typed.name === "string" ? typed.name : "tool";
			let args = "";
			try {
				args = typed.arguments === undefined ? "" : truncateSnippet(JSON.stringify(typed.arguments), 500);
			} catch {
				args = "";
			}
			parts.push(args ? `[tool call: ${name} ${args}]` : `[tool call: ${name}]`);
		} else if (typeof typed.text === "string") {
			parts.push(typed.text);
		}
	}
	return truncateSnippet(parts.join("\n"), maxChars);
}

function emergencyMessageText(message: EmergencyMessage, maxChars = 6000): string {
	const role = String(message.role ?? "");
	if (role === "bashExecution") {
		const command = typeof message.command === "string" ? message.command : "";
		const output = typeof message.output === "string" ? message.output : "";
		return truncateSnippet(`Command: ${command}\nOutput: ${output}`, maxChars);
	}
	if (role === "compactionSummary" || role === "branchSummary") {
		return truncateSnippet(String(message.summary ?? ""), maxChars);
	}
	return contentToText(message.content, maxChars);
}

function messageFromEntry(entry: unknown): EmergencyMessage | undefined {
	if (!entry || typeof entry !== "object") return undefined;
	const typed = entry as Record<string, unknown>;
	if (typed.type !== "message" || !typed.message || typeof typed.message !== "object") return undefined;
	return typed.message as EmergencyMessage;
}

function latestAssistantErrorMessage(branchEntries: readonly unknown[]): EmergencyMessage | undefined {
	for (let i = branchEntries.length - 1; i >= 0; i--) {
		const message = messageFromEntry(branchEntries[i]);
		if (message?.role === "assistant" && message.stopReason === "error") return message;
	}
	return undefined;
}

function uniqueLimited(values: Iterable<string>, limit: number): string[] {
	const seen = new Set<string>();
	const out: string[] = [];
	for (const value of values) {
		const cleaned = value.trim().replace(/[),.;]+$/, "");
		if (!cleaned || seen.has(cleaned)) continue;
		seen.add(cleaned);
		out.push(cleaned);
		if (out.length >= limit) break;
	}
	return out;
}

function extractUrls(text: string, limit: number): string[] {
	return uniqueLimited(text.match(OMLX_EMERGENCY_URL_RE) ?? [], limit);
}

function usefulLine(line: string): string | undefined {
	const cleaned = normalizeSnippet(line.replace(/^\s*[|>]\s?/, ""));
	if (!cleaned || cleaned.length < 4 || cleaned.length > 420) return undefined;
	if (/^(?:[{}\[\],:]|"[^"]*"\s*[:,]?)+$/.test(cleaned)) return undefined;
	if (/\b(?:base64|data:image|__NEXT_DATA__|webpack|script|stylesheet|aria-|class=|style=)\b/i.test(cleaned)) return undefined;
	if (/https?:\/\//i.test(cleaned)) return cleaned;
	if (/^(?:[-*•]|\d+[.)])\s+/.test(cleaned)) return cleaned;
	if (/\b(?:goal|objective|request|constraint|must|do not|don't|skip|exclude|include|found|selected|candidate|title|company|location|source|freshness|link|url|posted|tracker|duplicate|error|blocked|next|todo|remaining|apply|job|role|fit)\b/i.test(cleaned)) {
		return cleaned;
	}
	return undefined;
}

function collectUsefulLines(messages: EmergencyMessage[], limit: number): string[] {
	const lines: string[] = [];
	for (const message of messages) {
		const role = String(message.role ?? "");
		if (role === "user") continue;
		const text = emergencyMessageText(message, 9000);
		for (const rawLine of text.split("\n")) {
			const line = usefulLine(rawLine);
			if (line) lines.push(line);
		}
	}
	return uniqueLimited(lines.slice(-Math.max(limit * 2, limit)), limit);
}

function importantRequestLines(text: string, limit: number): string[] {
	const lines: string[] = [];
	for (const rawLine of text.split("\n")) {
		const line = usefulLine(rawLine);
		if (!line) continue;
		if (/\b(?:objective|critical|runtime|hard constraints?|must|do not|don't|only|skip|exclude|include|target|return|final output|tracker|posted within|past 24|source)\b/i.test(line)) {
			lines.push(line);
		}
	}
	return uniqueLimited(lines, limit);
}

function activeRequestSummary(messages: EmergencyMessage[]): string {
	const userTexts = messages
		.filter((message) => message.role === "user")
		.map((message) => emergencyMessageText(message, 9000))
		.filter(Boolean);
	if (userTexts.length === 0) return "Continue the active user request from the preserved context.";

	const first = userTexts[0];
	const latest = userTexts[userTexts.length - 1];
	const parts = [`Initial request excerpt:\n${truncateSnippet(first, 1400)}`];
	if (latest && latest !== first) parts.push(`Latest user follow-up excerpt:\n${truncateSnippet(latest, 900)}`);
	const important = importantRequestLines(first, 18);
	if (important.length > 0) parts.push(`Important request constraints:\n${important.map((line) => `- ${line}`).join("\n")}`);
	return parts.join("\n\n");
}

function stringsFromMaybeSet(value: unknown): string[] {
	if (value instanceof Set) return [...value].filter((item): item is string => typeof item === "string");
	if (Array.isArray(value)) return value.filter((item): item is string => typeof item === "string");
	return [];
}

function fileDetailsFromFileOps(fileOps: unknown): EmergencyCompactionDetails {
	if (!fileOps || typeof fileOps !== "object") return { readFiles: [], modifiedFiles: [] };
	const typed = fileOps as Record<string, unknown>;
	const read = new Set(stringsFromMaybeSet(typed.read));
	const modified = new Set([...stringsFromMaybeSet(typed.edited), ...stringsFromMaybeSet(typed.written)]);
	return {
		readFiles: [...read].filter((file) => !modified.has(file)).sort(),
		modifiedFiles: [...modified].sort(),
	};
}

function buildEmergencyOverflowCompaction(preparation: EmergencyPreparation, branchEntries: readonly unknown[]) {
	const maxSummaryChars = parsePositiveIntEnv("OMLX_EMERGENCY_COMPACTION_MAX_SUMMARY_CHARS", 10000);
	const maxUrls = parsePositiveIntEnv("OMLX_EMERGENCY_COMPACTION_MAX_URLS", 30);
	const maxNotes = parsePositiveIntEnv("OMLX_EMERGENCY_COMPACTION_MAX_NOTES", 28);
	const messages = [...preparation.messagesToSummarize, ...preparation.turnPrefixMessages];
	const branchMessages = branchEntries.map(messageFromEntry).filter((message): message is EmergencyMessage => Boolean(message));
	const extractionMessages = messages.length > 0 ? messages : branchMessages;
	const latestError = latestAssistantErrorMessage(branchEntries);
	const details = fileDetailsFromFileOps(preparation.fileOps);
	const previousSummary = preparation.previousSummary ? truncateSnippet(preparation.previousSummary, 1800) : "";
	const request = activeRequestSummary(extractionMessages);
	const notes = collectUsefulLines(extractionMessages, maxNotes);
	const allText = [previousSummary, ...extractionMessages.map((message) => emergencyMessageText(message, 7000))].join("\n");
	const urls = extractUrls(allText, maxUrls);
	const latestErrorText = latestError?.errorMessage ? truncateSnippet(String(latestError.errorMessage), 900) : "";

	const sections = [
		"## Emergency Overflow Compaction",
		"Generated locally because oMLX hit a context overflow. Verbose raw tool, browser, search, and page output before this checkpoint was intentionally discarded; no pre-compaction messages are kept in live context.",
		"## Active Request",
		request,
	];
	if (previousSummary) sections.push("## Previous Compaction Summary", previousSummary);
	if (notes.length > 0) sections.push("## Preserved Useful Notes", notes.map((line) => `- ${line}`).join("\n"));
	if (urls.length > 0) sections.push("## Preserved URLs", urls.map((url) => `- ${url}`).join("\n"));
	if (details.readFiles.length > 0 || details.modifiedFiles.length > 0) {
		sections.push(
			"## Files Touched",
			`Read: ${details.readFiles.length ? details.readFiles.join(", ") : "none"}\nModified: ${details.modifiedFiles.length ? details.modifiedFiles.join(", ") : "none"}`,
		);
	}
	if (latestErrorText) sections.push("## Latest Overflow Error", latestErrorText);
	sections.push(
		"## Continuation Instructions",
		"Continue the active request from this compacted context. Do not redo completed searches or repeat already completed tool work unless necessary. If enough findings are preserved, finalize from them. If more work is needed, keep it bounded and preserve concise findings instead of raw page dumps.",
	);

	return {
		summary: truncateSnippet(sections.join("\n\n"), maxSummaryChars),
		details,
	};
}

function registerOmlxEmergencyOverflowCompaction(pi: ExtensionAPI) {
	pi.on("session_before_compact", (event, ctx) => {
		if (event.reason !== "overflow") return;
		const latestError = latestAssistantErrorMessage(event.branchEntries);
		if (!isOmlxProvider(ctx.model?.provider) && !isOmlxProvider(latestError?.provider)) return;

		const { summary, details } = buildEmergencyOverflowCompaction(event.preparation as EmergencyPreparation, event.branchEntries);
		return {
			compaction: {
				summary,
				// Deliberately keep no raw pre-compaction messages. The local summary above
				// replaces them so the retry cannot overflow on retained browser/tool output.
				firstKeptEntryId: OMLX_EMERGENCY_KEEP_NONE_ENTRY_ID,
				tokensBefore: event.preparation.tokensBefore,
				details,
			},
		};
	});
}

function registerOmlxOverflowNormalizer(pi: ExtensionAPI) {
	pi.on("message_end", (event, ctx) => {
		const message = event.message;
		if (message.role !== "assistant") return;
		if (message.stopReason !== "error") return;
		if (!isOmlxProvider(message.provider) && !isOmlxProvider(ctx.model?.provider)) return;

		const errorMessage = String(message.errorMessage ?? "");
		if (!errorMessage || errorMessage.includes("context_length_exceeded")) return;
		const isRecoverableOverflow =
			isOmlxPromptTooLongError(errorMessage) || isOmlxPrefillMemoryGuardError(errorMessage);
		if (!isRecoverableOverflow) return;

		return {
			message: {
				...message,
				errorMessage: `context_length_exceeded: ${errorMessage}`,
			},
		};
	});
}

function registerOmlxPrefillMemoryRecovery(pi: ExtensionAPI) {
	const maxConsecutiveRecoveries = parsePositiveIntEnv("OMLX_PREFILL_MEMORY_MAX_RECOVERIES", 3);
	let consecutiveRecoveries = 0;
	let recoveryInFlight = false;
	let recoveryPromptQueued = false;

	const sendRecoveryPrompt = () => {
		recoveryPromptQueued = true;
		try {
			pi.sendUserMessage(OMLX_PREFILL_MEMORY_RECOVERY_PROMPT, { deliverAs: "followUp" });
		} catch {
			try {
				pi.sendUserMessage(OMLX_PREFILL_MEMORY_RECOVERY_PROMPT);
			} catch {
				recoveryPromptQueued = false;
			}
		}
	};

	pi.on("message_end", (event, ctx) => {
		const message = event.message;
		if (message.role === "user") {
			if (recoveryPromptQueued && messageText(message).includes(OMLX_PREFILL_MEMORY_RECOVERY_PROMPT.slice(0, 80))) {
				recoveryPromptQueued = false;
				return;
			}
			consecutiveRecoveries = 0;
			return;
		}
		if (message.role !== "assistant") return;
		if (message.stopReason !== "error") {
			consecutiveRecoveries = 0;
			return;
		}
		if (!isOmlxProvider(message.provider) && !isOmlxProvider(ctx.model?.provider)) return;

		const errorMessage = String(message.errorMessage ?? "");
		if (!errorMessage) return;
		// Pi/OpenAI-compatible clients may prefix the same oMLX memory-guard body with
		// `context_length_exceeded`; still recover if the underlying body matches.
		if (!isOmlxPrefillMemoryGuardError(errorMessage)) return;
		if (recoveryInFlight || consecutiveRecoveries >= maxConsecutiveRecoveries) return;

		consecutiveRecoveries += 1;
		recoveryInFlight = true;

		setTimeout(() => {
			try {
				ctx.compact({
					customInstructions: OMLX_PREFILL_MEMORY_COMPACTION_INSTRUCTIONS,
					onComplete: () => {
						recoveryInFlight = false;
						setTimeout(sendRecoveryPrompt, 0);
					},
					onError: () => {
						recoveryInFlight = false;
					},
				});
			} catch {
				recoveryInFlight = false;
			}
		}, 0);
	});
}

export default function registerOmlxProviderSetupAndRecovery(pi: ExtensionAPI) {
	registerOmlxOverflowNormalizer(pi);
	registerOmlxEmergencyOverflowCompaction(pi);
	registerOmlxPrefillMemoryRecovery(pi);

	const dotenvValues = loadDotEnvValues();
	const apiKey = firstNonEmptyEnv(["OMLX_API_KEY", "DISCORD_VOICE_API_KEY"], dotenvValues) || "local";
	const cache = loadContextWindowCache();
	const resolved: ResolvedProvider[] = OMLX_PROVIDER_SEEDS.map((seed) => {
		const baseUrl = normalizeBaseUrl(firstNonEmptyEnv(seed.baseUrlEnvKeys, dotenvValues) || seed.defaultBaseUrl);
		return { seed, baseUrl, cachedContextByModel: cachedContextWindows(cache, seed, baseUrl) };
	});

	// Register synchronously from the last-known cache (or static seeds on first
	// run), making every provider available before Pi chooses its startup model.
	for (const item of resolved) {
		registerResolvedProvider(pi, item, apiKey, item.cachedContextByModel);
	}

	let refreshStarted = false;
	let refreshTimer: ReturnType<typeof setTimeout> | undefined;
	pi.on("session_start", () => {
		if (isPiOffline() || refreshStarted || refreshTimer) return;

		// Do not return the discovery Promise: session_start is on Pi's critical path.
		// A short grace period lets the TUI/RPC become ready before fetch setup runs.
		refreshTimer = setTimeout(() => {
			refreshTimer = undefined;
			refreshStarted = true;
			void refreshResolvedProviderContexts(pi, resolved, apiKey, cache).catch(() => {
				// Seed/cached registrations remain usable when discovery is unavailable.
			});
		}, BACKGROUND_DISCOVERY_DELAY_MS);
		refreshTimer.unref?.();
	});

	pi.on("session_shutdown", () => {
		if (!refreshTimer) return;
		clearTimeout(refreshTimer);
		refreshTimer = undefined;
	});
}
