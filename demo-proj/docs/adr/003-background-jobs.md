# ADR 003: Persist notification intent and process with BullMQ

Status: accepted for the demo.

A committed match must not depend on Expo availability. Its transaction writes one notification intent per participant; a separate worker dispatches those intents to Redis/BullMQ using stable IDs. The worker uses bounded retries and explicit terminal statuses.

Tradeoff: a small polling delay and an at-least-once external side effect. Stable IDs and persisted success prevent normal duplicate processing, but they cannot guarantee exactly-once device delivery. Receipt reconciliation is planned rather than claimed.
