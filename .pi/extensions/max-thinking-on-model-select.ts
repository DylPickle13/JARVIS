import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const HIGHEST_THINKING_LEVEL = "xhigh";

export default function maxThinkingOnModelSelect(pi: ExtensionAPI) {
  pi.on("model_select", async (event) => {
    // Keep restored sessions untouched, but maximize thinking whenever you actively
    // switch models via Ctrl+P/Shift+Ctrl+P or the /model selector.
    if (event.source !== "cycle" && event.source !== "set") {
      return;
    }

    // Pi clamps this to the selected model's highest supported level:
    // xhigh -> high -> medium -> low -> minimal -> off.
    pi.setThinkingLevel(HIGHEST_THINKING_LEVEL);
  });
}
