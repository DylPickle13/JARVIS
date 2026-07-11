import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const DEFAULT_THINKING_LEVEL = "xhigh";

export default function xhighThinkingOnModelSelect(pi: ExtensionAPI) {
  pi.on("model_select", async (event) => {
    // Keep restored sessions untouched, but use xhigh whenever you actively switch
    // models via Ctrl+P/Shift+Ctrl+P or the /model selector.
    if (event.source !== "cycle" && event.source !== "set") {
      return;
    }

    // Pi clamps this if the selected model does not support xhigh.
    pi.setThinkingLevel(DEFAULT_THINKING_LEVEL);
  });
}
