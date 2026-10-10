import { test } from 'node:test';
import assert from 'node:assert/strict';
import { sendPush } from '../src/providers';
import { providerFetch } from '../src/http';
test('push acceptance is parsed; provider errors and malformed payloads do not report success', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => new Response(JSON.stringify({ data: { status: 'ok', id: 'fictional-ticket' } }));
    assert.equal(await sendPush('ExpoPushToken[fictional]', 'fictional-match'), 'fictional-ticket');
    globalThis.fetch = async () => new Response(JSON.stringify({ data: { status: 'error', details: { error: 'DeviceNotRegistered' } } }));
    await assert.rejects(sendPush('ExpoPushToken[fictional]', 'fictional-match'), /expo-DeviceNotRegistered/);
    globalThis.fetch = async () => new Response(JSON.stringify({ unexpected: true }));
    await assert.rejects(sendPush('ExpoPushToken[fictional]', 'fictional-match'), /expo-invalid-response/);
    globalThis.fetch = async () => new Response('outage', { status: 503 });
    await assert.rejects(sendPush('ExpoPushToken[fictional]', 'fictional-match'));
  } finally { globalThis.fetch = original; }
});
test('external calls receive a bounded abort signal and propagate transport failures', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async (_url, options) => {
      assert(options?.signal instanceof AbortSignal);
      throw new Error('fictional transport failure');
    };
    await assert.rejects(providerFetch('https://example.invalid'), /Provider request unavailable/);
  } finally { globalThis.fetch = original; }
});
