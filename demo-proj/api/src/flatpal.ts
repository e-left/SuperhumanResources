import { BadRequestException, ConflictException, ForbiddenException, Injectable, NotFoundException } from '@nestjs/common';
import { Db, isBlocked, lockPair, transactionOptions, Transaction } from './db';
import { ProfileDto, DiscoveryDto, SwipeDto } from './dto';
import { Chat, Photos } from './providers';
@Injectable()
export class FlatPal {
  constructor(private readonly db: Db, private readonly chat: Chat, private readonly photos: Photos) {}
  async profile(userId: string) {
    const profile = await this.db.profile.findUnique({ where: { id: userId } });
    if (!profile) throw new NotFoundException('Complete onboarding first');
    const [point] = await this.db.$queryRaw<{ longitude: number; latitude: number }[]>`
      SELECT ST_X("location"::geometry) AS longitude, ST_Y("location"::geometry) AS latitude
      FROM "Profile" WHERE "id" = ${userId}::uuid`;
    const { pushToken, photoPath, ...fields } = profile;
    return { ...fields, ...point, photoPath, photoUrl: await this.photos.url(photoPath) };
  }
  async saveProfile(userId: string, input: ProfileDto) {
    if (input.budgetMax < input.budgetMin) throw new BadRequestException('budgetMax must be >= budgetMin');
    if (input.photoPath && !new RegExp(`^${userId}/(?:[0-9a-f-]{36}|fixture)\\.jpg$`).test(input.photoPath))
      throw new BadRequestException('Photo path must belong to the authenticated user');
    const { longitude, latitude, moveIn, ...fields } = input;
    await this.db.$transaction(async tx => {
      await tx.profile.upsert({ where: { id: userId }, create: { id: userId, ...fields, moveIn: new Date(moveIn) }, update: { ...fields, moveIn: new Date(moveIn) } });
      await tx.$executeRaw`UPDATE "Profile" SET "location" = ST_SetSRID(ST_MakePoint(${longitude}, ${latitude}),4326)::geography WHERE "id" = ${userId}::uuid`;
    }, transactionOptions);
    return this.profile(userId);
  }
  async discover(userId: string, filters: DiscoveryDto) {
    const me = await this.db.profile.findUnique({ where: { id: userId } });
    if (!me) throw new NotFoundException('Complete onboarding first');
    const min = filters.budgetMin ?? me.budgetMin, max = filters.budgetMax ?? me.budgetMax;
    if (max < min) throw new BadRequestException('Invalid budget range');
    const cards = await this.db.$queryRaw<Array<{
      id: string; name: string; bio: string; budgetMin: number; budgetMax: number; area: string;
      moveIn: Date; smoking: string; pets: string; sleep: string; photoPath: string | null; distanceKm: number;
    }>>`
      SELECT p."id", p."name", p."bio", p."budgetMin", p."budgetMax", p."area", p."moveIn",
        p."smoking", p."pets", p."sleep", p."photoPath", ST_Distance(p."location", me."location")/1000 AS "distanceKm"
      FROM "Profile" p JOIN "Profile" me ON me."id" = ${userId}::uuid
      WHERE p."id" <> me."id" AND p."budgetMax" >= ${min} AND p."budgetMin" <= ${max}
        AND ABS(p."moveIn" - me."moveIn") <= ${filters.moveInDays}
        AND ST_DWithin(p."location", me."location", ${filters.radiusKm * 1000})
        AND NOT EXISTS (SELECT 1 FROM "Block" b WHERE
          (b."actorId" = me."id" AND b."targetId" = p."id") OR (b."actorId" = p."id" AND b."targetId" = me."id"))
        AND NOT EXISTS (SELECT 1 FROM "Swipe" s WHERE s."actorId" = me."id" AND s."targetId" = p."id")
      ORDER BY "distanceKm", p."id" LIMIT 20`;
    const result = [];
    for (const { photoPath, ...card } of cards) result.push({ ...card, photoUrl: await this.photos.url(photoPath) });
    return result;
  }
  async swipe(userId: string, input: SwipeDto) {
    const targetId = input.targetId.toLowerCase();
    if (userId === targetId) throw new BadRequestException('Cannot swipe on yourself');
    return this.db.$transaction(async tx => {
      if (!await lockPair(tx, userId, targetId)) throw new NotFoundException('Profile not found');
      if (await isBlocked(tx, userId, targetId)) throw new ForbiddenException('User pair is blocked');
      const [lowId, highId] = [userId, targetId].sort();
      const existing = await tx.match.findUnique({ where: { lowId_highId: { lowId, highId } } });
      if (existing) {
        if (input.decision === 'pass') throw new ConflictException('Already matched; use block to end contact');
        return { matchId: existing.id };
      }
      await tx.swipe.upsert({ where: { actorId_targetId: { actorId: userId, targetId } },
        create: { actorId: userId, targetId, decision: input.decision }, update: { decision: input.decision } });
      const reciprocal = await tx.swipe.findUnique({ where: { actorId_targetId: { actorId: targetId, targetId: userId } } });
      if (input.decision !== 'like' || reciprocal?.decision !== 'like') return { matchId: null };
      const match = await tx.match.create({ data: { lowId, highId } });
      // Durable notification intent commits atomically with the match; Redis is not in this transaction.
      await tx.notification.createMany({ data: [lowId, highId].map(recipientId => ({ matchId: match.id, recipientId })) });
      return { matchId: match.id };
    }, transactionOptions);
  }
  async matches(userId: string) {
    const matches = await this.db.match.findMany({ where: { OR: [{ lowId: userId }, { highId: userId }] }, orderBy: { createdAt: 'desc' }, take: 50 });
    const result = [];
    for (const match of matches) {
      const otherId = match.lowId === userId ? match.highId : match.lowId;
      if (await isBlocked(this.db, userId, otherId)) continue;
      const other = await this.db.profile.findUniqueOrThrow({ where: { id: otherId } });
      result.push({ id: match.id, createdAt: match.createdAt, other: { id: other.id, name: other.name, area: other.area } });
    }
    return result;
  }
  private async authorizedMatch(tx: Transaction, userId: string, matchId: string) {
    const match = await tx.match.findUnique({ where: { id: matchId } });
    if (!match || ![match.lowId, match.highId].includes(userId)) throw new NotFoundException('Match not found');
    await lockPair(tx, match.lowId, match.highId);
    if (await isBlocked(tx, match.lowId, match.highId)) throw new ForbiddenException('Chat access blocked');
    return match;
  }
  async messages(userId: string, matchId: string) {
    return this.db.$transaction(async tx => this.chat.messages(tx, await this.authorizedMatch(tx, userId, matchId)), transactionOptions);
  }
  async send(userId: string, matchId: string, text: string) {
    if (!text.trim()) throw new BadRequestException('Message cannot be blank');
    return this.db.$transaction(async tx => this.chat.send(tx, await this.authorizedMatch(tx, userId, matchId), userId, text.trim()), transactionOptions);
  }
  async block(userId: string, targetId: string) {
    targetId = targetId.toLowerCase();
    if (userId === targetId) throw new BadRequestException('Cannot block yourself');
    await this.db.$transaction(async tx => {
      if (!await lockPair(tx, userId, targetId)) throw new NotFoundException('Profile not found');
      await tx.block.upsert({ where: { actorId_targetId: { actorId: userId, targetId } }, create: { actorId: userId, targetId }, update: {} });
    }, transactionOptions);
    return { blocked: true };
  }
  async pushToken(userId: string, token: string) {
    const result = await this.db.profile.updateMany({ where: { id: userId }, data: { pushToken: token } });
    if (!result.count) throw new NotFoundException('Complete onboarding first');
    return { registered: true };
  }
  async notifications(userId: string) {
    return this.db.notification.findMany({ where: { recipientId: userId }, select: {
      id: true, matchId: true, status: true, attempts: true, lastError: true, createdAt: true,
    }, orderBy: { createdAt: 'desc' }, take: 20 });
  }
}
