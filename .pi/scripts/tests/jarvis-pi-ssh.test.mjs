import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { chmod, mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const wrapperPath = join(projectRoot, ".pi", "scripts", "jarvis-pi-ssh");

test("jarvis-pi-ssh creates only a private reverse stream-local picker bridge", async () => {
  const directory = await mkdtemp(join(tmpdir(), "jarvis-pi-ssh-test-"));
  const fakeSsh = join(directory, "fake-ssh.mjs");
  const capturePath = join(directory, "ssh-arguments.json");
  await writeFile(
    fakeSsh,
    `#!/usr/bin/env node\nimport { writeFileSync } from "node:fs";\nwriteFileSync(process.env.PI_ATTACH_TEST_CAPTURE, JSON.stringify(process.argv.slice(2)));\n`,
    "utf8",
  );
  await chmod(fakeSsh, 0o755);

  try {
    await execFileAsync(wrapperPath, ["example-host"], {
      env: {
        ...process.env,
        PI_ATTACH_SSH_BIN: fakeSsh,
        PI_ATTACH_NODE_BIN: process.execPath,
        PI_ATTACH_TEST_CAPTURE: capturePath,
        TMPDIR: directory,
      },
      encoding: "utf8",
      timeout: 20_000,
      maxBuffer: 256 * 1024,
    });
    const args = JSON.parse(await readFile(capturePath, "utf8"));
    const reverseIndex = args.indexOf("-R");
    assert.notEqual(reverseIndex, -1);
    assert.match(args[reverseIndex + 1], /^\/tmp\/pi-attach-[0-9]+-[0-9a-f]{20}\.sock:127\.0\.0\.1:[0-9]+$/);
    assert.ok(args.includes("ExitOnForwardFailure=yes"));
    assert.ok(args.includes("StreamLocalBindUnlink=yes"));
    assert.ok(args.includes("StreamLocalBindMask=0177"));
    assert.equal(args.at(-2), "example-host");
    assert.match(args.at(-1), /export PI_ATTACH_BRIDGE_SOCKET='\/tmp\/pi-attach-/);
    assert.match(args.at(-1), /export PI_ATTACH_BRIDGE_TOKEN='[0-9a-f]{64}'/);
    assert.doesNotMatch(args.join(" "), /0\.0\.0\.0/);
    assert.deepEqual(
      (await readdir(directory)).filter((name) => name.startsWith("jarvis-pi-ssh.")),
      [],
      "wrapper must stop its bridge and remove private runtime state after SSH exits",
    );
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
