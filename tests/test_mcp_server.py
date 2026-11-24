"""The MCP server, driven in-process by a real MCP client."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mcp import Client

from qabench.findings import FindingsFile
from qabench.mcp_server import ExamSession, build_server
from qabench.scoring import Verdict, score
from qabench.target.bugs import ALL_BUG_IDS, BUGS

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _text(result: object) -> str:
    return "".join(getattr(block, "text", "") for block in result.content)  # type: ignore[attr-defined]


async def test_exam_over_mcp_produces_a_scorable_findings_file(tmp_path: Path) -> None:
    session = ExamSession(ALL_BUG_IDS, tmp_path)
    try:
        async with Client(build_server(session)) as client:
            tools = await client.list_tools()
            assert {t.name for t in tools.tools} == {
                "read_specification",
                "http_request",
                "replay_steps",
                "report_bug",
            }

            spec = await client.call_tool("read_specification", {})
            assert "Matchday Tickets API" in _text(spec)

            explore = await client.call_tool(
                "http_request", {"method": "GET", "path": "/events/9999"}
            )
            assert json.loads(_text(explore))["body"] == {"detail": "Not Found"}

            bad = await client.call_tool("http_request", {"method": "GET", "path": "no-slash"})
            assert bad.is_error

            bug = BUGS["order-idor"]
            report = await client.call_tool(
                "report_bug",
                {
                    "title": "Bob reads Alice's order",
                    "severity": "critical",
                    "category": "security",
                    "spec_rule": "Otherwise 404",
                    "expected": "404",
                    "actual": "200",
                    "repro_steps": [s.model_dump() for s in bug.canonical_repro],
                },
            )
            assert "Recorded as finding #1" in _text(report)
    finally:
        session.close()

    saved = FindingsFile.model_validate_json(session.findings_path.read_text(encoding="utf-8"))
    assert saved.bugs == sorted(ALL_BUG_IDS)
    card = score(saved.findings, frozenset(saved.bugs))
    assert [(s.verdict, s.attributed_to) for s in card.scored] == [
        (Verdict.CONFIRMED, ("order-idor",))
    ]
    log = (tmp_path / "transcript.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["tool"] for line in log] == [
        "read_specification",
        "http_request",
        "http_request",
        "report_bug",
    ]
