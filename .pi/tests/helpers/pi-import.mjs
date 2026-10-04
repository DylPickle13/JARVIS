import { readFileSync } from 'node:fs';
import { piRequire, piDependencyRoot } from '../../scripts/pi-runtime.mjs';
import { join } from 'node:path';
const { createJiti } = piRequire()('jiti');
function resolvePi(name) {
  const root = piDependencyRoot(name);
  const pkg = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'));
  const entry = pkg.exports?.['.'];
  return join(root, typeof entry === 'string' ? entry : entry?.import || entry?.default || pkg.module || pkg.main);
}
export const jiti = createJiti(import.meta.url, { interopDefault: true, alias: Object.fromEntries(
  ['@earendil-works/pi-ai', '@earendil-works/pi-tui', 'typebox'].map(name => [name, resolvePi(name)])) });
