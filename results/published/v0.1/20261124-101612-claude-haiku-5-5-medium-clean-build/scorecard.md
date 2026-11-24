# QA agent scorecard

- **Model:** `claude-haiku-5-5` (effort `medium`), served by claude-haiku-5-5
- **Session:** 14 turns, 86 tool calls, 69.4s, stopped on `end_turn`
- **Tokens:** 30 in, 16,267 out, 209,291 cache read, 25,841 cache write
- **Estimated cost:** $0.01

| Metric | Value |
| --- | --- |
| Recall (seeded bugs found) | 0/0 (n/a) |
| Precision (confirmed findings) | 0/0 (n/a) |
| F1 | n/a |
| False positives | 0 |
| Invalid repros | 0 |
| Duplicate reports | 0 |
| Severity agreement | n/a |

## Seeded bugs

| Bug | Category | Severity | Found by |
| --- | --- | --- | --- |

## Findings

_No findings reported._

## Agent summary

I tested the API against the specification and found no defects that I could reproduce, so I filed no bug reports.

**What I covered**
- **Authentication:** logins for all three seeded accounts; wrong password (401 `invalid_credentials`); missing or malformed bearer header and unknown tokens (401 `unauthorized`); login body validation (missing field and wrong type both return 400 `validation_error`).
- **Events:** list pagination (default values, `page=0`, `pageSize=51`, non-integer and fractional values, page beyond the end, and concatenated pages matching `total`); single event lookup, including a non-integer ID and a missing ID (404).
- **Order creation:** quantity bounds (0 and 7 rejected, 6 accepted); string, float, boolean, and missing quantity all rejected; unknown event (404); unknown, lowercase, whitespace-padded, and empty promo codes rejected; `promoCode: null` accepted; extra fields and a missing body rejected.
- **Pricing:** FAN10 rounding, including 999.8 → 1000 and 779.4 → 779 and 389.7 → 390; WELCOME5 capped at the subtotal (total 0 on a 300-cent ticket).
- **Promo rules:** WELCOME5 rejected on a second use (`promo_already_used`); still rejected after the first order was cancelled; a rejected order does not consume it; rule order is respected (quantity, then event, then promo, then sold-out).
- **Inventory:** `remaining` decreases on purchase and increases on cancellation, including admin cancellation; sold-out at exact capacity (5 of 5, then 0 left); 10 sequential purchases of 6 on a 60-seat event stop exactly at 0 with no overselling.
- **Cancellation and visibility:** owner cancels (200, `cancelled`); double cancel (409 `already_cancelled`); a non-owner gets 404 and never 403; admin can cancel and read any order; fans' order lists contain only their own orders; admin's list contains all orders.

**What I did not cover:** true parallel requests. The tool runs calls one after another, so the overselling test only confirms sequential correctness, not race-condition safety under concurrent load.
