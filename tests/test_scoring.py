from __future__ import annotations

from pathlib import Path

import pytest

from qabench.findings import FindingsFile
from qabench.report import render_markdown, to_json
from qabench.scoring import Scorecard, Verdict, score
from qabench.target.bugs import ALL_BUG_IDS, BUGS

FIXTURE = Path(__file__).parent / "fixtures" / "sample-findings.json"


@pytest.fixture(scope="module")
def card() -> Scorecard:
    data = FindingsFile.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    return score(data.findings, frozenset(data.bugs))


def test_each_finding_gets_the_expected_verdict(card: Scorecard) -> None:
    verdicts = [(s.verdict, s.attributed_to, s.duplicate) for s in card.scored]
    assert verdicts == [
        (Verdict.CONFIRMED, ("order-idor",), False),
        (Verdict.CONFIRMED, ("order-idor",), True),
        (Verdict.FALSE_POSITIVE, (), False),
        (Verdict.INVALID_REPRO, (), False),
        (Verdict.CONFIRMED, ("promo-percent-rounding",), False),
        (Verdict.CONFIRMED, ("discount-exceeds-subtotal", "welcome-promo-reuse"), False),
    ]


def test_aggregate_metrics(card: Scorecard) -> None:
    assert card.precision == pytest.approx(4 / 6)
    assert card.recall == pytest.approx(4 / 10)
    assert card.duplicates == 1
    # Single-bug confirmed findings: #1 critical (match), #2 high (miss), #5 medium (miss).
    assert card.severity_agreement == pytest.approx(1 / 3)


def test_canonical_repros_score_perfectly() -> None:
    from qabench.findings import Finding

    findings = [
        Finding(
            title=bug.title,
            severity=bug.severity,
            category=bug.category,
            spec_rule="n/a",
            expected="n/a",
            actual="n/a",
            repro_steps=list(bug.canonical_repro),
        )
        for bug in BUGS.values()
    ]
    perfect = score(findings, ALL_BUG_IDS)
    assert (perfect.precision, perfect.recall, perfect.severity_agreement) == (1.0, 1.0, 1.0)


def test_clean_build_has_no_recall_and_every_finding_is_a_false_positive(card: Scorecard) -> None:
    data = FindingsFile.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    clean = score(data.findings, frozenset())
    assert clean.recall is None
    assert {s.verdict for s in clean.scored} == {Verdict.FALSE_POSITIVE, Verdict.INVALID_REPRO}


def test_reports_render(card: Scorecard) -> None:
    markdown = render_markdown(card)
    assert "| Recall (seeded bugs found) | 4/10 (40%) |" in markdown
    assert "**missed**" in markdown
    data = to_json(card)
    assert data["score"]["missed"] == sorted(set(card.bugs_in_build) - set(card.detected))
    assert FindingsFile.model_validate(data).findings[0].title.startswith("Bob can read")
