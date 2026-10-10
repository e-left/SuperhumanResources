import { Injectable, ServiceUnavailableException } from '@nestjs/common';
import { createClient } from '@supabase/supabase-js';
import { StreamChat } from 'stream-chat';
import { randomUUID } from 'node:crypto';
import { config } from './config';
import { Transaction } from './db';
import { object, providerFetch, providerJson } from './http';
@Injectable()
export class Photos {
  private readonly client = config.fixture ? null : createClient(config.supabaseUrl, config.supabaseServiceKey, {
    auth: { persistSession: false, autoRefreshToken: false }, global: { fetch: providerFetch },
  });
  async upload(userId: string) {
    if (!this.client) return { mode: 'fixture', path: `${userId}/fixture.jpg`, signedUrl: null, token: null };
    const path = `${userId}/${randomUUID()}.jpg`;
    const { data, error } = await this.client.storage.from('profile-photos').createSignedUploadUrl(path);
    if (error || !data) throw new ServiceUnavailableException('Supabase Storage upload signing failed');
    return { mode: 'live', path, signedUrl: data.signedUrl, token: data.token };
  }
  async url(path: string | null) {
    if (!path || !this.client) return null;
    const { data, error } = await this.client.storage.from('profile-photos').createSignedUrl(path, 300);
    if (error || !data) throw new ServiceUnavailableException('Supabase Storage photo signing failed');
    return data.signedUrl;
  }
}
@Injectable()
export class Chat {
  // Server authentication/signing and channel membership stay here. No Stream tokens leave the API.
  private readonly client = config.fixture ? null : new StreamChat(config.streamKey, config.streamSecret, { timeout: 5000 });
  async channel(match: { id: string; lowId: string; highId: string }) {
    if (!this.client) return null;
    try {
      await this.client.upsertUsers([{ id: match.lowId }, { id: match.highId }]);
      const channel = this.client.channel('messaging', `flatpal-${match.id}`, {
        created_by_id: match.lowId, members: [match.lowId, match.highId],
      });
      await channel.create();
      return channel;
    } catch { throw new ServiceUnavailableException('Stream channel provisioning failed'); }
  }
  async messages(tx: Transaction, match: { id: string; lowId: string; highId: string }) {
    if (!this.client) {
      const messages = await tx.fixtureMessage.findMany({ where: { matchId: match.id }, orderBy: { createdAt: 'desc' }, take: 50 });
      return { mode: 'fixture', messages: messages.reverse() };
    }
    const channel = await this.channel(match);
    try {
      const state = await channel!.query({ messages: { limit: 50 }, watch: false });
      return { mode: 'live', messages: (state.messages ?? []).map(m => ({ id: m.id, text: m.text ?? '', senderId: m.user?.id, createdAt: m.created_at })) };
    } catch { throw new ServiceUnavailableException('Stream message fetch failed'); }
  }
  async send(tx: Transaction, match: { id: string; lowId: string; highId: string }, senderId: string, text: string) {
    if (!this.client) return tx.fixtureMessage.create({ data: { matchId: match.id, senderId, text } });
    const channel = await this.channel(match);
    try {
      const result = await channel!.sendMessage({ text, user_id: senderId });
      return { id: result.message.id, text: result.message.text, senderId, createdAt: result.message.created_at };
    } catch { throw new ServiceUnavailableException('Stream message send failed; delivery may be unknown, refresh before retrying'); }
  }
}
export async function sendPush(token: string, matchId: string): Promise<string> {
  const response = await providerFetch('https://exp.host/--/api/v2/push/send', {
    method: 'POST', headers: { 'Content-Type': 'application/json',
      ...(config.expoAccessToken ? { Authorization: `Bearer ${config.expoAccessToken}` } : {}) },
    body: JSON.stringify({ to: token, title: 'A new FlatPal match', body: 'Open FlatPal to say hello.', data: { matchId } }),
  });
  const body = await providerJson(response);
  if (!object(body) || !object(body.data)) throw new Error('expo-invalid-response');
  if (body.data.status !== 'ok' || typeof body.data.id !== 'string') {
    const code = object(body.data.details) && typeof body.data.details.error === 'string' ? body.data.details.error : 'unknown';
    // Never include raw provider payloads or push tokens in errors.
    throw new Error(['DeviceNotRegistered','MessageTooBig','InvalidCredentials','MessageRateExceeded'].includes(code) ? `expo-${code}` : 'expo-rejected');
  }
  return body.data.id; // Acceptance ticket; not proof of delivery.
}
