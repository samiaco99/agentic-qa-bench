"""Benchmark validity: every seeded bug must be observable, and bugs must not mask each other.

If a bug's canonical repro did not diverge from the clean build, no agent could ever get
credit for it and recall would be capped below 100% without anyone noticing.
"""

from __future__ import annotations

from functools import partial

import pytest

from qabench.repro import run_repro
from qabench.target import create_app
from qabench.target.bugs import ALL_BUG_IDS, BUGS, parse_bug_selection


@pytest.mark.parametrize("bug_id", sorted(BUGS))
def test_canonical_repro_reveals_the_bug(bug_id: str) -> None:
    steps = list(BUGS[bug_id].canonical_repro)
    clean = run_repro(lambda: create_app(), steps)
    buggy = run_repro(lambda: create_app({bug_id}), steps)
    assert not clean.has_replay_error
    assert buggy.differs_from(clean)


@pytest.mark.parametrize("bug_id", sorted(BUGS))
def test_canonical_repro_is_attributed_only_to_its_own_bug(bug_id: str) -> None:
    steps = list(BUGS[bug_id].canonical_repro)
    clean = run_repro(lambda: create_app(), steps)
    for other in sorted(ALL_BUG_IDS - {bug_id}):
        trace = run_repro(partial(create_app, {other}), steps)
        assert not trace.differs_from(clean), f"{other} also changes the repro of {bug_id}"


@pytest.mark.parametrize("bug_id", sorted(BUGS))
def test_canonical_repro_still_reveals_bug_with_all_bugs_enabled(bug_id: str) -> None:
    steps = list(BUGS[bug_id].canonical_repro)
    clean = run_repro(lambda: create_app(), steps)
    assert run_repro(lambda: create_app(ALL_BUG_IDS), steps).differs_from(clean)


def test_parse_bug_selection() -> None:
    assert parse_bug_selection("all") == ALL_BUG_IDS
    assert parse_bug_selection("none") == frozenset()
    assert parse_bug_selection("order-idor, oversell-by-one") == {"order-idor", "oversell-by-one"}
    with pytest.raises(ValueError, match="unknown bug"):
        parse_bug_selection("order-idor,not-a-bug")


def test_unknown_bug_is_rejected_by_app_factory() -> None:
    with pytest.raises(ValueError):
        create_app({"not-a-bug"})
