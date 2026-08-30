import { execFile } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { extname, join } from "node:path";
import { promisify } from "node:util";

import type { ImageContent } from "@earendil-works/pi-ai";
import {
  detectSupportedImageMimeTypeFromFile,
  resizeImage,
} from "@earendil-works/pi-coding-agent";

import type { StagedAttachment } from "./core.ts";

const execFileAsync = promisify(execFile);
const RAW_IMAGE_BASE64_LIMIT = Math.floor(4.5 * 1024 * 1024);
const SIPS_CONVERTIBLE_EXTENSIONS = new Set([".heic", ".heif", ".tif", ".tiff", ".avif"]);

export type PreparedAttachmentImages = {
  images: ImageContent[];
  nativeImageIds: Set<string>;
};

async function convertWithSips(path: string): Promise<{ path: string; cleanup: () => Promise<void> } | null> {
  if (process.platform !== "darwin" || !SIPS_CONVERTIBLE_EXTENSIONS.has(extname(path).toLowerCase())) return null;
  const directory = await mkdtemp(join(tmpdir(), "pi-attach-image-"));
  const outputPath = join(directory, "converted.png");
  try {
    await execFileAsync("/usr/bin/sips", ["-s", "format", "png", path, "--out", outputPath], {
      encoding: "utf8",
      timeout: 30_000,
      maxBuffer: 256 * 1024,
    });
    return {
      path: outputPath,
      cleanup: () => rm(directory, { recursive: true, force: true }),
    };
  } catch {
    await rm(directory, { recursive: true, force: true }).catch(() => undefined);
    return null;
  }
}

async function prepareOne(item: StagedAttachment): Promise<ImageContent | null> {
  let sourcePath = item.path;
  let cleanup: (() => Promise<void>) | undefined;
  let mimeType = await detectSupportedImageMimeTypeFromFile(sourcePath).catch(() => null);

  if (!mimeType) {
    const converted = await convertWithSips(sourcePath);
    if (!converted) return null;
    sourcePath = converted.path;
    cleanup = converted.cleanup;
    mimeType = await detectSupportedImageMimeTypeFromFile(sourcePath).catch(() => null);
  }

  try {
    if (!mimeType) return null;
    const bytes = await readFile(sourcePath);
    const resized = await resizeImage(bytes, mimeType);
    if (resized) {
      return { type: "image", data: resized.data, mimeType: resized.mimeType };
    }

    const encoded = bytes.toString("base64");
    if (mimeType !== "image/bmp" && Buffer.byteLength(encoded, "utf8") < RAW_IMAGE_BASE64_LIMIT) {
      return { type: "image", data: encoded, mimeType };
    }
    return null;
  } finally {
    if (cleanup) await cleanup().catch(() => undefined);
  }
}

export async function prepareAttachmentImages(
  items: StagedAttachment[],
  modelSupportsImages: boolean,
): Promise<PreparedAttachmentImages> {
  const images: ImageContent[] = [];
  const nativeImageIds = new Set<string>();
  if (!modelSupportsImages) return { images, nativeImageIds };

  for (const item of items) {
    const image = await prepareOne(item).catch(() => null);
    if (!image) continue;
    images.push(image);
    nativeImageIds.add(item.id);
  }
  return { images, nativeImageIds };
}
