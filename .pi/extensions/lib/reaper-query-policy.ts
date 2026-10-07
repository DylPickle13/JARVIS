// REAPER-specific query guidance, shared by the tool schemas and the explicit /
// automatic group-loading playbooks. The Actions-window overflow came from an
// assistant-generated SSH/AppleScript query, not from a built-in bridge query.
// Keep this policy scoped to REAPER; it does not change generic SSH execution.
export const REAPER_QUERY_GUIDELINES = [
  "Keep REAPER inspection queries narrow: return only requested fields or counts, filter by track/item/FX/action identity before enumeration, and page collections with explicit offsets and limits.",
  "Bound reaper_lua inspection results at source: normally at most 50 rows and 8 KiB of text per query. Do not dump complete project/track state chunks, all FX parameters, or the entire action catalog; request smaller pages instead.",
  "A reaper_ping timeout means the bridge is unavailable, not permission to launch REAPER, change routing, start transport/recording, or repeat a possibly completed write. Diagnose only within the owner's existing authorization.",
  "For owner-authorized REAPER bridge startup via SSH/AppleScript, inspect window names and specific controls directly. Filter the Actions list by the exact bridge name before inspecting at most 20 matching rows. Never request `entire contents` of REAPER windows or the application, or dump the full accessibility tree.",
  "Bound REAPER UI query output before printing: select scalar names/values rather than raw UI object lists, cap each text field and the total serialized output to 8 KiB, and return counts/has_more for additional rows. If larger diagnostics are authorized, save them privately and print only their path and a brief summary, never the full stdout.",
];
