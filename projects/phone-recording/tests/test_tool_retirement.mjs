import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { piRequire } from '../../../.pi/scripts/pi-runtime.mjs';
import { resolve } from 'node:path';
const require = piRequire();
const { createJiti } = require('jiti');
const jiti = createJiti(import.meta.url, { alias: { typebox: require.resolve('typebox') } });
const root = resolve(import.meta.dirname, '../../..');
assert(!existsSync(root + '/.pi/extensions/59-obs-control.ts'));
assert(!existsSync(root + '/projects/obs-control'));
const source = readFileSync(root + '/.pi/extensions/99-lazy-tools.ts', 'utf8');
assert(!source.includes('"obs"'));
const lazy = await jiti.import(root + '/.pi/extensions/99-lazy-tools.ts');
const tools = new Map();
const events = new Map();
let active = [];
lazy.default({
  registerTool: tool => tools.set(tool.name, tool), registerCommand() {},
  on: (name, handler) => events.set(name, handler),
  getAllTools: () => [...tools.values()], getActiveTools: () => active,
  setActiveTools: names => { active = names; },
});
events.get('session_start')();
assert(!tools.has('obs'));
assert(!active.includes('obs'));
assert(!tools.get('load_tools').description.includes('obs='));
console.log('PASS: OBS extension removed; lazy loader imports and initializes without OBS group');
