import { chmodSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import xtermHeadless from "@xterm/headless";
import type { Terminal as HeadlessTerminal } from "@xterm/headless";
import { spawn, type IPty } from "node-pty";

const { Terminal } = xtermHeadless as unknown as { Terminal: typeof HeadlessTerminal };

const MODULE_DIR = dirname(fileURLToPath(import.meta.url));

function ensureSpawnHelperExecutable(): void {
  if (process.platform !== "darwin") return;
  const candidates = [
    join(MODULE_DIR, "node_modules", "node-pty", "prebuilds", `darwin-${process.arch}`, "spawn-helper"),
    join(MODULE_DIR, "node_modules", "node-pty", "build", "Release", "spawn-helper"),
  ];
  for (const path of candidates) {
    if (!existsSync(path)) continue;
    chmodSync(path, 0o755);
    return;
  }
}

export type SshPtyOptions = {
  cols?: number;
  rows?: number;
  cwd?: string;
  env?: NodeJS.ProcessEnv;
};

/**
 * Spawn a local SSH client inside a local PTY. The SSH client's -tt option
 * allocates the remote PTY; this local PTY also makes resize/input handling
 * reliable for RPC sessions that cannot inherit the process terminal.
 */
export function spawnSshPty(args: string[], options: SshPtyOptions = {}): IPty {
  ensureSpawnHelperExecutable();
  return spawn("ssh", args, {
    name: process.env.TERM || "xterm-256color",
    cols: options.cols ?? 120,
    rows: options.rows ?? 40,
    cwd: options.cwd ?? process.cwd(),
    env: options.env ?? process.env,
    encoding: "utf8",
  });
}

export function createHeadlessTerminal(cols = 120, rows = 40): Terminal {
  return new Terminal({ allowProposedApi: true, cols, rows, scrollback: 2000 });
}

export function terminalScreen(terminal: Terminal): string {
  const buffer = terminal.buffer.active;
  const start = buffer.viewportY;
  const lines: string[] = [];
  for (let row = 0; row < terminal.rows; row += 1) {
    lines.push(buffer.getLine(start + row)?.translateToString(true) ?? "");
  }
  while (lines.length && !lines[lines.length - 1]) lines.pop();
  return lines.join("\n").trimEnd();
}

export type { IPty } from "node-pty";
export type Terminal = HeadlessTerminal;
