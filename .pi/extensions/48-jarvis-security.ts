import { join } from "node:path";
import { StringEnum } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { operationDir } from "./45-jarvis";
import { alias, commissioned, projectSecurity, resolveRule, runSecurity, type SecurityRunner } from "./lib/operation-jarvis-security";

type Dependencies = { run?: SecurityRunner; commissioned?: typeof commissioned; directory?: (cwd: string) => string };
function output(value: any, isError = false) {
  return { content: [{ type: "text" as const, text: JSON.stringify(value, null, 2) }], details: value, isError };
}

// Injectable only in offline tests, never through model arguments.
export function registerSecurity(pi: ExtensionAPI, deps: Dependencies = {}) {
  const run = deps.run ?? runSecurity;
  const accepted = deps.commissioned ?? commissioned;
  const directory = deps.directory ?? ((cwd: string) => join(operationDir(cwd), "security"));
  let busy = false;
  async function exclusive(fn: () => Promise<any>) {
    if (busy) return output({ result: "device_busy", automatic_retry: false }, true);
    busy = true;
    try { return await fn(); }
    catch {
      // No raw subprocess, SDK, filesystem or private configuration exceptions.
      return output({ result: "error", reason: "security_read_or_preflight_failed", security_assessment: "not_assessed", automatic_retry: false }, true);
    } finally { busy = false; }
  }
  async function read(dir: string, args: string[], signal?: AbortSignal) {
    const result = await run(dir, args, signal);
    if (result.code !== 0 || !["configured", "read_succeeded"].includes(result.payload.result)) throw new Error("security_read_failed");
    if (["status", "capabilities"].includes(args[0]) && result.payload.device !== args[1]) throw new Error("security_identity_mismatch");
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
    description: "Manage Operation JARVIS Tapo CLOUD rules, including named security protocols: list/describe or enable/disable an automation. Not Pi cron jobs or shortcut execution. Changes require commissioned support and a user confirmation dialog; never retry uncertain writes.",
    parameters: Type.Object({
      action: StringEnum(["list", "describe", "enable", "disable"]),
      name: Type.Optional(Type.String({ minLength: 1, maxLength: 128, description: "Exact current rule name (case-insensitive); required except list. Discover with list, never invent a rule." })),
    }, { additionalProperties: false }),
    executionMode: "sequential",
    async execute(_id, p, signal, _update, ctx) {
      return exclusive(async () => {
        if (!["list", "describe", "enable", "disable"].includes(p.action)) throw new Error("unsupported_action");
        if (p.action === "list" && p.name !== undefined) throw new Error("unexpected_name");
        const dir = directory(ctx.cwd);
        const listing = await read(dir, ["smart-actions", "list"], signal);
        if (p.action === "list") return output(listing);
        let target;
        try { target = resolveRule(listing, p.name); }
        catch { return output({ result: "error", reason: "rule_name_missing_or_ambiguous", automatic_retry: false }, true); }
        const description = await read(dir, ["smart-actions", "describe", target.ref], signal);
        // Bind consent to the exact definition observed, including name and enabled state.
        if (!description.rule || description.rule.ref !== target.ref || description.rule.revision !== target.revision) return output({ result: "rule_changed", automatic_retry: false }, true);
        if (p.action === "describe") return output(description);
        if (target.kind !== "automation") return output({ result: "unsupported_rule_kind", message: "Only automation enable/disable is exposed; no shortcut execution." }, true);
        if (target.enabled === (p.action === "enable")) return output({ ...description, result: "unchanged", writes_attempted: 0 });
        if (!await accepted(dir, p.action)) return output({ ...description, result: "commissioning_required", requested_action: p.action, writes_attempted: 0,
          message: "Enable/disable is not live-accepted for this installation. Commission with an owner-approved disposable rule first; do not bypass through shell." }, true);
        if (!ctx.hasUI) return output({ ...description, result: "confirmation_ui_required", writes_attempted: 0 }, true);
        const confirmed = await ctx.ui.confirm(`Operation JARVIS: ${p.action} automation?`,
          `${JSON.stringify(description, null, 2)}\n\n${p.action === "enable" ? "May cause physical actions immediately or later." : "Stops future rule activation, not an already sounding alarm."}`);
        if (!confirmed || signal?.aborted) return output({ result: "cancelled", writes_attempted: 0 });
        // Recheck installation gate after consent. The CLI itself rereads and rejects
        // stale revisions before sending at most one mutation; no server-atomic CAS.
        if (!await accepted(dir, p.action)) return output({ result: "commissioning_required", writes_attempted: 0 }, true);
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
