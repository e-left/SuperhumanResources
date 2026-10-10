import { PrismaClient } from '@prisma/client';
import { fixturePeople } from '../src/fixtures';
const db = new PrismaClient();
async function seed() {
  if (process.env.FIXTURE_MODE !== 'true') throw new Error('Fictional seed requires FIXTURE_MODE=true');
  const moveIn = new Date();
  moveIn.setUTCDate(moveIn.getUTCDate() + 30);
  for (const person of fixturePeople) {
    const { longitude, latitude, ...profile } = person;
    await db.$transaction(async tx => {
      await tx.profile.upsert({ where: { id: person.id }, create: { ...profile, moveIn }, update: {} });
      await tx.$executeRaw`UPDATE "Profile" SET "location" = ST_SetSRID(ST_MakePoint(${longitude}, ${latitude}),4326)::geography WHERE "id" = ${person.id}::uuid AND "location" IS NULL`;
    });
  }
  console.log('Seeded four fictional profiles. Existing profiles and interactions preserved.');
}
seed().catch(() => { console.error('Seed failed; check database connectivity and migrations.'); process.exitCode = 1; }).finally(() => db.$disconnect());
