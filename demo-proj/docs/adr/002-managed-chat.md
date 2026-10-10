# ADR 002: Use managed Stream chat through the API

Status: accepted for the demo.

Stream owns live message storage. NestJS provisions deterministic match channels and holds the signing secret. Mobile accesses chat through authenticated REST, so every operation enforces current match and block state. Fixtures substitute a small PostgreSQL message table.

Tradeoff: REST polling adds API traffic and lacks Stream's full realtime UI. This keeps token issuance and provider-outage revocation out of the small vertical slice. A future direct client must implement token and membership revocation before rollout.
