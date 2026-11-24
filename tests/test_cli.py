from __future__ import annotations

import os
from pathlib import Path

import pytest

from qabench.cli import load_dotenv, main


def test_load_dotenv_reads_values_without_overriding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = tmp_path / ".env"
    env.write_text('# comment\nQABENCH_A="from-file"\nQABENCH_B=from-file\n\n', encoding="utf-8")
    monkeypatch.delenv("QABENCH_A", raising=False)
    monkeypatch.setenv("QABENCH_B", "from-env")

    load_dotenv(env)

    assert os.environ["QABENCH_A"] == "from-file"
    assert os.environ["QABENCH_B"] == "from-env"


def test_score_save_writes_scorecard_next_to_findings(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "sample-findings.json"
    findings = tmp_path / "findings.json"
    findings.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")

    assert main(["score", str(findings), "--agent", "test agent", "--save"]) == 0

    assert "- **Agent:** test agent" in (tmp_path / "scorecard.md").read_text(encoding="utf-8")
    assert (tmp_path / "result.json").is_file()


def test_score_warns_when_findings_come_from_another_exam_version(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # v0.1 result files predate the "exam" field.
    findings = tmp_path / "result.json"
    findings.write_text('{"bugs": ["order-idor"], "findings": []}', encoding="utf-8")

    assert main(["score", str(findings)]) == 0

    err = capsys.readouterr().err
    assert "exam v0.1" in err
    assert "git tag v0.1.0" in err


def test_bugs_lists_tiers_and_decoys(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["bugs"]) == 0
    out = capsys.readouterr().out
    assert "20 seeded bugs" in out
    assert "logout-revokes-wrong-session     deep" in out
    assert "6 decoys" in out


def test_max_cost_requires_a_priced_model(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", "--model", "some-unpriced-model", "--max-cost", "1"]) == 2
    assert "needs a priced model" in capsys.readouterr().out
