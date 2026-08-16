import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const DEFAULT_THINKING_LEVEL = "xhigh";

export default function thinkingLevelOnModelSelect(pi: ExtensionAPI) {
  pi.on("model_select", async (event, ctx) => {
    // Keep restored sessions untouched. Active model switches honor any thinking
    // level pinned in enabledModels/--models, with xhigh as the fallback.
    if (event.source !== "cycle" && event.source !== "set") {
      return;
    }

    const scopedSelection = ctx.scopedModels.find(
      ({ model }) => model.provider === event.model.provider && model.id === event.model.id,
    );
    pi.setThinkingLevel(scopedSelection?.thinkingLevel ?? DEFAULT_THINKING_LEVEL);
  });
}
