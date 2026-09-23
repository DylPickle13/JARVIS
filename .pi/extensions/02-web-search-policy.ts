import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

/** Keep search content fetching explicit: never launch later-turn background fetches. */
export default function (pi: ExtensionAPI) {
  pi.on("tool_call", (event) => {
    if (event.toolName === "web_search") {
      event.input.includeContent = false;
    }
  });
}
