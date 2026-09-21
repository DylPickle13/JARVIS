import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { StringEnum } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { findAncestorFile, parseDotEnv } from "./lib/env";
import { truncate } from "./lib/text";

// Small model-facing schemas; the existing CLI/backends still own device safety.
export function operationDir(cwd: string): string {
  let current = resolve(cwd);
  while (true) {
    const candidate = join(current, "projects", "operation-jarvis");
    if (existsSync(join(candidate, "jarvis.py"))) return candidate;
    const parent = dirname(current);
    if (parent === current) break;
    current = parent;
  }
  const candidate = join(resolve(process.env.JARVIS_ROOT || process.cwd()), "projects", "operation-jarvis");
  if (!existsSync(join(candidate, "jarvis.py"))) throw new Error("Operation JARVIS installation unavailable");
  return candidate;
}

const credentialKeys = ["SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "SPOTIFY_REFRESH_TOKEN", "SPOTIFY_SP_DC", "SPOTIFY_SP_KEY", "SP_DC", "SP_KEY"];
function secrets(cwd: string, dir: string): string[] {
  const envs = [process.env, parseDotEnv(findAncestorFile(cwd, ".env")), parseDotEnv(join(dir, ".env"))];
  return [...new Set(envs.flatMap(env => credentialKeys.map(key => env[key]?.trim()).filter((v): v is string => !!v && v.length >= 6)))];
}
function redact(value: any, credentials: string[]): any {
  if (typeof value === "string") {
    for (const secret of credentials) value = value.split(secret).join("[REDACTED_CREDENTIAL]");
    return value.replace(/((?:Authorization|Proxy-Authorization)\s*:\s*(?:Bearer|Basic)\s+)\S+/gi, "$1[REDACTED_CREDENTIAL]");
  }
  if (Array.isArray(value)) return value.map(v => redact(v, credentials));
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([k, v]) =>
    [k, /authorization|password|secret|token|spotify.*(?:client.?id|sp.?dc|sp.?key)|sp.?dc|sp.?key/i.test(k) ? "[REDACTED_CREDENTIAL]" : redact(v, credentials)]));
  return value;
}
async function run(pi: ExtensionAPI, cwd: string, args: string[], signal: AbortSignal | undefined, timeout: number) {
  const dir = operationDir(cwd);
  const root = resolve(dir, "../..");
  const python = [join(dir, ".venv/bin/python"), join(root, ".venv/bin/python")].find(existsSync) || "python3";
  const credentials = secrets(cwd, dir);
  const result = await pi.exec(python, [join(dir, "jarvis.py"), "--json", ...args], { signal, timeout });
  let payload: any;
  try { payload = redact(JSON.parse(result.stdout), credentials); }
  catch { throw new Error("Operation JARVIS returned invalid output; outcome unverified. Do not replay writes."); }
  if (result.code !== 0 || payload?.ok === false) {
    // Never expose raw stderr/exception text or command lines.
    throw new Error(typeof payload?.error === "string" ? payload.error : "Operation JARVIS failed; outcome unverified. Do not replay writes.");
  }
  return { content: [{ type: "text" as const, text: truncate(String(payload.summary || payload.answer || JSON.stringify(payload))) }], details: payload };
}
const text = (description: string) => Type.Optional(Type.String({ minLength: 1, maxLength: 2048, description }));
const integer = (minimum: number, maximum: number, description: string) => Type.Optional(Type.Integer({ minimum, maximum, description }));
function required(value: unknown, name: string): string {
  if (typeof value !== "string" || !value.trim() || value.trim().startsWith("-") || /[\x00-\x1f]/.test(value)) throw new Error(`${name} is required and must not be an option`);
  return value.trim();
}
function add(args: string[], flag: string, value: unknown) {
  if (value !== undefined) args.push(flag, String(value));
}
function bounds(value: unknown, min: number, max: number, name: string) {
  if (value !== undefined && (typeof value !== "number" || !Number.isInteger(value) || value < min || value > max)) throw new Error(`${name} must be ${min}..${max}`);
}
export function preparePlugArguments(args: unknown): unknown {
  if (!args || typeof args !== "object" || Array.isArray(args)) return args;
  const p = { ...args } as Record<string, any>;
  if (typeof p.plug === "string") p.plug = p.plug.trim().toLowerCase().replace(/[\s_]+/g, "-");
  return p;
}

export default function registerOperationJarvis(pi: ExtensionAPI) {
  pi.registerTool({
    name: "operation_jarvis_presence", label: "Operation JARVIS · Presence",
    description: "Read Dylan's estimated basement (Mac) and living room (Pi) proximity from the authenticated backend. Zones are independent and may overlap; do not infer a unique room. Unknown/stale is not away; BLE device presence is not proof of human location. No scanning, enrollment or household actions.",
    parameters: Type.Object({}, { additionalProperties: false }),
    async execute(_id, _p, signal, _update, ctx) {
      const dir = operationDir(ctx.cwd);
      const result = await pi.exec(join(dir, ".venv/bin/python"), [join(dir, "presence/status.py")], { signal, timeout: 8000 });
      let payload: any;
      try { payload = JSON.parse(result.stdout); }
      catch { throw new Error("Presence unavailable; location unknown."); }
      return { content: [{ type: "text" as const, text: JSON.stringify(payload) }], details: payload };
    },
  });
  pi.registerTool({
    name: "operation_jarvis_plugs", label: "Operation JARVIS · Plugs",
    description: "Control Operation JARVIS household lights and Kasa plugs over the local network. List aliases if unclear; writes return verified state. Not TV media control.",
    parameters: Type.Object({
      action: StringEnum(["list", "status", "on", "off", "toggle"]),
      plug: text("Configured plug alias; required except for list."),
    }, { additionalProperties: false }),
    executionMode: "sequential",
    prepareArguments: preparePlugArguments,
    async execute(_id, p, signal, _update, ctx) {
      if (!["list", "status", "on", "off", "toggle"].includes(p.action)) throw new Error("Unsupported plug action");
      const args = [`plug-${p.action}`];
      if (p.action === "list") {
        if (p.plug !== undefined) throw new Error("list does not accept a plug");
      } else {
        const alias = required(p.plug, "plug");
        if (!/^[a-z][a-z0-9-]{0,63}$/.test(alias)) throw new Error("Use a configured plug alias, not an IP or path");
        args.push(alias);
      }
      return run(pi, ctx.cwd, args, signal, 75_000);
    },
  });

  pi.registerTool({
    name: "operation_jarvis_purifier", label: "Operation JARVIS · Purifier",
    description: "Read/control Operation JARVIS VeSync/Levoit air purifiers. list discovers devices; status-all refreshes all; set changes one device. Writes may take over a minute; never retry automatically.",
    parameters: Type.Object({
      action: StringEnum(["list", "status", "status-all", "set"]),
      purifier: text("Configured alias or unique device name; omit for default. No selector on list/status-all."),
      setting: Type.Optional(StringEnum(["power", "mode", "speed", "display", "child-lock", "light-detection", "auto-preference", "timer"])),
      value: text("set: on/off/toggle; mode auto/manual/sleep/pet; auto-preference default/quiet/efficient; timer clear."),
      level: integer(1, 4, "set speed: fan level 1–4."),
      minutes: integer(1, 1440, "set timer: minutes."),
      roomSize: integer(1, 10000, "set auto-preference: optional square feet."),
      retryCooldown: Type.Optional(Type.Boolean({ description: "Owner-authorized recovery status read only; never automatically." })),
    }, { additionalProperties: false }),
    executionMode: "sequential",
    async execute(_id, p, signal, _update, ctx) {
      if (!["list", "status", "status-all", "set"].includes(p.action)) throw new Error("Unsupported purifier action");
      if (p.retryCooldown && !["status", "status-all"].includes(p.action)) throw new Error("retryCooldown is only allowed for explicit status reads");
      if (["list", "status-all"].includes(p.action) && p.purifier) throw new Error("Collection actions reject a device selector");
      if (p.action !== "set" && [p.setting, p.value, p.level, p.minutes, p.roomSize].some(v => v !== undefined)) throw new Error("Settings require action=set");
      bounds(p.level, 1, 4, "level"); bounds(p.minutes, 1, 1440, "minutes"); bounds(p.roomSize, 1, 10000, "roomSize");
      const args = [`purifier-${p.action}`];
      if (p.retryCooldown) args.push("--retry-cooldown");
      if (p.purifier !== undefined) add(args, "--purifier", required(p.purifier, "purifier"));
      if (p.action === "set") {
        const setting = required(p.setting, "setting");
        add(args, "--level", p.level); add(args, "--minutes", p.minutes); add(args, "--room-size", p.roomSize);
        args.push(setting);
        if (p.value !== undefined) args.push(required(p.value, "value"));
      }
      return run(pi, ctx.cwd, args, signal, p.action === "set" ? 210_000 : 180_000);
    },
  });

  pi.registerTool({
    name: "operation_jarvis_media", label: "Operation JARVIS · Media",
    description: "Operation JARVIS Google Cast, Spotify Connect, and speech through household speakers/TV. Use status for playback, speak for aloud text; not electrical power or camera audio.",
    parameters: Type.Object({
      action: StringEnum(["status", "volume", "mute", "stop", "youtube", "play-url", "speak", "spotify-devices", "spotify", "spotify-pause", "spotify-next", "spotify-previous", "spotify-volume", "spotify-queue", "spotify-queue-add", "spotify-seek", "spotify-shuffle", "spotify-repeat"]),
      device: Type.Optional(StringEnum(["tv", "speakers"], { description: "Default TV for video/status/stop; speakers for speech/volume/mute/Spotify." })),
      text: text("speak: short text to say aloud."),
      query: text("youtube/spotify/spotify-queue-add: search text or media URL."),
      url: text("play-url: direct HTTP(S) media URL."),
      contentType: text("play-url: MIME type; default video/mp4."),
      level: integer(0, 100, "volume/spotify-volume: percent."),
      state: Type.Optional(StringEnum(["on", "off", "toggle"], { description: "mute defaults on; spotify-shuffle defaults toggle." })),
      spotifyUri: text("spotify/spotify-queue-add: Spotify URI or URL instead of query."),
      spotifyDeviceName: text("Exact Spotify Connect name instead of configured device."),
      spotifyType: Type.Optional(StringEnum(["track", "album", "playlist", "artist", "any"])),
      resume: Type.Optional(Type.Boolean({ description: "spotify: resume instead of selecting media." })),
      position: text("spotify-seek: timestamp such as 1:30 or 90s."),
      repeatState: Type.Optional(StringEnum(["off", "context", "track", "toggle"])),
      limit: integer(1, 100, "spotify-queue: maximum items; default 20."),
      enqueue: Type.Optional(Type.Boolean({ description: "youtube: queue instead of immediate playback." })),
    }, { additionalProperties: false }),
    executionMode: "sequential",
    async execute(_id, p, signal, _update, ctx) {
      bounds(p.level, 0, 100, "level"); bounds(p.limit, 1, 100, "limit");
      const args = [p.action === "speak" ? "speak" : `cast-${p.action}`];
      const defaultDevice = ["status", "stop", "youtube", "play-url"].includes(p.action) ? "tv" : "speakers";
      add(args, "--device", p.device ?? defaultDevice);
      if (p.action.startsWith("spotify")) add(args, "--spotify-device-name", p.spotifyDeviceName);
      switch (p.action) {
        case "status": case "spotify-devices": case "spotify-pause": case "spotify-next": case "spotify-previous": break;
        case "stop": args.push("--quit-app"); break;
        case "speak": args.push(required(p.text, "text")); break;
        case "volume": case "spotify-volume":
          if (p.level === undefined) throw new Error("level is required");
          args.push(String(p.level)); break;
        case "mute": args.push(p.state ?? "on"); break;
        case "youtube":
          if (p.enqueue) args.push("--enqueue");
          args.push(required(p.query, "query")); break;
        case "play-url": {
          const url = required(p.url, "url");
          if (!/^https?:\/\//i.test(url)) throw new Error("HTTP(S) media URL required");
          add(args, "--type", p.contentType ?? "video/mp4"); args.push(url); break;
        }
        case "spotify": case "spotify-queue-add":
          if (!p.query && !p.spotifyUri && !(p.action === "spotify" && p.resume)) throw new Error("query, spotifyUri or spotify resume=true required");
          add(args, "--spotify-uri", p.spotifyUri);
          if (p.action === "spotify") {
            if (p.resume) args.push("--resume");
            add(args, "--spotify-type", p.spotifyType);
          }
          if (p.query) args.push(required(p.query, "query"));
          break;
        case "spotify-queue": add(args, "--limit", p.limit); break;
        case "spotify-seek": args.push(required(p.position, "position")); break;
        case "spotify-shuffle": args.push(p.state ?? "toggle"); break;
        case "spotify-repeat": args.push(p.repeatState ?? "toggle"); break;
        default: throw new Error("Unsupported media action");
      }
      return run(pi, ctx.cwd, args, signal, p.action === "speak" ? 195_000 : 180_000);
    },
  });
}
