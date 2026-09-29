import { createAssistantMessageEventStream, type AssistantMessage } from "@earendil-works/pi-ai";
import { openAICompletionsApi } from "@earendil-works/pi-ai/compat";
import type { ProviderConfig } from "@earendil-works/pi-coding-agent";

// Delegate directly to Pi's implementation, not the provider dispatcher (which
// would dispatch straight back into this wrapper). Preserve all instrumentation.
const concreteStream = openAICompletionsApi().streamSimple;
type Stream = NonNullable<ProviderConfig["streamSimple"]>;

export function createOmlxStream(timeoutMs: number, report: (message: string) => void, inner: Stream = concreteStream): Stream {
	return (model, context, options) => {
		if (timeoutMs <= 0) return inner(model, context, options);
		const output = createAssistantMessageEventStream();
		const controller = new AbortController();
		const signal = options?.signal ? AbortSignal.any([options.signal, controller.signal]) : controller.signal;
		let timedOut = false;
		let timer: ReturnType<typeof setTimeout> | undefined;
		const clear = () => { if (timer) clearTimeout(timer); timer = undefined; };
		const arm = () => {
			if (timer || signal.aborted) return;
			timer = setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs);
		};
		// Includes connecting, loading and prefill. Keepalive/start events do not
		// count as progress. No transparent retry: never replay emitted tool calls.
		arm();
		void (async () => {
			let partial: AssistantMessage | undefined;
			let terminal = false;
			try {
				for await (const event of inner(model, context, { ...options, signal })) {
					if ("partial" in event) partial = event.partial;
					if ("message" in event) partial = event.message;
					if ("error" in event) partial = event.error;
					if (timedOut) break;
					if ((event.type === "text_delta" && event.delta.trim()) ||
						(event.type === "thinking_delta" && event.delta.trim()) ||
						(event.type === "toolcall_delta" && event.delta.length > 0) || event.type === "toolcall_end") clear();
					if (event.type === "done" || event.type === "error") { terminal = true; clear(); }
					output.push(event);
				}
				if (!terminal) {
					const errorMessage = timedOut ? `oMLX first-delta timeout after ${timeoutMs}ms (includes connection, load and prefill); no request was replayed.` : signal.aborted ? "oMLX request cancelled" : "oMLX stream ended without a terminal event";
					report(errorMessage);
					const reason = signal.aborted && !timedOut ? "aborted" : "error";
					output.push({ type: "error", reason, error: errorMessageFor(model, errorMessage, reason, partial) });
				}
			} catch {
				const reason = signal.aborted && !timedOut ? "aborted" : "error";
				const errorMessage = timedOut ? `oMLX first-delta timeout after ${timeoutMs}ms; no request was replayed.` : reason === "aborted" ? "oMLX request cancelled" : "oMLX stream failed";
				report(errorMessage);
				if (!terminal) output.push({ type: "error", reason, error: errorMessageFor(model, errorMessage, reason, partial) });
			} finally { clear(); output.end(); }
		})();
		return output;
	};
}

function errorMessageFor(model: Parameters<Stream>[0], errorMessage: string, stopReason: "error" | "aborted", partial?: AssistantMessage): AssistantMessage {
	return {
		...(partial ?? {
			role: "assistant", api: model.api, provider: model.provider, model: model.id,
			content: [], timestamp: Date.now(),
			usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
				cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
		}),
		stopReason, errorMessage,
	};
}
