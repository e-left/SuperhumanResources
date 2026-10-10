export const fixture = process.env.EXPO_PUBLIC_FIXTURE_MODE === 'true';
if (!['true','false'].includes(process.env.EXPO_PUBLIC_FIXTURE_MODE ?? '')) throw new Error('Set EXPO_PUBLIC_FIXTURE_MODE explicitly');
const base = process.env.EXPO_PUBLIC_API_URL;
if (!base) throw new Error('Set EXPO_PUBLIC_API_URL');
export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}
export async function api<T>(path: string, token?: string | null, body?: unknown, method?: string): Promise<T> {
  const response = await fetch(`${base}${path}`, {
    method: method ?? (body === undefined ? 'GET' : 'POST'),
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(25000),
  });
  const data = await response.json();
  if (!response.ok) throw new ApiError(response.status, Array.isArray(data.message) ? data.message.join(', ') : data.message ?? 'API request failed');
  return data as T;
}
export type Profile = {
  id: string; name: string; bio: string; budgetMin: number; budgetMax: number; area: string;
  moveIn: string; smoking: string; pets: string; sleep: string; longitude: number; latitude: number;
  photoPath?: string; photoUrl?: string | null; distanceKm?: number;
};
export type Match = { id: string; other: { id: string; name: string; area: string } };
export type Message = { id: string; senderId: string; text: string; createdAt: string };
