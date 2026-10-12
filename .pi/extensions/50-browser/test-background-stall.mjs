// Offline only. This demonstrates the pinned mechanism, not real Chrome occlusion.
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {registerExecution,installExecutionObserver} from './execution-observer.mjs';
import {patchObservedExecution} from './execution-patch.mjs';
const require=createRequire(import.meta.url);
const bundle=readFileSync(require.resolve('playwright-core/lib/coreBundle'),'utf8');
const literal=bundle.split('\n').find(line=>line.startsWith('    source4 = '));
assert(literal,'Pinned injected-script source anchor changed');
const injected=vm.runInNewContext(literal.trim().slice('source4 = '.length).replace(/;$/,''));
const start=injected.indexOf('  async _checkElementIsStable(node) {');
const end=injected.indexOf('\n  _createAriaRefEngine()',start);
assert(start>=0&&end>start,'Pinned stability helper anchor changed');
const helper=vm.runInNewContext('({'+injected.slice(start,end)+'})')._checkElementIsStable;
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));

test('actual pinned stability helper stays pending without animation frames and completes when they resume',async()=>{
  const frames=[];let reads=0,terminal=false;
  const node={getBoundingClientRect:()=>{reads++;return {top:0,left:0,width:80,height:20};}};
  const context={retarget:value=>value,_stableRafCount:1,
    utils:{builtins:{performance,requestAnimationFrame:fn=>frames.push(fn)}}};
  const pending=helper.call(context,node).then(result=>{terminal=true;return result;});
  await pause(35);
  assert.equal(terminal,false);assert.equal(reads,0);assert.equal(frames.length,1);
  frames.shift()();
  assert.equal(reads,1);assert.equal(terminal,false);
  frames.shift()();
  assert.equal(await pending,true);assert.equal(reads,2);
});

test('deadline of the pinned stability wait does not terminate its downstream execution',async()=>{
  const frames=[];
  const node={getBoundingClientRect:()=>({top:0,left:0,width:80,height:20})};
  const context={retarget:value=>value,_stableRafCount:1,
    utils:{builtins:{performance,requestAnimationFrame:fn=>frames.push(fn)}}};
  const hooks=installExecutionObserver(), observed=registerExecution('stability-fixture',{id:'fixture'});
  let receipt;
  await hooks.request('stability-fixture',()=>hooks.snippet('stability-fixture',async()=>{
    receipt=hooks.command({},'chrome.debugger.sendCommand',[{},'Runtime.callFunctionOn',{functionDeclaration:'PRIVATE SENTINEL'}]);
    const pending=helper.call(context,node).then(()=>hooks.acknowledge(receipt));
    await Promise.race([pending,pause(10)]);
    throw new Error('Synthetic local action deadline');
  })).catch(()=>{});
  assert.equal(observed.snapshot().requestTerminal,true);
  assert.equal(observed.snapshot().snippetTerminal,true);
  assert.equal(observed.snapshot().pending,1);
  assert.equal(observed.snapshot().quiescent,false);
  assert.equal(observed.diagnostics().pendingCommands[0].name,'Runtime.callFunctionOn');
  assert(!JSON.stringify(observed.diagnostics()).includes('PRIVATE'));
  frames.shift()();frames.shift()();await pause(0);
  assert.equal(observed.snapshot().quiescent,true);observed.retire();
});

test('diagnostics are allowlisted, bounded, payload-free and cannot alter completion proof',async()=>{
  const hooks=installExecutionObserver(), observed=registerExecution('privacy-fixture',{id:'fixture'});
  const connection={},tokens=[];
  await hooks.request('privacy-fixture',()=>hooks.snippet('privacy-fixture',async()=>{
    for(let i=0;i<40;i++) tokens.push(hooks.command(connection,'chrome.debugger.sendCommand',
      [{tabId:123},i===0?'Input.dispatchMouseEvent':'SECRET-METHOD',{expression:'SECRET-EXPRESSION',text:'SECRET-INPUT'}]));
    return {};
  }));
  const before=observed.snapshot(), diagnostics=observed.diagnostics();
  assert.equal(diagnostics.pendingCommands.length,32);assert.equal(diagnostics.pending,40);
  assert.equal(diagnostics.pendingCommands[0].name,'Input.dispatchMouseEvent');
  assert(diagnostics.pendingCommands.slice(1).every(c=>c.name==='other'));
  assert(diagnostics.pendingCommands.every(c=>Number.isInteger(c.ageMs)&&c.ageMs>=0));
  assert(!JSON.stringify(diagnostics).includes('SECRET'));assert.deepEqual(observed.snapshot(),before);
  for(const token of tokens) hooks.acknowledge(token);
  assert.equal(observed.snapshot().quiescent,true);
  assert.deepEqual(observed.diagnostics().pendingCommands,[]);observed.retire();
});

test('diagnostic patch migrates only the exact prior hook and is idempotent',()=>{
  const current=patchObservedExecution(bundle);
  const prior=current.replace('?.command(this, method, params2);','?.command(this);');
  assert.notEqual(prior,current);
  assert.equal(patchObservedExecution(prior),current);
  assert.equal(patchObservedExecution(current),current);
  assert.throws(()=>patchObservedExecution(current.replace('?.command(this, method, params2);','?.command(this, arbitraryPayload);')),/anchor/);
});
