import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
const modules = process.env.PI_TEST_NODE_MODULES || execFileSync('npm', ['root', '-g'], {encoding:'utf8'}).trim();
const { createJiti } = await import(pathToFileURL(join(modules, '@earendil-works/pi-coding-agent/node_modules/jiti/lib/jiti.mjs')));
function resolvePi(name) {
 const root=join(modules, '@earendil-works/pi-coding-agent/node_modules', name);
 const pkg=JSON.parse(readFileSync(join(root,'package.json'),'utf8'));
 const entry=pkg.exports?.['.'];
 return join(root, typeof entry==='string' ? entry : entry?.import || entry?.default || pkg.module || pkg.main);
}
const jiti = createJiti(import.meta.url, {interopDefault:true, alias:Object.fromEntries(
 ['@earendil-works/pi-ai','@earendil-works/pi-tui','typebox'].map(name => [name, resolvePi(name)]))});
const register = await jiti.import(resolve(import.meta.dirname, '../../extensions/45-jarvis.ts'), {default:true});
const tools = {}; const calls = [];
register({registerTool(t){tools[t.name]=t;}, async exec(command,args){calls.push(args);return {code:0,stdout:'{"ok":true}',stderr:''};}});
const invoke = params => tools.jarvis.execute('offline-test', params, undefined, undefined, {cwd:resolve(import.meta.dirname, '../../..')});
test('discovery and batch actions route without spawning a real process', async()=>{
 for (const action of ['purifier-list','purifier-status-all']) {
  await invoke({action});assert.deepEqual(calls.at(-1).slice(-2), ['--json',action]);
 }
});
test('read recovery flag and exact name preserved', async()=>{
 await invoke({action:'purifier-status',purifier:"Dylan's Air Purifier",retryCooldown:true});
 assert.deepEqual(calls.at(-1).slice(-4), ['purifier-status','--retry-cooldown','--purifier',"Dylan's Air Purifier"]);
});
test('batch recovery and timeout route', async()=>{
 await invoke({action:'purifier-status-all',retryCooldown:true,purifierTimeout:60});
 assert.deepEqual(calls.at(-1).slice(-4), ['purifier-status-all','--purifier-timeout','60','--retry-cooldown']);
});
test('recovery cannot be applied to writes or discovery', async()=>{
 for(const action of ['purifier-set','purifier-list']) {
  const before=calls.length;
  await assert.rejects(invoke({action,setting:'mode',value:'auto',retryCooldown:true}),/only allowed/);
  assert.equal(calls.length,before);
 }
});
test('collection rejects device selector rather than silently ignoring it', async()=>{
 await assert.rejects(invoke({action:'purifier-status-all',purifier:'dylan'}),/selector/);
});
test('single-device write retains selector and no group expansion', async()=>{
 await invoke({action:'purifier-set',purifier:'bran',setting:'mode',value:'auto'});
 assert.ok(calls.at(-1).includes('bran'));assert.ok(calls.at(-1).includes('purifier-set'));
});
