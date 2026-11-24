"""Seeded defect registry - the benchmark's ground truth.

The agent never sees this module. Each bug is a switch in the target app plus a
canonical reproduction that proves the bug is observable through the public API
(``tests/test_seeded_bugs.py`` enforces that, and that bugs do not mask each other).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from qabench.findings import Severity
from qabench.repro import ReproStep


@dataclass(frozen=True)
class SeededBug:
    id: str
    title: str
    category: str
    severity: Severity
    description: str
    canonical_repro: tuple[ReproStep, ...]


def _login(user: str, var: str = "tok") -> ReproStep:
    return ReproStep(
        method="POST",
        path="/auth/login",
        body={"username": user, "password": f"{user}-pass"},
        capture={var: "token"},
    )


def _auth(var: str = "tok") -> dict[str, str]:
    return {"Authorization": f"Bearer {{{{{var}}}}}"}


def _order(body: dict[str, Any], capture: dict[str, str] | None = None) -> ReproStep:
    return ReproStep(
        method="POST", path="/orders", headers=_auth(), body=body, capture=capture or {}
    )


_BUG_LIST: tuple[SeededBug, ...] = (
    SeededBug(
        id="events-pagination-overlap",
        title="Event pages overlap: page 2 repeats the last event of page 1",
        category="functional",
        severity=Severity.MEDIUM,
        description="Offset is computed as (page-1)*pageSize-1 for pages after the first.",
        canonical_repro=(
            ReproStep(method="GET", path="/events?page=1&pageSize=5"),
            ReproStep(method="GET", path="/events?page=2&pageSize=5"),
        ),
    ),
    SeededBug(
        id="order-quantity-upper-bound",
        title="Order quantity 7 is accepted although the maximum is 6",
        category="validation",
        severity=Severity.MEDIUM,
        description="Upper bound check uses 7 instead of 6.",
        canonical_repro=(_login("alice"), _order({"eventId": 2, "quantity": 7})),
    ),
    SeededBug(
        id="promo-percent-rounding",
        title="FAN10 discount is truncated instead of rounded half-up",
        category="calculation",
        severity=Severity.LOW,
        description="10% discount uses floor division, losing a cent on e.g. 4999.",
        canonical_repro=(
            _login("alice"),
            _order({"eventId": 1, "quantity": 1, "promoCode": "FAN10"}),
        ),
    ),
    SeededBug(
        id="welcome-promo-reuse",
        title="WELCOME5 can be redeemed more than once by the same user",
        category="business-rule",
        severity=Severity.HIGH,
        description="The one-use-per-user check for WELCOME5 is skipped.",
        canonical_repro=(
            _login("alice"),
            _order({"eventId": 2, "quantity": 1, "promoCode": "WELCOME5"}),
            _order({"eventId": 2, "quantity": 1, "promoCode": "WELCOME5"}),
        ),
    ),
    SeededBug(
        id="order-idor",
        title="Any authenticated user can read another user's order by ID",
        category="security",
        severity=Severity.CRITICAL,
        description="GET /orders/{id} does not check ownership.",
        canonical_repro=(
            _login("alice"),
            _order({"eventId": 2, "quantity": 1}, capture={"oid": "id"}),
            _login("bob", var="btok"),
            ReproStep(method="GET", path="/orders/{{oid}}", headers=_auth("btok")),
        ),
    ),
    SeededBug(
        id="cancel-does-not-restock",
        title="Cancelling an order does not return tickets to the event",
        category="inventory",
        severity=Severity.HIGH,
        description="Cancel flips the status but never increments event.remaining.",
        canonical_repro=(
            _login("alice"),
            _order({"eventId": 5, "quantity": 2}, capture={"oid": "id"}),
            ReproStep(method="POST", path="/orders/{{oid}}/cancel", headers=_auth()),
            ReproStep(method="GET", path="/events/5"),
        ),
    ),
    SeededBug(
        id="cancel-twice-allowed",
        title="An already-cancelled order can be cancelled again",
        category="state",
        severity=Severity.MEDIUM,
        description="Second cancel returns 200 instead of 409 and restocks again.",
        canonical_repro=(
            _login("alice"),
            _order({"eventId": 6, "quantity": 1}, capture={"oid": "id"}),
            ReproStep(method="POST", path="/orders/{{oid}}/cancel", headers=_auth()),
            ReproStep(method="POST", path="/orders/{{oid}}/cancel", headers=_auth()),
        ),
    ),
    SeededBug(
        id="discount-exceeds-subtotal",
        title="WELCOME5 on a ticket cheaper than 5.00 produces a negative total",
        category="calculation",
        severity=Severity.HIGH,
        description="Fixed discount is not capped at the subtotal.",
        canonical_repro=(
            _login("alice"),
            _order({"eventId": 3, "quantity": 1, "promoCode": "WELCOME5"}),
        ),
    ),
    SeededBug(
        id="not-found-error-contract",
        title="Unknown event returns FastAPI's default body instead of the error envelope",
        category="contract",
        severity=Severity.LOW,
        description="GET /events/{id} 404 body is {'detail': ...} not {'error': {...}}.",
        canonical_repro=(ReproStep(method="GET", path="/events/9999"),),
    ),
    SeededBug(
        id="oversell-by-one",
        title="Availability check allows buying one ticket more than remain",
        category="inventory",
        severity=Severity.HIGH,
        description="Check is quantity > remaining + 1, so remaining can reach -1.",
        canonical_repro=(_login("alice"), _order({"eventId": 11, "quantity": 6})),
    ),
)

BUGS: dict[str, SeededBug] = {bug.id: bug for bug in _BUG_LIST}
ALL_BUG_IDS: frozenset[str] = frozenset(BUGS)


def parse_bug_selection(value: str) -> frozenset[str]:
    """Parse ``all`` / ``none`` / ``id1,id2`` into a validated set of bug IDs."""
    value = value.strip()
    if value == "all":
        return ALL_BUG_IDS
    if value in ("none", ""):
        return frozenset()
    selected = frozenset(part.strip() for part in value.split(",") if part.strip())
    unknown = selected - ALL_BUG_IDS
    if unknown:
        raise ValueError(f"unknown bug id(s): {', '.join(sorted(unknown))}")
    return selected
