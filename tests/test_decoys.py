"""Benchmark validity for decoys: each trap must be a false positive whatever bugs are on,
and must be attributable to exactly one decoy.

If a trap repro diverged on some bug build, reporting the decoy could score as a real bug
on that exam. If it diverged on another decoy's flipped build, the scorecard would blame
the wrong trap.
"""

from __future__ import annotations

from functools import partial

import pytest

from qabench.repro import run_repro
from qabench.target import create_app
from qabench.target.bugs import ALL_BUG_IDS
from qabench.target.decoys import ALL_DECOY_IDS, DECOYS


@pytest.mark.parametrize("decoy_id", sorted(DECOYS))
def test_trap_repro_is_a_false_positive_on_every_build(decoy_id: str) -> None:
    steps = list(DECOYS[decoy_id].trap_repro)
    clean = run_repro(lambda: create_app(), steps)
    assert not clean.has_replay_error
    for bugs in [ALL_BUG_IDS, *({b} for b in sorted(ALL_BUG_IDS))]:
        trace = run_repro(partial(create_app, bugs), steps)
        assert not trace.differs_from(clean), f"bugs {sorted(bugs)} change the trap"


@pytest.mark.parametrize("decoy_id", sorted(DECOYS))
def test_trap_repro_diverges_only_on_its_own_flipped_build(decoy_id: str) -> None:
    steps = list(DECOYS[decoy_id].trap_repro)
    clean = run_repro(lambda: create_app(), steps)
    for other in sorted(ALL_DECOY_IDS):
        trace = run_repro(partial(create_app, flip_decoys={other}), steps)
        assert trace.differs_from(clean) == (other == decoy_id), other


def test_unknown_decoy_is_rejected_by_app_factory() -> None:
    with pytest.raises(ValueError):
        create_app(flip_decoys={"not-a-decoy"})
