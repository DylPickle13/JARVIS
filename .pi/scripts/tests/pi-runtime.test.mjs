import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { execFileSync, spawnSync } from 'node:child_process';
import { piRuntimeRoot, piRequire, piDependencyRoot } from '../pi-runtime.mjs';
const name = '@earendil-works/pi-coding-agent';
function fixture(t) {
  const dir = mkdtempSync(join(tmpdir(), 'pi-layout-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const put = (path, text, mode) => { mkdirSync(resolve(path, '..'), { recursive: true }); writeFileSync(path, text, { mode }); };
  const pkg = (modules, pkgName = name) => {
    const root = join(modules, pkgName);
    put(join(root, 'package.json'), JSON.stringify({ name: pkgName, main: 'index.cjs' }));
    put(join(root, 'index.cjs'), 'module.exports = { fixture: true };');
    return root;
  };
  return { dir, put, pkg };
}
test('npm discovery and explicit overrides retain their precedence', t => {
  const { dir, pkg } = fixture(t);
  const modules = join(dir, 'global');
  const root = pkg(modules);
  assert.equal(piRuntimeRoot({ env: {}, home: dir, npmRoot: () => modules }), root);
  assert.equal(piRuntimeRoot({ env: { PI_TEST_NODE_MODULES: modules }, home: dir }), root);
  assert.equal(piRuntimeRoot({ env: { PI_CODEMODE_TEST_RUNTIME: root, PI_TEST_NODE_MODULES: '/missing' } }), root);
  assert.throws(() => piRuntimeRoot({ env: { PI_CODEMODE_TEST_RUNTIME: dir } }));
});
test('managed release discovery is dynamic and dependencies may be hoisted', t => {
  const { dir, put, pkg } = fixture(t);
  const install = join(dir, '.pi/agent/install');
  put(join(install, 'managed-install.json'), JSON.stringify({ kind: 'pi-managed-install', schemaVersion: 1, layout: 'releases-v1' }));
  for (const version of ['1.0.2', '1.0.3']) {
    const modules = join(install, 'releases', version, 'node_modules');
    const root = pkg(modules);
    const dep = pkg(modules, 'test-dependency');
    put(join(install, 'current-version'), version + '\n');
    assert.equal(piRuntimeRoot({ env: {}, home: dir }), root);
    assert.equal(piDependencyRoot('test-dependency', root), dep);
    assert.deepEqual(piRequire(root)('test-dependency'), { fixture: true });
  }
  put(join(install, 'current-version'), '../../outside');
  assert.throws(() => piRuntimeRoot({ env: {}, home: dir }), /Invalid managed/);
  put(join(install, 'current-version'), '9.9.9');
  assert.throws(() => piRuntimeRoot({ env: {}, home: dir })); // no silent npm fallback
});
test('npm dependencies may remain nested; custom managed roots are supported', t => {
  const { dir, put, pkg } = fixture(t);
  const install = join(dir, 'custom');
  put(join(install, 'managed-install.json'), JSON.stringify({ kind: 'pi-managed-install', schemaVersion: 1, layout: 'releases-v1' }));
  put(join(install, 'current-version'), '1.0.2\n');
  const root = pkg(join(install, 'releases/1.0.2/node_modules'));
  const dep = pkg(join(root, 'node_modules'), 'test-dependency');
  assert.equal(piRuntimeRoot({ env: { PI_MANAGED_INSTALL_ROOT: install } }), root);
  assert.equal(piDependencyRoot('test-dependency', root), dep);
});
test('stable launcher preserves arguments and fails closed for incomplete managed installs', t => {
  const { dir, put } = fixture(t);
  const agent = join(dir, 'agent with spaces');
  put(join(agent, 'install/managed-install.json'), '{}');
  const launcher = resolve('.pi/scripts/pi-cli');
  const env = { ...process.env, PI_CODING_AGENT_DIR: agent };
  assert.equal(spawnSync(launcher, ['--version'], { env }).status, 127);
  put(join(agent, 'bin/pi'), '#!/bin/sh\nprintf "<%s>\\n" "$@"\n', 0o755);
  assert.equal(execFileSync(launcher, ['--session', '/history with spaces.jsonl', 'a; b'], { env, encoding: 'utf8' }),
    '<--session>\n</history with spaces.jsonl>\n<a; b>\n');
});
