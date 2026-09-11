import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const TIME_ZONE = "America/Toronto";

function formatCurrentLocalDate(now: Date): string {
  return new Intl.DateTimeFormat("en-US", {
    timeZone: TIME_ZONE,
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
  }).format(now);
}

export default function registerCurrentDateContext(pi: ExtensionAPI) {
  pi.on("before_agent_start", (event) => ({
    systemPrompt: `${event.systemPrompt}\n\nCurrent local date at the start of this turn: ${formatCurrentLocalDate(new Date())} (${TIME_ZONE}). Interpret relative dates from this value; never guess them.`,
  }));
}
