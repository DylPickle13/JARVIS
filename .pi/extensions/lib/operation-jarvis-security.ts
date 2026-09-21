import { spawn } from "node:child_process";
import { join } from "node:path";

export type SecurityResult = { code: number; payload: any };
export type SecurityRunner = (dir: string, args: string[], signal?: AbortSignal) => Promise<SecurityResult>;
const MAX_OUTPUT = 256 * 1024;

// Fixed executable, no shell, minimal environment, no stderr propagation/retries.
// Kill the whole dedicated process group, including the CLI's isolated workers.
export const runSecurity: SecurityRunner = (dir, args, signal) => new Promise((resolve, reject) => {
  if (signal?.aborted) return reject(new Error("security_cancelled"));
  const child = spawn(join(dir, "security"), ["--json", ...args], {
    cwd: dir, detached: true, stdio: ["ignore", "pipe", "ignore"],
    env: Object.fromEntries(["PATH", "HOME", "TMPDIR", "LANG"].flatMap(k => process.env[k] ? [[k, process.env[k]!]] : [])),
  });
  let size = 0, failure = "", settled = false;
  const chunks: Buffer[] = [];
  const kill = () => { try { if (child.pid) process.kill(-child.pid, "SIGKILL"); } catch {} };
  const stop = (reason: string) => { failure ||= reason; kill(); };
  const aborted = () => stop("security_cancelled");
  const timer = setTimeout(() => stop("security_timeout"), 120_000);
  const cleanup = () => { clearTimeout(timer); signal?.removeEventListener("abort", aborted); kill(); };
  signal?.addEventListener("abort", aborted, { once: true });
  if (signal?.aborted) aborted();
  child.stdout.on("data", chunk => {
    size += chunk.length;
    if (size > MAX_OUTPUT) stop("security_output_limit");
    else chunks.push(chunk);
  });
  child.on("error", () => {
    if (settled) return;
    settled = true; cleanup(); reject(new Error("security_launcher_unavailable"));
  });
  child.on("close", code => {
    if (settled) return;
    settled = true; cleanup();
    if (failure) return reject(new Error(failure));
    try {
      const payload = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      if (!payload || typeof payload !== "object" || Array.isArray(payload)) throw new Error();
      resolve({ code: code ?? 2, payload });
    } catch { reject(new Error("security_invalid_output")); }
  });
});

const MODELS = new Set(["H200", "C230", "D235", "T100", "T110"]);
const RESULTS = new Set(["configured", "read_succeeded", "unchanged", "write_verified", "write_outcome_unknown", "error", "cancelled"]);
const FEATURES = new Set(["state", "led", "motion_detection", "person_detection", "pet_detection", "baby_cry_detection", "tamper_detection", "alarm_sound", "alarm_volume", "alarm_duration", "alarm", "rssi", "signal_level", "device_time", "battery_low", "motion_detected", "is_open"]);
export function alias(value: unknown): string {
  if (typeof value !== "string" || !/^[a-z][a-z0-9-]{0,39}$/.test(value)) throw new Error("Configured device alias required");
  return value;
}
export function ruleSummary(rule: any) {
  if (!rule || typeof rule.name !== "string" || !rule.name.trim() || rule.name.length > 128 || /[\x00-\x1f]/.test(rule.name)
      || !/^[a-f0-9]{16}$/.test(rule.ref) || !/^[a-f0-9]{64}$/.test(rule.revision)
      || !["automation", "shortcut"].includes(rule.kind) || typeof rule.enabled !== "boolean") throw new Error("security_invalid_rule_summary");
  return { name: rule.name, ref: rule.ref, revision: rule.revision, kind: rule.kind, enabled: rule.enabled };
}
export function rulesFrom(payload: any) {
  if (payload.result !== "read_succeeded" || !Array.isArray(payload.rules) || payload.rules.length > 100) throw new Error("security_invalid_listing");
  const rules = payload.rules.map(ruleSummary);
  if (new Set(rules.map((r: any) => r.ref)).size !== rules.length) throw new Error("security_ambiguous_listing");
  return rules;
}
export function resolveRule(payload: any, name: unknown) {
  if (typeof name !== "string" || !name.trim()) throw new Error("Automation name required; list first if unknown");
  const matches = rulesFrom(payload).filter((r: any) => r.name.normalize("NFC").toLowerCase() === name.trim().normalize("NFC").toLowerCase());
  if (matches.length !== 1) throw new Error("Automation name missing or ambiguous; list current rules");
  return matches[0];
}
function scalar(value: unknown): unknown {
  if (value === null || typeof value === "boolean" || (typeof value === "number" && Number.isFinite(value))) return value;
  if (typeof value === "string" && /^[A-Za-z0-9 _().:+/\-]{1,100}$/.test(value)) return value;
  return null;
}
export function projectSecurity(payload: any): any {
  const result: any = {
    result: RESULTS.has(payload.result) ? payload.result : "error",
    security_assessment: "not_assessed",
    observed_at: typeof payload.observed_at === "string" && /^\d{4}-\d\d-\d\dT[0-9:.+Z-]+$/.test(payload.observed_at) ? payload.observed_at : null,
  };
  // Do not return free-form error text, private exports/backups, IDs, addresses,
  // raw capabilities, firmware inventory, credentials, or nested unknown fields.
  if (payload.result === "error") result.reason = "security_operation_failed";
  if (payload.result === "write_outcome_unknown" || payload.outcome === "unknown") Object.assign(result, { result: "write_outcome_unknown", outcome: "unknown", automatic_retry: false });
  if (payload.device !== undefined) result.device = alias(payload.device);
  if (MODELS.has(payload.model)) result.model = payload.model;
  if (payload.devices && typeof payload.devices === "object" && !Array.isArray(payload.devices)) {
    result.devices = Object.fromEntries(Object.entries(payload.devices).slice(0, 16).map(([key, entry]: any) => [alias(key), { model: MODELS.has(entry?.model) ? entry.model : "unknown" }]));
  }
  if (payload.features && typeof payload.features === "object" && !Array.isArray(payload.features)) {
    result.features = Object.fromEntries(Object.entries(payload.features).filter(([key]) => FEATURES.has(key)).map(([key, feature]: any) => [key,
      { value: feature?.status === "unknown" ? null : scalar(feature?.value), status: feature?.status === "unknown" || feature?.value === undefined ? "unknown" : "reported" }]));
  }
  if (["T100", "T110"].includes(payload.model)) Object.assign(result, { observation_scope: "hub_reported_snapshot", radio_freshness: "unknown" });
  if (payload.rules !== undefined) result.rules = rulesFrom(payload);
  if (payload.rule !== undefined && payload.rule !== null) result.rule = ruleSummary(payload.rule);
  if (payload.configuration) {
    const c = payload.configuration;
    if (!Array.isArray(c.triggers) || !Array.isArray(c.actions) || c.triggers.length > 32 || c.actions.length > 32) throw new Error("security_invalid_description");
    result.configuration = {
      triggers: c.triggers.map((t: any) => ({ model: MODELS.has(t?.model) ? t.model : "unknown", event: ["open", "close", "motion"].includes(t?.event) ? t.event : "unknown" })),
      actions: c.actions.map((a: any) => ({ model: MODELS.has(a?.model) ? a.model : "unknown", effect: "unverified_device_action",
        ...(Number.isInteger(a?.configured_duration_seconds) && a.configured_duration_seconds >= 0 && a.configured_duration_seconds <= 3600 ? { configured_duration_seconds: a.configured_duration_seconds } : {}),
        ...(typeof a?.configured_alarm_tone === "string" && /^Alarm [0-9]{1,2}$/.test(a.configured_alarm_tone) ? { configured_alarm_tone: a.configured_alarm_tone } : {}),
        ...(typeof a?.configured_volume_raw === "string" && /^[0-9]{1,3}$/.test(a.configured_volume_raw) ? { configured_volume_raw: a.configured_volume_raw } : {}),
      })),
      all_day: typeof c.all_day === "boolean" ? c.all_day : null,
      trigger_combination: "not_interpreted", description_scope: "partial_allowlisted_fields", physical_behavior: "not_verified",
      warning: "Enabling may cause physical actions immediately or later. Disabling does not stop an already sounding alarm.",
    };
  }
  return result;
}
