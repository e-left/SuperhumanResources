# FlatPal

A fictional “Tinder for roommates” reference codebase inside `demo-proj`. FlatPal exists so the hackathon's repository-analysis agent can inspect concrete source, dependencies, migrations, tests, and decisions. This repository contains the demo product, not hiring automation or candidate sourcing.

**Code-only hackathon scaffold:** dependencies have not been installed; the app, migrations and tests have not been run. Treat the integration adapters as implementation examples awaiting runtime validation. See [verification](docs/verification.md).

## Stack

- `mobile/`: React Native + Expo SDK 55, TypeScript, Expo Router, Gesture Handler, Reanimated, TanStack Query.
- `api/`: NestJS REST + validation, Prisma 6, PostgreSQL 16 + PostGIS 3.5.
- Providers: Supabase Auth/Storage, Stream Chat, Expo Push Service.
- Jobs: Redis 7 + BullMQ 5, with database notification intent written in the matching transaction.

Direct package versions are exact pins, chosen against package metadata and Expo's bundled-native-module list. [Compatibility notes](docs/compatibility.md) explain the choices. No lockfiles have been generated because installation was intentionally skipped; transitive dependencies are not yet frozen.

## Local quick start

Requires Node 22.22.3, npm, Docker Compose, and an iOS/Android simulator or phone. Run these commands from `demo-proj` when you want to exercise the scaffold:

```sh
nvm install
nvm use
cp api/.env.example api/.env
cp mobile/.env.example mobile/.env
npm --prefix api install
npm --prefix mobile install
docker compose up -d --wait
npm run db:migrate
npm run db:seed
npm run api
```

In separate terminals, from `demo-proj`:

```sh
npm --prefix api run worker
npm run mobile
```

Select the iOS/Android target in Expo CLI. Android emulator: change `EXPO_PUBLIC_API_URL` to `http://10.0.2.2:3000`. A phone needs the computer's LAN address and a reachable API port. This is a native mobile demo; browser support is not part of the slice. Fixtures intentionally run on a trusted local network only.

## Fixture mode

Both example environments explicitly enable fixture mode. There is no automatic fallback when real integrations fail.

| Behavior | Fixture mode | Live mode |
| --- | --- | --- |
| Sign in | Four fictional identities and signed one-hour demo tokens | Supabase access tokens verified with Auth `/user` |
| Profile, discovery, likes, matching, blocks | Real PostgreSQL transactions and PostGIS | Same |
| Photos | Initial avatar; simulated upload path | Supabase private bucket + signed upload/read URLs |
| Chat | PostgreSQL `FixtureMessage` records | Stream-managed channels/messages through authenticated API |
| Notifications | Real Redis/BullMQ jobs; `simulated` database status, no device push | Expo acceptance tickets, bounded retries |

Fixture mode is rejected with `NODE_ENV=production`; fixture endpoints disappear in live mode. Demo tokens are deliberately easy to obtain as known fictional users. They are not a production authentication mechanism. No provider secrets belong in `mobile/.env`.

## Demo walkthrough

1. Choose **Alex** on Home. Review and save the profile. All identities, biographies and coordinates are fictional; budget units are monthly CHF.
2. Discover cards. Filters use budget overlap, distance, and days around your own move-in date. Swipe right/Like on **Sam**.
3. Sign out and choose **Sam**, then like **Alex**. A single mutual match appears.
4. Open Matches, enter chat, and send a message. Switch identities to see the shared conversation.
5. Run the worker to see `simulated` notification entries under Matches. No external credentials or device push are needed in fixture mode.
6. Block the other user. Both participants lose access to the chat and match list; blocked profiles are filtered out of discovery.

Seed is repeatable and preserves existing profiles/interactions. For a fresh demo use a fresh local database; reseeding does not undo swipes or blocks.

## Checks, when desired

```sh
npm run check
npm test
```

Without `TEST_DATABASE_URL`, the database/Redis integration suite is **skipped**. To exercise it, start the disposable services and migrate their database:

```sh
docker compose -f compose.test.yaml up -d --wait
cd api
DATABASE_URL='postgresql://flatpal:local-demo-only@localhost:54330/flatpal_test?schema=public' npm run db:migrate
cd ..
```

Set `TEST_DATABASE_URL` in `api/.env` to that test URL, keep `FIXTURE_MODE=true`, and use `TEST_REDIS_PORT=63800`; then run `npm test`. The integration suite deletes data only in the explicitly configured database whose name ends in `_test`. Never point it at the demo database. Tests cover concurrent matching, acting-user authorization, spatial discovery, blocking and notification retries with injected provider failures.

## Scope

Included: onboarding, card discovery, like/pass, mutual matches, chat, match notification jobs and blocking. Excluded: apartment listings, payments, identity verification, ML recommendations and production deployment.

[Product](docs/product.md) · [Architecture](docs/architecture.md) · [API](docs/api.md) · [Data model](docs/data-model.md) · [Integrations](docs/integrations.md) · [Roadmap](docs/roadmap.md)
