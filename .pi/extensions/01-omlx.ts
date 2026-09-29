import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI, ProviderConfig } from "@earendil-works/pi-coding-agent";
import { findAncestorFile, parseDotEnv } from "./lib/env.ts";
import { OMLX_PROVIDER_SEEDS, type ProviderSeed } from "./lib/omlx-seeds.ts";
import { discoverCatalog, isPiOffline, loadCatalogCache, normalizeBaseUrl, providerModels, restoreRecords, type ProviderState } from "./lib/omlx-catalog.ts";
import { isOmlxProvider, isRecoverableOverflow, registerOmlxRecovery, type RecoveryState } from "./lib/omlx-recovery.ts";
import { createOmlxStream } from "./lib/omlx-stream.ts";

const PROJECT_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const CACHE_PATH = join(PROJECT_ROOT, ".pi/runtime/omlx-catalog.json");
const LEGACY_CACHE_PATH = join(PROJECT_ROOT, ".pi/runtime/omlx-context-windows.json");
function envValue(keys: string[], dotenv: Record<string, string>): string | undefined {
	for (const key of keys) {
		const value = process.env[key]?.trim() || dotenv[key]?.trim();
		if (value) return value;
	}
}
function timeoutValue(value: string | undefined): number {
	const n = Number(value); return value !== undefined && Number.isFinite(n) && n >= 0 ? Math.floor(n) : 120000;
}
type Options = { dotenv?: Record<string, string>; cachePath?: string; legacyPath?: string; seeds?: ProviderSeed[]; fetcher?: typeof fetch };

export function registerOmlx(pi: ExtensionAPI, options: Options = {}) {
	const dotenv = options.dotenv ?? parseDotEnv(findAncestorFile(process.cwd(), ".env"));
	const cachePath = options.cachePath ?? CACHE_PATH;
	const cache = loadCatalogCache(cachePath);
	const states: ProviderState[] = (options.seeds ?? OMLX_PROVIDER_SEEDS).map(seed => {
		const baseUrl = normalizeBaseUrl(envValue(seed.baseUrlEnvKeys, dotenv) ?? seed.defaultBaseUrl);
		return { seed, baseUrl,
			apiKey: envValue(seed.apiKeyEnvKeys, dotenv) ?? "local",
			adminSession: envValue(seed.adminSessionEnvKeys, dotenv),
			...restoreRecords(seed, baseUrl, cache, options.legacyPath ?? LEGACY_CACHE_PATH), warnings: [],
		};
	});
	const recovery: RecoveryState = { emptyRetries: 0, overflowCompactions: 0, disableThinkingOnce: false };
	registerOmlxRecovery(pi, recovery);
	let controller = new AbortController();
	let timer: ReturnType<typeof setTimeout> | undefined;
	let started = false;
	let stopped = false;
	const inFlight = new Map<ProviderState, Promise<ReturnType<typeof providerModels>>>();
	const lastStreamErrors = new Map<string, string>();
	pi.on("message_end", (event) => {
		const message = event.message;
		if (message.role === "assistant" && message.stopReason === "error" && isOmlxProvider(message.provider)) {
			lastStreamErrors.set(message.provider, isRecoverableOverflow(message.errorMessage ?? "") ? "Context/memory overflow" : "Provider error (see session response; raw payload omitted)");
		}
	});
	const streams = new Map(states.map(state => {
		const key = state.seed.provider === "omlx-64" ? ["OMLX_64_STREAM_FIRST_DELTA_TIMEOUT_MS", "OMLX_STREAM_FIRST_DELTA_TIMEOUT_MS"] : ["OMLX_STREAM_FIRST_DELTA_TIMEOUT_MS"];
		return [state, createOmlxStream(timeoutValue(envValue(key, dotenv)), error => lastStreamErrors.set(state.seed.provider, error))] as const;
	}));
	async function refresh(state: ProviderState, signal?: AbortSignal) {
		if (stopped || isPiOffline() || signal?.aborted) return providerModels(state);
		// Serialize per-host discovery; different hosts still refresh in parallel.
		// A caller cancellation doesn't abort a different caller's work.
		const existing = inFlight.get(state);
		if (existing) {
			if (!signal) return existing;
			return new Promise<ReturnType<typeof providerModels>>(resolve => {
				const done = () => { signal.removeEventListener("abort", done); resolve(providerModels(state)); };
				signal.addEventListener("abort", done, { once: true });
				void existing.then(done, done);
			});
		}
		const combined = signal ? AbortSignal.any([signal, controller.signal]) : controller.signal;
		const work = discoverCatalog(state, cache, cachePath, combined, options.fetcher);
		inFlight.set(state, work);
		try { return await work; } finally { if (inFlight.get(state) === work) inFlight.delete(state); }
	}
	function config(state: ProviderState): ProviderConfig {
		return {
			name: state.seed.provider === "omlx-64" ? "oMLX 64" : "oMLX",
			baseUrl: state.baseUrl, api: "openai-completions", apiKey: state.apiKey,
			authHeader: true,
			models: providerModels(state), streamSimple: streams.get(state),
			refreshModels: async ({ allowNetwork, signal }) => allowNetwork ? refresh(state, signal) : providerModels(state),
		};
	}
	const register = (state: ProviderState) => pi.registerProvider(state.seed.provider, config(state));
	// Synchronous registration makes startup and --list-models independent of a
	// sleeping server. Never create sockets or timers in the factory itself.
	for (const state of states) register(state);
	async function refreshAll(signal?: AbortSignal) {
		await Promise.all(states.map(async state => {
			await refresh(state, signal);
			if (!stopped && !signal?.aborted) register(state);
		}));
	}
	pi.on("session_start", () => {
		stopped = false;
		if (controller.signal.aborted) controller = new AbortController();
		if (isPiOffline() || started || timer) return;
		timer = setTimeout(() => {
			timer = undefined; started = true;
			void refreshAll().catch(() => { /* Last-known registrations remain usable. */ });
		}, 500);
		timer.unref?.();
	});
	pi.on("session_shutdown", () => {
		stopped = true; started = false;
		if (timer) clearTimeout(timer); timer = undefined;
		controller.abort();
	});
	pi.registerCommand("omlx-status", {
		description: "Inspect oMLX hosts, model limits, thinking and recovery. Add --refresh for live discovery.",
		handler: async (args, ctx) => {
			if (args.trim() && args.trim() !== "--refresh") { ctx.ui.notify("Usage: /omlx-status [--refresh]", "warning"); return; }
			if (args.trim() === "--refresh") await refreshAll(ctx.signal);
			const lines = [isPiOffline() ? "oMLX (PI_OFFLINE: network disabled)" : "oMLX"];
			for (const state of states) {
				const loaded = state.records.filter(r => r.loaded).length;
				lines.push(`\n${state.seed.provider}: ${state.baseUrl}`, `Catalog: ${state.source}; ${state.records.length} chat models; ${loaded} last-reported loaded`,
					`Last success: ${state.lastSuccess ?? "never"}; last attempt: ${state.lastAttempt ?? "not this run"}`);
				if (state.memory) lines.push(`Reported model memory: ${state.memory}`);
				if (state.lastError) lines.push(`Discovery: ${state.lastError}`);
				for (const warning of state.warnings.slice(0, 8)) lines.push(`Warning: ${warning}`);
				for (const record of state.records.slice(0, 20)) lines.push(`  ${record.name}${record.name === record.id ? "" : ` [${record.id}]`}: ctx ${record.contextWindow}, output ${record.maxTokens}, ${record.vision ? "text+image" : "text"}, ${record.limitSource}`);
				if (state.records.length > 20) lines.push(`  … ${state.records.length - 20} more models`);
				if (lastStreamErrors.has(state.seed.provider)) lines.push(`Last stream issue: ${lastStreamErrors.get(state.seed.provider)}`);
			}
			if (ctx.model) {
				lines.push(`\nActive: ${ctx.model.provider}/${ctx.model.id}; thinking ${pi.getThinkingLevel()}`,
					`Effective Pi limits: ctx ${ctx.model.contextWindow}, output ${ctx.model.maxTokens}`);
				const state = states.find(s => s.seed.provider === ctx.model?.provider);
				const record = state?.records.find(r => r.id === ctx.model?.id);
				if (record?.forcedCtKwargs.length) lines.push(`Server-enforced template keys (may block overrides): ${record.forcedCtKwargs.join(", ")}`);
			}
			lines.push(`Recovery: ${recovery.lastAction ?? "none"}; ${recovery.overflowCompactions} emergency checkpoints this session`);
			// UI-only: diagnostics do not pollute model context or expose credentials.
			ctx.ui.notify(lines.join("\n"), "info");
		},
	});
	return { states, recovery, refreshAll };
}

export default function omlx(pi: ExtensionAPI) { registerOmlx(pi); }
