import { openAICompletionsApi } from "@earendil-works/pi-ai/compat";
import type { ProviderConfig } from "@earendil-works/pi-coding-agent";

type Stream = NonNullable<ProviderConfig["streamSimple"]>;

// Use the concrete implementation to avoid dispatching back into this provider.
// No first-output deadline: model loading and prefill may take arbitrarily long.
// Pi retains ownership of instrumentation, cancellation and transport errors.
export function createOmlxStream(inner: Stream = openAICompletionsApi().streamSimple): Stream {
	return inner;
}
