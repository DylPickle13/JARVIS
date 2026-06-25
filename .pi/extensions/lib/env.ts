import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

export type DotEnv = Record<string, string>;

export function findAncestorFile(startDir: string, fileName: string): string | undefined {
  let current = resolve(startDir || process.cwd());
  while (true) {
    const candidate = join(current, fileName);
    if (existsSync(candidate)) return candidate;
    const parent = dirname(current);
    if (parent === current) return undefined;
    current = parent;
  }
}

export function unquoteDotEnvValue(rawValue: string): string {
  const trimmed = rawValue.trim();
  if (trimmed.length >= 2 && trimmed.startsWith('"') && trimmed.endsWith('"')) {
    return trimmed
      .slice(1, -1)
      .replace(/\\n/g, "\n")
      .replace(/\\r/g, "\r")
      .replace(/\\t/g, "\t")
      .replace(/\\"/g, '"')
      .replace(/\\\\/g, "\\");
  }
  if (trimmed.length >= 2 && trimmed.startsWith("'") && trimmed.endsWith("'")) {
    return trimmed.slice(1, -1);
  }
  return trimmed.replace(/\s+#.*$/, "");
}

export function parseDotEnv(envPath: string | undefined): DotEnv {
  if (!envPath) return {};
  const values: DotEnv = {};
  let text = "";
  try {
    text = readFileSync(envPath, "utf8");
  } catch {
    return values;
  }

  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const match = line.match(/^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/);
    if (!match) continue;
    values[match[1]] = unquoteDotEnvValue(match[2]);
  }
  return values;
}

export const parseDotEnvFile = parseDotEnv;

export function envValue(name: string, cwd: string, dotenv?: DotEnv): string {
  const direct = process.env[name]?.trim();
  if (direct) return direct;
  const env = dotenv ?? parseDotEnv(findAncestorFile(cwd, ".env"));
  return env[name]?.trim() ?? "";
}

export function firstEnvValue(names: readonly string[], cwd: string, dotenv?: DotEnv): string {
  for (const name of names) {
    const value = envValue(name, cwd, dotenv).trim();
    if (value) return value;
  }
  return "";
}
