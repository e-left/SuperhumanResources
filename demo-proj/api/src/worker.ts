import { Queue, Worker } from 'bullmq';
import { PrismaClient } from '@prisma/client';
import { config } from './config';
import { deliverNotification, notificationJobOptions } from './notifications';
import { object, uuidPattern } from './http';
const db = new PrismaClient();
const queue = new Queue('flatpal-match', { connection: { ...config.redis, maxRetriesPerRequest: 1, commandTimeout: 5000 } });
const worker = new Worker('flatpal-match', async job => {
  if (!object(job.data) || typeof job.data.id !== 'string' || !uuidPattern.test(job.data.id)) throw new Error('Invalid notification job');
  await deliverNotification(db, job.data.id, job.attemptsMade + 1);
}, { connection: { ...config.redis, maxRetriesPerRequest: null }, concurrency: 2, maxStalledCount: 1 });
queue.on('error', () => console.error('Notification queue connection failed'));
worker.on('error', () => console.error('Notification worker connection failed'));
worker.on('failed', (job) => console.error(`Notification job failed; id=${job?.id ?? 'unknown'} attempt=${job?.attemptsMade ?? 0}`));
let stopping = false;
let timer: NodeJS.Timeout;
async function dispatch() {
  if (stopping) return;
  try {
    const pending = await db.notification.findMany({ where: { status: 'pending' }, orderBy: { createdAt: 'asc' }, take: 100 });
    for (const item of pending) {
      if (stopping) break;
      await queue.add('match', { id: item.id }, { ...notificationJobOptions, jobId: item.id });
    }
  } catch { console.error('Notification dispatch failed; pending database rows retained for next poll'); }
  finally { if (!stopping) timer = setTimeout(dispatch, 5000); }
}
async function shutdown() {
  stopping = true;
  clearTimeout(timer);
  try { await worker.close(); await queue.close(); await db.$disconnect(); }
  catch { console.error('Notification shutdown failed'); process.exitCode = 1; }
}
process.once('SIGINT', shutdown);
process.once('SIGTERM', shutdown);
dispatch().catch(() => { console.error('Unexpected notification dispatcher failure'); process.exitCode = 1; });
console.log(`FlatPal notification worker started; mode=${config.fixture ? 'fixture' : 'live'}`);
