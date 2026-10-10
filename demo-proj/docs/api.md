# REST API

Default local base: `http://localhost:3000`. All endpoints except liveness and fixture login require `Authorization: Bearer <access token>`. Unknown body/query properties are rejected. Acting IDs are always derived from authentication, never body parameters. JSON responses follow Nest error behavior: `{statusCode,message,error}` for framework errors; unexpected errors return a generic 500.

| Method / path | Request | Response / behavior |
| --- | --- | --- |
| `GET /health/live` | None | `{live:true, mode}`; does not check remote dependencies |
| `GET /fixture/users` | None | Fictional `{id,name}[]`; 404 outside fixture mode |
| `POST /fixture/session` | `{userId:uuid}` | `{mode,accessToken,expiresIn:3600}`; known demo identity only |
| `GET /me/profile` | None | Own profile and signed photo URL; 404 before onboarding |
| `PUT /me/profile` | Profile below | Saved own profile |
| `GET /discovery` | Optional `budgetMin`, `budgetMax`, `radiusKm=10`, `moveInDays=30` | Up to 20 public cards sorted by distance then ID |
| `POST /swipes` | `{targetId:uuid,decision:"like" or "pass"}` | `{matchId:uuid or null}`; repeated like returns existing match |
| `GET /matches` | None | Up to 50 unblocked `{id,createdAt,other:{id,name,area}}` |
| `GET /matches/:id/messages` | None | `{mode,messages:[{id,senderId,text,createdAt,...}]}`; last 50 chronological |
| `POST /matches/:id/messages` | `{text:string}` (1–1000 chars) | Sent message; no automatic retries |
| `POST /blocks` | `{targetId:uuid}` | `{blocked:true}`; repeat is idempotent |
| `POST /me/photo-upload` | Empty object | `{mode,path,signedUrl,token}` for own JPEG path; fixture URLs/tokens are null |
| `PUT /me/push-token` | `{token:ExpoPushToken[...]}` | `{registered:true}`; onboarding required |
| `GET /me/notifications` | None | Own last 20 statuses and attempt counts; never returns push tokens |

Profile body:

```json
{
  "name": "Alex", "bio": "Fictional weekend baker",
  "budgetMin": 900, "budgetMax": 1400, "area": "Wiedikon",
  "moveIn": "2026-11-01", "smoking": "no", "pets": "none", "sleep": "regular",
  "longitude": 8.518, "latitude": 47.369
}
```

Optional `photoPath` must be the authenticated user's signed-upload path. Smoking: `no|yes|outside`; pets: `none|cat|dog|other`; sleep: `early|regular|late`. Budgets are integers 0–20000 with max ≥ min. Coordinates are validated WGS84 values. Area is descriptive; coordinates define distance. Discovery budgets overlap the candidate's budget; move-in tolerance is absolute days around the caller's date. Distance is geography meters converted to kilometers, capped at 100 km. No cursor pagination in this slice.

## Errors

- 400: invalid input, forged actor property, invalid UUID, self-swipe/block, reversed budget, wrong photo ownership.
- 401: missing, forged, expired or rejected access token; sign in again.
- 403: blocked user pair; chat and further likes denied in either direction.
- 404: missing profile/match, or match belonging to another user; no match enumeration.
- 409: passing an already matched user; use block instead.
- 503: authentication, Storage or Stream unavailable/malformed/timed out. An ambiguous Stream send says to refresh before retrying.
- 500: unexpected database/API failure; logged safely. Transaction failures are not reported as successful matches.

POST success uses Nest's default 201; GET/PUT use 200. Failed push jobs do not undo a committed match; notification activity reports their separate outcome.
