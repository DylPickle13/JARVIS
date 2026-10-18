import { test } from 'node:test';
import assert from 'node:assert/strict';
import { refresh } from './anthropic-refresh.mjs';

test('Pi request shape, single attempt, rotated token and expiry margin', async () => {
  let calls = 0;
  const before = Date.now();
  const result = await refresh('fake-refresh', async (url, init) => {
    calls++;
    assert.equal(url, 'https://platform.claude.com/v1/oauth/token');
    assert.equal(init.method, 'POST');
    assert.equal(init.redirect, 'error');
    assert.deepEqual(init.headers, { 'Content-Type': 'application/json' });
    assert.equal(JSON.parse(init.body).refresh_token, 'fake-refresh');
    assert.ok(init.signal instanceof AbortSignal);
    return Response.json({ access_token: 'new', refresh_token: 'rotated', expires_in: 3600 });
  });
  assert.equal(calls, 1);
  assert.equal(result.refresh, 'rotated');
  assert.ok(result.expires >= before + 3300000);
});

test('missing rotated token retains original; malformed responses fail closed', async () => {
  const result = await refresh('old', async () => Response.json({ access_token: 'new', expires_in: 3600 }));
  assert.equal(result.refresh, 'old');
  for (const payload of [null, {}, { access_token: '', expires_in: 3600 },
    { access_token: 'new', expires_in: true }, { access_token: 'new', expires_in: 1 },
    { access_token: 'new', refresh_token: '', expires_in: 3600 }]) {
    assert.equal((await refresh('old', async () => Response.json(payload))).ok, false);
  }
});

test('HTTP and transport errors are sanitized and never retried', async () => {
  for (const status of [400, 401, 403, 429, 500, 503]) {
    let calls = 0;
    const result = await refresh('secret', async () => {
      calls++;
      return new Response('secret provider body', { status });
    });
    assert.deepEqual(result, { ok: false, code: 'http_error', status });
    assert.equal(calls, 1);
  }
  for (const name of ['TimeoutError', 'TypeError']) {
    let calls = 0;
    const result = await refresh('secret', async () => {
      calls++;
      throw Object.assign(new Error('secret'), { name });
    });
    assert.equal(calls, 1);
    assert.equal(result.code, name === 'TimeoutError' ? 'timeout' : 'transport_error');
    assert.ok(!JSON.stringify(result).includes('secret'));
  }
});

test('invalid input makes no network request', async () => {
  for (const token of [null, '', 1, 'x'.repeat(32769)]) {
    assert.equal((await refresh(token, () => { throw new Error('must not call'); })).code, 'invalid_input');
  }
});
