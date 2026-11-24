# QA agent scorecard

- **Model:** `claude-opus-5-5` (effort `high`), served by claude-opus-5-5
- **Session:** 26 turns, 88 tool calls, 188.9s, stopped on `end_turn`
- **Tokens:** 54 in, 17,377 out, 445,007 cache read, 37,331 cache write
- **Estimated cost:** $0.62

| Metric | Value |
| --- | --- |
| Recall (seeded bugs found) | 10/10 (100%) |
| Precision (confirmed findings) | 10/10 (100%) |
| F1 | 100% |
| False positives | 0 |
| Invalid repros | 0 |
| Duplicate reports | 0 |
| Severity agreement | 90% |

## Seeded bugs

| Bug | Category | Severity | Found by |
| --- | --- | --- | --- |
| `cancel-does-not-restock` | inventory | high | #9 |
| `cancel-twice-allowed` | state | medium | #10 |
| `discount-exceeds-subtotal` | calculation | high | #5 |
| `events-pagination-overlap` | functional | medium | #2 |
| `not-found-error-contract` | contract | low | #3 |
| `order-idor` | security | critical | #6 |
| `order-quantity-upper-bound` | validation | medium | #7 |
| `oversell-by-one` | inventory | high | #8 |
| `promo-percent-rounding` | calculation | low | #4 |
| `welcome-promo-reuse` | business-rule | high | #1 |

## Findings

| # | Verdict | Severity | Title | Demonstrates |
| --- | --- | --- | --- | --- |
| 1 | confirmed | high | WELCOME5 promo can be redeemed multiple times by the same user | `welcome-promo-reuse` |
| 2 | confirmed | medium | Event pagination overlaps: page N repeats the last item of page N-1 and skips one | `events-pagination-overlap` |
| 3 | confirmed | low | GET /events/{id} for unknown id returns non-standard error body {"detail": "Not Found"} | `not-found-error-contract` |
| 4 | confirmed | high | FAN10 discount truncates instead of rounding to nearest cent | `promo-percent-rounding` |
| 5 | confirmed | high | WELCOME5 on a cheap order produces a negative totalCents | `discount-exceeds-subtotal` |
| 6 | confirmed | critical | Fan can read another user's order via GET /orders/{id} (IDOR) | `order-idor` |
| 7 | confirmed | medium | Quantity 7 accepted on order creation (upper bound off by one) | `order-quantity-upper-bound` |
| 8 | confirmed | high | Overselling: order for more than remaining succeeds and remaining goes negative | `oversell-by-one` |
| 9 | confirmed | high | Cancelling an order does not restore the event's remaining tickets | `cancel-does-not-restock` |
| 10 | confirmed | medium | Cancelling an already-cancelled order returns 200 instead of 409 already_cancelled | `cancel-twice-allowed` |

## Agent summary

I tested the whole spec and filed 10 defects. Each one was replayed on a fresh instance and showed the problem there.

**What I tested:** login (good and bad credentials, missing or extra fields, wrong-case username); the bearer-token rules (missing, malformed or unknown token, and old tokens staying valid after a new login); event paging and its limits; order creation (quantity limits, wrong types, extra fields, the order in which rules are checked, promo codes, pricing and rounding, stock limits); who can read and cancel orders (owner, another fan, admin); cancelling (stock coming back, cancelling twice); and the error body format, including unknown routes and IDs that aren't numbers.

**Defects found:**
1. **Critical – security:** any fan can read another user's order with `GET /orders/{id}` (bob gets alice's full order). The spec says this should return 404.
2. **High – business rule:** `WELCOME5` can be used any number of times by the same user, not once.
3. **High – calculation:** `WELCOME5` on a cheap order gives a negative total (300 − 500 = −200). The discount isn't capped at the subtotal.
4. **High – calculation:** the `FAN10` discount is cut off instead of rounded (1499.7 becomes 1499, 649.5 becomes 649).
5. **High – inventory:** an order can be one ticket larger than what's left, so events oversell and `remaining` goes to −1.
6. **High – inventory:** cancelling an order doesn't give the tickets back to the event, whether the owner or an admin cancels.
7. **Medium – validation:** quantity 7 is accepted; 8 is correctly rejected. The quantity check also runs after the event-exists check, so event 999 with quantity 7 returns 404 instead of `invalid_quantity`.
8. **Medium – state:** cancelling an order that's already cancelled returns 200 instead of 409 `already_cancelled`.
9. **Medium – functional:** event pages overlap. Each page repeats the last event of the page before.
10. **Low – contract:** `GET /events/{id}` for an unknown ID returns `{"detail": "Not Found"}` instead of the standard error body.

**Working as specified:** login and token handling, the other validation errors, fans seeing only their own orders in `GET /orders`, cancel permissions, case-sensitive promo codes, the unknown-promo error coming before the sold-out error, and the 404 body for unknown routes.

**Not tested:** whether a second `WELCOME5` use is rejected before the sold-out check, because the once-per-user limit itself doesn't work.
