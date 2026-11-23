// Frame-independent page input, serialized into the MCP code tool like
// verifiedType. Keep every helper self-contained: the snippet VM only provides
// `page` and JS builtins (no setTimeout or module scope).
//
// Chrome stops drawing a window that sits on a hidden macOS Space. Wheel input
// and Playwright's requestAnimationFrame stability check both wait for a drawn
// frame, so they hang there. JS geometry, Node-side timers and discrete mouse
// press/release events do not. Public browser_* schemas are unchanged.

// Scroll with JS instead of a wheel event. Picks the innermost container under
// the point (default: viewport centre) that can still move in that direction,
// like a wheel would, else the page. Reports the pixels actually moved.
export async function backgroundScroll(page, body, budgetMs = 8000) {
  const amount = Math.max(50, Math.min(Number(body.amount ?? 700), 3000));
  const direction = body.direction || 'down';
  if (!['up', 'down', 'left', 'right'].includes(direction)) throw new Error('Invalid scroll direction');
  const dx = direction === 'left' ? -amount : direction === 'right' ? amount : 0;
  const dy = direction === 'up' ? -amount : direction === 'down' ? amount : 0;
  const point = body.x !== undefined && body.y !== undefined && Number.isFinite(Number(body.x)) && Number.isFinite(Number(body.y))
    ? {x: Number(body.x), y: Number(body.y)} : null;
  const run = page.evaluate(({dx, dy, point}) => {
    const root = document.scrollingElement || document.documentElement;
    const vw = innerWidth, vh = innerHeight;
    const x = Math.min(Math.max(point ? point.x : vw / 2, 0), Math.max(vw - 1, 0));
    const y = Math.min(Math.max(point ? point.y : vh / 2, 0), Math.max(vh - 1, 0));
    let node = document.elementFromPoint(x, y);
    while (node && node.shadowRoot) {
      const inner = node.shadowRoot.elementFromPoint(x, y);
      if (!inner || inner === node) break;
      node = inner;
    }
    const parent = n => n.assignedSlot || n.parentElement || (n.getRootNode && n.getRootNode() instanceof ShadowRoot ? n.getRootNode().host : null);
    const canMove = el => {
      if (el === root || el.tagName === 'IFRAME') return false;
      const style = getComputedStyle(el);
      if (dy) {
        if (!/(auto|scroll|overlay)/.test(style.overflowY) || el.scrollHeight <= el.clientHeight + 1) return false;
        return dy > 0 ? el.scrollTop + el.clientHeight < el.scrollHeight - 1 : el.scrollTop > 0;
      }
      if (!/(auto|scroll|overlay)/.test(style.overflowX) || el.scrollWidth <= el.clientWidth + 1) return false;
      return dx > 0 ? Math.abs(el.scrollLeft) + el.clientWidth < el.scrollWidth - 1 : Math.abs(el.scrollLeft) > 0;
    };
    // 'instant' overrides CSS scroll-behavior:smooth, which would need frames.
    // Try candidates innermost-first; a computed overflow can be propagated to
    // the viewport, so only a container that actually moved counts.
    const attempt = target => {
      const read = () => target ? [target.scrollLeft, target.scrollTop] : [scrollX, scrollY];
      const before = read();
      (target || window).scrollBy({left: dx, top: dy, behavior: 'instant'});
      const after = read();
      return {container: target ? 'element' : 'page', movedX: Math.round(after[0] - before[0]), movedY: Math.round(after[1] - before[1])};
    };
    for (let el = node; el; el = parent(el)) {
      if (!canMove(el)) continue;
      const result = attempt(el);
      if (result.movedX || result.movedY) return result;
    }
    return attempt(null);
  }, {dx, dy, point});
  run.catch(() => {});
  // Fail locally (session-fenced) before the 15 s outer deadline would reset
  // the whole bridge. The page may still apply the scroll later: inspect first.
  const timer = page.waitForTimeout(budgetMs).then(() => 'timeout', () => 'timeout');
  const result = await Promise.race([run, timer]);
  if (result === 'timeout') throw new Error(`TimeoutError: page did not run the scroll within ${budgetMs}ms; outcome uncertain, inspect before retrying`);
  return {amount, direction, method: 'script', ...result};
}

// Real mouse click at the element centre, after the same actionability checks
// as Playwright (attached, visible, enabled, stable, receives the click), but
// measured with JS geometry and Node-side timers instead of animation frames.
// Never clicks a covering element and never dispatches a synthetic DOM click.
export async function backgroundClick(page, target, options = {}, timeout = 10000) {
  const deadline = Date.now() + timeout;
  const backoff = [0, 20, 100, 100, 500];
  const probe = (el, scroll) => {
    if (!el.isConnected) return {state: 'detached'};
    if (scroll) el.scrollIntoView({block: 'center', inline: 'center', behavior: 'instant'});
    const win = el.ownerDocument.defaultView;
    const style = win.getComputedStyle(el);
    const r = el.getBoundingClientRect();
    const rect = [r.left, r.top, r.width, r.height];
    const describe = n => n ? n.tagName.toLowerCase() + (n.id ? '#' + n.id : '') : 'nothing';
    const visible = r.width > 0 && r.height > 0 && style.visibility !== 'hidden' &&
      (typeof el.checkVisibility !== 'function' || el.checkVisibility({visibilityProperty: true}));
    if (!visible) return {state: 'not visible', rect};
    // Nearest explicit aria-disabled wins ("false" re-enables), like Playwright.
    const ariaDisabled = (el.closest && el.closest('[aria-disabled]')) ? el.closest('[aria-disabled]').getAttribute('aria-disabled').toLowerCase() === 'true' : false;
    if ((el.matches && el.matches(':disabled')) || ariaDisabled) return {state: 'disabled', rect};
    const x = r.left + r.width / 2, y = r.top + r.height / 2;
    if (x < 0 || y < 0 || x >= win.innerWidth || y >= win.innerHeight) return {state: 'outside the viewport', rect};
    let hit = el.ownerDocument.elementFromPoint(x, y);
    while (hit && hit.shadowRoot) {
      const inner = hit.shadowRoot.elementFromPoint(x, y);
      if (!inner || inner === hit) break;
      hit = inner;
    }
    const parent = n => n.assignedSlot || n.parentElement || (n.getRootNode && n.getRootNode() instanceof win.ShadowRoot ? n.getRootNode().host : null);
    const within = (n, container) => { for (; n; n = parent(n)) if (n === container) return true; return false; };
    const labels = Array.from(el.labels || []);
    const receives = hit && (within(hit, el) || labels.some(label => within(hit, label)) || (el.control && within(hit, el.control)));
    if (!receives) return {state: `covered by ${describe(hit)}`, rect};
    return {state: 'ready', rect};
  };
  const same = (a, b) => a && b && a.every((v, i) => Math.abs(v - b[i]) < 0.5);
  let reason = 'not found';
  for (let attempt = 0; ; attempt++) {
    if (attempt) {
      const wait = Math.min(backoff[Math.min(attempt, backoff.length - 1)], deadline - Date.now());
      if (wait > 0) await page.waitForTimeout(wait);
    }
    const remaining = deadline - Date.now();
    if (remaining <= 0) throw new Error(`TimeoutError: click target not actionable within ${timeout}ms (last check: ${reason}); nothing was clicked`);
    // Locator waits for attachment with server-side retries and stays strict.
    const first = await target.evaluate(probe, true, {timeout: remaining});
    if (first.state !== 'ready') { reason = first.state; continue; }
    await page.waitForTimeout(100);
    const second = await target.evaluate(probe, false, {timeout: Math.max(1, deadline - Date.now())});
    if (second.state !== 'ready') { reason = second.state; continue; }
    if (!same(first.rect, second.rect)) { reason = 'element is moving'; continue; }
    // Main-frame coordinates (handles iframes); recheck the viewport there too.
    const box = await target.boundingBox({timeout: Math.max(1, deadline - Date.now())});
    if (!box) { reason = 'no bounding box'; continue; }
    const x = box.x + box.width / 2, y = box.y + box.height / 2;
    const [vw, vh] = await page.evaluate(() => [innerWidth, innerHeight]);
    if (x < 0 || y < 0 || x >= vw || y >= vh) { reason = 'outside the page viewport'; continue; }
    await page.mouse.click(x, y, {button: options.button || 'left', clickCount: options.clickCount || 1});
    return {x, y, method: 'frame-free'};
  }
}
