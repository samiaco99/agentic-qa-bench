"""Differential-replay scoring.

The oracle is the clean build. For each finding the scorer replays the agent's repro on
fresh instances and classifies it:

- ``invalid_repro``  the repro does not even run on the build under test
                     (unresolved variables), so nobody could act on the report.
- ``false_positive`` the clean build produces the same trace, so the reported behaviour
                     is what the spec allows - not a defect. The repro is then replayed
                     on each flipped-decoy build: a decoy whose build diverges is the trap
                     the report fell into.
- ``confirmed``      clean and buggy traces differ. Attribution then replays the repro on
                     single-bug builds: every bug whose build diverges from clean is a
                     bug this finding demonstrates.

No LLM judge is involved, so scores are reproducible and cheap to recompute.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from fastapi import FastAPI

from qabench.findings import Finding
from qabench.repro import ReproStep, Trace, run_repro
from qabench.target import create_app
from qabench.target.bugs import BUGS, TIERS
from qabench.target.decoys import DECOYS


class Verdict(StrEnum):
    CONFIRMED = "confirmed"
    FALSE_POSITIVE = "false_positive"
    INVALID_REPRO = "invalid_repro"


@dataclass(frozen=True)
class ScoredFinding:
    index: int
    finding: Finding
    verdict: Verdict
    attributed_to: tuple[str, ...]
    duplicate: bool
    decoys: tuple[str, ...] = ()


@dataclass(frozen=True)
class Scorecard:
    bugs_in_build: tuple[str, ...]
    scored: tuple[ScoredFinding, ...]
    detected: dict[str, tuple[int, ...]] = field(default_factory=dict)
    decoys_taken: dict[str, tuple[int, ...]] = field(default_factory=dict)

    @property
    def total_findings(self) -> int:
        return len(self.scored)

    def count(self, verdict: Verdict) -> int:
        return sum(1 for s in self.scored if s.verdict is verdict)

    @property
    def duplicates(self) -> int:
        return sum(1 for s in self.scored if s.duplicate)

    @property
    def precision(self) -> float | None:
        if not self.scored:
            return None
        return self.count(Verdict.CONFIRMED) / self.total_findings

    @property
    def recall(self) -> float | None:
        if not self.bugs_in_build:
            return None
        return len(self.detected) / len(self.bugs_in_build)

    def recall_by_tier(self) -> dict[str, tuple[int, int]]:
        """Tier -> (bugs found, bugs in build), for tiers present in the build."""
        totals: dict[str, tuple[int, int]] = {}
        for tier in TIERS:
            in_tier = [b for b in self.bugs_in_build if BUGS[b].tier == tier]
            if in_tier:
                totals[tier] = (sum(1 for b in in_tier if b in self.detected), len(in_tier))
        return totals

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        if p is None or r is None or p + r == 0:
            return None
        return 2 * p * r / (p + r)

    @property
    def severity_agreement(self) -> float | None:
        """Share of single-bug confirmed findings whose severity matches the ground truth."""
        pairs = [
            (s.finding.severity, BUGS[s.attributed_to[0]].severity)
            for s in self.scored
            if s.verdict is Verdict.CONFIRMED and len(s.attributed_to) == 1
        ]
        if not pairs:
            return None
        return sum(1 for got, want in pairs if got is want) / len(pairs)


def score(findings: list[Finding], bugs_in_build: frozenset[str]) -> Scorecard:
    ordered_bugs = tuple(sorted(bugs_in_build))
    builds: dict[str, Callable[[], FastAPI]] = {
        bug_id: _factory(frozenset({bug_id})) for bug_id in ordered_bugs
    }
    flipped: dict[str, Callable[[], FastAPI]] = {
        decoy_id: _factory(frozenset(), frozenset({decoy_id})) for decoy_id in DECOYS
    }
    clean = _factory(frozenset())
    under_test = _factory(bugs_in_build)

    scored: list[ScoredFinding] = []
    detected: dict[str, list[int]] = {}
    taken: dict[str, list[int]] = {}
    for index, finding in enumerate(findings):
        steps = list(finding.repro_steps)
        test_trace = run_repro(under_test, steps)
        if test_trace.has_replay_error:
            scored.append(ScoredFinding(index, finding, Verdict.INVALID_REPRO, (), False))
            continue

        clean_trace = run_repro(clean, steps)
        if not test_trace.differs_from(clean_trace):
            decoys = tuple(
                decoy_id
                for decoy_id, factory in flipped.items()
                if _diverges(factory, steps, clean_trace)
            )
            for decoy_id in decoys:
                taken.setdefault(decoy_id, []).append(index)
            scored.append(ScoredFinding(index, finding, Verdict.FALSE_POSITIVE, (), False, decoys))
            continue

        attributed = tuple(
            bug_id for bug_id, factory in builds.items() if _diverges(factory, steps, clean_trace)
        )
        duplicate = bool(attributed) and all(bug_id in detected for bug_id in attributed)
        for bug_id in attributed:
            detected.setdefault(bug_id, []).append(index)
        scored.append(ScoredFinding(index, finding, Verdict.CONFIRMED, attributed, duplicate))

    return Scorecard(
        bugs_in_build=ordered_bugs,
        scored=tuple(scored),
        detected={bug_id: tuple(idx) for bug_id, idx in detected.items()},
        decoys_taken={decoy_id: tuple(idx) for decoy_id, idx in taken.items()},
    )


def _factory(bugs: frozenset[str], flips: frozenset[str] = frozenset()) -> Callable[[], FastAPI]:
    return lambda: create_app(bugs, flip_decoys=flips)


def _diverges(factory: Callable[[], FastAPI], steps: list[ReproStep], clean: Trace) -> bool:
    return run_repro(factory, steps).differs_from(clean)
