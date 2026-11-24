from __future__ import annotations

from pathlib import Path

import pytest

from qabench.findings import Finding, FindingsFile
from qabench.report import render_markdown, to_json
from qabench.scoring import Scorecard, Verdict, score
from qabench.target import EXAM_VERSION
from qabench.target.bugs import ALL_BUG_IDS, BUGS
from qabench.target.decoys import DECOYS

FIXTURE = Path(__file__).parent / "fixtures" / "sample-findings.json"


def _finding(title: str, steps: object, severity: str = "low") -> Finding:
    return Finding.model_validate(
        {
            "title": title,
            "severity": severity,
            "category": "n/a",
            "spec_rule": "n/a",
            "expected": "n/a",
            "actual": "n/a",
            "repro_steps": steps,
        }
    )


@pytest.fixture(scope="module")
def card() -> Scorecard:
    data = FindingsFile.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    return score(data.findings, frozenset(data.bugs))


def test_each_finding_gets_the_expected_verdict(card: Scorecard) -> None:
    verdicts = [(s.verdict, s.attributed_to, s.duplicate, s.decoys) for s in card.scored]
    assert verdicts == [
        (Verdict.CONFIRMED, ("order-idor",), False, ()),
        (Verdict.CONFIRMED, ("order-idor",), True, ()),
        (Verdict.FALSE_POSITIVE, (), False, ()),
        (Verdict.INVALID_REPRO, (), False, ()),
        (Verdict.CONFIRMED, ("promo-percent-rounding",), False, ()),
        (Verdict.CONFIRMED, ("discount-exceeds-subtotal", "welcome-promo-reuse"), False, ()),
        (Verdict.CONFIRMED, ("refund-ignores-discount",), False, ()),
        (Verdict.FALSE_POSITIVE, (), False, ("admin-reads-any-order",)),
    ]


def test_aggregate_metrics(card: Scorecard) -> None:
    assert card.precision == pytest.approx(5 / 8)
    assert card.recall == pytest.approx(5 / 20)
    assert card.recall_by_tier() == {"core": (4, 12), "deep": (1, 8)}
    assert card.duplicates == 1
    assert card.decoys_taken == {"admin-reads-any-order": (7,)}
    # Single-bug confirmed findings: #1 critical (match), #2 high (miss), #5 medium (miss),
    # #7 high (match).
    assert card.severity_agreement == pytest.approx(2 / 4)


def test_canonical_repros_score_perfectly() -> None:
    findings = [_finding(b.title, b.canonical_repro, b.severity) for b in BUGS.values()]
    perfect = score(findings, ALL_BUG_IDS)
    assert (perfect.precision, perfect.recall, perfect.severity_agreement) == (1.0, 1.0, 1.0)
    assert perfect.recall_by_tier() == {"core": (12, 12), "deep": (8, 8)}


def test_each_decoy_trap_is_a_false_positive_blamed_on_its_decoy() -> None:
    traps = [_finding(decoy.title, decoy.trap_repro) for decoy in DECOYS.values()]
    card = score(traps, ALL_BUG_IDS)
    assert [s.verdict for s in card.scored] == [Verdict.FALSE_POSITIVE] * len(DECOYS)
    assert [s.decoys for s in card.scored] == [(decoy_id,) for decoy_id in DECOYS]
    assert card.precision == 0.0


def test_tier_selection_only_reports_tiers_in_the_build() -> None:
    deep_only = frozenset(b for b in ALL_BUG_IDS if BUGS[b].tier == "deep")
    assert score([], deep_only).recall_by_tier() == {"deep": (0, 8)}
    assert score([], frozenset()).recall_by_tier() == {}


def test_clean_build_has_no_recall_and_every_finding_is_a_false_positive(card: Scorecard) -> None:
    data = FindingsFile.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    clean = score(data.findings, frozenset())
    assert clean.recall is None
    assert {s.verdict for s in clean.scored} == {Verdict.FALSE_POSITIVE, Verdict.INVALID_REPRO}


def test_reports_render(card: Scorecard) -> None:
    markdown = render_markdown(card)
    assert f"- **Exam:** v{EXAM_VERSION}" in markdown
    assert "| Recall (seeded bugs found) | 5/20 (25%) |" in markdown
    assert "| Recall, deep tier | 1/8 (12%) |" in markdown
    assert "| Decoys taken | 1/6 |" in markdown
    assert "| `admin-reads-any-order` | **#8** |" in markdown
    assert "decoy `admin-reads-any-order`" in markdown
    assert "**missed**" in markdown
    data = to_json(card)
    assert data["exam"] == EXAM_VERSION
    assert data["score"]["missed"] == sorted(set(card.bugs_in_build) - set(card.detected))
    assert data["score"]["recall_by_tier"]["deep"] == {"found": 1, "total": 8}
    assert data["score"]["decoys_taken"] == {"admin-reads-any-order": [8]}
    assert FindingsFile.model_validate(data).findings[0].title.startswith("Bob can read")
