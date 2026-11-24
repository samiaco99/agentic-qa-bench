# Matchday Tickets API — Product Specification v1.0

Matchday Tickets sells tickets for sports events. This document is the source of truth for
expected behaviour. Anything not stated here is unspecified and is not a defect.

## Conventions

- All request and response bodies are JSON. Money is always an integer number of cents.
- Field names in requests and responses are camelCase.
- Every error response has the status code listed below and this body shape:
  `{"error": {"code": "<machine_code>", "message": "<human text>"}}`.
  This applies to every endpoint, including unknown routes (404, code `not_found`).
- Malformed input (missing/extra fields, wrong JSON types, non-integer path or query
  parameters) returns `400` with code `validation_error`. Numbers must be JSON integers;
  strings such as `"2"` are rejected.

## Authentication

`POST /auth/login` with `{"username": string, "password": string}`.

- Valid credentials: `200` with `{"token": string, "user": {"id", "username", "role"}}`.
- Invalid credentials: `401`, code `invalid_credentials`.

Seeded accounts:

| username | password     | role  |
| -------- | ------------ | ----- |
| alice    | alice-pass   | fan   |
| bob      | bob-pass     | fan   |
| admin    | admin-pass   | admin |

Protected endpoints require `Authorization: Bearer <token>`. A missing, malformed, or
unknown token returns `401`, code `unauthorized`. Every login issues a new token; earlier
tokens remain valid.

## Events

Event fields: `id`, `name`, `venue`, `startsAt` (ISO-8601 UTC), `priceCents`, `capacity`,
`remaining` (tickets still available).

`GET /events?page=<int>&pageSize=<int>` — public.

- `page` defaults to 1 and must be >= 1. `pageSize` defaults to 10 and must be 1..50.
  Out-of-range values return `400`, code `validation_error`.
- Events are ordered by `id` ascending. Response:
  `{"items": [Event], "page": int, "pageSize": int, "total": int}` where `total` is the
  number of events across all pages.
- Pages are disjoint and contiguous: concatenating pages 1..n yields every event exactly
  once, in order.

`GET /events/{id}` — public. `200` with the event, or `404` code `not_found`.

## Orders

Order fields: `id`, `eventId`, `userId`, `quantity`, `unitPriceCents`, `discountCents`,
`totalCents`, `promoCode` (string or null), `status` (`confirmed` | `cancelled`).

### Create — `POST /orders` (authenticated)

Body: `{"eventId": int, "quantity": int, "promoCode"?: string | null}`.

Rules, evaluated in this order:

1. `quantity` must be between 1 and 6 inclusive, otherwise `400` code `invalid_quantity`.
2. The event must exist, otherwise `404` code `not_found`.
3. `promoCode`, when present and not null, must be a known code (case-sensitive),
   otherwise `400` code `invalid_promo_code`. Known codes:
   - `FAN10` — 10% off the subtotal, rounded to the nearest cent, halves rounded up.
     Unlimited use.
   - `WELCOME5` — 500 cents off. Each user can redeem it **once** in total (a later
     cancellation does not give it back). A second redemption returns `400` code
     `promo_already_used`.
4. `quantity` must not exceed the event's `remaining`, otherwise `409` code `sold_out`.

Pricing: `subtotal = unitPriceCents * quantity`. `discountCents` never exceeds the
subtotal, so `totalCents = subtotal - discountCents` is never negative.

On success: `201` with the order (`status: "confirmed"`), and the event's `remaining`
decreases by `quantity`. `remaining` can never go below 0.

### Read

- `GET /orders` (authenticated) — `{"items": [Order]}` ordered by `id`. Fans see only their
  own orders; admins see all orders.
- `GET /orders/{id}` (authenticated) — the order if the caller owns it or is an admin.
  Otherwise `404` code `not_found` (never `403`, so order IDs are not disclosed).

### Cancel — `POST /orders/{id}/cancel` (authenticated)

- Allowed for the order's owner or an admin; anyone else gets `404` code `not_found`.
- A confirmed order becomes `cancelled`, the response is `200` with the updated order,
  and the event's `remaining` increases by the order's `quantity`.
- Cancelling an order that is already cancelled returns `409` code `already_cancelled` and
  changes nothing.
