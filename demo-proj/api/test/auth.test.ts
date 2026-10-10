import 'reflect-metadata';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ExecutionContext } from '@nestjs/common';
import { plainToInstance } from 'class-transformer';
import { validate } from 'class-validator';
import { AuthGuard, AuthRequest, fixtureToken } from '../src/auth';
import { fixturePeople } from '../src/fixtures';
import { SwipeDto, ProfileDto } from '../src/dto';
const id = fixturePeople[0].id;
function context(token?: string) {
  const request: AuthRequest = { headers: { authorization: token ? `Bearer ${token}` : undefined }, userId: '' };
  return { request, ctx: { switchToHttp: () => ({ getRequest: () => request }) } as unknown as ExecutionContext };
}
test('fixture authentication verifies signatures and derives the actor', async () => {
  const { request, ctx } = context(fixtureToken(id));
  assert.equal(await new AuthGuard().canActivate(ctx), true);
  assert.equal(request.userId, id);
});
test('missing and forged tokens are denied', async () => {
  const guard = new AuthGuard();
  await assert.rejects(guard.canActivate(context().ctx));
  const forged = fixtureToken(id).split('.')[0] + '.invalid';
  await assert.rejects(guard.canActivate(context(forged).ctx));
});
test('request validation rejects caller-supplied acting user and invalid coordinates', async () => {
  const swipe = plainToInstance(SwipeDto, { targetId: fixturePeople[1].id, decision: 'like', actorId: id });
  const errors = await validate(swipe, { whitelist: true, forbidNonWhitelisted: true });
  assert(errors.some(e => e.property === 'actorId'));
  const profile = plainToInstance(ProfileDto, { longitude: 181, latitude: 91 });
  const fields = (await validate(profile)).map(e => e.property);
  assert(fields.includes('longitude') && fields.includes('latitude'));
});
