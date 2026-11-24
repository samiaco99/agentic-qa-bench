# QA agent scorecard

- **Exam:** v0.2

- **Model:** `claude-haiku-5-5` (effort `medium`), served by claude-haiku-5-5
- **Session:** 15 turns, 70 tool calls, 82.2s, stopped on `end_turn`
- **Tokens:** 32 in, 20,669 out, 218,310 cache read, 38,252 cache write
- **Estimated cost:** $0.02

| Metric | Value |
| --- | --- |
| Recall (seeded bugs found) | 10/20 (50%) |
| Recall, core tier | 8/12 (67%) |
| Recall, deep tier | 2/8 (25%) |
| Precision (confirmed findings) | 10/10 (100%) |
| F1 | 67% |
| False positives | 0 |
| Decoys taken | 0/6 |
| Invalid repros | 0 |
| Duplicate reports | 1 |
| Severity agreement | 78% |

## Seeded bugs

| Bug | Tier | Category | Severity | Found by |
| --- | --- | --- | --- | --- |
| `cancel-does-not-restock` | core | inventory | high | **missed** |
| `cancel-twice-allowed` | core | state | medium | **missed** |
| `closed-sales-bypass-with-promo` | deep | business-rule | high | **missed** |
| `discount-exceeds-subtotal` | core | calculation | high | #3, #4 |
| `events-pagination-overlap` | core | functional | medium | **missed** |
| `fan-can-update-event` | core | security | critical | #1 |
| `fee-cap-ignored` | core | calculation | high | #5 |
| `idempotency-key-not-user-scoped` | deep | security | critical | **missed** |
| `idempotent-replay-reserves-again` | deep | inventory | high | **missed** |
| `logout-revokes-wrong-session` | deep | security | critical | **missed** |
| `not-found-error-contract` | core | contract | low | #10 |
| `order-idor` | core | security | critical | **missed** |
| `order-price-not-snapshotted` | deep | calculation | high | #8 |
| `order-quantity-upper-bound` | core | validation | medium | #6 |
| `oversell-by-one` | core | inventory | high | #7 |
| `promo-percent-rounding` | core | calculation | low | #9 |
| `refund-ignores-discount` | deep | calculation | high | #2 |
| `sold-out-events-hidden` | deep | functional | medium | **missed** |
| `ticket-limit-counts-cancelled` | deep | business-rule | high | **missed** |
| `welcome-promo-reuse` | core | business-rule | high | #3 |

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
| 1 | confirmed | critical | Non-admin fan can update event price and capacity (PATCH /events/{id}) | `fan-can-update-event` |
| 2 | confirmed | high | Refund on cancellation equals subtotal instead of totalCents minus feeCents | `refund-ignores-discount` |
| 3 | confirmed | high | WELCOME5 promo can be redeemed more than once by the same user | `discount-exceeds-subtotal`, `welcome-promo-reuse` |
| 4 | confirmed | high | Promo discount can exceed the subtotal, producing negative order totals | `discount-exceeds-subtotal` (duplicate) |
| 5 | confirmed | high | Service fee cap of 600 cents per order is not applied | `fee-cap-ignored` |
| 6 | confirmed | high | Quantity of 7 accepted when the maximum per order is 6 | `order-quantity-upper-bound` |
| 7 | confirmed | high | Orders are accepted beyond event capacity; remaining goes negative (sold_out not enforced) | `oversell-by-one` |
| 8 | confirmed | high | Price change retroactively changes existing orders' unitPriceCents, discount, and total | `order-price-not-snapshotted` |
| 9 | confirmed | medium | FAN10 discount rounds half-cent down instead of to nearest cent with halves up | `promo-percent-rounding` |
| 10 | confirmed | low | GET /events/{id} for unknown event returns framework body instead of standard error shape | `not-found-error-contract` |

## Agent summary

I filed 10 defects. Each was reproduced on a fresh instance, and the replays confirmed them.

**What I tested**
- **Authentication:** valid and invalid logins, login with multiple tokens, logout (the revoked token returns 401 and the other token stays valid), and requests with no token.
- **Events:** listing with paging and bounds (`page=0`, `pageSize=51`, non-integer values, out-of-range pages), single-event lookup, and unknown routes.
- **Order creation:** quantity bounds, unknown event, sales closed, promo codes (case-sensitivity, FAN10 and WELCOME5), the 8-ticket limit, the `Idempotency-Key` replay and conflict cases, and strict-body validation.
- **Cancellation:** refund math, double cancel (`already_cancelled`), cancel by a non-owner (404), and visibility of orders to fans and admins.
- **Admin event update:** price and capacity changes, the `capacity_below_sold` rule, and negative-price validation.

**Defects reported**
1. **Critical, security:** a fan can PATCH event prices and capacity (200 instead of 403).
2. **High, calculation:** refund on cancel is the subtotal, not `totalCents - feeCents` (over-refund of 1500 cents in the repro).
3. **High, business rule:** WELCOME5 can be redeemed repeatedly by the same user.
4. **High, calculation:** promo discount can exceed the subtotal, giving negative totals (-50 cents).
5. **High, calculation:** the 600-cent per-order fee cap is not applied (6 tickets gave a 900 fee).
6. **High, validation:** quantity 7 is accepted, though the maximum is 6.
7. **High, inventory:** sold-out is not enforced; an order for 6 on an event with 5 remaining succeeds and `remaining` goes to -1.
8. **High, business rule:** an admin price change alters existing orders' `unitPriceCents`, discount, and totals.
9. **Medium, calculation:** FAN10 rounds 129.9 down to 129 instead of rounding halves up to 130.
10. **Low, contract:** `GET /events/{id}` for an unknown event returns `{"detail": "Not Found"}` rather than the standard error body with code `not_found`.

**Not reproduced or not checked:** the `sold_out` check works only when the quantity exceeds `remaining` by a single order; I did not exhaust a sold-out event. Idempotency replay and conflict behaved as specified. The unknown-route 404 used the standard error shape.
