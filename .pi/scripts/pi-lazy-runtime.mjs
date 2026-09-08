#!/usr/bin/env node
// Reproducible opt-in Pi build. Never edits the globally installed package.
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, lstatSync, mkdirSync, readFileSync, readlinkSync, renameSync, symlinkSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const base = join(root, ".pi/runtime/pi-lazy-tools");
const patch = join(root, ".pi/patches/pi-0.85.1-lazy-execution.patch");
const version = "0.85.1";
const commit = "d981de1229ef899957bbe968bc8dcda02a21f477";
const packageName = "@earendil-works/pi-coding-agent";
const buildFile = join(base, "build.json");
const installFile = join(base, "installation.json");
const action = process.argv[2] || "status";
const json = (path) => JSON.parse(readFileSync(path, "utf8"));
function save(path, value) { writeFileSync(path, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 }); }
function run(command, args, cwd = root, env = {}) {
  console.log(`$ ${command} ${args.join(" ")}`);
  execFileSync(command, args, { cwd, stdio: "inherit", env: { ...process.env, ...env }, timeout: 600_000 });
}
function output(command, args, cwd = root) {
  return execFileSync(command, args, { cwd, encoding: "utf8", timeout: 60_000 }).trim();
}
function linkAtomically(target, link) {
  const temporary = `${link}.jarvis-lazy-${process.pid}`;
  symlinkSync(target, temporary);
  renameSync(temporary, link);
}
function tests(runtime) {
  const script = join(root, ".pi/scripts/tests/pi-lazy-tools.test.mjs");
  for (const bundled of ["0", "1"]) {
    run(process.execPath, ["--test", script], root,
      { PI_OFFLINE: "1", PI_LAZY_TEST_RUNTIME: runtime, PI_LAZY_TEST_BUNDLED: bundled, JARVIS_PI_LAZY_AUTOCALL: "1" });
  }
}
mkdirSync(base, { recursive: true, mode: 0o700 });

if (action === "build") {
  const patchSha256 = createHash("sha256").update(readFileSync(patch)).digest("hex");
  const release = join(base, "releases", patchSha256.slice(0, 16));
  const source = join(release, "source");
  const consumer = join(release, "node");
  const runtime = join(consumer, "node_modules", packageName);
  const completed = join(release, "build.json");
  if (existsSync(completed)) {
    const build = json(completed);
    if (build.patchSha256 !== patchSha256 || build.commit !== commit) throw new Error("Build identity mismatch");
    tests(build.runtime);
    save(buildFile, build);
    console.log(`Verified existing build: ${runtime}`);
    process.exit(0);
  }
  if (existsSync(release)) throw new Error(`Incomplete build exists; inspect/move it before rebuilding: ${release}`);
  mkdirSync(release, { recursive: true, mode: 0o700 });
  run("git", ["clone", "--depth", "1", "--branch", `v${version}`, "https://github.com/earendil-works/pi.git", source]);
  if (output("git", ["rev-parse", "HEAD"], source) !== commit) throw new Error("Upstream tag changed; refusing build");
  run("git", ["apply", "--check", patch], source);
  run("git", ["apply", patch], source);
  run("npm", ["ci", "--ignore-scripts"], source);
  // The upstream checkout omits generated catalog data. Reuse the matching npm
  // release's data, not a moving online catalog or any provider login.
  const catalogDir = join(release, "catalog");
  mkdirSync(catalogDir);
  run("npm", ["pack", `@earendil-works/pi-ai@${version}`, "--ignore-scripts", "--pack-destination", catalogDir], release);
  run("tar", ["-xzf", join(catalogDir, `earendil-works-pi-ai-${version}.tgz`), "--strip-components=3", "-C",
    join(source, "packages/ai/src/providers"), "package/dist/providers/data"]);
  run("npm", ["run", "build:offline"], source);
  run("npx", ["tsgo", "--noEmit"], source);
  run("npx", ["vitest", "run", "test/agent-loop.test.ts", "test/agent.test.ts"], join(source, "packages/agent"));
  run("npx", ["vitest", "run", "test/agent-session-dynamic-tools.test.ts", "test/extensions-runner.test.ts",
    "test/default-tools-setting.test.ts", "test/tool-system-prompt-contributions.test.ts"], join(source, "packages/coding-agent"));
  run("npx", ["vitest", "run", "test/deferred-tools.test.ts"], join(source, "packages/ai"));
  const { packReleasePackages, installCodingAgentConsumer, smokeTestCodingAgentConsumer } =
    await import(pathToFileURL(join(source, "scripts/coding-agent-consumer.mjs")));
  const tarballs = packReleasePackages([
    { name: "@earendil-works/pi-agent-core", directory: join(source, "packages/agent") },
    { name: packageName, directory: join(source, "packages/coding-agent") },
  ], join(release, "tarballs"));
  installCodingAgentConsumer(consumer, tarballs);
  smokeTestCodingAgentConsumer(consumer);
  tests(runtime);
  const build = { version, commit, patchSha256, runtime, source, consumer,
    cli: join(runtime, "dist/bundle/cli.js"), rpc: join(runtime, "dist/bundle/rpc-entry.js") };
  save(completed, build);
  save(buildFile, build);
  console.log(`Build passed. Activate with: node .pi/scripts/pi-lazy-runtime.mjs install`);
} else if (action === "install") {
  const build = json(buildFile);
  const currentHash = createHash("sha256").update(readFileSync(patch)).digest("hex");
  if (build.commit !== commit || build.patchSha256 !== currentHash) throw new Error("Patch changed; build first");
  tests(build.runtime);
  const prefix = output("npm", ["prefix", "-g"]);
  const link = join(prefix, "bin/pi");
  if (!lstatSync(link).isSymbolicLink()) throw new Error(`Refusing to replace a non-symlink: ${link}`);
  const target = readlinkSync(link);
  const prior = existsSync(installFile) ? json(installFile) : undefined;
  const stockRuntime = join(prefix, "lib/node_modules", packageName);
  const stockCLI = join(stockRuntime, "dist/bundle/cli.js");
  const isStock = resolve(dirname(link), target) === stockCLI;
  const isManaged = prior?.link === link && resolve(dirname(link), target) === prior.installedTarget;
  if (!isStock && !isManaged) throw new Error(`pi points elsewhere; refusing to replace ${link} -> ${target}`);
  if (isStock && json(join(stockRuntime, "package.json")).version !== version) {
    throw new Error(`Global Pi is no longer ${version}; review/rebase instead of silently downgrading`);
  }
  const state = { link, originalTarget: isManaged ? prior.originalTarget : target,
    installedTarget: build.cli, patchSha256: build.patchSha256 };
  // Persist rollback information before the atomic link replacement.
  save(installFile, state);
  linkAtomically(build.cli, link);
  console.log(`Activated ${link} -> ${build.cli}\nRestart Pi processes to use the new core; /reload alone cannot upgrade a running core.`);
} else if (action === "rollback") {
  const state = json(installFile);
  const target = readlinkSync(state.link);
  if (resolve(dirname(state.link), target) !== state.installedTarget) {
    throw new Error("pi has changed since installation; refusing to overwrite it");
  }
  if (!existsSync(resolve(dirname(state.link), state.originalTarget))) throw new Error("Original Pi target is missing");
  linkAtomically(state.originalTarget, state.link);
  console.log(`Restored ${state.link} -> ${state.originalTarget}. Restart Pi to use stock core.`);
} else if (action === "test") {
  tests(json(buildFile).runtime);
} else if (action === "status") {
  console.log(existsSync(buildFile) ? JSON.stringify(json(buildFile), null, 2) : "No reproducible build yet.");
  if (existsSync(installFile)) {
    const state = json(installFile);
    console.log(`Executable: ${state.link} -> ${readlinkSync(state.link)}`);
  }
} else {
  throw new Error("Usage: node .pi/scripts/pi-lazy-runtime.mjs build|install|test|status|rollback");
}
