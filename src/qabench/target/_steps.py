"""Builders for the reproduction steps used by the bug and decoy registries."""

from __future__ import annotations

from typing import Any

from qabench.repro import ReproStep


def login(user: str, var: str = "tok") -> ReproStep:
    return ReproStep(
        method="POST",
        path="/auth/login",
        body={"username": user, "password": f"{user}-pass"},
        capture={var: "token"},
    )


def auth(var: str = "tok") -> dict[str, str]:
    return {"Authorization": f"Bearer {{{{{var}}}}}"}


def order(
    body: dict[str, Any],
    capture: dict[str, str] | None = None,
    *,
    var: str = "tok",
    key: str | None = None,
) -> ReproStep:
    headers = auth(var) | ({"Idempotency-Key": key} if key else {})
    return ReproStep(
        method="POST", path="/orders", headers=headers, body=body, capture=capture or {}
    )


def cancel(var: str = "tok") -> ReproStep:
    """Cancel the order captured as ``oid``."""
    return ReproStep(method="POST", path="/orders/{{oid}}/cancel", headers=auth(var))
