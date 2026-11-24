# QA agent scorecard

- **Model:** `claude-haiku-5-5` (effort `medium`), served by claude-haiku-5-5
- **Session:** 13 turns, 55 tool calls, 64.9s, stopped on `end_turn`
- **Tokens:** 28 in, 15,104 out, 148,053 cache read, 23,399 cache write
- **Estimated cost:** $0.01

| Metric | Value |
| --- | --- |
| Recall (seeded bugs found) | 8/10 (80%) |
| Precision (confirmed findings) | 8/8 (100%) |
| F1 | 89% |
| False positives | 0 |
| Invalid repros | 0 |
| Duplicate reports | 0 |
| Severity agreement | 88% |

## Seeded bugs

| Bug | Category | Severity | Found by |
| --- | --- | --- | --- |
| `cancel-does-not-restock` | inventory | high | #2 |
| `cancel-twice-allowed` | state | medium | #7 |
| `discount-exceeds-subtotal` | calculation | high | #5 |
| `events-pagination-overlap` | functional | medium | **missed** |
| `not-found-error-contract` | contract | low | #8 |
| `order-idor` | security | critical | #1 |
| `order-quantity-upper-bound` | validation | medium | **missed** |
| `oversell-by-one` | inventory | high | #3 |
| `promo-percent-rounding` | calculation | low | #6 |
| `welcome-promo-reuse` | business-rule | high | #4 |

## Findings

| # | Verdict | Severity | Title | Demonstrates |
| --- | --- | --- | --- | --- |
| 1 | confirmed | critical | Fans can read other users' orders by ID (broken object-level authorization) | `order-idor` |
| 2 | confirmed | high | Cancelling an order does not restore event remaining inventory | `cancel-does-not-restock` |
| 3 | confirmed | high | Orders are accepted beyond event capacity; remaining goes negative | `oversell-by-one` |
| 4 | confirmed | high | WELCOME5 promo can be redeemed more than once by the same user | `welcome-promo-reuse` |
| 5 | confirmed | high | WELCOME5 discount is not capped at the subtotal, producing negative totals | `discount-exceeds-subtotal` |
| 6 | confirmed | high | FAN10 discount rounds down instead of to nearest cent with halves rounded up | `promo-percent-rounding` |
| 7 | confirmed | medium | Cancelling an already-cancelled order returns 200 instead of 409 already_cancelled | `cancel-twice-allowed` |
| 8 | confirmed | low | Unknown event ID returns 404 in a non-standard error shape | `not-found-error-contract` |

## Agent summary

I tested the Matchday Tickets API against the specification and filed 8 defects. Each one was reproduced on a fresh instance, but one of the reports (the IDOR) was filed before its replay output was shown, so it's worth a glance at the replay log.

**Defects filed**

1. **Critical, security:** Fans can read other users' orders. Bob's token returned Alice's order with `GET /orders/{id}` (200) when the spec requires 404.
2. **High, inventory:** Cancelling an order does not restore the event's `remaining`. An order for 2 on event 3 took it from 200 to 198, and cancelling left it at 198.
3. **High, inventory:** Orders beyond capacity are accepted. Event 11 (capacity 5) accepted an order for 6, leaving `remaining` at -1. The spec requires 409 `sold_out` and no negative remaining.
4. **High, business rule:** WELCOME5 can be redeemed repeatedly. The same user got a second 201 with the discount instead of `promo_already_used`.
5. **High, calculation:** WELCOME5 discount is not capped at the subtotal. A 300-cent ticket produced `discountCents: 500` and `totalCents: -200`.
6. **High, calculation:** FAN10 rounding is wrong. 3 × 4999 gives a 1499.7 discount that should round to 1500, but the API returned 1499 (total 13498 instead of 13497).
7. **Medium, state:** Cancelling an already-cancelled order returns 200 instead of 409 `already_cancelled`. The state is not changed again, so the defect is in the status code.
8. **Low, contract:** An unknown event ID (`GET /events/999`) returns `{"detail": "Not Found"}` rather than the standard error envelope with code `not_found`.

**What I checked and found correct**

- Login: valid and invalid credentials, and the `invalid_credentials` response.
- Token handling: a malformed or unknown token returns 401 `unauthorized`.
- Pagination: `page` and `pageSize` bounds, and the `total` field.
- Input validation: non-integer path and query parameters, string quantities, extra fields, and out-of-range quantities.
- Promo handling: an unknown promo code (including a lowercase variant) returns `invalid_promo_code`.
- Admin cancellation of another user's order is allowed.
- Repeated cancels did not double-restore inventory.
- Unknown routes return the standard `not_found` envelope.

Not covered: the `GET /orders` listing for admins versus fans beyond a single check, and the `WELCOME5` behaviour after a cancellation.
