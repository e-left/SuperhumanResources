# Roadmap (planned, not implemented)

1. **Validate the scaffold:** install dependencies, commit generated lockfiles, run type checks/tests, apply migrations to a disposable DB, verify a two-user native-device walkthrough, then exercise live providers with fictional accounts.
2. **Improve spatial discovery performance:** measure `EXPLAIN (ANALYZE, BUFFERS)` at realistic fictional profile counts; verify GiST usage for `ST_DWithin`; add stable cursor pagination and investigate bounding/KNN ordering only if measurements justify it. Track latency and rows scanned before changing the query.
3. **Improve notification delivery reliability:** poll Expo receipts, clear unregistered device tokens, expose failed-job replay with audit records, test crash/recovery between acceptance and DB update, and define notification age/retention limits. Measure pending age, permanent failures and acceptance-to-receipt outcomes with Datadog.
4. **Improve swipe animation performance on lower-end devices:** profile UI/JS frame times on a modest Android phone, pre-size/decode photos, reduce card rerenders and verify gesture/scroll cancellation. Keep translation/rotation work on the UI thread; add a bounded card preload only if traces show image stalls.
5. **Product polish:** account signup, accessible onboarding fields and date/area inputs, unblock/report flows, message pagination and safe message idempotency. Direct Stream clients require a documented token-revocation design before replacing the proxy.

No candidate search logic or hiring conclusion belongs here. Consumers should infer capabilities from implemented code and distinguish this planned work from existing behavior.
