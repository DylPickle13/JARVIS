import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
const modules = process.env.PI_TEST_NODE_MODULES || execFileSync('npm', ['root', '-g'], { encoding: 'utf8' }).trim();
const base = join(modules, '@earendil-works/pi-coding-agent/node_modules');
const { createJiti } = await import(pathToFileURL(join(base, 'jiti/lib/jiti.mjs')));
function resolvePi(name) {
  const root = join(base, name);
  const pkg = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'));
  const entry = pkg.exports?.['.'];
  return join(root, typeof entry === 'string' ? entry : entry?.import || entry?.default || pkg.module || pkg.main);
}
export const jiti = createJiti(import.meta.url, { interopDefault: true, alias: Object.fromEntries(
  ['@earendil-works/pi-ai', '@earendil-works/pi-tui', 'typebox'].map(name => [name, resolvePi(name)])) });
