# Integrations

Keep both `.env.example` files as templates. Actual `.env` files are gitignored. Fixtures are explicitly selected, never a rescue path for misconfigured live credentials.

## Supabase Auth

Set `FIXTURE_MODE=false` on the API and `EXPO_PUBLIC_FIXTURE_MODE=false` on mobile. Configure matching project URL and publishable key. Provision fictional test accounts in Supabase Auth; mobile supports email/password sign-in for these pre-created accounts. There is no account-signup UI in this slice.

The backend calls `GET /auth/v1/user` with the bearer token and project key. Supabase verifies the access token; the API uses the returned UUID as actor. Invalid authentication returns 401; outage or malformed data returns 503. Mobile persists live auth sessions in SecureStore. Set the matching environment mode before starting either process.

## Supabase Storage

Create a **private** `profile-photos` bucket. Restrict uploads to JPEG and 5 MB in bucket settings. Put the service-role key only in `api/.env`. The backend signs a unique upload path under the authenticated UUID; mobile uses `uploadToSignedUrl`. Saving a photo path checks the UUID prefix. Backend signs five-minute read URLs for cards. No arbitrary client URL is stored.

Fixture upload returns an owned fake path with no URL/token and mobile shows an initial avatar. It does not upload a file or contact Storage. Signed URLs already issued remain usable until expiration; blocking controls discovery/chat and cannot revoke previously issued photo URLs.

## Stream Chat

Create a Stream Chat application with a `messaging` channel type. Put its API key/secret only in `api/.env`; neither is sent to mobile. Disable guest/anonymous access in the Stream dashboard. Do not add a second client integration that issues Stream tokens outside this backend.

`api/src/providers.ts` instantiates the server SDK with a five-second timeout, upserts the two verified match identities and provisions `flatpal-<match UUID>` with those members. Backend server JWT signing/authentication is handled by the SDK. All user chat operations pass through the API's authentication, pair locks, match membership and block checks. No user Stream token endpoint exists. Blocking therefore prevents subsequent REST chat access without waiting for remote membership cleanup. Historical Stream channels remain stored.

Errors return 503 rather than simulated success. A send timeout may mean Stream accepted a message; refresh before retrying. Fixture mode persists messages in `FixtureMessage` and makes no Stream requests. Typing, read receipts, attachments and sockets are outside the slice.

## Expo Push / Redis / BullMQ

For real push, use an Expo development build on a physical device, configure the EAS project ID, native push credentials and notification permissions. This setup is separate from the fixture demo; Expo Go/simulators are not the push verification target. If Expo enhanced push security is enabled, configure its access token only on the backend.

Mobile registers the Expo token on its own profile. A separate worker polls database intent and uses Redis/BullMQ with stable job IDs and concurrency two. Three total attempts use exponential backoff and jitter. Expo HTTP calls have a five-second timeout. Permanent token/credential/message errors fail immediately; other failures retry. A missing device token yields `skipped`. A block yields `suppressed`. Fixture mode records `simulated` without calling Expo.

Successful provider submission stores `accepted` plus the ticket ID, **not delivered**. Receipt polling, stale-token cleanup and redelivery tooling are planned. A crash after provider acceptance but before the database update may duplicate a push. Pending intent survives a Redis outage; terminal failures stay visible in the database and retained failed jobs. If Redis connection retries exhaust, restart the worker after restoring Redis. Do not blindly erase failed jobs or reset database status.

Provider failures are logged with safe context and are visible via API errors or `/me/notifications`. The code avoids raw tokens, secrets and provider payloads in logs. No external integration has been exercised in this code-only delivery.
