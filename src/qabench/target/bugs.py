"""Seeded defect registry - the benchmark's ground truth.

The agent never sees this module. Each bug is a switch in the target app plus a
canonical reproduction that proves the bug is observable through the public API
(``tests/test_seeded_bugs.py`` enforces that, and that bugs do not mask each other).

Tiers:

- ``core``  the direct test of the violated rule exposes the bug (the ten exam v0.1 bugs,
            plus two more of the same kind).
- ``deep``  the direct test of the rule passes. Exposing the bug needs extra state (a
            second session or user, a cancelled order, a sold-out event, an admin change)
            or a second rule in play.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from qabench.findings import Severity
from qabench.repro import ReproStep
from qabench.target._steps import auth, cancel, login, order

Tier = Literal["core", "deep"]
TIERS: tuple[Tier, ...] = ("core", "deep")


@dataclass(frozen=True)
class SeededBug:
    id: str
    title: str
    category: str
    severity: Severity
    tier: Tier
    description: str
    canonical_repro: tuple[ReproStep, ...]


_BUG_LIST: tuple[SeededBug, ...] = (
    SeededBug(
        id="events-pagination-overlap",
        title="Event pages overlap: page 2 repeats the last event of page 1",
        category="functional",
        severity=Severity.MEDIUM,
        tier="core",
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
        tier="core",
        description="Upper bound check uses 7 instead of 6.",
        canonical_repro=(login("alice"), order({"eventId": 2, "quantity": 7})),
    ),
    SeededBug(
        id="promo-percent-rounding",
        title="FAN10 discount is truncated instead of rounded half-up",
        category="calculation",
        severity=Severity.LOW,
        tier="core",
        description="10% discount uses floor division, losing a cent on e.g. 4999.",
        canonical_repro=(
            login("alice"),
            order({"eventId": 1, "quantity": 1, "promoCode": "FAN10"}),
        ),
    ),
    SeededBug(
        id="welcome-promo-reuse",
        title="WELCOME5 can be redeemed more than once by the same user",
        category="business-rule",
        severity=Severity.HIGH,
        tier="core",
        description="The one-use-per-user check for WELCOME5 is skipped.",
        canonical_repro=(
            login("alice"),
            order({"eventId": 2, "quantity": 1, "promoCode": "WELCOME5"}),
            order({"eventId": 2, "quantity": 1, "promoCode": "WELCOME5"}),
        ),
    ),
    SeededBug(
        id="order-idor",
        title="Any authenticated user can read another user's order by ID",
        category="security",
        severity=Severity.CRITICAL,
        tier="core",
        description="GET /orders/{id} does not check ownership.",
        canonical_repro=(
            login("alice"),
            order({"eventId": 2, "quantity": 1}, capture={"oid": "id"}),
            login("bob", var="btok"),
            ReproStep(method="GET", path="/orders/{{oid}}", headers=auth("btok")),
        ),
    ),
    SeededBug(
        id="cancel-does-not-restock",
        title="Cancelling an order does not return tickets to the event",
        category="inventory",
        severity=Severity.HIGH,
        tier="core",
        description="Cancel flips the status but never increments event.remaining.",
        canonical_repro=(
            login("alice"),
            order({"eventId": 5, "quantity": 2}, capture={"oid": "id"}),
            cancel(),
            ReproStep(method="GET", path="/events/5"),
        ),
    ),
    SeededBug(
        id="cancel-twice-allowed",
        title="An already-cancelled order can be cancelled again",
        category="state",
        severity=Severity.MEDIUM,
        tier="core",
        description="Second cancel returns 200 instead of 409 and restocks again.",
        canonical_repro=(
            login("alice"),
            order({"eventId": 6, "quantity": 1}, capture={"oid": "id"}),
            cancel(),
            cancel(),
        ),
    ),
    SeededBug(
        id="discount-exceeds-subtotal",
        title="WELCOME5 on a ticket cheaper than 5.00 produces a negative total",
        category="calculation",
        severity=Severity.HIGH,
        tier="core",
        description="Fixed discount is not capped at the subtotal.",
        canonical_repro=(
            login("alice"),
            order({"eventId": 3, "quantity": 1, "promoCode": "WELCOME5"}),
        ),
    ),
    SeededBug(
        id="not-found-error-contract",
        title="Unknown event returns FastAPI's default body instead of the error envelope",
        category="contract",
        severity=Severity.LOW,
        tier="core",
        description="GET /events/{id} 404 body is {'detail': ...} not {'error': {...}}.",
        canonical_repro=(ReproStep(method="GET", path="/events/9999"),),
    ),
    SeededBug(
        id="oversell-by-one",
        title="Availability check allows buying one ticket more than remain",
        category="inventory",
        severity=Severity.HIGH,
        tier="core",
        description="Check is quantity > remaining + 1, so remaining can reach -1.",
        canonical_repro=(login("alice"), order({"eventId": 11, "quantity": 6})),
    ),
    SeededBug(
        id="fan-can-update-event",
        title="A fan can change an event's price through the admin endpoint",
        category="security",
        severity=Severity.CRITICAL,
        tier="core",
        description="PATCH /events/{id} checks authentication but not the admin role.",
        canonical_repro=(
            login("alice"),
            ReproStep(method="PATCH", path="/events/1", headers=auth(), body={"priceCents": 100}),
        ),
    ),
    SeededBug(
        id="fee-cap-ignored",
        title="Service fee is not capped at 600 cents for orders of 5 or more tickets",
        category="calculation",
        severity=Severity.HIGH,
        tier="core",
        description="feeCents is 150 * quantity with no cap, so 6 tickets pay 900.",
        canonical_repro=(login("alice"), order({"eventId": 2, "quantity": 6})),
    ),
    SeededBug(
        id="logout-revokes-wrong-session",
        title="Logout revokes the user's newest token instead of the one presented",
        category="security",
        severity=Severity.CRITICAL,
        tier="deep",
        description="Logout revokes the user's latest session, not the request's token. With "
        "a single session the two coincide, so a one-login test passes.",
        canonical_repro=(
            login("alice", "t1"),
            login("alice", "t2"),
            ReproStep(method="POST", path="/auth/logout", headers=auth("t1")),
            ReproStep(method="GET", path="/orders", headers=auth("t1")),
            ReproStep(method="GET", path="/orders", headers=auth("t2")),
        ),
    ),
    SeededBug(
        id="closed-sales-bypass-with-promo",
        title="Tickets for an event with closed sales can be bought with a promo code",
        category="business-rule",
        severity=Severity.HIGH,
        tier="deep",
        description="The salesOpen check only runs on the no-promo code path.",
        canonical_repro=(
            login("alice"),
            order({"eventId": 13, "quantity": 1, "promoCode": "FAN10"}),
        ),
    ),
    SeededBug(
        id="ticket-limit-counts-cancelled",
        title="Cancelled orders still count towards the 8-tickets-per-event limit",
        category="business-rule",
        severity=Severity.HIGH,
        tier="deep",
        description="The per-user limit sums every order for the event, cancelled or not.",
        canonical_repro=(
            login("alice"),
            order({"eventId": 5, "quantity": 4}, capture={"oid": "id"}),
            cancel(),
            order({"eventId": 5, "quantity": 4}),
            order({"eventId": 5, "quantity": 1}),
        ),
    ),
    SeededBug(
        id="idempotency-key-not-user-scoped",
        title="Idempotency keys are global: reusing another user's key returns their order",
        category="security",
        severity=Severity.CRITICAL,
        tier="deep",
        description="Keys are stored without the user ID, so Bob sending Alice's key with the "
        "same body gets Alice's order back.",
        canonical_repro=(
            login("alice"),
            order({"eventId": 2, "quantity": 1}, key="order-1"),
            login("bob", var="btok"),
            order({"eventId": 2, "quantity": 1}, var="btok", key="order-1"),
        ),
    ),
    SeededBug(
        id="idempotent-replay-reserves-again",
        title="An idempotent replay returns the original order but takes the tickets again",
        category="inventory",
        severity=Severity.HIGH,
        tier="deep",
        description="The replay path decrements remaining before returning the stored order.",
        canonical_repro=(
            login("alice"),
            order({"eventId": 5, "quantity": 2}, key="retry-1"),
            order({"eventId": 5, "quantity": 2}, key="retry-1"),
            ReproStep(method="GET", path="/events/5"),
        ),
    ),
    SeededBug(
        id="order-price-not-snapshotted",
        title="Changing an event's price rewrites the price of existing orders",
        category="calculation",
        severity=Severity.HIGH,
        tier="deep",
        description="A price update re-prices every existing order for the event.",
        canonical_repro=(
            login("alice"),
            order({"eventId": 2, "quantity": 1}, capture={"oid": "id"}),
            login("admin", "atok"),
            ReproStep(
                method="PATCH", path="/events/2", headers=auth("atok"), body={"priceCents": 8000}
            ),
            ReproStep(method="GET", path="/orders/{{oid}}", headers=auth()),
        ),
    ),
    SeededBug(
        id="sold-out-events-hidden",
        title="Sold-out events disappear from the event list",
        category="functional",
        severity=Severity.MEDIUM,
        tier="deep",
        description="GET /events filters out events with remaining 0, and total shrinks.",
        canonical_repro=(
            login("alice"),
            order({"eventId": 11, "quantity": 4}),
            order({"eventId": 11, "quantity": 1}),
            ReproStep(method="GET", path="/events?pageSize=50"),
        ),
    ),
    SeededBug(
        id="refund-ignores-discount",
        title="Refund ignores the promo discount, so the customer gets back more than they paid",
        category="calculation",
        severity=Severity.HIGH,
        tier="deep",
        description="refundCents is unitPrice * quantity. Without a promo that equals "
        "totalCents - feeCents, so only a discounted order shows the bug.",
        canonical_repro=(
            login("alice"),
            order({"eventId": 2, "quantity": 1, "promoCode": "FAN10"}, capture={"oid": "id"}),
            cancel(),
        ),
    ),
)

BUGS: dict[str, SeededBug] = {bug.id: bug for bug in _BUG_LIST}
ALL_BUG_IDS: frozenset[str] = frozenset(BUGS)


def parse_bug_selection(value: str) -> frozenset[str]:
    """Parse ``all`` / ``none`` / ``core`` / ``deep`` / ``id1,id2`` into validated bug IDs."""
    value = value.strip()
    if value == "all":
        return ALL_BUG_IDS
    if value in ("none", ""):
        return frozenset()
    if value in TIERS:
        return frozenset(bug.id for bug in BUGS.values() if bug.tier == value)
    selected = frozenset(part.strip() for part in value.split(",") if part.strip())
    unknown = selected - ALL_BUG_IDS
    if unknown:
        raise ValueError(f"unknown bug id(s): {', '.join(sorted(unknown))}")
    return selected
