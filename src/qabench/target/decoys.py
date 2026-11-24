"""Decoy registry - behaviour that looks like a defect but is what the spec requires.

Decoys stress precision. Each one is the mirror image of a seeded bug: the clean build
does what the spec says, and a *flipped* build (``create_app(flip_decoys={id})``) does
what a careless tester would expect instead. A false positive whose repro behaves
differently on a flipped build is attributed to that decoy, so the scorecard can say
which trap the agent fell into, not only that it reported something wrong.

``tests/test_decoys.py`` checks that each trap repro is a false positive on every bug
build, and that it diverges on its own flipped build and on no other.
"""

from __future__ import annotations

from dataclasses import dataclass

from qabench.repro import ReproStep
from qabench.target._steps import auth, login, order


@dataclass(frozen=True)
class Decoy:
    id: str
    title: str
    spec_rule: str
    naive_expectation: str
    trap_repro: tuple[ReproStep, ...]


_DECOY_LIST: tuple[Decoy, ...] = (
    Decoy(
        id="earlier-tokens-stay-valid",
        title="An older token still works after the user logs in again",
        spec_rule="Every login issues a new token; earlier tokens of the same user remain valid.",
        naive_expectation="A new login invalidates the user's earlier tokens.",
        trap_repro=(
            login("alice", "t1"),
            login("alice", "t2"),
            ReproStep(method="GET", path="/orders", headers=auth("t1")),
        ),
    ),
    Decoy(
        id="promo-codes-case-sensitive",
        title="A lower-case promo code is rejected",
        spec_rule="Codes are case-sensitive: fan10 is not FAN10.",
        naive_expectation="Promo codes match case-insensitively.",
        trap_repro=(
            login("alice"),
            order({"eventId": 2, "quantity": 1, "promoCode": "fan10"}),
        ),
    ),
    Decoy(
        id="admin-reads-any-order",
        title="An admin can read any fan's order",
        spec_rule="GET /orders/{id} - the order if the caller owns it or is an admin.",
        naive_expectation="Nobody but the owner can read an order.",
        trap_repro=(
            login("alice"),
            order({"eventId": 2, "quantity": 1}, capture={"oid": "id"}),
            login("admin", "atok"),
            ReproStep(method="GET", path="/orders/{{oid}}", headers=auth("atok")),
        ),
    ),
    Decoy(
        id="foreign-order-is-404",
        title="Touching another user's order returns 404, not 403",
        spec_rule="Otherwise 404 code not_found (never 403, so order IDs are not disclosed).",
        naive_expectation="Access to an order that exists but is not yours returns 403.",
        trap_repro=(
            login("alice"),
            order({"eventId": 2, "quantity": 1}, capture={"oid": "id"}),
            login("bob", "btok"),
            ReproStep(method="POST", path="/orders/{{oid}}/cancel", headers=auth("btok")),
        ),
    ),
    Decoy(
        id="page-past-end-is-empty",
        title="A page after the last one returns 200 with no items",
        spec_rule="A page after the last one returns 200 with an empty items list.",
        naive_expectation="A page that does not exist returns 404.",
        trap_repro=(ReproStep(method="GET", path="/events?page=3&pageSize=10"),),
    ),
    Decoy(
        id="idempotent-replay-returns-200",
        title="Repeating an order with the same Idempotency-Key returns 200, not 201",
        spec_rule="The API returns 200 with that original order as it is now (not 201).",
        naive_expectation="Every successful POST /orders returns 201.",
        trap_repro=(
            login("alice"),
            order({"eventId": 2, "quantity": 1}, key="retry-1"),
            order({"eventId": 2, "quantity": 1}, key="retry-1"),
        ),
    ),
)

DECOYS: dict[str, Decoy] = {decoy.id: decoy for decoy in _DECOY_LIST}
ALL_DECOY_IDS: frozenset[str] = frozenset(DECOYS)
