# Data model

IDs are UUIDs. `Profile.id` is the verified Auth subject; fixture identities use fixed fictional UUIDs. The four seed profiles use Zurich-area approximate points and a move-in date thirty days after initial seeding. No real person or address is represented.

| Table | Purpose / constraints |
| --- | --- |
| `Profile` | Preferences, budget, date, owned photo path, private push token; budget and enum CHECK constraints |
| `Swipe` | Composite primary key `(actorId,targetId)`; decision CHECK; no self-swipe |
| `Match` | Canonical `lowId < highId`; unique pair index; `highId` index for match lookup |
| `Block` | Directed composite primary key; queries enforce either direction; reverse lookup index |
| `Notification` | Durable match notification intent; unique `(matchId,recipientId)`; status, attempts, safe error code and provider acceptance ticket |
| `FixtureMessage` | Local simulated managed-chat history; `(matchId,createdAt)` index |

SQL migrations add foreign keys, CHECK constraints and indexes explicitly. Prisma models intentionally stay flat; UUID foreign keys are in SQL rather than relation navigation. Do not use `prisma db push` to replace these migrations.

The second migration adds `geography(Point,4326)` and a GiST index. Prisma represents location as `Unsupported` and omits it from normal model writes. Tagged `$executeRaw` sets `ST_MakePoint(longitude,latitude)` with SRID 4326. Tagged `$queryRaw` uses `ST_DWithin` against geography for an index-compatible radius condition, then `ST_Distance` for ordering. Values are bound parameters, never interpolated SQL strings. Discovery does not expose exact coordinates.

Pair row locks serialize reciprocal likes and blocks under PostgreSQL's default READ COMMITTED isolation. Unique constraints backstop the locking rule. The match and its two notification rows commit together; no network call occurs in the matching transaction.

Notification statuses: `pending`, `simulated` (fixture), `accepted` (Expo ticket, not confirmed delivery), `skipped` (no registered push token), `suppressed` (blocked), `failed` (permanent error or retries exhausted). Receipts and delivery confirmation are planned. Existing match/message records are retained after blocking; there is no deletion or retention policy in this demo.
