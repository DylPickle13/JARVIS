// Single-attempt OAuth transport matching Pi's Node fetch request.
// Credentials travel only over private stdin/stdout pipes; never argv or logs.
import { pathToFileURL } from 'node:url';

export async function refresh(token, fetchImpl = fetch) {
  try {
    if (typeof token !== 'string' || !token || token.length > 32768)
      return { ok: false, code: 'invalid_input' };
    const response = await fetchImpl('https://platform.claude.com/v1/oauth/token', {
      method: 'POST',
      redirect: 'error',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ grant_type: 'refresh_token',
        client_id: '9d1c250a-e61b-44d9-88ed-5944d1962f5e', refresh_token: token }),
      signal: AbortSignal.timeout(15000),
    });
    if (!response.ok) {
      // Never emit provider bodies, error messages, headers or account data.
      await response.body?.cancel();
      return { ok: false, code: 'http_error', status: response.status };
    }
    // Bound the successful token response before parsing or forwarding it.
    const reader = response.body.getReader();
    const chunks = [];
    let size = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > 131072) {
        await reader.cancel();
        return { ok: false, code: 'invalid_response' };
      }
      chunks.push(Buffer.from(value));
    }
    const payload = JSON.parse(Buffer.concat(chunks).toString('utf8'));
    const rotated = payload.refresh_token ?? token;
    if (typeof payload.access_token !== 'string' || !payload.access_token ||
        payload.access_token.length > 32768 || typeof rotated !== 'string' ||
        !rotated || rotated.length > 32768 ||
        typeof payload.expires_in !== 'number' || !Number.isFinite(payload.expires_in) ||
        payload.expires_in <= 300 || payload.expires_in > 31536000)
      return { ok: false, code: 'invalid_response' };
    return { ok: true, access: payload.access_token, refresh: rotated,
      expires: Math.floor(Date.now() + payload.expires_in * 1000 - 300000) };
  } catch (error) {
    return { ok: false, code: error?.name === 'TimeoutError' ? 'timeout' : 'transport_error' };
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  let result;
  try {
    let input = '';
    for await (const chunk of process.stdin) {
      input += chunk;
      if (input.length > 65536) throw new Error('input limit');
    }
    result = await refresh(JSON.parse(input).refresh);
  } catch {
    result = { ok: false, code: 'invalid_input' };
  }
  process.stdout.write(JSON.stringify(result));
  process.exitCode = result.ok ? 0 : 2;
}
