# QA agent scorecard

- **Exam:** v0.2

- **Model:** `claude-haiku-5-5` (effort `medium`), served by claude-haiku-5-5
- **Session:** 20 turns, 73 tool calls, 97.6s, stopped on `end_turn`
- **Tokens:** 42 in, 23,737 out, 356,894 cache read, 38,211 cache write
- **Estimated cost:** $0.02

| Metric | Value |
| --- | --- |
| Recall (seeded bugs found) | 12/20 (60%) |
| Recall, core tier | 9/12 (75%) |
| Recall, deep tier | 3/8 (38%) |
| Precision (confirmed findings) | 12/12 (100%) |
| F1 | 75% |
| False positives | 0 |
| Decoys taken | 0/6 |
| Invalid repros | 0 |
| Duplicate reports | 0 |
| Severity agreement | 82% |

## Seeded bugs

| Bug | Tier | Category | Severity | Found by |
| --- | --- | --- | --- | --- |
| `cancel-does-not-restock` | core | inventory | high | #8 |
| `cancel-twice-allowed` | core | state | medium | #9 |
| `closed-sales-bypass-with-promo` | deep | business-rule | high | **missed** |
| `discount-exceeds-subtotal` | core | calculation | high | #4 |
| `events-pagination-overlap` | core | functional | medium | **missed** |
| `fan-can-update-event` | core | security | critical | #1 |
| `fee-cap-ignored` | core | calculation | high | #5 |
| `idempotency-key-not-user-scoped` | deep | security | critical | **missed** |
| `idempotent-replay-reserves-again` | deep | inventory | high | #7 |
| `logout-revokes-wrong-session` | deep | security | critical | **missed** |
| `not-found-error-contract` | core | contract | low | #12 |
| `order-idor` | core | security | critical | #2 |
| `order-price-not-snapshotted` | deep | calculation | high | #11 |
| `order-quantity-upper-bound` | core | validation | medium | **missed** |
| `oversell-by-one` | core | inventory | high | **missed** |
| `promo-percent-rounding` | core | calculation | low | #6, #10 |
| `refund-ignores-discount` | deep | calculation | high | #10 |
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
| 1 | confirmed | critical | Fan can change event price and capacity via PATCH /events/{id} | `fan-can-update-event` |
| 2 | confirmed | critical | Fan can read another user's order by ID (IDOR on GET /orders/{id}) | `order-idor` |
| 3 | confirmed | high | WELCOME5 promo can be redeemed more than once per user | `welcome-promo-reuse` |
| 4 | confirmed | high | Promo discount can exceed subtotal, producing a negative order total | `discount-exceeds-subtotal` |
| 5 | confirmed | high | Service fee is not capped at 600 cents per order | `fee-cap-ignored` |
| 6 | confirmed | high | FAN10 discount rounds down instead of rounding half-up to nearest cent | `promo-percent-rounding` |
| 7 | confirmed | high | Idempotent replay of POST /orders decrements event remaining on every repeat | `idempotent-replay-reserves-again` |
| 8 | confirmed | high | Cancelling an order does not restore the event's remaining tickets | `cancel-does-not-restock` |
| 9 | confirmed | high | Second cancellation of an order returns 200 instead of 409 already_cancelled | `cancel-twice-allowed` |
| 10 | confirmed | high | Refund on cancellation ignores discount and fee (refund equals subtotal) when a promo is used | `promo-percent-rounding`, `refund-ignores-discount` |
| 11 | confirmed | high | Admin price change rewrites unitPriceCents and totals of existing orders | `order-price-not-snapshotted` |
| 12 | confirmed | low | GET /events/{id} for unknown event returns non-standard error body | `not-found-error-contract` |

## Agent summary

I've covered the spec's main areas and filed 12 reports. Four are critical or high-severity security and money issues; the rest are inventory, state, and contract problems.

**What I tested**
- **Authentication:** valid and invalid logins, missing tokens, logout revoking only the presented token, and multiple tokens per user. These matched the spec.
- **Events:** listing, pagination bounds, disjoint pages, the empty page past the end, path validation, and admin PATCH rules (validation, 404, `capacity_below_sold`, and recalculated `remaining`). Most matched; the exceptions are in the reports.
- **Orders:** quantity bounds, string-typed quantity, the 8-ticket limit, sales-closed and unknown-event handling, promo case sensitivity, idempotency (replay and conflict), and ownership.
- **Cancellation:** owner and non-owner access, plus refund and inventory effects.

**Defects filed**
1. **Critical, security:** a fan can change event price and capacity via `PATCH /events/{id}` and gets 200 instead of 403.
2. **Critical, security:** a fan can read another user's order via `GET /orders/{id}` (IDOR). The spec requires a 404.
3. **High, business rule:** WELCOME5 can be redeemed more than once per user.
4. **High, calculation:** the discount can exceed the subtotal, giving a negative total (-50 on a 300-cent ticket).
5. **High, calculation:** the service fee is not capped at 600 cents per order (900 for 6 tickets).
6. **High, calculation:** FAN10 rounds down (999 instead of 1000 on a 999.8 discount).
7. **High, inventory:** each idempotent replay of `POST /orders` reduces `remaining`.
8. **High, inventory:** cancelling an order does not restore `remaining`.
9. **High, state:** a repeat cancellation returns 200 instead of 409 `already_cancelled`.
10. **High, calculation:** on cancellation with a promo, `refundCents` equals the subtotal instead of `totalCents - feeCents`.
11. **High, money:** an admin price change rewrites `unitPriceCents` and totals on existing orders.
12. **Low, contract:** `GET /events/{id}` for an unknown ID returns `{"detail": "Not Found"}` instead of the standard error envelope.

Every report was reproduced on a fresh instance with replay_steps before filing, except finding 7, which was reproduced in the replay output for the idempotent-replay case. Several of the money and inventory defects compound: the fee cap, promo, and refund issues would all affect real customer charges.
