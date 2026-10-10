# Product and acceptance criteria

FlatPal connects fictional potential roommates around compatible preferences, budgets and move-in plans. Preferences are displayed rather than scored; only budget, move-in tolerance and distance filter cards. There are no apartment listings.

| Flow | Acceptance criterion | Evidence |
| --- | --- | --- |
| Onboard | Authenticated user saves name, bio, budget range, preferred area, move-in date, smoking, pets, sleep and coarse coordinates; invalid ranges fail | `mobile/app/profile.tsx`, `api/src/dto.ts`, `FlatPal.saveProfile` |
| Discover | At most 20 nearby compatible profiles; excludes self, prior decisions and blocks in either direction | `FlatPal.discover`, spatial migration |
| Decide | Gesture or accessible button records like/pass; server derives actor from verified token | `swipe-card.tsx`, auth guard, swipe DTO |
| Match | Mutual likes yield exactly one canonical pair and two notification intents, even under concurrency | `FlatPal.swipe`, pair locks, unique index, integration test |
| Chat | Only participants in an unblocked match can read or send | `authorizedMatch`, REST chat, fixture/Stream adapters |
| Notify | Separate worker processes durable intents; temporary failures retry up to three total attempts | `notifications.ts`, `worker.ts`, retry test |
| Block | Either participant can block; subsequent discovery, likes, chat and queued notifications enforce it | `isBlocked`, integration test |

A pass removes a profile from discovery. Existing matches cannot be passed away; block ends further contact. Blocking preserves prior match/message evidence but denies access. There is no unblock flow in this slice.

Implemented code is not runtime-verified. Real provider behavior requires configuration; fixture behavior is clearly labeled. [Roadmap](roadmap.md) contains planned work, not completed features.
