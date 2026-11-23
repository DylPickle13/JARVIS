// Offline checks for frame-free scroll/click (hidden-Space automation window).
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { backgroundScroll, backgroundClick } from './background-input.mjs';
import { ExtensionBrowserBackend } from './extension-browser-backend.mjs';
import { isLocalActionFailure } from './action-policy.mjs';

const sleep = ms => new Promise(r => setTimeout(r, ms));

// Minimal DOM for the in-page scroll function. `window` is the VM global.
function scrollDom({pageHeight = 3000, viewport = 600} = {}) {
  const behaviors = [];
  const g = vm.createContext({innerWidth: 1000, innerHeight: viewport, scrollX: 0, scrollY: 0, ShadowRoot: class {}});
  g.window = g;
  g.scrollBy = ({left, top, behavior}) => {
    behaviors.push(behavior);
    g.scrollY = Math.max(0, Math.min(pageHeight - viewport, g.scrollY + top));
    g.scrollX = Math.max(0, g.scrollX + left);
  };
  const node = (tag, {overflowY = 'visible', scrollHeight = 0, clientHeight = 0, moves = true, parent = null} = {}) => {
    const n = {tagName: tag, parentElement: parent, assignedSlot: null, scrollTop: 0, scrollLeft: 0, scrollHeight, clientHeight,
      scrollWidth: 0, clientWidth: 0, style: {overflowY, overflowX: 'visible'}, getRootNode: () => ({}),
      scrollBy({top, behavior}) { behaviors.push(behavior); if (moves) n.scrollTop = Math.max(0, Math.min(n.scrollHeight - n.clientHeight, n.scrollTop + top)); }};
    return n;
  };
  const root = node('HTML');
  const body = node('BODY', {parent: root});
  g.document = {scrollingElement: root, documentElement: root, body, elementFromPoint: () => g.hit};
  g.getComputedStyle = n => n.style;
  g.hit = node('P', {parent: body});
  const page = {
    evaluate: async (fn, arg) => vm.runInContext(`(${fn})(${JSON.stringify(arg)})`, g),
    waitForTimeout: async ms => { await sleep(Math.min(ms, 50)); },
  };
  return {g, node, root, body, page, behaviors};
}

test('scroll moves the page with an instant script scroll, never a wheel event', async () => {
  const d = scrollDom();
  d.page.mouse = {wheel: () => assert.fail('wheel must not be used'), move: () => assert.fail('mouse must not move')};
  const result = await backgroundScroll(d.page, {direction: 'down', amount: 400});
  assert.deepEqual(result, {amount: 400, direction: 'down', method: 'script', container: 'page', movedX: 0, movedY: 400});
  assert.deepEqual(d.behaviors, ['instant']);
  assert.equal((await backgroundScroll(d.page, {direction: 'up', amount: 9999})).movedY, -400);
});

test('scroll targets the scrollable panel under the point, then falls back to the page at its edge', async () => {
  const d = scrollDom();
  const panel = d.node('DIV', {overflowY: 'auto', scrollHeight: 2000, clientHeight: 240, parent: d.body});
  d.g.hit = d.node('SPAN', {parent: panel});
  let result = await backgroundScroll(d.page, {direction: 'down', amount: 300, x: 150, y: 280});
  assert.equal(result.container, 'element'); assert.equal(result.movedY, 300); assert.equal(d.g.scrollY, 0);
  panel.scrollTop = panel.scrollHeight - panel.clientHeight; // at the bottom, like a wheel it chains to the page
  result = await backgroundScroll(d.page, {direction: 'down', amount: 300, x: 150, y: 280});
  assert.equal(result.container, 'page'); assert.equal(result.movedY, 300);
});

test('overflow propagated to the viewport (non-moving candidate) still scrolls the page', async () => {
  const d = scrollDom();
  d.body.style.overflowY = 'auto'; d.body.scrollHeight = 3000; d.body.clientHeight = 600; d.body.scrollBy = () => {};
  const result = await backgroundScroll(d.page, {direction: 'down', amount: 500});
  assert.equal(result.container, 'page'); assert.equal(result.movedY, 500);
});

test('nothing scrollable reports zero movement rather than claiming success', async () => {
  const d = scrollDom({pageHeight: 600});
  assert.equal((await backgroundScroll(d.page, {})).movedY, 0);
  await assert.rejects(backgroundScroll(d.page, {direction: 'sideways'}), /Invalid scroll direction/);
});

test('an unresponsive page fails locally before the outer deadline, without an unhandled rejection', async () => {
  let rejectLate;
  const page = {evaluate: () => new Promise((_, r) => { rejectLate = r; }), waitForTimeout: async () => {}};
  const unhandled = [];
  const onUnhandled = e => unhandled.push(e);
  process.on('unhandledRejection', onUnhandled);
  try {
    await assert.rejects(backgroundScroll(page, {}, 5), e => /^TimeoutError: page did not run the scroll/.test(e.message) && isLocalActionFailure('/scroll', e.message));
    rejectLate(new Error('late renderer failure'));
    await sleep(20);
    assert.deepEqual(unhandled, []);
  } finally { process.off('unhandledRejection', onUnhandled); }
});

// Element fixture for the in-page click probe. The probe runs in its own VM
// context to prove it is self-contained (Playwright serializes it).
function clickFixture({rect = [100, 900, 80, 30], hitSelf = true, frames = null} = {}) {
  const events = [], clicks = [];
  const win = {innerWidth: 1000, innerHeight: 600, ShadowRoot: class {}, getComputedStyle: () => ({visibility: 'visible'})};
  const doc = {defaultView: win};
  const el = {tagName: 'BUTTON', id: 'go', isConnected: true, ownerDocument: doc, parentElement: null, assignedSlot: null, labels: [],
    getRootNode: () => doc, checkVisibility: () => true, matches: () => false, closest: () => null,
    disabled: false, rect: [...rect],
    getBoundingClientRect() { const [left, top, width, height] = frames ? frames.shift() || el.rect : el.rect; return {left, top, width, height}; },
    scrollIntoView(options) { events.push(['scrollIntoView', options.behavior]); el.rect[1] = 285; }};
  const overlay = {tagName: 'DIV', id: 'overlay', parentElement: null, assignedSlot: null, getRootNode: () => doc};
  doc.elementFromPoint = () => (hitSelf ? el : overlay);
  const target = {
    evaluate: async (fn, arg) => vm.runInNewContext(`(${fn})(el, arg)`, {el, arg}),
    boundingBox: async () => { const r = el.getBoundingClientRect(); return {x: r.left, y: r.top, width: r.width, height: r.height}; },
    click: () => assert.fail('Playwright rAF click must not be used'),
  };
  const page = {
    evaluate: async fn => vm.runInNewContext(`(${fn})()`, {innerWidth: 1000, innerHeight: 600}),
    waitForTimeout: async ms => { events.push(['wait', ms]); await sleep(Math.min(ms, 30)); },
    mouse: {click: async (x, y, options) => clicks.push([x, y, options])},
  };
  return {el, doc, overlay, target, page, events, clicks};
}

test('selector click scrolls into view, checks stability by timer, then clicks once at the centre', async () => {
  const f = clickFixture();
  const result = await backgroundClick(f.page, f.target, {button: 'left', clickCount: 1}, 2000);
  assert.deepEqual(result, {x: 140, y: 300, method: 'frame-free'});
  assert.deepEqual(f.clicks, [[140, 300, {button: 'left', clickCount: 1}]]);
  assert.deepEqual(f.events, [['scrollIntoView', 'instant'], ['wait', 100]]);
});

test('a covered target is never clicked and fails as a local TimeoutError naming the cover', async () => {
  const f = clickFixture({hitSelf: false});
  await assert.rejects(backgroundClick(f.page, f.target, {}, 250),
    e => /^TimeoutError: .*covered by div#overlay.*nothing was clicked/.test(e.message) && isLocalActionFailure('/click', e.message));
  assert.deepEqual(f.clicks, []);
});

test('a moving target waits until two samples match before clicking', async () => {
  const f = clickFixture({frames: [[100, 285, 80, 30], [100, 290, 80, 30]]});
  await backgroundClick(f.page, f.target, {}, 2000);
  assert.equal(f.clicks.length, 1);
  assert(f.events.filter(e => e[0] === 'scrollIntoView').length >= 2, 'expected a retry after movement');
});

test('disabled, invisible and detached targets are never clicked', async () => {
  for (const change of [el => { el.matches = s => s === ':disabled'; }, el => { el.closest = () => ({getAttribute: () => 'TRUE'}); },
    el => { el.checkVisibility = () => false; }, el => { el.isConnected = false; }]) {
    const f = clickFixture(); change(f.el);
    await assert.rejects(backgroundClick(f.page, f.target, {}, 200), /TimeoutError: click target not actionable/);
    assert.deepEqual(f.clicks, []);
  }
  const f = clickFixture(); f.el.closest = () => ({getAttribute: () => 'false'});
  await backgroundClick(f.page, f.target, {}, 1000);
  assert.equal(f.clicks.length, 1, 'explicit aria-disabled=false stays clickable');
});

test('a hit on the element label counts as receiving the click (Playwright follow-label)', async () => {
  const f = clickFixture({hitSelf: false});
  const label = {tagName: 'LABEL', parentElement: null, assignedSlot: null, getRootNode: () => f.doc};
  f.el.labels = [label]; f.doc.elementFromPoint = () => ({tagName: 'SPAN', parentElement: label, assignedSlot: null, getRootNode: () => f.doc});
  await backgroundClick(f.page, f.target, {}, 1000);
  assert.equal(f.clicks.length, 1);
});

test('strict-mode and locator timeouts propagate without clicking', async () => {
  const f = clickFixture();
  f.target.evaluate = async () => { throw new Error('strict mode violation: locator resolved to 2 elements'); };
  await assert.rejects(backgroundClick(f.page, f.target, {}, 1000), /strict mode violation/);
  assert.deepEqual(f.clicks, []);
});

// Execute the exact serialized MCP wrapper in a bare VM (no setTimeout), as the
// Playwright code tool does, and prove routing never uses wheel or Locator.click.
test('serialized /scroll and selector /click run frame-free through the real backend wrapper', async () => {
  const d = scrollDom();
  const f = clickFixture();
  const page = {
    isClosed: () => false, url: () => 'https://fixture.test', title: async () => 'Fixture', bringToFront: async () => {},
    evaluate: async (fn, arg) => typeof fn === 'string' ? JSON.stringify({tabId: 7}) : String(fn).includes('elementFromPoint') ? d.page.evaluate(fn, arg) : f.page.evaluate(fn),
    waitForTimeout: f.page.waitForTimeout,
    mouse: {wheel: () => assert.fail('wheel must not be used'), move: () => assert.fail('mouse must not move'), click: f.page.mouse.click},
    locator: () => f.target, getByText: () => f.target,
  };
  const anchor = {isClosed: () => false, url: () => 'chrome-extension://mmlmfjhmonkocbjadbfplnigmagldckm/connect.html#jarvis-automation-anchor-v2',
    evaluate: async () => JSON.stringify({tabs: [{tabId: 7, active: true}]})};
  const seed = {context: () => ({pages: () => [anchor, page]})};
  const b = new ExtensionBrowserBackend({});
  b.prepare = async () => { b.connected = true; return {pages: [{tabId: 7}]}; };
  b.diagnostic = () => {};
  b.client = {callTool: async args => {
    const run = vm.runInNewContext(`(${args.arguments.code})`, {});
    return {content: [{type: 'text', text: '### Result\n' + JSON.stringify(await run(seed))}]};
  }};
  await b.handle('/tabs', {action: 'switch', tabId: 7}, 'A');
  const scrolled = await b.handle('/scroll', {direction: 'down', amount: 400}, 'A');
  assert.equal(scrolled.movedY, 400); assert.equal(scrolled.method, 'script'); assert.equal(scrolled.tabId, 7);
  const clicked = await b.handle('/click', {selector: '#go'}, 'A');
  assert.deepEqual([clicked.x, clicked.y], [140, 300]); assert.equal(f.clicks.length, 1);
  assert.equal(b.resetCount, 0);
});
