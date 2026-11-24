"""Matchday Tickets API - the system under test.

``create_app(bugs)`` builds an independent instance with the given seeded defects
switched on. ``create_app()`` with no bugs is the reference ("clean") build that the
oracle trusts; ``tests/test_target_spec.py`` checks it against ``spec.md``.

No ``from __future__ import annotations`` here: FastAPI must resolve the route
annotations at definition time, and ``CurrentUser`` is local to the factory.
"""

from collections.abc import Iterable
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from qabench.target.bugs import ALL_BUG_IDS
from qabench.target.store import Event, Order, Store, User

MAX_QUANTITY = 6
MAX_PAGE_SIZE = 50
FAN10_PERCENT = 10
WELCOME5_CENTS = 500


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


def create_app(bugs: Iterable[str] = ()) -> FastAPI:
    enabled = frozenset(bugs)
    unknown = enabled - ALL_BUG_IDS
    if unknown:
        raise ValueError(f"unknown bug id(s): {sorted(unknown)}")

    def bug(bug_id: str) -> bool:
        return bug_id in enabled

    store = Store.seeded()
    app = FastAPI(title="Matchday Tickets API", version="1.0.0")

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

    def current_user(authorization: Annotated[str | None, Header()] = None) -> User:
        if not authorization or not authorization.startswith("Bearer "):
            raise ApiError(401, "unauthorized", "Missing or malformed Authorization header")
        user_id = store.sessions.get(authorization.removeprefix("Bearer "))
        if user_id is None:
            raise ApiError(401, "unauthorized", "Invalid token")
        return store.users[user_id]

    CurrentUser = Annotated[User, Depends(current_user)]

    @app.post("/auth/login")
    def login(body: LoginBody) -> dict[str, Any]:
        user = store.find_user(body.username)
        if user is None or user.password != body.password:
            raise ApiError(401, "invalid_credentials", "Invalid username or password")
        return {
            "token": store.issue_token(user),
            "user": {"id": user.id, "username": user.username, "role": user.role},
        }

    @app.get("/events")
    def list_events(
        page: int = 1, page_size: Annotated[int, Query(alias="pageSize")] = 10
    ) -> dict[str, Any]:
        if page < 1:
            raise ApiError(400, "validation_error", "page must be >= 1")
        if not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ApiError(400, "validation_error", f"pageSize must be 1..{MAX_PAGE_SIZE}")
        events = sorted(store.events.values(), key=lambda e: e.id)
        offset = (page - 1) * page_size
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

    @app.post("/orders", status_code=201)
    def create_order(body: CreateOrderBody, user: CurrentUser) -> dict[str, Any]:
        max_quantity = MAX_QUANTITY + 1 if bug("order-quantity-upper-bound") else MAX_QUANTITY
        if not 1 <= body.quantity <= max_quantity:
            raise ApiError(400, "invalid_quantity", f"quantity must be 1..{MAX_QUANTITY}")

        event = store.events.get(body.event_id)
        if event is None:
            raise ApiError(404, "not_found", f"Event {body.event_id} not found")

        subtotal = event.price_cents * body.quantity
        discount = 0
        if body.promo_code == "FAN10":
            if bug("promo-percent-rounding"):
                discount = subtotal * FAN10_PERCENT // 100
            else:
                discount = (subtotal * FAN10_PERCENT + 50) // 100
        elif body.promo_code == "WELCOME5":
            if user.id in store.welcome_used_by and not bug("welcome-promo-reuse"):
                raise ApiError(400, "promo_already_used", "WELCOME5 can be used once per user")
            if bug("discount-exceeds-subtotal"):
                discount = WELCOME5_CENTS
            else:
                discount = min(WELCOME5_CENTS, subtotal)
        elif body.promo_code is not None:
            raise ApiError(400, "invalid_promo_code", f"Unknown promo code {body.promo_code!r}")

        allowed = event.remaining + 1 if bug("oversell-by-one") else event.remaining
        if body.quantity > allowed:
            raise ApiError(409, "sold_out", f"Only {event.remaining} tickets remaining")

        if body.promo_code == "WELCOME5":
            store.welcome_used_by.add(user.id)
        event.remaining -= body.quantity
        order = Order(
            id=store.next_order_id(),
            event_id=event.id,
            user_id=user.id,
            quantity=body.quantity,
            unit_price_cents=event.price_cents,
            discount_cents=discount,
            total_cents=subtotal - discount,
            promo_code=body.promo_code,
            status="confirmed",
        )
        store.orders[order.id] = order
        return _order_json(order)

    @app.get("/orders")
    def list_orders(user: CurrentUser) -> dict[str, Any]:
        visible = [o for o in store.orders.values() if user.role == "admin" or o.user_id == user.id]
        return {"items": [_order_json(o) for o in sorted(visible, key=lambda o: o.id)]}

    @app.get("/orders/{order_id}")
    def get_order(order_id: int, user: CurrentUser) -> dict[str, Any]:
        order = store.orders.get(order_id)
        can_see = order is not None and (
            bug("order-idor") or user.role == "admin" or order.user_id == user.id
        )
        if order is None or not can_see:
            raise ApiError(404, "not_found", f"Order {order_id} not found")
        return _order_json(order)

    @app.post("/orders/{order_id}/cancel")
    def cancel_order(order_id: int, user: CurrentUser) -> dict[str, Any]:
        order = store.orders.get(order_id)
        if order is None or (user.role != "admin" and order.user_id != user.id):
            raise ApiError(404, "not_found", f"Order {order_id} not found")
        if order.status == "cancelled" and not bug("cancel-twice-allowed"):
            raise ApiError(409, "already_cancelled", f"Order {order_id} is already cancelled")
        order.status = "cancelled"
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
    }


def _order_json(order: Order) -> dict[str, Any]:
    return {
        "id": order.id,
        "eventId": order.event_id,
        "userId": order.user_id,
        "quantity": order.quantity,
        "unitPriceCents": order.unit_price_cents,
        "discountCents": order.discount_cents,
        "totalCents": order.total_cents,
        "promoCode": order.promo_code,
        "status": order.status,
    }
