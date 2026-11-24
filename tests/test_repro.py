from __future__ import annotations

import pytest

from qabench.repro import ReproStep, UnresolvedVariableError, lookup_path, render, run_repro
from qabench.target import create_app


def test_whole_template_keeps_type_and_inline_template_becomes_text() -> None:
    variables = {"eid": 3, "tok": "abc"}
    assert render({"eventId": "{{eid}}"}, variables) == {"eventId": 3}
    assert render("Bearer {{ tok }}", variables) == "Bearer abc"
    assert render(["{{eid}}", 1], variables) == [3, 1]


def test_unknown_variable_raises() -> None:
    with pytest.raises(UnresolvedVariableError):
        render("/orders/{{missing}}", {})


def test_lookup_path_walks_dicts_and_lists() -> None:
    data = {"items": [{"id": 7}]}
    assert lookup_path(data, "items.0.id") == 7
    with pytest.raises(KeyError):
        lookup_path(data, "items.3.id")


def test_replay_runs_on_a_fresh_instance_every_time() -> None:
    steps = [
        ReproStep(
            method="POST",
            path="/auth/login",
            body={"username": "alice", "password": "alice-pass"},
            capture={"tok": "token"},
        ),
        ReproStep(
            method="POST",
            path="/orders",
            headers={"Authorization": "Bearer {{tok}}"},
            body={"eventId": 11, "quantity": 5},
        ),
    ]
    first = run_repro(create_app, steps)
    second = run_repro(create_app, steps)
    assert [s.status for s in first.steps] == [200, 201]
    assert not first.differs_from(second)


def test_unresolved_variable_is_recorded_not_raised() -> None:
    trace = run_repro(create_app, [ReproStep(method="GET", path="/orders/{{oid}}")])
    assert trace.has_replay_error
