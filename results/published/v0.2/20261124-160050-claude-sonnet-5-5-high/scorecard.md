# QA agent scorecard

- **Exam:** v0.2

- **Model:** `claude-sonnet-5-5` (effort `high`), served by claude-sonnet-5-5
- **Session:** 20 turns, 96 tool calls, 136.4s, stopped on `end_turn`
- **Tokens:** 42 in, 23,350 out, 369,895 cache read, 47,384 cache write
- **Estimated cost:** $0.43

| Metric | Value |
| --- | --- |
| Recall (seeded bugs found) | 15/20 (75%) |
| Recall, core tier | 11/12 (92%) |
| Recall, deep tier | 4/8 (50%) |
| Precision (confirmed findings) | 15/15 (100%) |
| F1 | 86% |
| False positives | 0 |
| Decoys taken | 0/6 |
| Invalid repros | 0 |
| Duplicate reports | 0 |
| Severity agreement | 85% |

## Seeded bugs

| Bug | Tier | Category | Severity | Found by |
| --- | --- | --- | --- | --- |
| `cancel-does-not-restock` | core | inventory | high | #11 |
| `cancel-twice-allowed` | core | state | medium | #12 |
| `closed-sales-bypass-with-promo` | deep | business-rule | high | **missed** |
| `discount-exceeds-subtotal` | core | calculation | high | #5 |
| `events-pagination-overlap` | core | functional | medium | **missed** |
| `fan-can-update-event` | core | security | critical | #1 |
| `fee-cap-ignored` | core | calculation | high | #4, #8, #10 |
| `idempotency-key-not-user-scoped` | deep | security | critical | #14 |
| `idempotent-replay-reserves-again` | deep | inventory | high | #13 |
| `logout-revokes-wrong-session` | deep | security | critical | **missed** |
| `not-found-error-contract` | core | contract | low | #3 |
| `order-idor` | core | security | critical | #2 |
| `order-price-not-snapshotted` | deep | calculation | high | #15 |
| `order-quantity-upper-bound` | core | validation | medium | #7 |
| `oversell-by-one` | core | inventory | high | #8 |
| `promo-percent-rounding` | core | calculation | low | #6 |
| `refund-ignores-discount` | deep | calculation | high | **missed** |
| `sold-out-events-hidden` | deep | functional | medium | **missed** |
| `ticket-limit-counts-cancelled` | deep | business-rule | high | #10 |
| `welcome-promo-reuse` | core | business-rule | high | #9 |

## Decoys

Behaviour the spec requires that a careless tester might report as a bug.

| Decoy | Reported as a bug by |
| --- | --- |
| `earlier-tokens-stay-valid` | - |
| `promo-codes-case-sensitive` | - |
| `admin-reads-any-order` | - |
| `foreign-order-is-404` | - |
| `page-past-end-is-empty` | - |
| `idempotent-replay-returns-200` | - |

## Findings

| # | Verdict | Severity | Title | Demonstrates |
| --- | --- | --- | --- | --- |
| 1 | confirmed | critical | Non-admin (fan) can update events via PATCH /events/{id} | `fan-can-update-event` |
| 2 | confirmed | critical | GET /orders/{id} discloses other users' orders | `order-idor` |
| 3 | confirmed | low | GET /events/{id} for unknown event returns non-standard error body | `not-found-error-contract` |
| 4 | confirmed | high | Service fee is not capped at 600 cents per order | `fee-cap-ignored` |
| 5 | confirmed | high | WELCOME5 discount exceeds subtotal, producing negative total | `discount-exceeds-subtotal` |
| 6 | confirmed | high | FAN10 discount truncated instead of rounded to nearest cent (halves up) | `promo-percent-rounding` |
| 7 | confirmed | medium | Quantity above 6 is accepted when creating an order | `order-quantity-upper-bound` |
| 8 | confirmed | high | Overselling: orders accepted beyond remaining, remaining goes negative | `fee-cap-ignored`, `oversell-by-one` |
| 9 | confirmed | high | WELCOME5 can be redeemed more than once per user | `welcome-promo-reuse` |
| 10 | confirmed | high | Cancelled orders count toward the 8-tickets-per-event limit | `fee-cap-ignored`, `ticket-limit-counts-cancelled` |
| 11 | confirmed | high | Cancelling an order does not restore event remaining | `cancel-does-not-restock` |
| 12 | confirmed | medium | Cancelling an already cancelled order returns 200 instead of 409 | `cancel-twice-allowed` |
| 13 | confirmed | high | Idempotent replay (200) decrements event remaining again | `idempotent-replay-reserves-again` |
| 14 | confirmed | high | Idempotency keys are not scoped per user | `idempotency-key-not-user-scoped` |
| 15 | confirmed | high | Event price change rewrites existing orders' prices and totals | `order-price-not-snapshotted` |

## Agent summary

I tested the API against the spec and filed 15 defects. Each one has a repro that I replayed on a fresh instance, and each replay showed the problem.

**Security**
- A fan (alice) can change an event's price with `PATCH /events/{id}`. It returns 200 instead of 403.
- `GET /orders/{id}` shows bob another user's order instead of returning 404.

**Money**
- The service fee is not capped at 600 cents. Five tickets are charged 750.
- The `WELCOME5` discount can exceed the subtotal, which gives a negative total (-50).
- `FAN10` truncates instead of rounding to the nearest cent. A 14,997 subtotal gets 1499 off instead of 1500.
- Changing an event's price rewrites `unitPriceCents` and `totalCents` on orders that already exist.

**Business rules and inventory**
- Quantity 7 is accepted. Only 9 and above are rejected.
- Events can be oversold. Event 11 has capacity 5, and a sixth ticket was sold, leaving `remaining` at -1.
- A user can redeem `WELCOME5` more than once.
- Cancelled orders count toward the 8-tickets-per-event limit.
- Cancelling an order does not give the tickets back to `remaining`.
- Cancelling an already-cancelled order returns 200 instead of 409 `already_cancelled`.
- Repeating a request with the same `Idempotency-Key` returns 200 but still lowers `remaining` again.
- Idempotency keys are shared across users. Bob reusing alice's key gets 409 `idempotency_conflict`.

**Error format**
- `GET /events/{id}` for an unknown event returns `{"detail":"Not Found"}` instead of the standard error body.

I also checked these and found nothing wrong:
- Login, logout and token revocation.
- Event pagination and its bounds.
- Validation on `PATCH /events/{id}`, including the 409 when capacity would drop below tickets sold.
- Non-integer path and query parameters.
- Promo codes being case-sensitive.
- The `sales_closed` and `invalid_quantity` checks on order creation.
- The `Idempotency-Key` length limits.
- Owner and admin access to cancel.
