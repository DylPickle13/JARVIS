import { chmodSync, existsSync, mkdirSync, readdirSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const PROJECT_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const PRIVATE_FILE_MODE = 0o600;
const PRIVATE_DIR_MODE = 0o700;

const PRIVATE_FILES = [
	join(PROJECT_ROOT, ".env"),
	join(PROJECT_ROOT, ".pi", "settings.json"),
	join(PROJECT_ROOT, ".pi", "APPEND_SYSTEM.md"),
	join(PROJECT_ROOT, ".pi", "ssh-hosts.json"),
	join(PROJECT_ROOT, ".pi", "discord-cron.json"),
	join(PROJECT_ROOT, ".pi", "discord-cron.sqlite"),
	join(PROJECT_ROOT, ".pi", "discord-cron.sqlite-wal"),
	join(PROJECT_ROOT, ".pi", "discord-cron.sqlite-shm"),
	join(PROJECT_ROOT, ".pi", "discord-cron.sqlite-journal"),
];

const PRIVATE_DIRS = [
	join(PROJECT_ROOT, ".pi", "runtime"),
	join(PROJECT_ROOT, ".pi", "memory"),
	join(PROJECT_ROOT, ".pi", "session-search"),
	join(PROJECT_ROOT, ".pi", "discord-cron"),
];

const PRIVATE_RUNTIME_FILE_RE = /(?:\.sqlite(?:-(?:wal|shm|journal))?|\.sqlite\.lock|^deleted-sessions-.*\.json)$/;

function secureFile(path: string): void {
	if (!existsSync(path)) return;
	const stat = statSync(path);
	if (!stat.isFile()) throw new Error(`Refusing to chmod non-file private path: ${path}`);
	chmodSync(path, PRIVATE_FILE_MODE);
}

function secureDirectory(path: string): void {
	mkdirSync(path, { recursive: true, mode: PRIVATE_DIR_MODE });
	const stat = statSync(path);
	if (!stat.isDirectory()) throw new Error(`Private runtime path is not a directory: ${path}`);
	chmodSync(path, PRIVATE_DIR_MODE);
}

export default function enforcePrivatePermissions(_pi: ExtensionAPI) {
	for (const path of PRIVATE_DIRS) secureDirectory(path);
	for (const path of PRIVATE_FILES) secureFile(path);

	for (const directory of PRIVATE_DIRS.slice(1)) {
		for (const entry of readdirSync(directory, { withFileTypes: true })) {
			if (entry.isFile() && PRIVATE_RUNTIME_FILE_RE.test(entry.name)) {
				secureFile(join(directory, entry.name));
			}
		}
	}
}
