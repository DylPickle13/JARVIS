import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

import { findAncestorFile, parseDotEnvFile } from "./lib/env";
import { truncate } from "./lib/text";

type DotEnv = Record<string, string>;
type MapsEnv = {
  envPath?: string;
  apiKey?: string;
  apiKeySource?: string;
  languageCode: string;
  regionCode: string;
  defaultLabel: string;
  defaultLat: number;
  defaultLng: number;
  defaultRadiusMeters: number;
  homeAddress?: string;
};

type MapsIntent = "status" | "route" | "geocode" | "place_search";
type TravelMode = "DRIVE" | "WALK" | "BICYCLE" | "TRANSIT" | "TWO_WHEELER";

const PICKERING = {
  label: "Pickering, Ontario, Canada",
  lat: 43.8384,
  lng: -79.0868,
  radiusMeters: 25_000,
};

function firstNonEmptyLine(pathValue: string | undefined): string | undefined {
  if (!pathValue) return undefined;
  const resolved = resolve(pathValue.replace(/^~(?=\/|$)/, process.env.HOME ?? ""));
  if (!existsSync(resolved)) return undefined;
  for (const line of readFileSync(resolved, "utf8").split(/\r?\n/)) {
    const candidate = line.trim();
    if (candidate) return candidate;
  }
  return undefined;
}

function parseNumber(value: string | undefined, fallback: number, min?: number, max?: number): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  if (min !== undefined && parsed < min) return fallback;
  if (max !== undefined && parsed > max) return fallback;
  return parsed;
}

function firstEnv(dotenv: DotEnv, names: string[]): { value?: string; source?: string } {
  for (const name of names) {
    const value = (process.env[name] || dotenv[name] || "").trim();
    if (value) return { value, source: name };
  }
  return {};
}

function loadMapsEnv(cwd: string): MapsEnv {
  const envPath = findAncestorFile(cwd, ".env");
  const dotenv = parseDotEnvFile(envPath);

  for (const [key, value] of Object.entries(dotenv)) {
    if ((key.startsWith("GOOGLE_MAPS_") || key === "MAPS_API_KEY") && value && !process.env[key]) {
      process.env[key] = value;
    }
  }

  let { value: apiKey, source: apiKeySource } = firstEnv(dotenv, ["GOOGLE_MAPS_API_KEY", "MAPS_API_KEY"]);
  if (!apiKey) {
    const fileSource = firstEnv(dotenv, ["GOOGLE_MAPS_API_KEY_FILE", "GOOGLE_MAPS_API_KEY_PATH"]);
    const fileKey = firstNonEmptyLine(fileSource.value);
    if (fileKey) {
      apiKey = fileKey;
      apiKeySource = fileSource.value;
      if (!process.env.GOOGLE_MAPS_API_KEY) process.env.GOOGLE_MAPS_API_KEY = fileKey;
    }
  }

  // Optional compatibility fallback. Many Google API keys are restricted per API, so prefer GOOGLE_MAPS_API_KEY.
  const allowGoogleApiKeyFallback = ((process.env.GOOGLE_MAPS_ALLOW_GOOGLE_API_KEY_FALLBACK || dotenv.GOOGLE_MAPS_ALLOW_GOOGLE_API_KEY_FALLBACK || "").trim() === "1");
  if (!apiKey && allowGoogleApiKeyFallback) {
    const fallback = firstEnv(dotenv, ["GOOGLE_API_KEY"]);
    apiKey = fallback.value;
    apiKeySource = fallback.source;
  }

  const languageCode = firstEnv(dotenv, ["GOOGLE_MAPS_DEFAULT_LANGUAGE"]).value || "en";
  const regionCode = firstEnv(dotenv, ["GOOGLE_MAPS_DEFAULT_REGION"]).value || "CA";
  const defaultLabel = firstEnv(dotenv, ["GOOGLE_MAPS_DEFAULT_LOCATION_LABEL"]).value || PICKERING.label;
  const defaultLat = parseNumber(firstEnv(dotenv, ["GOOGLE_MAPS_DEFAULT_LAT"]).value, PICKERING.lat, -90, 90);
  const defaultLng = parseNumber(firstEnv(dotenv, ["GOOGLE_MAPS_DEFAULT_LNG"]).value, PICKERING.lng, -180, 180);
  const defaultRadiusMeters = parseNumber(firstEnv(dotenv, ["GOOGLE_MAPS_DEFAULT_RADIUS_METERS"]).value, PICKERING.radiusMeters, 100, 50_000);
  const homeAddress = firstEnv(dotenv, ["GOOGLE_MAPS_HOME_ADDRESS"]).value;

  return {
    envPath,
    apiKey: apiKey || undefined,
    apiKeySource,
    languageCode,
    regionCode,
    defaultLabel,
    defaultLat,
    defaultLng,
    defaultRadiusMeters,
    homeAddress,
  };
}

function redact(text: string, env: MapsEnv): string {
  let output = text;
  if (env.apiKey && env.apiKey.length >= 6) output = output.split(env.apiKey).join("<redacted>");
  output = output.replace(/((?:key|api_key|apiKey|X-Goog-Api-Key)=)[^&\s]+/gi, "$1<redacted>");
  output = output.replace(/("(?:key|apiKey|api_key|X-Goog-Api-Key)"\s*:\s*")[^"]+(")/gi, "$1<redacted>$2");
  return output;
}

function requireApiKey(env: MapsEnv): string {
  if (!env.apiKey) {
    throw new Error(
      "Google Maps API key is not configured. Set GOOGLE_MAPS_API_KEY in .env and enable Places API (New), Geocoding API, and Routes API."
    );
  }
  return env.apiKey;
}

async function requestJson(url: string, init: RequestInit, env: MapsEnv, signal?: AbortSignal): Promise<any> {
  const response = await fetch(url, { ...init, signal });
  const text = await response.text();
  let data: any = undefined;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { raw: text };
  }

  if (!response.ok) {
    const message = data?.error?.message || data?.error_message || data?.status || text || response.statusText;
    throw new Error(`Google Maps request failed (${response.status}): ${redact(String(message), env)}`);
  }

  if (data?.status && data.status !== "OK" && data.status !== "ZERO_RESULTS") {
    throw new Error(`Google Maps API returned ${data.status}: ${redact(String(data.error_message || "No details"), env)}`);
  }

  return data;
}

function classifyQuery(query: string): MapsIntent {
  const q = query.trim().toLowerCase();
  if (!q || /^(status|health|setup|config|configuration)$/i.test(q)) return "status";
  if (/\b(direction|directions|route|routing|drive|driving|walk|walking|bike|biking|cycling|transit|bus|train|subway|commute|travel time|eta|how long)\b/i.test(query)) return "route";
  if (/\b(geocode|coordinates?|lat(?:itude)?|lng|longitude|reverse geocode)\b/i.test(query)) return "geocode";
  return "place_search";
}

function cleanRouteEndpoint(value: string): string {
  return value
    .replace(/[?.!,]+$/g, "")
    .replace(/\s+\b(right now|now|today|with traffic|using traffic)\b.*$/i, "")
    .replace(/\s+\b(by|via|using)\s+(car|drive|driving|walking|walk|transit|bus|train|bike|bicycle|cycling)\b.*$/i, "")
    .trim();
}

function resolveRelativePlace(value: string, env: MapsEnv): string {
  const trimmed = value.trim();
  if (/^(home|my home|house|my house)$/i.test(trimmed)) return env.homeAddress || env.defaultLabel;
  if (/^(here|me|my location|current location|near me)$/i.test(trimmed)) return env.defaultLabel;
  return trimmed;
}

function travelModeFor(query: string): TravelMode {
  if (/\b(walk|walking|on foot)\b/i.test(query)) return "WALK";
  if (/\b(bike|biking|bicycle|cycling)\b/i.test(query)) return "BICYCLE";
  if (/\b(transit|bus|train|subway|streetcar|go train)\b/i.test(query)) return "TRANSIT";
  if (/\b(motorcycle|scooter|two[- ]wheeler)\b/i.test(query)) return "TWO_WHEELER";
  return "DRIVE";
}

function parseRoute(query: string, env: MapsEnv): { origin: string; destination: string; travelMode: TravelMode } | undefined {
  const normalized = query.replace(/\s+/g, " ").trim();
  let origin = "";
  let destination = "";

  const fromTo = normalized.match(/\bfrom\s+(.+?)\s+to\s+(.+)$/i);
  if (fromTo) {
    origin = cleanRouteEndpoint(fromTo[1]);
    destination = cleanRouteEndpoint(fromTo[2]);
  } else {
    const toOnly = normalized.match(/\b(?:directions?|route|drive|driving|walk|walking|commute|travel time|eta|how long(?: would it take)?)\b.*?\bto\s+(.+)$/i);
    if (toOnly) {
      origin = env.homeAddress || env.defaultLabel;
      destination = cleanRouteEndpoint(toOnly[1]);
    }
  }

  origin = resolveRelativePlace(origin, env);
  destination = resolveRelativePlace(destination, env);
  if (!origin || !destination) return undefined;
  return { origin, destination, travelMode: travelModeFor(query) };
}

function parseCoordinatePair(query: string): { lat: number; lng: number } | undefined {
  const match = query.match(/(-?\d{1,2}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)/);
  if (!match) return undefined;
  const lat = Number(match[1]);
  const lng = Number(match[2]);
  if (!Number.isFinite(lat) || !Number.isFinite(lng) || lat < -90 || lat > 90 || lng < -180 || lng > 180) return undefined;
  return { lat, lng };
}

function parseGeocodeAddress(query: string, env: MapsEnv): string {
  const patterns = [
    /^geocode\s+(.+)$/i,
    /^(?:what are )?the coordinates (?:of|for)\s+(.+)$/i,
    /^(?:latitude|longitude|lat lng|lat\/lng) (?:of|for)\s+(.+)$/i,
  ];
  for (const pattern of patterns) {
    const match = query.trim().match(pattern);
    if (match?.[1]) return resolveRelativePlace(match[1].trim(), env);
  }
  return resolveRelativePlace(query.replace(/\b(coordinates?|geocode|latitude|longitude|lat|lng)\b/gi, "").trim(), env) || query;
}

function placeSearchQuery(query: string, env: MapsEnv): { textQuery: string; biased: boolean } {
  let textQuery = query.trim()
    .replace(/\bnear me\b/gi, `near ${env.defaultLabel}`)
    .replace(/\bnearby\b/gi, `near ${env.defaultLabel}`)
    .replace(/\baround me\b/gi, `around ${env.defaultLabel}`)
    .replace(/\blocal\b/gi, `${env.defaultLabel} local`)
    .replace(/\s+/g, " ")
    .trim();

  const hasLocationHint = /\b(near|in|around|at|from|to|within)\b/i.test(textQuery) || /,\s*[A-Za-z]{2,}/.test(textQuery);
  const genericFewWords = textQuery.split(/\s+/).length <= 4;
  if (!hasLocationHint && genericFewWords) textQuery = `${textQuery} near ${env.defaultLabel}`;
  return { textQuery, biased: true };
}

function wantsRichPlaceFields(query: string): boolean {
  return /\b(hours?|open|closed|phone|call|website|url|rating|reviews?|price|menu)\b/i.test(query);
}

function placeFieldMask(query: string): string {
  const fields = [
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.location",
    "places.googleMapsUri",
    "places.types",
  ];
  if (wantsRichPlaceFields(query)) {
    fields.push(
      "places.businessStatus",
      "places.nationalPhoneNumber",
      "places.internationalPhoneNumber",
      "places.websiteUri",
      "places.regularOpeningHours.openNow",
      "places.regularOpeningHours.weekdayDescriptions",
      "places.rating",
      "places.userRatingCount",
      "places.priceLevel",
    );
  }
  return fields.join(",");
}

function formatMeters(meters: number | undefined): string | undefined {
  if (typeof meters !== "number" || !Number.isFinite(meters)) return undefined;
  if (meters < 1000) return `${Math.round(meters)} m`;
  return `${(meters / 1000).toFixed(meters < 10_000 ? 1 : 0)} km`;
}

function parseDurationSeconds(value: string | undefined): number | undefined {
  const match = String(value ?? "").match(/^(\d+(?:\.\d+)?)s$/);
  if (!match) return undefined;
  const seconds = Number(match[1]);
  return Number.isFinite(seconds) ? seconds : undefined;
}

function formatDuration(value: string | undefined): string | undefined {
  const seconds = parseDurationSeconds(value);
  if (seconds === undefined) return undefined;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return remainder ? `${hours} hr ${remainder} min` : `${hours} hr`;
}

function mapsSearchUrl(query: string): string {
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`;
}

async function runStatus(cwd: string) {
  const env = loadMapsEnv(cwd);
  const enabled = Boolean(env.apiKey);
  return {
    content: [{ type: "text" as const, text: [
      `maps tool: ${enabled ? "configured" : "not configured"}`,
      `API key: ${enabled ? `loaded from ${env.apiKeySource ?? "environment"}` : "missing"}`,
      `.env: ${env.envPath ?? "not found"}`,
      `Default context: ${env.defaultLabel} (${env.defaultLat}, ${env.defaultLng}), region ${env.regionCode}`,
      enabled ? "Ready for one-parameter Google Maps queries." : "Set GOOGLE_MAPS_API_KEY in .env and enable Places API (New), Geocoding API, and Routes API.",
    ].join("\n") }],
    details: {
      ok: enabled,
      intent: "status",
      apiKeyLoaded: enabled,
      apiKeySource: env.apiKeySource,
      envPath: env.envPath,
      defaultContext: { label: env.defaultLabel, lat: env.defaultLat, lng: env.defaultLng, regionCode: env.regionCode, languageCode: env.languageCode },
    },
  };
}

async function runPlaceSearch(query: string, env: MapsEnv, signal?: AbortSignal) {
  const apiKey = requireApiKey(env);
  const { textQuery, biased } = placeSearchQuery(query, env);
  const body: any = {
    textQuery,
    languageCode: env.languageCode,
    regionCode: env.regionCode,
    maxResultCount: 5,
    locationBias: {
      circle: {
        center: { latitude: env.defaultLat, longitude: env.defaultLng },
        radius: env.defaultRadiusMeters,
      },
    },
  };

  const data = await requestJson("https://places.googleapis.com/v1/places:searchText", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Goog-Api-Key": apiKey,
      "X-Goog-FieldMask": placeFieldMask(query),
    },
    body: JSON.stringify(body),
  }, env, signal);

  const places = Array.isArray(data.places) ? data.places : [];
  const lines = [`Google Maps results for “${textQuery}”:`];
  if (!places.length) lines.push("No places found.");
  for (const [index, place] of places.entries()) {
    const name = place.displayName?.text || place.displayName || place.id || "Unnamed place";
    const address = place.formattedAddress ? ` — ${place.formattedAddress}` : "";
    lines.push(`${index + 1}. ${name}${address}`);
    const extras: string[] = [];
    if (place.rating) extras.push(`Rating: ${place.rating}${place.userRatingCount ? ` (${place.userRatingCount})` : ""}`);
    if (place.regularOpeningHours?.openNow !== undefined) extras.push(place.regularOpeningHours.openNow ? "Open now" : "Closed now");
    if (place.nationalPhoneNumber) extras.push(`Phone: ${place.nationalPhoneNumber}`);
    if (place.websiteUri) extras.push(`Website: ${place.websiteUri}`);
    if (extras.length) lines.push(`   ${extras.join(" · ")}`);
    if (place.googleMapsUri) lines.push(`   ${place.googleMapsUri}`);
    else lines.push(`   ${mapsSearchUrl(`${name} ${place.formattedAddress ?? ""}`.trim())}`);
  }
  if (biased) lines.push(`Context: biased near ${env.defaultLabel}.`);
  lines.push("Powered by Google Maps.");

  return {
    content: [{ type: "text" as const, text: truncate(lines.join("\n"), 16_000) }],
    details: { ok: true, intent: "place_search", query, textQuery, attribution: "Powered by Google Maps", places },
  };
}

async function runPlaceCoordinateLookup(query: string, target: string, env: MapsEnv, signal?: AbortSignal, fallbackReason?: string) {
  const apiKey = requireApiKey(env);
  const data = await requestJson("https://places.googleapis.com/v1/places:searchText", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Goog-Api-Key": apiKey,
      "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.location,places.googleMapsUri",
    },
    body: JSON.stringify({
      textQuery: target,
      languageCode: env.languageCode,
      regionCode: env.regionCode,
      maxResultCount: 5,
      locationBias: {
        circle: {
          center: { latitude: env.defaultLat, longitude: env.defaultLng },
          radius: env.defaultRadiusMeters,
        },
      },
    }),
  }, env, signal);

  const places = Array.isArray(data.places) ? data.places : [];
  const lines = [`Google Maps place-coordinate lookup for “${target}”:`];
  if (!places.length) lines.push("No place results found.");
  for (const [index, place] of places.entries()) {
    const name = place.displayName?.text || place.displayName || place.id || "Unnamed place";
    const location = place.location;
    const locationText = location ? ` (${location.latitude}, ${location.longitude})` : "";
    const address = place.formattedAddress ? ` — ${place.formattedAddress}` : "";
    lines.push(`${index + 1}. ${name}${address}${locationText}`);
    if (place.googleMapsUri) lines.push(`   ${place.googleMapsUri}`);
  }
  if (fallbackReason) lines.push("Note: used Places API because Geocoding API is not authorized for this key.");
  lines.push("Powered by Google Maps.");

  return {
    content: [{ type: "text" as const, text: truncate(lines.join("\n"), 16_000) }],
    details: { ok: true, intent: "place_coordinate_lookup", query, target, attribution: "Powered by Google Maps", fallbackReason, places },
  };
}

async function runGeocode(query: string, env: MapsEnv, signal?: AbortSignal) {
  const apiKey = requireApiKey(env);
  const coords = parseCoordinatePair(query);
  const params = new URLSearchParams({ key: apiKey, language: env.languageCode, region: env.regionCode });
  let mode: "geocode" | "reverse_geocode" = "geocode";
  let target: string;

  if (coords && /\b(address|where|reverse|near|what is at)\b/i.test(query)) {
    mode = "reverse_geocode";
    target = `${coords.lat},${coords.lng}`;
    params.set("latlng", target);
  } else {
    target = parseGeocodeAddress(query, env);
    params.set("address", target);
  }

  const url = `https://maps.googleapis.com/maps/api/geocode/json?${params.toString()}`;
  let data: any;
  try {
    data = await requestJson(url, { method: "GET" }, env, signal);
  } catch (error: any) {
    const message = redact(String(error?.message ?? error), env);
    if (mode === "geocode" && /REQUEST_DENIED|not authorized|not configured|not been used|disabled/i.test(message)) {
      return runPlaceCoordinateLookup(query, target, env, signal, message);
    }
    throw error;
  }
  const results = Array.isArray(data.results) ? data.results.slice(0, 5) : [];

  const lines = [`Google Maps ${mode === "reverse_geocode" ? "reverse geocode" : "geocode"} for “${target}”:`];
  if (!results.length) lines.push("No geocoding results found.");
  for (const [index, result] of results.entries()) {
    const location = result.geometry?.location;
    const locationText = location ? ` (${location.lat}, ${location.lng})` : "";
    lines.push(`${index + 1}. ${result.formatted_address || "Unnamed result"}${locationText}`);
    if (result.place_id) lines.push(`   Place ID: ${result.place_id}`);
  }
  lines.push("Powered by Google Maps.");

  return {
    content: [{ type: "text" as const, text: truncate(lines.join("\n"), 16_000) }],
    details: { ok: true, intent: mode, query, target, attribution: "Powered by Google Maps", results },
  };
}

async function runRoute(query: string, env: MapsEnv, signal?: AbortSignal) {
  const apiKey = requireApiKey(env);
  const parsed = parseRoute(query, env);
  if (!parsed) {
    // If route parsing is ambiguous, a plain place search is more useful than a schema error for a one-parameter tool.
    return runPlaceSearch(query, env, signal);
  }

  const body: any = {
    origin: { address: parsed.origin },
    destination: { address: parsed.destination },
    travelMode: parsed.travelMode,
    languageCode: env.languageCode,
    units: "METRIC",
    computeAlternativeRoutes: false,
  };
  if (parsed.travelMode === "DRIVE" || parsed.travelMode === "TWO_WHEELER") {
    body.routingPreference = "TRAFFIC_AWARE";
    // Routes API requires departureTime to be in the future; a small offset avoids clock/race skew.
    body.departureTime = new Date(Date.now() + 60_000).toISOString();
  }

  const data = await requestJson("https://routes.googleapis.com/directions/v2:computeRoutes", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Goog-Api-Key": apiKey,
      "X-Goog-FieldMask": [
        "routes.description",
        "routes.distanceMeters",
        "routes.duration",
        "routes.staticDuration",
        "routes.routeLabels",
        "routes.legs.distanceMeters",
        "routes.legs.duration",
        "routes.legs.steps.distanceMeters",
        "routes.legs.steps.staticDuration",
        "routes.legs.steps.navigationInstruction.instructions",
      ].join(","),
    },
    body: JSON.stringify(body),
  }, env, signal);

  const route = Array.isArray(data.routes) ? data.routes[0] : undefined;
  const lines = [`Google Maps route: ${parsed.origin} → ${parsed.destination} (${parsed.travelMode})`];
  if (!route) {
    lines.push("No route found.");
  } else {
    const distance = formatMeters(route.distanceMeters);
    const duration = formatDuration(route.duration);
    const staticDuration = formatDuration(route.staticDuration);
    const summary = [distance, duration ? `about ${duration}` : undefined, staticDuration && staticDuration !== duration ? `normally ${staticDuration}` : undefined]
      .filter(Boolean)
      .join(" · ");
    if (summary) lines.push(summary);
    if (route.description) lines.push(route.description);

    const steps = (Array.isArray(route.legs) ? route.legs : [])
      .flatMap((leg: any) => Array.isArray(leg.steps) ? leg.steps : [])
      .map((step: any) => step.navigationInstruction?.instructions)
      .filter((step: any): step is string => typeof step === "string" && step.trim().length > 0)
      .slice(0, 8);
    if (steps.length) {
      lines.push("Steps:");
      for (const [index, step] of steps.entries()) lines.push(`${index + 1}. ${step}`);
      const totalSteps = (Array.isArray(route.legs) ? route.legs : []).flatMap((leg: any) => Array.isArray(leg.steps) ? leg.steps : []).length;
      if (totalSteps > steps.length) lines.push(`… ${totalSteps - steps.length} more step${totalSteps - steps.length === 1 ? "" : "s"}.`);
    }
  }
  lines.push(mapsSearchUrl(`${parsed.origin} to ${parsed.destination}`));
  lines.push("Powered by Google Maps.");

  return {
    content: [{ type: "text" as const, text: truncate(lines.join("\n"), 16_000) }],
    details: { ok: true, intent: "route", query, routeRequest: parsed, attribution: "Powered by Google Maps", route },
  };
}

async function executeMapsQuery(cwd: string, rawQuery: unknown, signal?: AbortSignal) {
  const query = String(rawQuery ?? "").replace(/[\r\n\t]+/g, " ").replace(/\s+/g, " ").trim();
  if (!query) return runStatus(cwd);
  const env = loadMapsEnv(cwd);
  const intent = classifyQuery(query);

  try {
    if (intent === "status") return runStatus(cwd);
    if (intent === "route") return await runRoute(query, env, signal);
    if (intent === "geocode") return await runGeocode(query, env, signal);
    return await runPlaceSearch(query, env, signal);
  } catch (error: any) {
    const message = redact(String(error?.message ?? error), env);
    return {
      content: [{ type: "text" as const, text: `Maps query failed.\n\n${message}` }],
      details: { ok: false, intent, query, error: message, apiKeyLoaded: Boolean(env.apiKey), apiKeySource: env.apiKeySource, envPath: env.envPath },
    };
  }
}

export default function registerMaps(pi: ExtensionAPI) {
  pi.on("session_start", async (_event, ctx) => {
    loadMapsEnv(ctx.cwd);
  });

  pi.registerTool({
    name: "maps",
    label: "Maps",
    description: "One-parameter Google Maps tool. Ask natural-language questions about places, addresses, coordinates, directions, routes, travel time, or local searches.",
    promptSnippet: "Query Google Maps with one plain-language parameter: maps({ query: 'coffee near Pickering Town Centre' }) or maps({ query: 'directions from Pickering ON to Pearson Airport' }).",
    promptGuidelines: [
      "Use maps for Google Maps/location questions. It has exactly one parameter: query.",
      "Pass the user's natural-language request unchanged when possible; the tool internally chooses place search, geocoding, or Routes API.",
      "For ambiguous local searches such as 'coffee near me', maps uses the configured local context, defaulting to Pickering, Ontario, Canada.",
      "Do not pass API keys or hidden location details in query. If the tool reports missing configuration, tell sir to set GOOGLE_MAPS_API_KEY in .env.",
    ],
    parameters: Type.Object({
      query: Type.String({ description: "Natural-language Google Maps query: places, addresses, coordinates, directions, routes, travel time, or local searches." }),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      return executeMapsQuery(ctx.cwd, (params as any).query, signal);
    },
  });

  pi.registerCommand("maps", {
    description: "Run the one-parameter Google Maps helper. Examples: /maps status | /maps coffee near Pickering | /maps directions from Pickering ON to Pearson Airport",
    handler: async (args: string, ctx: ExtensionContext) => {
      const result = await executeMapsQuery(ctx.cwd, args.trim() || "status");
      ctx.ui.notify(String(result.content?.[0]?.text ?? "Done").slice(0, 4000), result.details?.ok === false ? "error" : "info");
    },
  });
}
