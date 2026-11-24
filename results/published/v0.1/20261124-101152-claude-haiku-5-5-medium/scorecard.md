# QA agent scorecard

- **Model:** `claude-haiku-5-5` (effort `medium`), served by claude-haiku-5-5
- **Session:** 14 turns, 58 tool calls, 88.1s, stopped on `end_turn`
- **Tokens:** 30 in, 16,003 out, 192,586 cache read, 31,892 cache write
- **Estimated cost:** $0.01

| Metric | Value |
| --- | --- |
| Recall (seeded bugs found) | 8/10 (80%) |
| Precision (confirmed findings) | 8/8 (100%) |
| F1 | 89% |
| False positives | 0 |
| Invalid repros | 0 |
| Duplicate reports | 0 |
| Severity agreement | 50% |

## Seeded bugs

| Bug | Category | Severity | Found by |
| --- | --- | --- | --- |
| `cancel-does-not-restock` | inventory | high | #8 |
| `cancel-twice-allowed` | state | medium | #2 |
| `discount-exceeds-subtotal` | calculation | high | **missed** |
| `events-pagination-overlap` | functional | medium | #6 |
| `not-found-error-contract` | contract | low | **missed** |
| `order-idor` | security | critical | #1 |
| `order-quantity-upper-bound` | validation | medium | #4 |
| `oversell-by-one` | inventory | high | #7 |
| `promo-percent-rounding` | calculation | low | #5 |
| `welcome-promo-reuse` | business-rule | high | #3 |

## Findings

| # | Verdict | Severity | Title | Demonstrates |
| --- | --- | --- | --- | --- |
| 1 | confirmed | critical | Fan can read another user's order via GET /orders/{id} | `order-idor` |
| 2 | confirmed | medium | Cancelling an already-cancelled order returns 200 instead of 409 already_cancelled | `cancel-twice-allowed` |
| 3 | confirmed | high | WELCOME5 promo can be redeemed more than once by the same user | `welcome-promo-reuse` |
| 4 | confirmed | high | Order quantity of 7 accepted; maximum is 6 | `order-quantity-upper-bound` |
| 5 | confirmed | medium | FAN10 discount rounds half-cent down instead of up (24995 cents gives 2499 instead of 2500) | `promo-percent-rounding` |
| 6 | confirmed | high | Pagination overlaps: each page after the first repeats the last event of the previous page | `events-pagination-overlap` |
| 7 | confirmed | critical | Orders are accepted beyond event capacity (sold_out check missing), driving remaining negative | `oversell-by-one` |
| 8 | confirmed | high | Cancelling an order does not restore the event's remaining tickets | `cancel-does-not-restock` |

## Agent summary

I tested the Matchday Tickets API against the specification and filed eight defects, each reproduced on a fresh instance. The most serious are the ownership leak and the overselling.

**Defects reported**

1. **Critical, security:** Any fan can read another user's order. Bob got a 200 with alice's full order from `GET /orders/{id}`; the spec requires 404.
2. **Critical, inventory:** Orders are accepted beyond capacity. Event 11 (capacity 5) accepted an order for 6, and `remaining` went to -1. The sold-out check is missing.
3. **High, inventory:** Cancelling an order does not restore `remaining`. Event 1 lost 2 seats permanently after an order of 2 was cancelled.
4. **High, business rule:** WELCOME5 can be redeemed repeatedly by the same user. Alice got a discount on two orders, when the spec allows one redemption per user.
5. **High, validation:** Quantity 7 is accepted. The spec caps quantity at 6 with `invalid_quantity`.
6. **High, functional:** Pagination overlaps. Page 2 repeats the last event of page 1 (with pageSize 5, event 5 appears on both pages).
7. **Medium, state:** Cancelling an already-cancelled order returns 200 instead of 409 `already_cancelled`.
8. **Medium, calculation:** FAN10 rounds halves down. 4999 × 5 = 24995, and 10% is 2499.5, which should round up to 2500. The API gives 2499.

**Checked and working as specified:** login success and failure, missing and bogus tokens, unknown routes, page and pageSize bounds, quantity 0 and non-integer quantity, unknown or case-mismatched promo codes, unknown events, non-integer path IDs, extra body fields, wrong-type promo codes, sold-out when remaining is already negative, the 404 on a fan cancelling someone else's order, and admin access to an order.

**Not fully covered:** I did not test admin cancelling another user's order, or pagination past the last page. The per-order `remaining` restoration issue (defect 3) also affects any test that relies on capacity, so later inventory results are unreliable until it is fixed.
