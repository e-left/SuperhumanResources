import 'reflect-metadata';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { Queue, Worker } from 'bullmq';
import { createApp } from '../src/app';
import { Db } from '../src/db';
import { fixtureToken } from '../src/auth';
import { fixturePeople } from '../src/fixtures';
import { config } from '../src/config';
import { deliverNotification, notificationJobOptions } from '../src/notifications';
const testUrl = process.env.TEST_DATABASE_URL;
const [alex, sam, jules] = fixturePeople;
test('database and queue vertical slice', { skip: !testUrl, timeout: 60000 }, async t => {
  assert(config.fixture, 'Tests require FIXTURE_MODE=true');
  assert.notEqual(testUrl, config.databaseUrl, 'Use a separate test database');
  assert(new URL(testUrl!).pathname.endsWith('_test'), 'Test database name must end in _test');
  process.env.DATABASE_URL = testUrl!;
  const app = await createApp();
  await app.listen(0, '127.0.0.1');
  const db = app.get(Db), base = await app.getUrl();
  t.after(async () => { await app.close(); });
  // This test suite owns the explicitly configured disposable test database.
  await db.fixtureMessage.deleteMany(); await db.notification.deleteMany(); await db.block.deleteMany();
  await db.swipe.deleteMany(); await db.match.deleteMany(); await db.profile.deleteMany();
  for (const person of fixturePeople) {
    const { longitude, latitude, ...fields } = person;
    await db.profile.create({ data: { ...fields, moveIn: new Date('2026-11-01') } });
    await db.$executeRaw`UPDATE "Profile" SET "location" = ST_SetSRID(ST_MakePoint(${longitude}, ${latitude}),4326)::geography WHERE "id" = ${person.id}::uuid`;
  }
  async function request(id: string, path: string, body?: unknown, method?: string) {
    const response = await fetch(`${base}${path}`, { method: method ?? (body ? 'POST' : 'GET'),
      headers: { Authorization: `Bearer ${fixtureToken(id)}`, 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined, signal: AbortSignal.timeout(25000) });
    return { status: response.status, data: await response.json() };
  }
  let matchId: string;
  await t.test('simultaneous reciprocal and repeated likes produce one match and two outbox rows', async () => {
    const requests = Array.from({ length: 8 }, (_, i) => i % 2
      ? request(sam.id, '/swipes', { targetId: alex.id, decision: 'like' })
      : request(alex.id, '/swipes', { targetId: sam.id, decision: 'like' }));
    const responses = await Promise.all(requests);
    assert(responses.every(r => r.status === 201));
    assert.equal(await db.match.count(), 1);
    assert.equal(await db.notification.count(), 2);
    matchId = (await db.match.findFirstOrThrow()).id;
    const ids = responses.map(r => r.data.matchId).filter(Boolean);
    assert(ids.every(id => id === matchId));
  });
  await t.test('only a matched participant may read or send; actor spoofing is rejected', async () => {
    assert.equal((await request(jules.id, `/matches/${matchId}/messages`)).status, 404);
    assert.equal((await request(jules.id, `/matches/${matchId}/messages`, { text: 'Unauthorized' })).status, 404);
    assert.equal((await request(alex.id, '/swipes', { actorId: sam.id, targetId: jules.id, decision: 'like' })).status, 400);
    assert.equal((await request(alex.id, `/matches/${matchId}/messages`, { text: 'Hello, fictional Sam!' })).status, 201);
    const result = await request(sam.id, `/matches/${matchId}/messages`);
    assert.equal(result.data.mode, 'fixture');
    assert.equal(result.data.messages[0].senderId, alex.id);
  });
  await t.test('PostGIS excludes distant profiles; blocks exclude both directions and deny chat', async () => {
    const before = await request(jules.id, '/discovery?radiusKm=10');
    assert(before.data.some((p: { id: string }) => p.id === alex.id));
    assert(!before.data.some((p: { id: string }) => p.id === fixturePeople[3].id));
    assert.equal((await request(jules.id, '/blocks', { targetId: alex.id })).status, 201);
    const after = await request(jules.id, '/discovery?radiusKm=10');
    assert(!after.data.some((p: { id: string }) => p.id === alex.id));
    const reverse = await request(alex.id, '/discovery?radiusKm=10');
    assert(!reverse.data.some((p: { id: string }) => p.id === jules.id));
    assert.equal((await request(alex.id, '/blocks', { targetId: sam.id })).status, 201);
    for (const id of [alex.id, sam.id]) {
      assert.equal((await request(id, `/matches/${matchId}/messages`)).status, 403);
      assert.equal((await request(id, `/matches/${matchId}/messages`, { text: 'Blocked' })).status, 403);
      assert.equal((await request(id, '/matches')).data.length, 0);
    }
    assert.equal((await request(sam.id, '/swipes', { targetId: alex.id, decision: 'like' })).status, 403);
    const pending = await db.notification.findFirstOrThrow();
    await deliverNotification(db, pending.id, 1);
    assert.equal((await db.notification.findUniqueOrThrow({ where: { id: pending.id } })).status, 'suppressed');
  });
  await t.test('BullMQ retries a transient push failure and records permanent failures', async () => {
    await db.block.deleteMany();
    await db.profile.update({ where: { id: alex.id }, data: { pushToken: 'ExpoPushToken[fictional-test-token]' } });
    const row = await db.notification.findFirstOrThrow({ where: { recipientId: alex.id } });
    await db.notification.update({ where: { id: row.id }, data: { status: 'pending', attempts: 0 } });
    const queueName = `flatpal-test-${randomUUID()}`;
    const connection = { host: '127.0.0.1', port: Number(process.env.TEST_REDIS_PORT ?? 63800), connectTimeout: 3000 };
    const queue = new Queue(queueName, { connection: { ...connection, maxRetriesPerRequest: 1, commandTimeout: 3000 } });
    let calls = 0, permanent = false;
    config.fixture = false; // Exercise the real delivery path with an injected fake Expo boundary.
    const worker = new Worker(queueName, job => deliverNotification(db, job.data.id, job.attemptsMade + 1, async () => {
      calls++;
      if (permanent) throw new Error('expo-DeviceNotRegistered');
      if (calls <= 2) throw new Error('temporary provider outage');
      return 'fictional-acceptance-ticket';
    }), { connection: { ...connection, maxRetriesPerRequest: null }, concurrency: 1 });
    const failures: unknown[] = [];
    worker.on('error', error => failures.push(error)); queue.on('error', error => failures.push(error));
    async function terminal(jobId: string) {
      const deadline = Date.now() + 15000;
      while (Date.now() < deadline) {
        const job = await queue.getJob(jobId);
        const state = await job?.getState();
        if (state === 'completed' || state === 'failed') return state;
        await new Promise(resolve => setTimeout(resolve, 100));
      }
      throw new Error('Timed out awaiting bounded notification retries');
    }
    try {
      await queue.add('match', { id: row.id }, { ...notificationJobOptions, jobId: row.id });
      assert.equal(await terminal(row.id), 'completed');
      assert.equal(calls, 3);
      const accepted = await db.notification.findUniqueOrThrow({ where: { id: row.id } });
      assert.equal(accepted.status, 'accepted'); assert.equal(accepted.attempts, 3);
      await deliverNotification(db, row.id, 4, async () => { throw new Error('Completed notification sent twice'); });
      permanent = true; calls = 0;
      await db.notification.update({ where: { id: row.id }, data: { status: 'pending', attempts: 0 } });
      const permanentId = randomUUID();
      await queue.add('match', { id: row.id }, { ...notificationJobOptions, jobId: permanentId });
      assert.equal(await terminal(permanentId), 'failed'); assert.equal(calls, 1);
      assert.equal((await db.notification.findUniqueOrThrow({ where: { id: row.id } })).status, 'failed');
      assert.equal(failures.length, 0);
    } finally {
      config.fixture = true;
      await worker.close(); await queue.obliterate({ force: true }); await queue.close();
    }
  });
});
