"""Matchday Tickets API - the system under test.

``create_app(bugs)`` builds an independent instance with the given seeded defects
switched on. ``create_app()`` with no bugs is the reference ("clean") build that the
oracle trusts; ``tests/test_target_spec.py`` checks it against ``spec.md``.

``flip_decoys`` replaces a decoy (behaviour the spec requires but a careless tester
might call a bug) with what that tester expects. The scorer uses flipped builds to tell
which decoy a false positive fell for; they are never served to an agent.

No ``from __future__ import annotations`` here: FastAPI must resolve the route
annotations at definition time, and ``CurrentUser`` is local to the factory.
"""

from collections.abc import Iterable
from typing import Annotated, Any, Self

from fastapi import Depends, FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

from qabench.target.bugs import ALL_BUG_IDS
from qabench.target.decoys import ALL_DECOY_IDS
from qabench.target.store import Event, IdempotentRequest, Order, Store, User

MAX_QUANTITY = 6
MAX_TICKETS_PER_USER_EVENT = 8
MAX_PAGE_SIZE = 50
FAN10_PERCENT = 10
WELCOME5_CENTS = 500
FEE_PER_TICKET_CENTS = 150
FEE_CAP_CENTS = 600
PROMO_CODES = ("FAN10", "WELCOME5")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    username: str
    password: str


class CreateOrderBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)

    event_id: int = Field(alias="eventId")
    quantity: int
    promo_code: str | None = Field(default=None, alias="promoCode")

    def fingerprint(self) -> tuple[int, int, str | None]:
        return (self.event_id, self.quantity, self.promo_code)


class UpdateEventBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)

    price_cents: int | None = Field(default=None, alias="priceCents", ge=0)
    capacity: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _at_least_one_field(self) -> Self:
        if self.price_cents is None and self.capacity is None:
            raise ValueError("send priceCents and/or capacity")
        return self


def create_app(bugs: Iterable[str] = (), *, flip_decoys: Iterable[str] = ()) -> FastAPI:
    enabled = frozenset(bugs)
    flipped = frozenset(flip_decoys)
    unknown = (enabled - ALL_BUG_IDS) | (flipped - ALL_DECOY_IDS)
    if unknown:
        raise ValueError(f"unknown bug or decoy id(s): {sorted(unknown)}")

    def bug(bug_id: str) -> bool:
        return bug_id in enabled

    def flip(decoy_id: str) -> bool:
        return decoy_id in flipped

    store = Store.seeded()
    app = FastAPI(title="Matchday Tickets API", version="2.0.0")

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return _error(exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
        return _error(400, "validation_error", f"{where}: {first.get('msg', 'invalid input')}")

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "not_found" if exc.status_code == 404 else "http_error"
        return _error(exc.status_code, code, str(exc.detail))

    def bearer_token(authorization: Annotated[str | None, Header()] = None) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            raise ApiError(401, "unauthorized", "Missing or malformed Authorization header")
        token = authorization.removeprefix("Bearer ")
        if token not in store.sessions:
            raise ApiError(401, "unauthorized", "Invalid token")
        return token

    Token = Annotated[str, Depends(bearer_token)]

    def current_user(token: Token) -> User:
        return store.users[store.sessions[token]]

    CurrentUser = Annotated[User, Depends(current_user)]

    def admin_user(user: CurrentUser) -> User:
        if user.role != "admin" and not bug("fan-can-update-event"):
            raise ApiError(403, "forbidden", "Admin role required")
        return user

    def foreign_order(order_id: int) -> ApiError:
        if flip("foreign-order-is-404"):
            return ApiError(403, "forbidden", f"Order {order_id} belongs to another user")
        return ApiError(404, "not_found", f"Order {order_id} not found")

    @app.post("/auth/login")
    def login(body: LoginBody) -> dict[str, Any]:
        user = store.find_user(body.username)
        if user is None or user.password != body.password:
            raise ApiError(401, "invalid_credentials", "Invalid username or password")
        if flip("earlier-tokens-stay-valid"):
            for old in store.tokens_of(user.id):
                store.revoke(old)
        return {
            "token": store.issue_token(user),
            "user": {"id": user.id, "username": user.username, "role": user.role},
        }

    @app.post("/auth/logout", status_code=204)
    def logout(token: Token, user: CurrentUser) -> Response:
        if bug("logout-revokes-wrong-session"):
            token = store.tokens_of(user.id)[-1]
        store.revoke(token)
        return Response(status_code=204)

    @app.get("/events")
    def list_events(
        page: int = 1, page_size: Annotated[int, Query(alias="pageSize")] = 10
    ) -> dict[str, Any]:
        if page < 1:
            raise ApiError(400, "validation_error", "page must be >= 1")
        if not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ApiError(400, "validation_error", f"pageSize must be 1..{MAX_PAGE_SIZE}")
        events = sorted(store.events.values(), key=lambda e: e.id)
        if bug("sold-out-events-hidden"):
            events = [e for e in events if e.remaining > 0]
        offset = (page - 1) * page_size
        if flip("page-past-end-is-empty") and page > 1 and offset >= len(events):
            raise ApiError(404, "not_found", f"Page {page} does not exist")
        if bug("events-pagination-overlap") and page > 1:
            offset -= 1
        return {
            "items": [_event_json(e) for e in events[offset : offset + page_size]],
            "page": page,
            "pageSize": page_size,
            "total": len(events),
        }

    @app.get("/events/{event_id}", response_model=None)
    def get_event(event_id: int) -> dict[str, Any] | JSONResponse:
        event = store.events.get(event_id)
        if event is None:
            if bug("not-found-error-contract"):
                return JSONResponse(status_code=404, content={"detail": "Not Found"})
            raise ApiError(404, "not_found", f"Event {event_id} not found")
        return _event_json(event)

    @app.patch("/events/{event_id}")
    def update_event(
        event_id: int, body: UpdateEventBody, _: Annotated[User, Depends(admin_user)]
    ) -> dict[str, Any]:
        event = store.events.get(event_id)
        if event is None:
            raise ApiError(404, "not_found", f"Event {event_id} not found")
        if body.capacity is not None:
            sold = event.capacity - event.remaining
            if body.capacity < sold:
                raise ApiError(409, "capacity_below_sold", f"{sold} tickets are already sold")
            event.capacity, event.remaining = body.capacity, body.capacity - sold
        if body.price_cents is not None:
            event.price_cents = body.price_cents
            if bug("order-price-not-snapshotted"):
                for order in store.orders.values():
                    if order.event_id == event.id:
                        subtotal = event.price_cents * order.quantity
                        order.unit_price_cents = event.price_cents
                        order.total_cents = subtotal - order.discount_cents + order.fee_cents
        return _event_json(event)

    @app.post("/orders", status_code=201)
    def create_order(
        body: CreateOrderBody,
        user: CurrentUser,
        response: Response,
        idempotency_key: Annotated[str | None, Header(min_length=1, max_length=64)] = None,
    ) -> dict[str, Any]:
        if idempotency_key is not None:
            scope = None if bug("idempotency-key-not-user-scoped") else user.id
            seen = store.idempotency.get((scope, idempotency_key))
            if seen is not None:
                if seen.fingerprint != body.fingerprint():
                    raise ApiError(
                        409, "idempotency_conflict", "Idempotency-Key reused with another body"
                    )
                original = store.orders[seen.order_id]
                if bug("idempotent-replay-reserves-again"):
                    store.events[original.event_id].remaining -= original.quantity
                if not flip("idempotent-replay-returns-200"):
                    response.status_code = 200
                return _order_json(original)

        max_quantity = MAX_QUANTITY + 1 if bug("order-quantity-upper-bound") else MAX_QUANTITY
        if not 1 <= body.quantity <= max_quantity:
            raise ApiError(400, "invalid_quantity", f"quantity must be 1..{MAX_QUANTITY}")

        event = store.events.get(body.event_id)
        if event is None:
            raise ApiError(404, "not_found", f"Event {body.event_id} not found")

        bypass = bug("closed-sales-bypass-with-promo") and body.promo_code is not None
        if not event.sales_open and not bypass:
            raise ApiError(409, "sales_closed", f"Sales for event {event.id} are closed")

        promo = body.promo_code
        if promo is not None and flip("promo-codes-case-sensitive"):
            promo = promo.upper()
        subtotal = event.price_cents * body.quantity
        discount = 0
        if promo == "FAN10":
            if bug("promo-percent-rounding"):
                discount = subtotal * FAN10_PERCENT // 100
            else:
                discount = (subtotal * FAN10_PERCENT + 50) // 100
        elif promo == "WELCOME5":
            if user.id in store.welcome_used_by and not bug("welcome-promo-reuse"):
                raise ApiError(400, "promo_already_used", "WELCOME5 can be used once per user")
            if bug("discount-exceeds-subtotal"):
                discount = WELCOME5_CENTS
            else:
                discount = min(WELCOME5_CENTS, subtotal)
        elif promo is not None:
            raise ApiError(400, "invalid_promo_code", f"Unknown promo code {promo!r}")

        held = sum(
            o.quantity
            for o in store.orders.values()
            if o.user_id == user.id
            and o.event_id == event.id
            and (o.status == "confirmed" or bug("ticket-limit-counts-cancelled"))
        )
        if held + body.quantity > MAX_TICKETS_PER_USER_EVENT:
            raise ApiError(
                409,
                "ticket_limit_exceeded",
                f"At most {MAX_TICKETS_PER_USER_EVENT} tickets per user per event",
            )

        allowed = event.remaining + 1 if bug("oversell-by-one") else event.remaining
        if body.quantity > allowed:
            raise ApiError(409, "sold_out", f"Only {event.remaining} tickets remaining")

        fee = FEE_PER_TICKET_CENTS * body.quantity
        if not bug("fee-cap-ignored"):
            fee = min(fee, FEE_CAP_CENTS)
        if promo == "WELCOME5":
            store.welcome_used_by.add(user.id)
        event.remaining -= body.quantity
        order = Order(
            id=store.next_order_id(),
            event_id=event.id,
            user_id=user.id,
            quantity=body.quantity,
            unit_price_cents=event.price_cents,
            discount_cents=discount,
            fee_cents=fee,
            total_cents=subtotal - discount + fee,
            promo_code=promo,
            status="confirmed",
        )
        store.orders[order.id] = order
        if idempotency_key is not None:
            scope = None if bug("idempotency-key-not-user-scoped") else user.id
            store.idempotency[(scope, idempotency_key)] = IdempotentRequest(
                order.id, body.fingerprint()
            )
        return _order_json(order)

    def can_read(order: Order, user: User) -> bool:
        is_admin = user.role == "admin" and not flip("admin-reads-any-order")
        return is_admin or order.user_id == user.id

    @app.get("/orders")
    def list_orders(user: CurrentUser) -> dict[str, Any]:
        visible = [o for o in store.orders.values() if can_read(o, user)]
        return {"items": [_order_json(o) for o in sorted(visible, key=lambda o: o.id)]}

    @app.get("/orders/{order_id}")
    def get_order(order_id: int, user: CurrentUser) -> dict[str, Any]:
        order = store.orders.get(order_id)
        if order is None:
            raise ApiError(404, "not_found", f"Order {order_id} not found")
        if not (bug("order-idor") or can_read(order, user)):
            raise foreign_order(order_id)
        return _order_json(order)

    @app.post("/orders/{order_id}/cancel")
    def cancel_order(order_id: int, user: CurrentUser) -> dict[str, Any]:
        order = store.orders.get(order_id)
        if order is None:
            raise ApiError(404, "not_found", f"Order {order_id} not found")
        if user.role != "admin" and order.user_id != user.id:
            raise foreign_order(order_id)
        if order.status == "cancelled" and not bug("cancel-twice-allowed"):
            raise ApiError(409, "already_cancelled", f"Order {order_id} is already cancelled")
        order.status = "cancelled"
        if bug("refund-ignores-discount"):
            order.refund_cents = order.unit_price_cents * order.quantity
        else:
            order.refund_cents = order.total_cents - order.fee_cents
        if not bug("cancel-does-not-restock"):
            store.events[order.event_id].remaining += order.quantity
        return _order_json(order)

    return app


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def _event_json(event: Event) -> dict[str, Any]:
    return {
        "id": event.id,
        "name": event.name,
        "venue": event.venue,
        "startsAt": event.starts_at,
        "priceCents": event.price_cents,
        "capacity": event.capacity,
        "remaining": event.remaining,
        "salesOpen": event.sales_open,
    }


def _order_json(order: Order) -> dict[str, Any]:
    return {
        "id": order.id,
        "eventId": order.event_id,
        "userId": order.user_id,
        "quantity": order.quantity,
        "unitPriceCents": order.unit_price_cents,
        "discountCents": order.discount_cents,
        "feeCents": order.fee_cents,
        "totalCents": order.total_cents,
        "promoCode": order.promo_code,
        "status": order.status,
        "refundCents": order.refund_cents,
    }
