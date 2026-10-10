import { ServiceUnavailableException } from '@nestjs/common';
// No automatic retries for provider calls; jobs own push retries.
export async function providerFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(input, { ...init, signal: init?.signal
      ? AbortSignal.any([init.signal, AbortSignal.timeout(5000)]) : AbortSignal.timeout(5000) });
  } catch {
    throw new ServiceUnavailableException('Provider request unavailable or timed out');
  }
}
export async function providerJson(response: Response): Promise<unknown> {
  if (!response.ok) throw new ServiceUnavailableException(`Provider returned HTTP ${response.status}`);
  try { return await response.json(); }
  catch { throw new ServiceUnavailableException('Provider returned invalid JSON'); }
}
export const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export function object(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
