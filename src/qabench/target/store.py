"""Deterministic in-memory state for the target app.

Every app instance starts from the same seed, IDs are sequential and tokens are derived
from a counter. Replaying the same steps on two instances therefore yields identical
responses unless a seeded bug changes the behaviour - which is what makes the
differential oracle possible.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Literal

Role = Literal["fan", "admin"]
OrderStatus = Literal["confirmed", "cancelled"]


@dataclass
class User:
    id: int
    username: str
    password: str
    role: Role


@dataclass
class Event:
    id: int
    name: str
    venue: str
    starts_at: str
    price_cents: int
    capacity: int
    remaining: int
    sales_open: bool = True


@dataclass
class Order:
    id: int
    event_id: int
    user_id: int
    quantity: int
    unit_price_cents: int
    discount_cents: int
    fee_cents: int
    total_cents: int
    promo_code: str | None
    status: OrderStatus
    refund_cents: int | None = None


@dataclass(frozen=True)
class IdempotentRequest:
    """What an ``Idempotency-Key`` was first used for: the order and the request body."""

    order_id: int
    fingerprint: tuple[int, int, str | None]


_SEED_USERS = (
    User(1, "alice", "alice-pass", "fan"),
    User(2, "bob", "bob-pass", "fan"),
    User(3, "admin", "admin-pass", "admin"),
)

# (name, venue, starts_at, price_cents, capacity)
_SEED_EVENTS = (
    ("Milano Lions vs Torino Bulls", "Stadio Nord, Milano", "2026-12-06T19:45:00Z", 4999, 500),
    ("Napoli Waves vs Roma Wolves", "Arena Sud, Napoli", "2026-12-13T17:00:00Z", 7500, 300),
    ("Youth Cup Final", "Centro Sportivo Comunale, Bologna", "2026-12-20T10:30:00Z", 300, 200),
    (
        "Continental Night: Lions vs Porto Anchors",
        "Stadio Nord, Milano",
        "2027-01-14T20:00:00Z",
        12000,
        150,
    ),
    (
        "Women's League: Roma Wolves vs Firenze Lilies",
        "Campo Tre Fontane, Roma",
        "2027-01-17T14:30:00Z",
        1500,
        100,
    ),
    ("Legends Charity Match", "Arena Sud, Napoli", "2027-01-24T18:00:00Z", 2550, 250),
    (
        "Basketball: Milano Giants vs Bologna Towers",
        "Forum, Assago",
        "2027-02-02T20:30:00Z",
        3500,
        120,
    ),
    ("Volleyball Super Cup", "PalaModena, Modena", "2027-02-09T18:00:00Z", 2000, 80),
    ("Rugby Six Cities: Roma vs Lyon", "Stadio Flaminio, Roma", "2027-02-21T15:00:00Z", 5500, 400),
    ("Motor Fan Day", "Circuito delle Colline, Scarperia", "2027-03-07T09:00:00Z", 6000, 60),
    ("Closed-Door Training Session", "Training Ground, Carnago", "2027-03-11T11:00:00Z", 9900, 5),
    ("Esports Finals", "Arena Digitale, Milano", "2027-03-20T16:00:00Z", 1299, 90),
    (
        "Season Finale: Milano Lions vs Roma Wolves",
        "Stadio Nord, Milano",
        "2027-05-23T18:00:00Z",
        8500,
        600,
    ),
)
_SALES_CLOSED_EVENT_IDS = frozenset({13})


@dataclass
class Store:
    users: dict[int, User] = field(default_factory=dict)
    events: dict[int, Event] = field(default_factory=dict)
    orders: dict[int, Order] = field(default_factory=dict)
    sessions: dict[str, int] = field(default_factory=dict)
    welcome_used_by: set[int] = field(default_factory=set)
    # (user id, key) -> first use. The user id is None when keys are (wrongly) global.
    idempotency: dict[tuple[int | None, str], IdempotentRequest] = field(default_factory=dict)
    _next_order_id: int = 1
    _token_counter: int = 0

    @classmethod
    def seeded(cls) -> Store:
        store = cls()
        for user in _SEED_USERS:
            store.users[user.id] = User(user.id, user.username, user.password, user.role)
        for index, (name, venue, starts_at, price, capacity) in enumerate(_SEED_EVENTS, 1):
            store.events[index] = Event(
                index,
                name,
                venue,
                starts_at,
                price,
                capacity,
                capacity,
                sales_open=index not in _SALES_CLOSED_EVENT_IDS,
            )
        return store

    def find_user(self, username: str) -> User | None:
        return next((u for u in self.users.values() if u.username == username), None)

    def issue_token(self, user: User) -> str:
        self._token_counter += 1
        digest = hashlib.sha256(f"qabench:{self._token_counter}:{user.username}".encode())
        token = digest.hexdigest()[:32]
        self.sessions[token] = user.id
        return token

    def tokens_of(self, user_id: int) -> list[str]:
        """The user's valid tokens, oldest first."""
        return [token for token, owner in self.sessions.items() if owner == user_id]

    def revoke(self, token: str) -> None:
        self.sessions.pop(token, None)

    def next_order_id(self) -> int:
        order_id = self._next_order_id
        self._next_order_id += 1
        return order_id
