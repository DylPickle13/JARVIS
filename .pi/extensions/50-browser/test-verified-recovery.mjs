import test from 'node:test';
import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { patchObservedExecution } from './execution-patch.mjs';
const exec=promisify(execFile), require=createRequire(import.meta.url);

const cases={
  deadline:'real MCP cancellation retains actual execution receipt without replay',
  'early-error':'real runner error cannot certify its still-running snippet',
  'relay-pending':'actual pinned relay acknowledgement gates quiescence; duplicates ignored',
  'relay-loss':'actual pinned relay callback disposal preserves sticky unknown evidence',
  'relay-generation':'different relay connections cannot fabricate same-generation completion',
  'backend-success':'verified backend recovers late wheel completion and preserves other clients',
  'backend-type':'verified late full-value typing completes exactly once',
  'backend-partial':'partial late typing leaves its owner fenced while other clients resume',
  'backend-click':'late click restores control, not business certainty; inspection remains possible',
  'backend-observe':'observation mode never releases its quarantine and persists it',
  'backend-budget':'grace exhaustion stays blocked even after late proof arrives',
  'backend-window':'changed window fails recovery without retargeting',
  'backend-tab':'closed or moved tab fails recovery without fallback',
  'backend-generation':'stale generation cannot release the execution fence',
  'backend-stock':'execution proof never grants an unsupervised stock recovery',
  'backend-release':'late receipt cannot resurrect an explicitly closed client',
  'backend-expired':'late completion cannot reacquire an expired lease',
};
for(const [mode,title] of Object.entries(cases)) test(title,async()=>{
  const {stdout}=await exec(process.execPath,[new URL('./test-execution-gate-fixture.mjs',import.meta.url).pathname,mode],{timeout:8000,maxBuffer:100000});
  const result=JSON.parse(stdout);assert.equal(result.mode,mode);
  if(result.executions!==undefined) assert.equal(result.executions,1);
});

for(const [program,args] of [
  [process.execPath,[new URL('./test-verified-recovery-live.mjs',import.meta.url).pathname]],
  ['/usr/bin/python3',[new URL('./test-verified-recovery-live.py',import.meta.url).pathname]],
  ['/usr/bin/python3',[new URL('./test-extension-focus.py',import.meta.url).pathname,'--script','test-verified-recovery-live.py']],
]) test(`live maintenance guard refuses before credentials/Chrome (${args[0].split('/').pop()})`,async()=>{
  const env={...process.env};delete env.JARVIS_TEST_VERIFIED_RECOVERY_MAINTENANCE;
  await assert.rejects(exec(program,args,{env,timeout:3000}),error=>/Not authorized|require explicit/.test(error.stderr)&&error.code!==0);
});

test('pinned observer patch is exact/idempotent and refuses changed upstream anchors',()=>{
  const source=readFileSync(require.resolve('playwright-core/lib/coreBundle'),'utf8');
  assert.equal(patchObservedExecution(source),source);
  assert.throws(()=>patchObservedExecution(source.replace('context.__jarvisRunSnippet__ = () => {','context.__jarvisRunSnippet__ = async () => {')),/anchor/);
  for(const marker of ['JARVIS_EXECUTION_REQUEST_V1','JARVIS_EXECUTION_SNIPPET_V1','JARVIS_EXECUTION_RELAY_V1','JARVIS_EXECUTION_ACK_V1','JARVIS_EXECUTION_LOSS_V1']) assert(source.includes(marker));
});
