import type { ExtensionAPI, ProviderConfig, ProviderModelConfig } from "@earendil-works/pi-coding-agent";

import { findAncestorFile, parseDotEnv } from "./lib/env";

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

	// This is the oMLX server's active per-model setting — the value shown in the
	// admin UI and actually configured for the model. It can differ from both the
	// model metadata exposed by /v1/models (`max_model_len`) and the raw model
	// generation config default.
	const adminModels = await fetchJson(`${rootUrl}/admin/api/models`) as { models?: unknown } | undefined;
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
		const globalSettings = await fetchJson(`${rootUrl}/admin/api/global-settings`) as { sampling?: unknown } | undefined;
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
	const contextByModel = await fetchListedContextWindows(baseUrl);
	const adminContextByModel = await fetchAdminSettingsContextWindows(baseUrl, modelIds);
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
		if (!errorMessage || errorMessage.includes("context_length_exceeded")) return;
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

export default async function registerOmlxProviderSetupAndRecovery(pi: ExtensionAPI) {
	registerOmlxOverflowNormalizer(pi);
	registerOmlxPrefillMemoryRecovery(pi);

	const dotenvValues = loadDotEnvValues();
	const apiKey = firstNonEmptyEnv(["OMLX_API_KEY", "DISCORD_VOICE_API_KEY"], dotenvValues) || "local";
	const contextByBaseUrl = new Map<string, Promise<Map<string, number>>>();

	const resolved = OMLX_PROVIDER_SEEDS.map((seed) => {
		const baseUrl = normalizeBaseUrl(firstNonEmptyEnv(seed.baseUrlEnvKeys, dotenvValues) || seed.defaultBaseUrl);
		const modelIds = seed.models.map((model) => model.id);
		if (!contextByBaseUrl.has(baseUrl)) contextByBaseUrl.set(baseUrl, fetchContextWindows(baseUrl, modelIds));
		return { seed, baseUrl, contextPromise: contextByBaseUrl.get(baseUrl)! };
	});

	for (const item of resolved) {
		const contextByModel = await item.contextPromise;
		pi.registerProvider(item.seed.provider, {
			baseUrl: item.baseUrl,
			api: "openai-completions",
			apiKey,
			compat: item.seed.compat,
			models: mergedModels(item.seed, contextByModel),
		});
	}
}
