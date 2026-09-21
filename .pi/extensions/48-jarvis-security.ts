import { join } from "node:path";
import { StringEnum } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { operationDir } from "./45-jarvis";
import { alias, projectSecurity, resolveRule, runSecurity, type SecurityRunner } from "./lib/operation-jarvis-security";

type Dependencies = { run?: SecurityRunner; directory?: (cwd: string) => string };
class ReauthenticationRequired extends Error {}
class SecurityReadFailure extends Error {
  constructor(readonly reason: string, readonly stage: "preflight" | "connection" | "state_read" | "unknown") { super(reason); }
}

const SAFE_FAILURE_REASONS = new Set([
  "device_busy", "sensor_missing_or_ambiguous", "device_identity_mismatch", "unknown_device",
  "unreachable", "authentication_failed", "timeout", "operation_failed", "dependency_unavailable",
  "private_credentials_unavailable", "invalid_device_registry", "network_or_local_io_error",
  "invalid_output", "output_limit", "worker_failed", "cancelled",
]);
const PREFLIGHT_FAILURES = new Set(["device_busy", "unknown_device", "invalid_device_registry", "private_credentials_unavailable"]);
const CONNECTION_FAILURES = new Set(["unreachable", "authentication_failed", "dependency_unavailable", "network_or_local_io_error", "device_identity_mismatch"]);
function failureStage(reason: string): "preflight" | "connection" | "state_read" | "unknown" {
  if (PREFLIGHT_FAILURES.has(reason)) return "preflight";
  if (CONNECTION_FAILURES.has(reason)) return "connection";
  if (["sensor_missing_or_ambiguous", "operation_failed", "invalid_output", "output_limit", "worker_failed"].includes(reason)) return "state_read";
  return "unknown";
}
function safeReason(value: unknown): string {
  return typeof value === "string" && SAFE_FAILURE_REASONS.has(value) ? value : "security_read_or_preflight_failed";
}
function runnerReason(error: unknown): string {
  const value = error instanceof Error ? error.message : "";
  return ({
    security_cancelled: "cancelled", security_timeout: "timeout", security_output_limit: "output_limit",
    security_launcher_unavailable: "worker_failed", security_invalid_output: "invalid_output",
  } as Record<string, string>)[value] ?? "security_read_or_preflight_failed";
}
function output(value: any, isError = false) {
  return { content: [{ type: "text" as const, text: JSON.stringify(value, null, 2) }], details: value, isError };
}

// Injectable only in offline tests, never through model arguments.
export function registerSecurity(pi: ExtensionAPI, deps: Dependencies = {}) {
  const run = deps.run ?? runSecurity;
  const directory = deps.directory ?? ((cwd: string) => join(operationDir(cwd), "security"));
  let busy = false;
  async function exclusive(fn: () => Promise<any>) {
    if (busy) return output({ result: "device_busy", automatic_retry: false }, true);
    busy = true;
    try { return await fn(); }
    catch (error) {
      if (error instanceof ReauthenticationRequired) return output({ result: "error", reason: "cloud_reauthentication_required", message: "Explicit TP-Link sign-in is required. With owner approval, use list with reauthenticate: true; this may trigger a login email.", automatic_retry: false }, true);
      // No raw subprocess, SDK, filesystem or private configuration exceptions.
      const reason = error instanceof SecurityReadFailure ? error.reason : runnerReason(error);
      const stage = error instanceof SecurityReadFailure ? error.stage : "unknown";
      return output({ result: "error", reason, stage, security_assessment: "not_assessed", automatic_retry: false }, true);
    } finally { busy = false; }
  }
  async function read(dir: string, args: string[], signal?: AbortSignal) {
    const result = await run(dir, args, signal);
    if (args[0] === "smart-actions" && result.payload.result === "error" && result.payload.reason === "cloud_reauthentication_required") throw new ReauthenticationRequired();
    if (result.code !== 0 || !["configured", "read_succeeded"].includes(result.payload.result)) {
      const reason = safeReason(result.payload.reason);
      const stage = ["preflight", "connection", "state_read"].includes(result.payload.stage) ? result.payload.stage : failureStage(reason);
      throw new SecurityReadFailure(reason, stage);
    }
    if (["status", "capabilities"].includes(args[0]) && result.payload.device !== args[1]) throw new SecurityReadFailure("device_identity_mismatch", "state_read");
    return projectSecurity(result.payload);
  }
  pi.registerTool({
    name: "operation_jarvis_security", label: "Operation JARVIS · Security",
    description: "Read Operation JARVIS local Tapo security devices/sensors. devices lists configured aliases offline; status/capabilities read one device. Hub snapshots do not prove sensor freshness or that the home is secure. No media or writes.",
    parameters: Type.Object({
      action: StringEnum(["devices", "status", "capabilities"]),
      device: Type.Optional(Type.String({ pattern: "^[a-z][a-z0-9-]{0,39}$", description: "Configured alias; required for status/capabilities." })),
    }, { additionalProperties: false }),
    executionMode: "sequential",
    async execute(_id, p, signal, _update, ctx) {
      return exclusive(async () => {
        if (!["devices", "status", "capabilities"].includes(p.action)) throw new Error("unsupported_action");
        if (p.action === "devices" && p.device !== undefined) throw new Error("unexpected_device");
        const args = p.action === "devices" ? ["devices"] : [p.action, alias(p.device)];
        return output(await read(directory(ctx.cwd), args, signal));
      });
    },
  });
  pi.registerTool({
    name: "operation_jarvis_automations", label: "Operation JARVIS · Automations",
    description: "Manage Operation JARVIS Tapo CLOUD rules, including named security protocols: list/describe or enable/disable an automation. Not Pi cron jobs or shortcut execution. Enabling can cause immediate or later physical actions; disabling does not stop an already sounding alarm. Reauthenticate (list only) signs in and may send a login email; never retry uncertain writes.",
    parameters: Type.Object({
      action: StringEnum(["list", "describe", "enable", "disable"]),
      name: Type.Optional(Type.String({ minLength: 1, maxLength: 128, description: "Exact current rule name (case-insensitive); required except list. Discover with list, never invent a rule." })),
      reauthenticate: Type.Optional(Type.Boolean({ description: "Explicitly sign in to TP-Link and cache a session; list only, may send a login email. Never use automatically." })),
    }, { additionalProperties: false }),
    executionMode: "sequential",
    async execute(_id, p, signal, _update, ctx) {
      return exclusive(async () => {
        if (!["list", "describe", "enable", "disable"].includes(p.action)) throw new Error("unsupported_action");
        if (p.action === "list" && p.name !== undefined) throw new Error("unexpected_name");
        const dir = directory(ctx.cwd);
        if (p.reauthenticate && p.action !== "list") throw new Error("reauthentication_requires_list");
        const listing = await read(dir, ["smart-actions", "list", ...(p.reauthenticate ? ["--reauthenticate"] : [])], signal);
        if (p.action === "list") return output(listing);
        let target;
        try { target = resolveRule(listing, p.name); }
        catch { return output({ result: "error", reason: "rule_name_missing_or_ambiguous", automatic_retry: false }, true); }
        const description = await read(dir, ["smart-actions", "describe", target.ref], signal);
        // Bind the operation to the exact definition observed, including name and enabled state.
        if (!description.rule || description.rule.ref !== target.ref || description.rule.revision !== target.revision) return output({ result: "rule_changed", automatic_retry: false }, true);
        if (p.action === "describe") return output(description);
        if (target.kind !== "automation") return output({ result: "unsupported_rule_kind", message: "Only automation enable/disable is exposed; no shortcut execution." }, true);
        if (target.enabled === (p.action === "enable")) return output({ ...description, result: "unchanged", writes_attempted: 0 });
        // The CLI rereads and rejects stale revisions before sending at most one mutation; no server-atomic CAS.
        if (signal?.aborted) return output({ result: "cancelled", writes_attempted: 0 });
        try {
          const result = await run(dir, ["smart-actions", p.action, target.ref, "--revision", target.revision, "--confirm"], signal);
          const value = projectSecurity(result.payload);
          if (result.code === 3 || value.result === "write_outcome_unknown") return output({ ...value, result: "write_outcome_unknown", outcome: "unknown", automatic_retry: false,
            message: "Inspect current rule state and the CLI's private recovery backups before further action. Do not repeat." }, true);
          if (result.code !== 0 || !["write_verified", "unchanged"].includes(value.result)) return output({ ...value, result: "error", automatic_retry: false }, true);
          if (!value.rule || value.rule.ref !== target.ref || value.rule.enabled !== (p.action === "enable")) throw new Error("unverified_write");
          return output({ ...value, configuration_verified: true, physical_behavior: "not_verified", automatic_retry: false });
        } catch {
          // A timeout/cancel/malformed reply after invocation may follow a sent write.
          return output({ result: "write_outcome_unknown", outcome: "unknown", automatic_retry: false, security_assessment: "not_assessed",
            message: "Inspect current state and private CLI backups; do not repeat the change." }, true);
        }
      });
    },
  });
}
export default function operationJarvisSecurity(pi: ExtensionAPI) { registerSecurity(pi); }
