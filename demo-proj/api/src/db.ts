import { Injectable, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { PrismaClient, Prisma } from '@prisma/client';
@Injectable()
export class Db extends PrismaClient implements OnModuleInit, OnModuleDestroy {
  async onModuleInit() { await this.$connect(); }
  async onModuleDestroy() { await this.$disconnect(); }
}
export type Transaction = Prisma.TransactionClient;
// All mutations involving two users share this ordering (including chat and jobs).
export async function lockPair(tx: Transaction, first: string, second: string) {
  const ids = [first, second].sort();
  const rows = await tx.$queryRaw<{ id: string }[]>`
    SELECT "id" FROM "Profile" WHERE "id" IN (${ids[0]}::uuid, ${ids[1]}::uuid)
    ORDER BY "id" FOR UPDATE`;
  return rows.length === 2;
}
export function isBlocked(tx: Transaction, first: string, second: string) {
  return tx.block.findFirst({ where: { OR: [
    { actorId: first, targetId: second }, { actorId: second, targetId: first },
  ] } });
}
export const transactionOptions = { maxWait: 5000, timeout: 20000 };
