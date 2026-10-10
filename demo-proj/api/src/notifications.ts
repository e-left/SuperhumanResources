import { PrismaClient } from '@prisma/client';
import { UnrecoverableError } from 'bullmq';
import { config } from './config';
import { isBlocked, lockPair, transactionOptions } from './db';
import { sendPush } from './providers';
export const notificationJobOptions = {
  attempts: 3,
  backoff: { type: 'exponential', delay: 1000, jitter: 0.5 },
  removeOnComplete: { count: 1000 },
  removeOnFail: false,
};
// Injecting the provider function keeps retries testable without contacting Expo.
export async function deliverNotification(db: PrismaClient, id: string, attempt: number, push = sendPush) {
  try {
    await db.$transaction(async tx => {
      await tx.$queryRaw`SELECT "id" FROM "Notification" WHERE "id" = ${id}::uuid FOR UPDATE`;
      const notification = await tx.notification.findUnique({ where: { id } });
      if (!notification || notification.status !== 'pending') return;
      const match = await tx.match.findUniqueOrThrow({ where: { id: notification.matchId } });
      await lockPair(tx, match.lowId, match.highId);
      const blocked = await isBlocked(tx, match.lowId, match.highId);
      const recipient = await tx.profile.findUniqueOrThrow({ where: { id: notification.recipientId } });
      let status: string, ticketId: string | undefined;
      if (blocked) status = 'suppressed';
      else if (config.fixture) status = 'simulated';
      else if (!recipient.pushToken) status = 'skipped';
      else { ticketId = await push(recipient.pushToken, match.id); status = 'accepted'; }
      await tx.notification.update({ where: { id }, data: { status, ticketId, attempts: attempt, lastError: null } });
    }, transactionOptions);
  } catch (error) {
    const code = error instanceof Error && /^expo-(DeviceNotRegistered|MessageTooBig|InvalidCredentials|MessageRateExceeded|invalid-response|rejected)$/.test(error.message)
      ? error.message : 'push-or-database-unavailable';
    const permanent = ['expo-DeviceNotRegistered','expo-MessageTooBig','expo-InvalidCredentials'].includes(code);
    await db.notification.updateMany({ where: { id, status: 'pending' }, data: {
      attempts: attempt, lastError: code, ...(permanent || attempt >= 3 ? { status: 'failed' } : {}),
    } });
    if (permanent) throw new UnrecoverableError(code);
    throw new Error(code);
  }
}
