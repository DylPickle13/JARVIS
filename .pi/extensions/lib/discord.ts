import { basename } from "node:path";

export function safeDiscordFilename(path: string): string {
  const name = basename(path).replace(/[\r\n"\\/]/g, "_").trim();
  return name || "attachment";
}

export function safeDiscordContentFilename(filename: string): string {
  return filename.replace(/[\r\n`*_~|>@]/g, "_").slice(0, 120) || "attachment";
}

export function jsonBuffer(value: unknown): Buffer {
  return Buffer.from(JSON.stringify(value), "utf8");
}

export function multipartHeader(boundary: string, name: string, filename?: string, contentType?: string): Buffer {
  const lines = [`--${boundary}`, `Content-Disposition: form-data; name="${name}"${filename ? `; filename="${filename}"` : ""}`];
  if (contentType) lines.push(`Content-Type: ${contentType}`);
  lines.push("", "");
  return Buffer.from(lines.join("\r\n"), "utf8");
}
