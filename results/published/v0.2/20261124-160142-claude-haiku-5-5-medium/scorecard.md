# QA agent scorecard

- **Exam:** v0.2

- **Model:** `claude-haiku-5-5` (effort `medium`), served by claude-haiku-5-5
- **Session:** 20 turns, 71 tool calls, 97.1s, stopped on `end_turn`
- **Tokens:** 42 in, 23,102 out, 381,216 cache read, 39,090 cache write
- **Estimated cost:** $0.02

| Metric | Value |
| --- | --- |
| Recall (seeded bugs found) | 11/20 (55%) |
| Recall, core tier | 8/12 (67%) |
| Recall, deep tier | 3/8 (38%) |
| Precision (confirmed findings) | 11/11 (100%) |
| F1 | 71% |
| False positives | 0 |
| Decoys taken | 0/6 |
| Invalid repros | 0 |
| Duplicate reports | 0 |
| Severity agreement | 91% |

## Seeded bugs

| Bug | Tier | Category | Severity | Found by |
| --- | --- | --- | --- | --- |
| `cancel-does-not-restock` | core | inventory | high | #5 |
| `cancel-twice-allowed` | core | state | medium | **missed** |
| `closed-sales-bypass-with-promo` | deep | business-rule | high | **missed** |
| `discount-exceeds-subtotal` | core | calculation | high | #7 |
| `events-pagination-overlap` | core | functional | medium | **missed** |
| `fan-can-update-event` | core | security | critical | #1 |
| `fee-cap-ignored` | core | calculation | high | #9 |
| `idempotency-key-not-user-scoped` | deep | security | critical | **missed** |
| `idempotent-replay-reserves-again` | deep | inventory | high | #3 |
| `logout-revokes-wrong-session` | deep | security | critical | #10 |
| `not-found-error-contract` | core | contract | low | #11 |
| `order-idor` | core | security | critical | **missed** |
| `order-price-not-snapshotted` | deep | calculation | high | #2 |
| `order-quantity-upper-bound` | core | validation | medium | **missed** |
| `oversell-by-one` | core | inventory | high | #4 |
| `promo-percent-rounding` | core | calculation | low | #8 |
| `refund-ignores-discount` | deep | calculation | high | **missed** |
| `sold-out-events-hidden` | deep | functional | medium | **missed** |
| `ticket-limit-counts-cancelled` | deep | business-rule | high | **missed** |
| `welcome-promo-reuse` | core | business-rule | high | #6 |

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
| 1 | confirmed | critical | Non-admin fan can change event price and capacity via PATCH /events/{id} | `fan-can-update-event` |
| 2 | confirmed | high | Price change rewrites unitPriceCents and totalCents of existing orders | `order-price-not-snapshotted` |
| 3 | confirmed | high | Repeating an Idempotency-Key request decrements event remaining again | `idempotent-replay-reserves-again` |
| 4 | confirmed | high | Sold-out check bypassed: orders succeed beyond remaining and remaining goes negative | `oversell-by-one` |
| 5 | confirmed | high | Cancelling an order does not return its tickets to event remaining | `cancel-does-not-restock` |
| 6 | confirmed | high | WELCOME5 promo can be redeemed more than once per user | `welcome-promo-reuse` |
| 7 | confirmed | high | WELCOME5 discount can exceed the subtotal, producing a negative totalCents | `discount-exceeds-subtotal` |
| 8 | confirmed | medium | FAN10 discount rounds down instead of half-up to the nearest cent | `promo-percent-rounding` |
| 9 | confirmed | high | Service fee is not capped at 600 cents per order | `fee-cap-ignored` |
| 10 | confirmed | critical | Logout revokes a different token; the logged-out token keeps working | `logout-revokes-wrong-session` |
| 11 | confirmed | low | Unknown event returns a non-standard 404 body on GET /events/{id} | `not-found-error-contract` |

## Agent summary

I tested the API against the specification and filed 11 defects, all reproduced on a fresh instance. I stopped there.

**Tested:** login and invalid credentials, bearer-token handling, logout, event listing and pagination bounds, event lookup, the admin PATCH, order creation (quantity, promo codes, fee, ticket limit, sold-out, sales closed), the Idempotency-Key flow, order reads and ownership, and cancellation.

**Found (filed with `report_bug`):**

| # | Severity | Defect |
|---|---|---|
| 1 | Critical | A fan token can PATCH event price and capacity (`200` instead of `403`). |
| 2 | Critical | After a logout, the logged-out token still works and the other session's token is revoked instead. |
| 3 | High | An admin price change rewrites `unitPriceCents` and `totalCents` on existing orders. |
| 4 | High | Repeating an Idempotency-Key request decrements `remaining` again. |
| 5 | High | The sold-out check is bypassed; `remaining` goes negative (-1). |
| 6 | High | Cancelling an order does not return its tickets to `remaining`. |
| 7 | High | WELCOME5 can be redeemed repeatedly by the same user. |
| 8 | High | WELCOME5 discount can exceed the subtotal, giving a negative total (-50). |
| 9 | High | The 600-cent per-order fee cap is not applied (6 tickets charged 900). |
| 10 | Medium | FAN10 rounds down instead of half-up (499 instead of 500). |
| 11 | Low | `GET /events/999` returns `{"detail": "Not Found"}` instead of the standard error envelope. |

**Verified as correct:** pagination bounds and empty out-of-range pages, `validation_error` for bad types and extra fields, Idempotency-Key length and conflict handling, the ticket limit, `capacity_below_sold`, the refund calculation (`totalCents - feeCents`), and cross-user `404`s on orders.
