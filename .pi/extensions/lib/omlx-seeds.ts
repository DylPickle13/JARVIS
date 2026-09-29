import type { ProviderModelConfig } from "@earendil-works/pi-coding-agent";

export type ChatModel = Extract<ProviderModelConfig, { maxTokens: number }>;
export type ProviderSeed = {
	provider: string;
	baseUrlEnvKeys: string[];
	apiKeyEnvKeys: string[];
	adminSessionEnvKeys: string[];
	defaultBaseUrl: string;
	models: ChatModel[];
};

export const OMLX_COMPAT: ChatModel["compat"] = {
	supportsDeveloperRole: false,
	supportsReasoningEffort: false,
	maxTokensField: "max_tokens",
};
export const LOCAL_ZERO_COST = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } as const;
const qwen = (id: string, contextWindow: number): ChatModel => ({
	id, name: id, reasoning: true, input: ["text", "image"],
	contextWindow, maxTokens: 32768, cost: LOCAL_ZERO_COST,
	compat: { thinkingFormat: "qwen-chat-template" },
});
const qwen38 = (id: string): ChatModel => ({
	...qwen(id, 262144),
	thinkingLevelMap: { minimal: "low", low: "low", medium: "medium", high: "xhigh", xhigh: "xhigh", max: null },
	compat: {
		thinkingFormat: "chat-template",
		chatTemplateKwargs: {
			enable_thinking: { $var: "thinking.enabled" },
			preserve_thinking: true,
			reasoning_effort: { $var: "thinking.effort", omitWhenOff: true },
		},
	},
});

// Verified request-shaping overrides; limits are offline/first-run fallbacks.
export const OMLX_PROVIDER_SEEDS: ProviderSeed[] = [
	{
		provider: "omlx",
		baseUrlEnvKeys: ["OMLX_BASE_URL", "JARVIS_VOICE_BASE_URL"],
		apiKeyEnvKeys: ["OMLX_API_KEY", "JARVIS_VOICE_API_KEY"],
		adminSessionEnvKeys: ["OMLX_ADMIN_SESSION"],
		defaultBaseUrl: "http://127.0.0.1:8000/v1",
		models: [qwen("Qwen3.5-9B-4bit", 24576)],
	},
	{
		provider: "omlx-64",
		baseUrlEnvKeys: ["OMLX_64_BASE_URL"],
		apiKeyEnvKeys: ["OMLX_64_API_KEY", "OMLX_API_KEY", "JARVIS_VOICE_API_KEY"],
		adminSessionEnvKeys: ["OMLX_64_ADMIN_SESSION"],
		defaultBaseUrl: "http://127.0.0.1:8000/v1",
		models: [qwen38("Qwen3.8-27B-4bit"), qwen38("Qwen3.8-27B-Uncensored-MLX-4bit"), qwen("Qwen3.6-35B-A3B-4bit", 262144)],
	},
];
