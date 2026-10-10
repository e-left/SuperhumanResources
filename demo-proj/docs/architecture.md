# Architecture

```text
Expo mobile ── authenticated REST ── NestJS API ── Prisma / parameterized SQL ── PostgreSQL + PostGIS
                                          ├── Supabase Auth and Storage
                                          └── Stream Chat (server credentials only)
PostgreSQL Notification intents ── worker poll ── Redis/BullMQ ── Expo Push
```

The mobile app owns UI, gesture worklets and TanStack Query state. It cannot assert the acting user or create a match/channel. Supabase login sessions use SecureStore; fixture sessions are held in memory. A sign-out clears query state.

The NestJS API validates DTOs and rejects unknown properties. Its guard verifies the Supabase token via a bounded Auth call or verifies a signed fixture token. Profile writes and ordinary models use Prisma; spatial updates/discovery use tagged SQL parameters. Raw coordinates and push tokens are not returned in public discovery cards.

Pair mutations lock both profile rows in ascending UUID order. Like, block, chat and notification delivery share that order. Mutual matching and both notification intents commit in one transaction. A unique canonical pair constraint independently prevents duplicate matches. A chat already holding the locks may finish before a simultaneous block commits; once the block completes, subsequent access is denied.

Stream stores managed chat. The API provisions a deterministic channel containing exactly the two match users and sends/reads on their behalf. The SDK manages server JWT authentication with the server secret. **No client Stream token is issued.** This small proxy design checks blocks on every operation without relying on remote membership revocation. The app polls chat every three seconds rather than implementing a socket client. Direct Stream client access would require a separate token/revocation design and is outside this slice.

The separate worker polls up to 100 pending notification rows every five seconds, schedules stable UUID job IDs, and runs at concurrency two. Redis failures leave database intent intact. Delivery status distinguishes simulated, suppressed, skipped, accepted and failed. Completed rows prevent normal replays; provider acceptance followed by a database/process failure can still duplicate a push. This is at-least-once delivery, not exactly-once delivery.

## Trust boundaries and failures

- Public mobile configuration contains only public URLs/keys. Service-role, Stream and Expo access secrets are server-only and ignored by git.
- Provider responses are checked; invalid tokens return 401, provider failures return 503. Requests are not silently converted to fixture success.
- HTTP provider calls use five-second abort/SDK timeouts. A live chat operation performs several bounded calls inside a twenty-second transaction; concurrency is intentionally small.
- BullMQ uses three total attempts, exponential backoff and jitter. Known permanent Expo errors stop retries early. Redis connection retries are bounded; restarting the worker restores service after exhausted connection retries.
- Nest's liveness route is process-only. Database startup must succeed; no shared-dependency readiness policy or production monitoring infrastructure is introduced for this local demo.
- Logs show failures without provider payloads/tokens. Full production metrics, traces and Datadog alerts are future work.

Fixture mode replaces only Auth, Storage, Stream and Expo boundaries. It keeps the database, PostGIS and queue path concrete.
