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


def test_max_cost_requires_a_priced_model(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", "--model", "some-unpriced-model", "--max-cost", "1"]) == 2
    assert "needs a priced model" in capsys.readouterr().out
