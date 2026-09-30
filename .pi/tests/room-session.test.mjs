import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { RoomSessionGate } from '../extensions/lib/room-session.ts';
import { ROOM_AUDIO_VOICE_PROMPT, registerRoomAudioVoicePrompt } from '../extensions/04-room-audio-session.ts';
let sends=[],aborts=0,ready=true;
const gate=new RoomSessionGate({ready:()=>ready,send:t=>sends.push(t),abort:async()=>{aborts++}});
const a='a'.repeat(32),b='b'.repeat(32);
const result=gate.prompt(a,'first');assert.equal(gate.input('extension','first'),true);gate.started();
assert.equal((await gate.prompt(b,'second')).ok,false);assert.equal((await gate.abort(b)).ok,false);assert.equal(aborts,0);
gate.settled('answer');assert.equal((await result).text,'answer');assert.equal((await gate.prompt(a,'again')).ok,false);
const cancelled=gate.prompt(b,'other');gate.input('extension','other');gate.started();assert.equal(gate.input('interactive','draft'),false);
assert.equal((await gate.abort(b)).ok,true);gate.settled('not spoken');assert.equal((await cancelled).ok,false);assert.equal(aborts,1);
gate.input('interactive','manual');assert.equal((await gate.prompt('c'.repeat(32),'voice')).ok,false);gate.started();
const manual=gate.status().requestID;assert.ok(manual);gate.settled('manual');assert.equal((await gate.abort(manual)).ok,false);
assert.deepEqual(sends,['first','other']);gate.close();assert.equal(gate.status().ok,false);
console.log('Room gate: single voice owner, manual input, exact abort, consumption and closure passed');

// Prompt-only hooks never start a socket, invoke a model, or touch live sessions.
for (const slot of [undefined, ...Array.from({ length: 10 }, (_, i) => i + 1)]) {
  const handlers = new Map();
  let currentSlot = slot;
  registerRoomAudioVoicePrompt(
    { on: (name, handler) => handlers.set(name, handler) },
    async () => currentSlot === undefined ? undefined : { slot: currentSlot },
  );
  assert.deepEqual([...handlers.keys()], ['before_agent_start']);
  const event = { systemPromptOptions: {
    customPrompt: 'Normal identity and instructions.',
    appendSystemPrompt: 'Current canonical local context.',
    selectedTools: ['read', 'load_tools'],
    toolGuidelines: { load_tools: ['Use the actual registered tools.'] },
    promptGuidelines: ['Preserve permissions and safety gates.'],
    contextFiles: [{ path: '/fixture/AGENTS.md', content: 'Project rules.' }],
    sections: { existing: 'Preserve existing instructions.' },
  } };
  const original = structuredClone(event);
  const apply = handlers.get('before_agent_start');
  await apply(event);
  if (slot !== 10) {
    assert.deepEqual(event, original, `Slot ${slot} must remain unchanged`);
    continue;
  }
  assert.equal(event.systemPromptOptions.sections.room_audio_voice, ROOM_AUDIO_VOICE_PROMPT);
  const withoutOverlay = structuredClone(event);
  delete withoutOverlay.systemPromptOptions.sections.room_audio_voice;
  assert.deepEqual(withoutOverlay, original, 'Voice may change presentation only, not core policy or tools');
  const once = structuredClone(event);
  await apply(event);
  assert.deepEqual(event, once, 'Repeated turns must not duplicate the prompt');
  currentSlot = undefined;
  const unidentified = structuredClone(original);
  await apply(unidentified);
  assert.deepEqual(unidentified, original, 'Identity must be verified on every turn');
}
assert.equal(ROOM_AUDIO_VOICE_PROMPT, readFileSync(
  new URL('../../projects/operation-jarvis/voice/APPEND_SYSTEM.md', import.meta.url), 'utf8',
).trim(), 'Interactive and standalone voice must use the same overlay');
assert.match(ROOM_AUDIO_VOICE_PROMPT, /presentation only/);
assert.match(ROOM_AUDIO_VOICE_PROMPT, /Only the confirmed final response is spoken/);
assert.doesNotMatch(ROOM_AUDIO_VOICE_PROMPT, /jarvis-cli|purifier-set|cast-spotify|shell fallback|everything you think/i);
assert.match(ROOM_AUDIO_VOICE_PROMPT, /one or two short sentences/);
assert.match(ROOM_AUDIO_VOICE_PROMPT, /verified success/);
assert.match(ROOM_AUDIO_VOICE_PROMPT, /essential safety information or truthful uncertainty/);
console.log('Room voice prompt: Session 10 only, per-turn identity, preservation and idempotence passed');

// Candidate events are speculative and never resolve the final-reply promise.
const frames = [];
const streamed = new RoomSessionGate({ ready: () => true, send: () => {}, abort: () => {} });
const streamID = 'd'.repeat(32);
let finished = false;
const pending = streamed.prompt(streamID, 'voice', event => frames.push(event));
pending.then(() => { finished = true; });
streamed.candidateStarted();
assert.equal(frames.length, 0, 'Do not export anything before voice admission');
assert.equal(streamed.input('extension', 'voice'), true);
streamed.started();
streamed.candidateStarted();
streamed.candidateDelta('Checking the light.');
streamed.candidateInvalidated();
streamed.candidateDelta('Late pre-tool text must not escape');
streamed.candidateEnded('Tool chatter', true);
streamed.candidateStarted();
streamed.candidateDelta('Done, sir.');
streamed.candidateEnded('Done, sir.');
await Promise.resolve();
assert.equal(finished, false);
assert.deepEqual(frames.map(e => e.type), ['candidate_start', 'candidate_delta', 'candidate_invalidate',
  'candidate_start', 'candidate_delta', 'candidate_end']);
assert.deepEqual(frames.map(e => e.candidate), [1, 1, 1, 2, 2, 2]);
streamed.settled('Done, sir.');
assert.equal((await pending).text, 'Done, sir.');
const count = frames.length;
streamed.input('interactive', 'manual'); streamed.started();
streamed.candidateStarted(); streamed.candidateDelta('Private manual reply');
assert.equal(frames.length, count, 'Manual Session 10 turns must never export candidates');
streamed.settled('manual');
const abortID = 'e'.repeat(32);
const aborting = streamed.prompt(abortID, 'cancel', event => frames.push(event));
streamed.input('extension', 'cancel'); streamed.started(); streamed.candidateStarted();
await streamed.abort(abortID);
const cancelledCount = frames.length;
streamed.candidateDelta('Must not render'); streamed.candidateEnded('Must not render');
assert.equal(frames.length, cancelledCount);
streamed.settled('Must not speak');
assert.equal((await aborting).ok, false);
const brokenSink = streamed.prompt('f'.repeat(32), 'broken', () => { throw new Error('fixture'); });
streamed.input('extension', 'broken'); streamed.started(); streamed.candidateStarted();
streamed.candidateDelta('Still completes'); streamed.settled('Still completes');
assert.equal((await brokenSink).ok, true);
console.log('Room candidates: admission, final-only commitment, message invalidation, manual privacy, abort and sink failure passed');
