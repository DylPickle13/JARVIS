// Resolve Pi without assuming npm's nested dependency layout. Managed installs
// hoist dependencies and select their release through install/current-version.
import { existsSync, readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join, resolve } from 'node:path';
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';

const packageName = '@earendil-works/pi-coding-agent';
function checkedRoot(root) {
  const absolute = resolve(root);
  const pkg = JSON.parse(readFileSync(join(absolute, 'package.json'), 'utf8'));
  if (pkg.name !== packageName) throw new Error(`Not a Pi runtime: ${absolute}`);
  return absolute;
}
export function piRuntimeRoot({ env = process.env, home = homedir(), npmRoot } = {}) {
  if (env.PI_CODEMODE_TEST_RUNTIME) return checkedRoot(env.PI_CODEMODE_TEST_RUNTIME);
  if (env.PI_TEST_NODE_MODULES) return checkedRoot(join(env.PI_TEST_NODE_MODULES, packageName));
  const agent = env.PI_CODING_AGENT_DIR || join(home, '.pi/agent');
  const managed = env.PI_MANAGED_INSTALL_ROOT || join(agent, 'install');
  if (existsSync(join(managed, 'managed-install.json'))) {
    const marker = JSON.parse(readFileSync(join(managed, 'managed-install.json'), 'utf8'));
    if (marker.kind !== 'pi-managed-install' || marker.schemaVersion !== 1 || marker.layout !== 'releases-v1') {
      throw new Error(`Unsupported managed Pi layout: ${managed}`);
    }
    const version = readFileSync(join(managed, 'current-version'), 'utf8').trim();
    if (!/^[0-9A-Za-z_+.-]+$/.test(version) || version === '.' || version === '..') {
      throw new Error('Invalid managed Pi version');
    }
    return checkedRoot(join(managed, 'releases', version, 'node_modules', packageName));
  }
  // npm --prefix test runners export a prefix that must not change discovery.
  const cleanEnv = Object.fromEntries(Object.entries(env).filter(([key]) => !/^npm_config_.*prefix$/i.test(key)));
  const modules = npmRoot ? npmRoot() : execFileSync('npm', ['root', '-g'], {
    encoding: 'utf8', env: cleanEnv, timeout: 10000,
  }).trim();
  return checkedRoot(join(modules, packageName));
}
export function piRequire(root = piRuntimeRoot()) {
  return createRequire(join(root, 'package.json'));
}
export function piDependencyRoot(name, root = piRuntimeRoot()) {
  // Inspect Node's lookup directories rather than require.resolve(name): Pi's
  // ESM-only dependencies may deliberately have no "require" export condition.
  for (const modules of piRequire(root).resolve.paths(name) || []) {
    const directory = join(modules, name);
    const manifest = join(directory, 'package.json');
    if (existsSync(manifest) && JSON.parse(readFileSync(manifest, 'utf8')).name === name) return directory;
  }
  throw new Error(`Could not locate Pi dependency: ${name}`);
}
