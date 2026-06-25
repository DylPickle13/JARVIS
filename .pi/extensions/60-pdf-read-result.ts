import { existsSync, readFileSync, statSync } from "node:fs";
import { mkdtemp, writeFile } from "node:fs/promises";
import { execFile as execFileCallback } from "node:child_process";
import { tmpdir } from "node:os";
import { promisify } from "node:util";
import { basename, join } from "node:path";

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
  DEFAULT_MAX_BYTES,
  DEFAULT_MAX_LINES,
  formatSize,
  truncateHead,
  withFileMutationQueue,
  type TruncationResult,
} from "@earendil-works/pi-coding-agent";

import { envValue, findAncestorFile, parseDotEnv } from "./lib/env";
import { normalizePathInput } from "./lib/path";

const DEFAULT_OMLX_BASE_URL = "http://127.0.0.1:8000";
const DEFAULT_OMLX_PDF_MODEL = "MarkItDown";
const DEFAULT_MAX_PDF_BYTES = 25 * 1024 * 1024;
const DEFAULT_OMLX_TIMEOUT_MS = 180_000;
const DEFAULT_LOCAL_FALLBACK_TIMEOUT_MS = 30_000;
const execFile = promisify(execFileCallback);

interface PdfReadDetails {
  ok: boolean;
  path: string;
  filename: string;
  sizeBytes?: number;
  implementation: "pi-extension-ts";
  replacedReadResult: true;
  source: "omlx-markitdown" | "local-pdftotext";
  omlxBaseUrl?: string;
  model?: string;
  fallback?: boolean;
  error?: string;
  originalReadWasError?: boolean;
  fullOutputPath?: string;
  truncation?: TruncationResult;
}

function normalizeBaseUrl(raw: string): string {
  const value = raw.trim().replace(/\/+$/, "");
  return value.endsWith("/v1") ? value.slice(0, -3) : value;
}

function isPdfReadEvent(event: any): event is { input: { path: string }; isError?: boolean } {
  if (event?.toolName !== "read") return false;
  const path = event?.input?.path;
  return typeof path === "string" && path.trim().toLowerCase().endsWith(".pdf");
}

async function truncateForTool(text: string): Promise<{ text: string; fullOutputPath?: string; truncation?: TruncationResult }> {
  const truncation = truncateHead(text, {
    maxBytes: DEFAULT_MAX_BYTES,
    maxLines: DEFAULT_MAX_LINES,
  });

  if (!truncation.truncated) return { text };

  const tempDir = await mkdtemp(join(tmpdir(), "pi-pdf-read-"));
  const fullOutputPath = join(tempDir, "pdf-output.md");
  await withFileMutationQueue(fullOutputPath, async () => {
    await writeFile(fullOutputPath, text, "utf8");
  });

  const notice = [
    "",
    `[PDF output truncated: showing ${truncation.outputLines} of ${truncation.totalLines} lines`,
    `(${formatSize(truncation.outputBytes)} of ${formatSize(truncation.totalBytes)}).`,
    `Full output saved to: ${fullOutputPath}]`,
  ].join(" ");

  return {
    text: `${truncation.content}${notice}`,
    fullOutputPath,
    truncation,
  };
}

function composeAbortSignal(parent: AbortSignal | undefined, timeoutMs: number): { signal: AbortSignal; cleanup: () => void } {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(new Error(`Timed out after ${timeoutMs}ms`)), timeoutMs);

  const abortFromParent = () => controller.abort(parent?.reason ?? new Error("Aborted"));
  if (parent) {
    if (parent.aborted) abortFromParent();
    else parent.addEventListener("abort", abortFromParent, { once: true });
  }

  return {
    signal: controller.signal,
    cleanup: () => {
      clearTimeout(timer);
      if (parent) parent.removeEventListener("abort", abortFromParent);
    },
  };
}

function extractChatCompletionText(payload: any): string {
  const content = payload?.choices?.[0]?.message?.content;
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((part) => {
        if (typeof part === "string") return part;
        if (typeof part?.text === "string") return part.text;
        if (typeof part?.content === "string") return part.content;
        return "";
      })
      .filter(Boolean)
      .join("\n");
  }
  return "";
}

async function readPdfViaOmlx(path: string, cwd: string, signal?: AbortSignal): Promise<{ text: string; details: Omit<PdfReadDetails, "ok" | "path" | "filename" | "sizeBytes" | "implementation" | "replacedReadResult" | "source"> }> {
  const dotenv = parseDotEnv(findAncestorFile(cwd, ".env"));
  const rawBaseUrl =
    envValue("OMLX_BASE_URL", cwd, dotenv) ||
    envValue("BRIEFING_OMLX_BASE_URL", cwd, dotenv) ||
    DEFAULT_OMLX_BASE_URL;
  const baseUrl = normalizeBaseUrl(rawBaseUrl || DEFAULT_OMLX_BASE_URL);
  const apiKey = envValue("OMLX_API_KEY", cwd, dotenv) || "local";
  const model = envValue("OMLX_PDF_MODEL", cwd, dotenv) || DEFAULT_OMLX_PDF_MODEL;
  const timeoutMs = Number(envValue("OMLX_PDF_TIMEOUT_MS", cwd, dotenv)) || DEFAULT_OMLX_TIMEOUT_MS;

  const data = readFileSync(path);
  const abort = composeAbortSignal(signal, timeoutMs);
  let raw = "";
  let ok = false;
  let status = 0;
  try {
    const response = await fetch(`${baseUrl}/v1/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}),
      },
      body: JSON.stringify({
        model,
        messages: [
          {
            role: "user",
            content: [
              {
                type: "file",
                file: {
                  filename: basename(path),
                  mime_type: "application/pdf",
                  file_data: data.toString("base64"),
                },
              },
            ],
          },
        ],
      }),
      signal: abort.signal,
    });
    ok = response.ok;
    status = response.status;
    raw = await response.text();
  } finally {
    abort.cleanup();
  }
  if (!ok) {
    throw new Error(`oMLX PDF request failed (${status}): ${raw.slice(0, 1000)}`);
  }

  let parsed: any;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error(`oMLX PDF request returned non-JSON response: ${raw.slice(0, 1000)}`);
  }

  const text = extractChatCompletionText(parsed).trim();
  if (!text) throw new Error("oMLX PDF request returned an empty document conversion");

  return { text, details: { omlxBaseUrl: baseUrl, model } };
}

async function readPdfViaLocalFallback(path: string, cwd: string, signal?: AbortSignal): Promise<string> {
  const candidates = [
    process.env.PDFTOTEXT_BIN?.trim(),
    "/opt/homebrew/bin/pdftotext",
    "/usr/local/bin/pdftotext",
    "pdftotext",
  ].filter(Boolean) as string[];

  let lastError = "pdftotext unavailable";
  for (const bin of candidates) {
    try {
      const result = await execFile(bin, ["-layout", "-enc", "UTF-8", path, "-"], {
        cwd: cwd || process.cwd(),
        timeout: DEFAULT_LOCAL_FALLBACK_TIMEOUT_MS,
        maxBuffer: DEFAULT_MAX_BYTES,
        signal,
      });
      const output = result.stdout.trim();
      if (output) return `# PDF text extraction fallback\n\n${output}`;
      lastError = `${bin} returned empty output`;
    } catch (err) {
      lastError = err instanceof Error ? err.message : String(err);
    }
  }

  throw new Error(lastError);
}

export default function registerPdfReadResult(pi: ExtensionAPI) {
  pi.on("tool_result", async (event, ctx) => {
    if (!isPdfReadEvent(event)) return undefined;

    const inputPath = event.input.path;
    const path = normalizePathInput(inputPath, ctx.cwd);
    const filename = basename(path);

    try {
      if (!existsSync(path)) throw new Error(`PDF file not found: ${path}`);
      const stat = statSync(path);
      if (!stat.isFile()) throw new Error(`PDF path is not a file: ${path}`);

      const dotenv = parseDotEnv(findAncestorFile(ctx.cwd, ".env"));
      const maxBytes = Number(envValue("OMLX_PDF_MAX_BYTES", ctx.cwd, dotenv)) || DEFAULT_MAX_PDF_BYTES;
      if (stat.size > maxBytes) {
        throw new Error(`PDF is too large for oMLX MarkItDown (${formatSize(stat.size)} > ${formatSize(maxBytes)})`);
      }

      try {
        const converted = await readPdfViaOmlx(path, ctx.cwd, ctx.signal);
        const output = await truncateForTool(converted.text);
        return {
          content: [{ type: "text", text: output.text }],
          details: {
            ok: true,
            path,
            filename,
            sizeBytes: stat.size,
            implementation: "pi-extension-ts",
            replacedReadResult: true,
            source: "omlx-markitdown",
            ...converted.details,
            originalReadWasError: Boolean(event.isError),
            fullOutputPath: output.fullOutputPath,
            truncation: output.truncation,
          } satisfies PdfReadDetails,
          isError: false,
        };
      } catch (omlxErr) {
        const fallbackText = await readPdfViaLocalFallback(path, ctx.cwd, ctx.signal);
        const output = await truncateForTool(
          [
            `<!-- oMLX PDF conversion failed; used local pdftotext fallback. Error: ${omlxErr instanceof Error ? omlxErr.message : String(omlxErr)} -->`,
            fallbackText,
          ].join("\n\n"),
        );
        return {
          content: [{ type: "text", text: output.text }],
          details: {
            ok: true,
            path,
            filename,
            sizeBytes: stat.size,
            implementation: "pi-extension-ts",
            replacedReadResult: true,
            source: "local-pdftotext",
            fallback: true,
            error: omlxErr instanceof Error ? omlxErr.message : String(omlxErr),
            originalReadWasError: Boolean(event.isError),
            fullOutputPath: output.fullOutputPath,
            truncation: output.truncation,
          } satisfies PdfReadDetails,
          isError: false,
        };
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      return {
        content: [{ type: "text", text: `PDF read failed for ${inputPath}: ${message}` }],
        details: {
          ok: false,
          path,
          filename,
          implementation: "pi-extension-ts",
          replacedReadResult: true,
          source: "local-pdftotext",
          error: message,
          originalReadWasError: Boolean(event.isError),
        } satisfies PdfReadDetails,
        isError: true,
      };
    }
  });
}
