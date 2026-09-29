import { chmodSync, mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import { randomUUID } from "node:crypto";
import { LOCAL_ZERO_COST, OMLX_COMPAT, type ChatModel, type ProviderSeed } from "./omlx-seeds.ts";

export type CatalogRecord = {
	id: string;
	name: string;
	contextWindow: number;
	maxTokens: number;
	vision: boolean;
	reasoning: boolean;
	thinkingDefault?: boolean;
	preserveThinkingDefault?: boolean;
	effortOptions?: string[];
	loaded?: boolean;
	forcedCtKwargs: string[];
	limitSource: string;
};
export type CatalogCache = { version: 2; providers: Record<string, { baseUrl: string; updatedAt: string; models: CatalogRecord[] }> };
export type ProviderState = {
	seed: ProviderSeed;
	baseUrl: string;
	apiKey: string;
	adminSession?: string;
	records: CatalogRecord[];
	source: "live" | "cache" | "fallback";
	lastSuccess?: string;
	lastAttempt?: string;
	lastError?: string;
	warnings: string[];
	memory?: string;
};
type JsonObject = Record<string, unknown>;
export const object = (value: unknown): JsonObject => value && typeof value === "object" && !Array.isArray(value) ? value as JsonObject : {};
export function positiveInt(value: unknown): number | undefined {
	if (typeof value !== "number" && typeof value !== "string") return;
	const n = Number(value);
	return Number.isFinite(n) && n >= 1 ? Math.floor(n) : undefined;
}
const text = (value: unknown): string | undefined => typeof value === "string" && value.trim() ? value.trim() : undefined;
const bool = (value: unknown): boolean | undefined => typeof value === "boolean" ? value : undefined;
const strings = (value: unknown): string[] => Array.isArray(value) ? value.filter((v): v is string => typeof v === "string" && v.length < 128) : [];
export function normalizeBaseUrl(raw: string): string {
	const url = new URL(raw.trim());
	if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash) {
		throw new Error("oMLX endpoint must be HTTP(S), without embedded credentials, query or fragment");
	}
	const base = url.href.replace(/\/+$/, "");
	return base.endsWith("/v1") ? base : `${base}/v1`;
}
export function isPiOffline(): boolean { return /^(?:1|true|yes)$/i.test(process.env.PI_OFFLINE?.trim() ?? ""); }
export function seedRecords(seed: ProviderSeed): CatalogRecord[] {
	return seed.models.map(m => ({ id: m.id, name: m.name, contextWindow: m.contextWindow,
		maxTokens: m.maxTokens, vision: m.input.includes("image"), reasoning: m.reasoning,
		forcedCtKwargs: [], limitSource: "fallback" }));
}

export function modelFromRecord(record: CatalogRecord, seed: ProviderSeed): ChatModel {
	const override = seed.models.find(m => m.id === record.id);
	let compat: ChatModel["compat"];
	let thinkingLevelMap: ChatModel["thinkingLevelMap"];
	if (record.effortOptions?.length) {
		thinkingLevelMap = {};
		for (const level of ["minimal", "low", "medium", "high", "xhigh", "max"] as const) {
			thinkingLevelMap[level] = record.effortOptions.includes(level) ? level : null;
		}
		if (record.thinkingDefault === undefined) {
			// Effort-only templates must receive an explicit off value too.
			thinkingLevelMap.off = "none";
			compat = { supportsReasoningEffort: true };
		} else compat = {
			thinkingFormat: "chat-template",
			chatTemplateKwargs: {
				enable_thinking: { $var: "thinking.enabled" },
				...(record.preserveThinkingDefault === undefined ? {} : { preserve_thinking: record.preserveThinkingDefault }),
				reasoning_effort: { $var: "thinking.effort", omitWhenOff: true },
			},
		};
	} else if (record.thinkingDefault !== undefined) {
		compat = { thinkingFormat: "chat-template", chatTemplateKwargs: {
			enable_thinking: { $var: "thinking.enabled" },
			...(record.preserveThinkingDefault === undefined ? {} : { preserve_thinking: record.preserveThinkingDefault }),
		} };
	}
	// Known models keep our verified thinking policy, not their stale seed limits.
	return {
		id: record.id, name: record.name, input: record.vision ? ["text", "image"] : ["text"],
		contextWindow: record.contextWindow, maxTokens: record.maxTokens,
		reasoning: override?.reasoning ?? record.reasoning, cost: LOCAL_ZERO_COST,
		...(thinkingLevelMap ? { thinkingLevelMap } : {}),
		compat: { ...OMLX_COMPAT, ...compat, ...override?.compat },
		...(override?.thinkingLevelMap ? { thinkingLevelMap: override.thinkingLevelMap } : {}),
	};
}
export const providerModels = (state: ProviderState): ChatModel[] => state.records.map(r => modelFromRecord(r, state.seed));

function validCachedRecord(value: unknown): CatalogRecord | undefined {
	const v = object(value), id = text(v.id), contextWindow = positiveInt(v.contextWindow), maxTokens = positiveInt(v.maxTokens);
	if (!id || !contextWindow || !maxTokens) return;
	return { id, name: text(v.name) ?? id, contextWindow, maxTokens,
		vision: v.vision === true, reasoning: v.reasoning === true,
		thinkingDefault: bool(v.thinkingDefault), preserveThinkingDefault: bool(v.preserveThinkingDefault),
		effortOptions: strings(v.effortOptions), loaded: bool(v.loaded), forcedCtKwargs: strings(v.forcedCtKwargs),
		limitSource: text(v.limitSource) ?? "cache" };
}
export function loadCatalogCache(path: string): CatalogCache {
	const cache: CatalogCache = { version: 2, providers: {} };
	try {
		const data = object(JSON.parse(readFileSync(path, "utf8")));
		if (data.version !== 2) return cache;
		for (const [id, value] of Object.entries(object(data.providers))) {
			const entry = object(value);
			if (typeof entry.baseUrl !== "string" || !Array.isArray(entry.models)) continue;
			const seen = new Set<string>();
			const models = entry.models.map(validCachedRecord).filter((r): r is CatalogRecord => {
				if (!r || seen.has(r.id)) return false;
				seen.add(r.id); return true;
			});
			cache.providers[id] = { baseUrl: entry.baseUrl, updatedAt: text(entry.updatedAt) ?? "", models };
		}
	} catch { /* First run or corrupt cache: seeds remain available. */ }
	return cache;
}
export function persistCatalogCache(path: string, cache: CatalogCache): boolean {
	const temporary = `${path}.${process.pid}.${randomUUID()}.tmp`;
	try {
		mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
		writeFileSync(temporary, `${JSON.stringify(cache, null, 2)}\n`, { mode: 0o600 });
		chmodSync(temporary, 0o600); renameSync(temporary, path); chmodSync(path, 0o600);
		return true;
	} catch { try { rmSync(temporary, { force: true }); } catch {} return false; }
}
export function restoreRecords(seed: ProviderSeed, baseUrl: string, cache: CatalogCache, legacyPath?: string): { records: CatalogRecord[]; source: ProviderState["source"]; lastSuccess?: string } {
	const stored = cache.providers[seed.provider];
	if (stored?.baseUrl === baseUrl && stored.models.length) return { records: stored.models, source: "cache", lastSuccess: stored.updatedAt };
	const records = seedRecords(seed);
	// One-way migration of the old private context-window cache; no credentials.
	try {
		if (legacyPath) {
			const legacy = object(JSON.parse(readFileSync(legacyPath, "utf8")));
			const entry = object(object(legacy.providers)[seed.provider]);
			if (legacy.version === 1 && entry.baseUrl === baseUrl) {
				for (const r of records) r.contextWindow = positiveInt(object(entry.models)[r.id]) ?? r.contextWindow;
				return { records, source: "cache", lastSuccess: text(entry.updatedAt) };
			}
		}
	} catch { /* Fall back to seeds. */ }
	return { records, source: "fallback" };
}

type FetchResult = { value?: unknown; error?: string };
export async function fetchJson(url: string, state: Pick<ProviderState, "apiKey" | "adminSession">, signal?: AbortSignal, timeoutMs = 2500, fetcher: typeof fetch = fetch): Promise<FetchResult> {
	const controller = new AbortController();
	const abort = () => controller.abort();
	if (signal?.aborted) controller.abort(); else signal?.addEventListener("abort", abort, { once: true });
	const timer = setTimeout(abort, timeoutMs);
	const headers: Record<string, string> = { accept: "application/json" };
	if (state.apiKey) headers.authorization = `Bearer ${state.apiKey}`;
	if (new URL(url).pathname.includes("/admin/") && state.adminSession) headers.cookie = `omlx_admin_session=${state.adminSession}`;
	try {
		const res = await fetcher(url, { headers, signal: controller.signal, redirect: "error" });
		if (!res.ok) return { error: `HTTP ${res.status}` };
		return { value: await res.json() };
	} catch {
		// Never include exception bodies: URLs, cookies or credentials may be echoed.
		return { error: signal?.aborted ? "cancelled" : controller.signal.aborted ? "timeout" : "unreachable or invalid JSON" };
	} finally { clearTimeout(timer); signal?.removeEventListener("abort", abort); }
}
function contextLimit(v: JsonObject): number | undefined {
	for (const key of ["max_context_window", "max_model_len", "maxModelLen", "max_context_length", "maxContextLength", "context_length", "contextLength", "context_window", "contextWindow"]) {
		const n = positiveInt(v[key]); if (n) return n;
	}
	const meta = object(v.metadata);
	return Object.keys(meta).length ? contextLimit({ ...meta, metadata: undefined }) : undefined;
}
const modelEntries = (value: unknown, key: string): JsonObject[] => {
	const array = object(value)[key]; return Array.isArray(array) ? array.map(object).filter(v => text(v.id)) : [];
};
const chatTypes = new Set(["llm", "vlm", "text", "chat", "language", "vision", "causal_lm"]);

export async function discoverCatalog(state: ProviderState, cache: CatalogCache, cachePath: string, signal?: AbortSignal, fetcher: typeof fetch = fetch): Promise<ChatModel[]> {
	if (isPiOffline() || signal?.aborted) return providerModels(state);
	state.lastAttempt = new Date().toISOString();
	const root = state.baseUrl.replace(/\/v1$/, "");
	const [status, listed, admin, global, runtime] = await Promise.all([
		fetchJson(`${state.baseUrl}/models/status`, state, signal, 2500, fetcher),
		fetchJson(`${state.baseUrl}/models`, state, signal, 2500, fetcher),
		fetchJson(`${root}/admin/api/models`, state, signal, 2500, fetcher),
		fetchJson(`${root}/admin/api/global-settings`, state, signal, 2500, fetcher),
		fetchJson(`${root}/api/status`, state, signal, 2500, fetcher),
	]);
	if (signal?.aborted) return providerModels(state); // Cancelled work must not mutate or persist catalog state.
	const hasStatus = Array.isArray(object(status.value).models);
	const hasList = Array.isArray(object(listed.value).data);
	if (!hasStatus && !hasList) {
		state.lastError = `Discovery failed: model status ${status.error ?? "invalid response"}; model list ${listed.error ?? "invalid response"}`;
		return providerModels(state);
	}
	const warnings: string[] = [];
	if (admin.error || global.error) warnings.push(`Admin limits unavailable (${admin.error ?? global.error}); using public metadata. Configure a per-host ADMIN_SESSION cookie if admin access is required.`);
	if (!hasStatus) warnings.push(`Model status unavailable (${status.error ?? "invalid response"}); using model list.`);
	const listedById = new Map(modelEntries(listed.value, "data").map(v => [String(v.id), v]));
	const adminById = new Map(modelEntries(admin.value, "models").map(v => [String(v.id), object(v.settings)]));
	const defaults = object(object(global.value).sampling);
	const records: CatalogRecord[] = [], seen = new Set<string>();
	for (const entry of modelEntries(hasStatus ? status.value : listed.value, hasStatus ? "models" : "data")) {
		const id = String(entry.id).trim();
		if (!id || seen.has(id)) continue;
		seen.add(id);
		const listedEntry = listedById.get(id) ?? {};
		const type = text(entry.model_type) ?? text(entry.engine_type) ?? text(listedEntry.model_type);
		if (type && !chatTypes.has(type.toLowerCase())) continue;
		if (entry.is_hidden === true) continue;
		const seed = state.seed.models.find(m => m.id === id);
		const previous = state.records.find(m => m.id === id);
		const settings = adminById.get(id) ?? {};
		const adminContext = contextLimit(settings), statusContext = hasStatus ? contextLimit(entry) : positiveInt(entry.max_context_window), globalContext = contextLimit(defaults), archContext = contextLimit(listedEntry);
		let contextWindow = adminContext ?? statusContext ?? globalContext ?? archContext ?? previous?.contextWindow ?? seed?.contextWindow;
		const maxTokens = positiveInt(settings.max_tokens) ?? positiveInt(entry.max_tokens) ?? positiveInt(defaults.max_tokens) ?? previous?.maxTokens ?? seed?.maxTokens;
		if (!contextWindow || !maxTokens) { warnings.push(`Skipped ${id}: missing verified context/output limits.`); continue; }
		if (archContext) contextWindow = Math.min(contextWindow, archContext);
		const kwargs = object(settings.chat_template_kwargs ?? entry.chat_template_kwargs);
		const thinkingDefault = bool(kwargs.enable_thinking) ?? bool(entry.enable_thinking) ?? bool(entry.thinking_default);
		const preserveThinkingDefault = bool(kwargs.preserve_thinking) ?? bool(entry.preserve_thinking_default) ?? bool(entry.preserve_thinking);
		const effortOptions = strings(entry.reasoning_effort_options).filter(v => ["minimal", "low", "medium", "high", "xhigh", "max"].includes(v));
		const modalities = strings(entry.input ?? object(entry.architecture).input_modalities);
		// config_model_type is a Hugging Face architecture (e.g. qwen3_5),
		// not a modality. Only explicit overrides or the server's runtime type
		// determine whether the loaded engine accepts images.
		const overrideType = text(settings.model_type_override) ?? text(entry.model_type_override) ?? text(entry.engine_type) ?? type;
		const vision = modalities.includes("image") || overrideType?.toLowerCase() === "vlm" || (!overrideType && previous?.vision === true);
		const contextSource = adminContext ? "admin per-model" : statusContext ? (hasStatus ? "model status" : "model list") : globalContext ? "admin global" : archContext ? "model metadata" : "cached/seed";
		const outputSource = positiveInt(settings.max_tokens) ? "admin per-model" : positiveInt(entry.max_tokens) ? (hasStatus ? "model status" : "model list") : positiveInt(defaults.max_tokens) ? "admin global" : "cached/seed";
		records.push({ id, name: text(entry.display_name) ?? text(entry.model_alias) ?? text(entry.name) ?? id,
			contextWindow, maxTokens, vision: vision || (!overrideType && seed?.input.includes("image") === true),
			reasoning: effortOptions.length > 0 || thinkingDefault !== undefined || entry.reasoning === true || seed?.reasoning === true,
			thinkingDefault, preserveThinkingDefault, effortOptions, loaded: bool(entry.loaded),
			forcedCtKwargs: strings(settings.forced_ct_kwargs ?? entry.forced_ct_kwargs),
			limitSource: `context ${contextSource}; output ${outputSource}`,
		});
	}
	// A transient/incompatible empty response should not destroy an offline catalog.
	if (!records.length) {
		state.lastError = "No usable chat models discovered; retaining last-known models.";
		state.warnings = warnings; return providerModels(state);
	}
	state.records = records; state.source = "live"; state.lastSuccess = new Date().toISOString(); state.lastError = undefined; state.warnings = warnings;
	const stats = object(runtime.value);
	const used = text(stats.model_memory_used_formatted), max = text(stats.model_memory_max_formatted);
	state.memory = used && max ? `${used} / ${max}` : undefined;
	cache.providers[state.seed.provider] = { baseUrl: state.baseUrl, updatedAt: state.lastSuccess, models: records };
	if (!persistCatalogCache(cachePath, cache)) state.warnings.push("Catalog is live, but the private cache could not be saved.");
	return providerModels(state);
}
