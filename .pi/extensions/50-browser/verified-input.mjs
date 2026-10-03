// Fixed page action, serialized into the existing MCP code tool. No external state.
// Keep the public browser_type schema and defaults unchanged. Explicit delayMs:0
// opts into bulk replacement; never silently change append or slow-typing semantics.
export async function verifiedType(page, body, timeout) {
  const text = String(body.text);
  const delay = body.delayMs === undefined ? 20 : Number(body.delayMs);
  if (!Number.isFinite(delay) || delay < 0 || delay > 1000) throw new Error('Invalid typing delay');
  // Leave headroom for extension round trips. Reject BEFORE focus/clear/input.
  if ((text.length > 1000 && !(delay === 0 && body.clear)) || text.length * delay > 30000) {
    throw new Error('Long slow typing exceeds the safe action budget. Use delayMs:0 and clear:true for verified bulk replacement; no field was changed.');
  }
  if (body.selector) await page.locator(body.selector).focus({timeout});
  const handle = await page.evaluateHandle(() => {
    let e = document.activeElement;
    while (e?.shadowRoot?.activeElement) e = e.shadowRoot.activeElement;
    return e;
  });
  try {
    const target = handle.asElement();
    if (!target) throw new Error('No editable element focused');
    const before = await target.evaluate(e => {
      const plain = e.tagName === 'TEXTAREA' || (e.tagName === 'INPUT' && ['text','search','email','url','tel','password'].includes(e.type));
      const supported = e.tagName === 'TEXTAREA' || (e.tagName === 'INPUT' && !['button','submit','checkbox','radio','file','hidden','reset','image','range','color'].includes(e.type)) || e.isContentEditable;
      return {plain, editable: !e.disabled && !e.readOnly && supported,
        value: e.isContentEditable ? e.textContent : e.value,
        start: e.selectionStart, end: e.selectionEnd, tag: e.tagName};
    });
    if (!before.editable) throw new Error('No supported editable element focused');
    if (text.length > 1000 && !before.plain) throw new Error('Long bulk replacement requires a plain text input or textarea; no text was changed.');
    const normalized = before.tag === 'TEXTAREA' ? text.replace(/\r\n?/g, '\n') : text;
    let expected;
    if (body.clear) expected = normalized;
    else if (Number.isInteger(before.start) && Number.isInteger(before.end)) {
      expected = before.value.slice(0, before.start) + normalized + before.value.slice(before.end);
    } else {
      throw new Error('Cannot verify this field insertion range. Use clear:true for a verified replacement; no text was changed.');
    }
    const assertFocused = async () => {
      if (!await target.evaluate(e => {
        let focused = document.activeElement;
        while (focused?.shadowRoot?.activeElement) focused = focused.shadowRoot.activeElement;
        return e.isConnected && focused === e;
      })) throw new Error('JARVIS_INPUT_UNCERTAIN: target focus changed; inspect before retrying');
    };
    await assertFocused();
    let method = 'keyboard';
    if (body.clear && delay === 0 && before.plain) {
      // One bounded Playwright operation, rather than thousands of CDP key events.
      await target.fill(text, {timeout});
      method = 'fill';
    } else {
      if (body.clear) await target.fill('', {timeout});
      await assertFocused();
      await page.keyboard.type(text, {delay});
    }
    await assertFocused();
    const matches = await target.evaluate((e, expected) => (e.isContentEditable ? e.textContent : e.value) === expected, expected);
    if (!matches) throw new Error('JARVIS_INPUT_UNCERTAIN: field value did not match requested text; inspect before retrying');
    return {typedCharacters:text.length, valueVerified:true, inputMethod:method};
  } finally {
    await handle.dispose();
  }
}
