import { spawnSync } from "node:child_process";
import { existsSync, unlinkSync } from "node:fs";
import { basename } from "node:path";

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

type DeleteSessionFileResult =
  | { ok: true; method: "trash" | "unlink" | "missing" }
  | { ok: false; method: "unlink"; error: string };

function deleteSessionFile(sessionPath: string): DeleteSessionFileResult {
  if (!existsSync(sessionPath)) return { ok: true, method: "missing" };

  const trashArgs = sessionPath.startsWith("-") ? ["--", sessionPath] : [sessionPath];
  const trashResult = spawnSync("trash", trashArgs, { encoding: "utf8", timeout: 10_000 });
  const trashErrorHint = () => {
    const parts: string[] = [];
    if (trashResult.error) parts.push(trashResult.error.message);
    const stderr = trashResult.stderr?.trim();
    if (stderr) parts.push(stderr.split("\n")[0] ?? stderr);
    if (parts.length === 0) return "";
    return ` trash: ${parts.join(" · ").slice(0, 200)}`;
  };

  if (trashResult.status === 0 || !existsSync(sessionPath)) {
    return { ok: true, method: "trash" };
  }

  try {
    unlinkSync(sessionPath);
    return { ok: true, method: "unlink" };
  } catch (error: any) {
    return {
      ok: false,
      method: "unlink",
      error: `${error?.message ?? String(error)}${trashErrorHint()}`,
    };
  }
}

function hasYesFlag(args: string): boolean {
  return args
    .split(/\s+/)
    .map((part) => part.trim().toLowerCase())
    .some((part) => part === "--yes" || part === "-y" || part === "yes" || part === "confirm");
}

export default function registerDeleteCurrentSession(pi: ExtensionAPI) {
  pi.registerCommand("delete", {
    description: "Delete/discard the current saved Pi session and immediately switch to a fresh session. Use /delete --yes to skip confirmation.",
    handler: async (args, ctx) => {
      await ctx.waitForIdle();

      const oldSessionFile = ctx.sessionManager.getSessionFile();
      const skipConfirm = hasYesFlag(args);

      if (oldSessionFile && !skipConfirm) {
        const ok = await ctx.ui.confirm(
          "Delete current Pi session?",
          `This will switch to a fresh session and remove the saved session file:\n${oldSessionFile}`,
        );
        if (!ok) {
          ctx.ui.notify("Session deletion cancelled.", "warning");
          return;
        }
      }

      const result = await ctx.newSession({
        withSession: async (newCtx) => {
          if (!oldSessionFile) {
            newCtx.ui.notify("New session started", "info");
            return;
          }

          const deletion = deleteSessionFile(oldSessionFile);
          if (!deletion.ok) {
            newCtx.ui.notify(
              `New session started, but failed to delete ${basename(oldSessionFile)}: ${deletion.error}`,
              "error",
            );
            return;
          }

          newCtx.ui.notify("New session started", "info");
        },
      });

      if (result.cancelled) {
        ctx.ui.notify("Session deletion cancelled by a session switch guard; the saved session was preserved.", "warning");
      }
    },
  });
}
