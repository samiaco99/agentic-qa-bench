# QA agent scorecard

- **Model:** `claude-haiku-5-5` (effort `medium`), served by claude-haiku-5-5
- **Session:** 23 turns, 58 tool calls, 80.7s, stopped on `end_turn`
- **Tokens:** 48 in, 18,168 out, 476,723 cache read, 31,037 cache write
- **Estimated cost:** $0.02

| Metric | Value |
| --- | --- |
| Recall (seeded bugs found) | 9/10 (90%) |
| Precision (confirmed findings) | 9/9 (100%) |
| F1 | 95% |
| False positives | 0 |
| Invalid repros | 0 |
| Duplicate reports | 0 |
| Severity agreement | 88% |

## Seeded bugs

| Bug | Category | Severity | Found by |
| --- | --- | --- | --- |
| `cancel-does-not-restock` | inventory | high | #5 |
| `cancel-twice-allowed` | state | medium | #4 |
| `discount-exceeds-subtotal` | calculation | high | #2, #3 |
| `events-pagination-overlap` | functional | medium | #1 |
| `not-found-error-contract` | contract | low | #9 |
| `order-idor` | security | critical | #7 |
| `order-quantity-upper-bound` | validation | medium | **missed** |
| `oversell-by-one` | inventory | high | #6 |
| `promo-percent-rounding` | calculation | low | #8 |
| `welcome-promo-reuse` | business-rule | high | #3 |

## Findings

| # | Verdict | Severity | Title | Demonstrates |
| --- | --- | --- | --- | --- |
| 1 | confirmed | medium | Event listing pages overlap and skip events (off-by-one offset) | `events-pagination-overlap` |
| 2 | confirmed | high | WELCOME5 promo produces negative order totals when discount exceeds subtotal | `discount-exceeds-subtotal` |
| 3 | confirmed | high | WELCOME5 promo can be redeemed more than once by the same user | `discount-exceeds-subtotal`, `welcome-promo-reuse` |
| 4 | confirmed | medium | Cancelling an already-cancelled order returns 200 instead of 409 already_cancelled | `cancel-twice-allowed` |
| 5 | confirmed | high | Cancelling an order does not restore the event's remaining tickets | `cancel-does-not-restock` |
| 6 | confirmed | high | Orders are accepted beyond event remaining capacity, driving remaining negative | `oversell-by-one` |
| 7 | confirmed | critical | Fans can read other users' orders by ID (broken object-level authorization) | `order-idor` |
| 8 | confirmed | medium | FAN10 discount is truncated instead of rounded to the nearest cent | `promo-percent-rounding` |
| 9 | confirmed | low | GET /events/{id} not-found response does not use the standard error envelope | `not-found-error-contract` |

## Agent summary

I tested the spec's main areas and filed nine defects, each with a repro that I replayed on a fresh instance. Seven are high or critical.

**Defects found**

1. **Critical, security:** fans can read other users' orders. Bob received alice's full order from `GET /orders/1`, where the spec requires `404 not_found`.
2. **High, calculation:** WELCOME5 on a 300-cent ticket gives `discountCents: 500` and `totalCents: -200`. The discount must be capped at the subtotal.
3. **High, business rule:** WELCOME5 can be redeemed repeatedly by the same user. The second order returns 201 instead of `promo_already_used`.
4. **High, inventory:** cancelling an order does not restore the event's `remaining`. Ordering 2 tickets and cancelling leaves `remaining` at 198 instead of 200.
5. **High, inventory:** a 6-ticket order for an event with 5 seats succeeds, and `remaining` goes to -1. The spec requires `409 sold_out` and no negative remaining.
6. **Medium, state:** cancelling an already-cancelled order returns 200 instead of `409 already_cancelled`.
7. **Medium, calculation:** FAN10 truncates the discount instead of rounding. A 1299-cent ticket gets 129 off instead of 130, and a 4999-cent ticket gets 499 off instead of 500.
8. **Medium, functional:** pagination overlaps. Page 2 with `pageSize=5` starts at id 5, which is already on page 1.
9. **Low, contract:** `GET /events/{id}` for an unknown event returns `{"detail": "Not Found"}` rather than the standard `{"error": {...}}` envelope.

**What passed:** login for all three seeded accounts, the 401 for bad or missing tokens, the 400 validation on non-integer and out-of-range inputs, the `invalid_quantity` and `invalid_promo_code` checks, FAN10 arithmetic on exact cents, the 404 for cross-user cancellation, and admin visibility of all orders.

**Not covered:** I did not test admin cancellation of another user's order or the full set of input-type edge cases beyond the samples above.
