# Matchday Tickets API — Product Specification v2.0

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

Protected endpoints require `Authorization: Bearer <token>`. A missing, malformed,
unknown, or revoked token returns `401`, code `unauthorized`.

Every login issues a new token; earlier tokens of the same user remain valid, so a user
can be signed in on several devices at once.

`POST /auth/logout` (authenticated) revokes the token sent with the request and returns
`204` with no body. The user's other tokens stay valid.

## Events

Event fields: `id`, `name`, `venue`, `startsAt` (ISO-8601 UTC), `priceCents`, `capacity`,
`remaining` (tickets still available), `salesOpen` (boolean).

`GET /events?page=<int>&pageSize=<int>` — public.

- `page` defaults to 1 and must be >= 1. `pageSize` defaults to 10 and must be 1..50.
  Out-of-range values return `400`, code `validation_error`.
- Every event is listed, including sold-out events (`remaining: 0`) and events whose sales
  are closed. Events are ordered by `id` ascending. Response:
  `{"items": [Event], "page": int, "pageSize": int, "total": int}` where `total` is the
  number of events across all pages.
- Pages are disjoint and contiguous: concatenating pages 1..n yields every event exactly
  once, in order. A page after the last one returns `200` with an empty `items` list.

`GET /events/{id}` — public. `200` with the event, or `404` code `not_found`.

### Update — `PATCH /events/{id}` (admin only)

Body: `{"priceCents"?: int, "capacity"?: int}` with at least one of the two fields.
`priceCents` must be >= 0 and `capacity` >= 1. Otherwise `400` code `validation_error`.

- An authenticated caller who is not an admin gets `403` code `forbidden`.
- Unknown event: `404` code `not_found`.
- `capacity` cannot go below the tickets already sold (`capacity - remaining`), otherwise
  `409` code `capacity_below_sold`. After a capacity change, `remaining` equals the new
  capacity minus the tickets sold.
- A price change applies to orders created afterwards. Existing orders keep their
  `unitPriceCents`, `discountCents`, `feeCents`, and `totalCents`.
- On success: `200` with the updated event.

## Orders

Order fields: `id`, `eventId`, `userId`, `quantity`, `unitPriceCents`, `discountCents`,
`feeCents`, `totalCents`, `promoCode` (string or null), `status` (`confirmed` |
`cancelled`), `refundCents` (null until the order is cancelled).

### Pricing

- `subtotal = unitPriceCents * quantity`.
- `discountCents` comes from the promo code and never exceeds the subtotal.
- `feeCents` is a service fee of 150 cents per ticket, at most 600 cents per order.
  Promo codes never reduce the fee.
- `totalCents = subtotal - discountCents + feeCents`.

### Create — `POST /orders` (authenticated)

Body: `{"eventId": int, "quantity": int, "promoCode"?: string | null}`.

Rules, evaluated in this order:

1. `quantity` must be between 1 and 6 inclusive, otherwise `400` code `invalid_quantity`.
2. The event must exist, otherwise `404` code `not_found`.
3. The event's sales must be open (`salesOpen: true`), otherwise `409` code
   `sales_closed`.
4. `promoCode`, when present and not null, must be a known code. Codes are
   case-sensitive: `fan10` is not `FAN10`. Unknown codes return `400` code
   `invalid_promo_code`. Known codes:
   - `FAN10` — 10% off the subtotal, rounded to the nearest cent, halves rounded up.
     Unlimited use.
   - `WELCOME5` — 500 cents off the subtotal. Each user can redeem it **once** in total
     (a later cancellation does not give it back). A second redemption returns `400` code
     `promo_already_used`.
5. A user can hold at most 8 tickets per event: the tickets in the user's confirmed orders
   for that event plus `quantity` must not exceed 8, otherwise `409` code
   `ticket_limit_exceeded`. Cancelled orders do not count.
6. `quantity` must not exceed the event's `remaining`, otherwise `409` code `sold_out`.

On success: `201` with the order (`status: "confirmed"`, `refundCents: null`), and the
event's `remaining` decreases by `quantity`. `remaining` can never go below 0.

### Safe retries — `Idempotency-Key`

`POST /orders` accepts an optional `Idempotency-Key` header (1 to 64 characters, otherwise
`400` code `validation_error`), so a client can retry without buying twice.

- Keys are scoped per user: two users can use the same key independently.
- A key is stored only when it creates an order (`201`).
- When a user repeats a key they already used, with the same `eventId`, `quantity`, and
  `promoCode` (an absent `promoCode` equals `null`), the API returns `200` with that
  original order as it is now (not `201`). No rule is evaluated again and nothing
  changes: no new order, no change to `remaining` or to promo usage.
- When a user repeats a key they already used with a different body, the API returns
  `409` code `idempotency_conflict` and nothing changes.

### Read

- `GET /orders` (authenticated) — `{"items": [Order]}` ordered by `id`, cancelled orders
  included. Fans see only their own orders; admins see all orders.
- `GET /orders/{id}` (authenticated) — the order if the caller owns it or is an admin.
  Otherwise `404` code `not_found` (never `403`, so order IDs are not disclosed).

### Cancel — `POST /orders/{id}/cancel` (authenticated)

- Allowed for the order's owner or an admin; anyone else gets `404` code `not_found`.
- A confirmed order becomes `cancelled` and the response is `200` with the updated order.
  The event's `remaining` increases by the order's `quantity`.
- The service fee is non-refundable: `refundCents = totalCents - feeCents`.
- Cancelling an order that is already cancelled returns `409` code `already_cancelled` and
  changes nothing.
