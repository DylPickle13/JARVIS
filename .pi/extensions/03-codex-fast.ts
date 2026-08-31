import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export default function registerCodexFastMode(pi: ExtensionAPI) {
  let enabled = false;

  pi.registerCommand("fast", {
    description: "Control Codex Fast mode: /fast [on|off|status]",
    handler: async (args, ctx) => {
      const action = args.trim().toLowerCase();

      if (action === "on") {
        enabled = true;
      } else if (action === "off") {
        enabled = false;
      } else if (action !== "" && action !== "status") {
        ctx.ui.notify("Usage: /fast [on|off|status]", "error");
        return;
      }

      ctx.ui.notify(`Codex Fast mode: ${enabled ? "on" : "off"}`, "info");
    },
  });

  pi.on("before_provider_request", (event, ctx) => {
    if (!enabled || ctx.model?.provider !== "openai-codex" || !isRecord(event.payload)) {
      return;
    }

    return {
      ...event.payload,
      service_tier: "priority",
    };
  });
}
