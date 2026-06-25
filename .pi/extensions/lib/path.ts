import { homedir } from "node:os";
import { resolve } from "node:path";

export function expandHomePath(pathValue: string): string {
  const cleaned = pathValue.trim();
  if (cleaned === "~") return homedir();
  if (cleaned.startsWith("~/")) return `${homedir()}${cleaned.slice(1)}`;
  return cleaned;
}

export function normalizePathInput(rawPath: string, cwd?: string): string {
  let cleaned = rawPath.trim();
  if (cleaned.startsWith("@")) cleaned = cleaned.slice(1).trim();
  cleaned = expandHomePath(cleaned);
  return cwd ? resolve(cwd || process.cwd(), cleaned) : cleaned;
}
