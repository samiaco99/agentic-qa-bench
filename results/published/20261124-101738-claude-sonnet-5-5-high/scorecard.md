# QA agent scorecard

- **Model:** `claude-sonnet-5-5` (effort `high`), served by claude-sonnet-5-5
- **Session:** 12 turns, 57 tool calls, 80.5s, stopped on `end_turn`
- **Tokens:** 26 in, 12,736 out, 134,942 cache read, 27,861 cache write
- **Estimated cost:** $0.22

| Metric | Value |
| --- | --- |
| Recall (seeded bugs found) | 10/10 (100%) |
| Precision (confirmed findings) | 10/10 (100%) |
| F1 | 100% |
| False positives | 0 |
| Invalid repros | 0 |
| Duplicate reports | 0 |
| Severity agreement | 80% |

## Seeded bugs

| Bug | Category | Severity | Found by |
| --- | --- | --- | --- |
| `cancel-does-not-restock` | inventory | high | #9 |
| `cancel-twice-allowed` | state | medium | #10 |
| `discount-exceeds-subtotal` | calculation | high | #6 |
| `events-pagination-overlap` | functional | medium | #2 |
| `not-found-error-contract` | contract | low | #1 |
| `order-idor` | security | critical | #8 |
| `order-quantity-upper-bound` | validation | medium | #3 |
| `oversell-by-one` | inventory | high | #4 |
| `promo-percent-rounding` | calculation | low | #5 |
| `welcome-promo-reuse` | business-rule | high | #7 |

## Findings

| # | Verdict | Severity | Title | Demonstrates |
| --- | --- | --- | --- | --- |
| 1 | confirmed | low | GET /events/{id} for a missing event returns non-conforming error body | `not-found-error-contract` |
| 2 | confirmed | medium | Pagination pages overlap (offset off by one) | `events-pagination-overlap` |
| 3 | confirmed | high | Quantity above 6 is accepted when creating an order | `order-quantity-upper-bound` |
| 4 | confirmed | high | Order can oversell: quantity exceeding remaining by one is accepted, remaining goes negative | `oversell-by-one` |
| 5 | confirmed | high | FAN10 discount is truncated instead of rounded to nearest cent (halves up) | `promo-percent-rounding` |
| 6 | confirmed | high | WELCOME5 discount exceeds subtotal, producing negative total | `discount-exceeds-subtotal` |
| 7 | confirmed | high | WELCOME5 can be redeemed again after cancelling the order that used it | `welcome-promo-reuse` |
| 8 | confirmed | critical | Any fan can read another user's order (broken object-level authorization) | `order-idor` |
| 9 | confirmed | high | Cancelling an order does not restore event remaining | `cancel-does-not-restock` |
| 10 | confirmed | medium | Cancelling an already-cancelled order returns 200 instead of 409 already_cancelled | `cancel-twice-allowed` |

## Agent summary

I tested events, orders, promo codes, cancellation, authentication and the error contract, and filed 10 defects. All 10 reproduced on a fresh instance.

**Defects found**
1. **Missing event error shape (low):** `GET /events/99` returns `{"detail":"Not Found"}` instead of the standard error body. Unknown routes like `/nope` are correct.
2. **Pagination overlap (medium):** with `pageSize=5`, page 2 starts at id 5, which page 1 already returned, so pages are not disjoint.
3. **Quantity above 6 accepted (high):** an order for quantity 7 returns 201 instead of 400 `invalid_quantity`.
4. **Oversell (high):** ordering 6 tickets for event 11, which has 5 remaining, returns 201 and leaves `remaining` at -1.
5. **FAN10 rounding (high):** the discount is rounded down instead of to the nearest cent, halves up. A 1,299 subtotal gives 129 instead of 130, and 6,495 gives 649 instead of 650.
6. **WELCOME5 negative total (high):** on a 300-cent ticket the discount is 500 and the total is -200, instead of a discount capped at 300 and a total of 0.
7. **WELCOME5 reusable after cancel (high):** a user can redeem it again after cancelling the order that used it, instead of getting 400 `promo_already_used`.
8. **Order read across users (critical):** bob can read alice's order with `GET /orders/{id}` and gets 200 instead of 404.
9. **Cancel doesn't restore inventory (high):** cancelling an order leaves the event's `remaining` unchanged.
10. **Second cancel returns 200 (medium):** cancelling an already-cancelled order returns 200 instead of 409 `already_cancelled`.

**Checked and behaving as specified**
- Login success and failure, and the 401 `unauthorized` response for a missing or bad token.
- Page and `pageSize` bounds, and non-integer query and path parameters.
- Rejection of extra fields and string quantities.
- Rule order for 400 `invalid_quantity`, 404 for an unknown event, and 400 `invalid_promo_code`.
- Case-sensitive promo codes.
- Fans see only their own orders in `GET /orders`, and admins see all.
- Non-owners get 404 on cancel.
- Admins can cancel other users' orders.
