"""Serve the exam over MCP, so any MCP-capable agent (Claude Code, IDE agents, local
models) can take it - no API key needed on this side.

The tools are the same ones the built-in API agent gets, plus ``read_specification``
because an MCP client has no system prompt we control. Every ``report_bug`` rewrites the
findings file, so even an interrupted session can be scored with ``qabench score``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio
import mcp_types as types
from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server

from qabench.agent.tools import TOOL_DEFINITIONS, ToolBox, ToolError
from qabench.target import load_spec

SPEC_TOOL: dict[str, Any] = {
    "name": "read_specification",
    "description": (
        "Return the Matchday Tickets API product specification - the only source of truth "
        "for expected behaviour. Read it before testing."
    ),
    "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
}

INSTRUCTIONS = (
    "You are taking a QA exam. Call read_specification first, then explore the API with "
    "http_request, dry-run reproductions with replay_steps, and file every defect you can "
    "reproduce with report_bug. Only behaviour that violates the specification is a defect."
)


class ExamSession:
    """Owns the tool box and persists findings plus an audit log after every call."""

    def __init__(self, bugs: frozenset[str], out_dir: Path) -> None:
        self._bugs = bugs
        self._tools = ToolBox(bugs)
        self._out_dir = out_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        self.findings_path = out_dir / "findings.json"
        self._log_path = out_dir / "transcript.jsonl"
        self._calls = 0
        self._save_findings()

    def call(self, name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        self._calls += 1
        if name == SPEC_TOOL["name"]:
            output, is_error = load_spec(), False
        else:
            try:
                output, is_error = self._tools.call(name, arguments), False
            except ToolError as exc:
                output, is_error = str(exc), True
        if name == "report_bug" and not is_error:
            self._save_findings()
        with self._log_path.open("a", encoding="utf-8") as fh:
            entry = {"call": self._calls, "tool": name, "input": arguments, "is_error": is_error}
            fh.write(json.dumps(entry) + "\n")
        return output, is_error

    def close(self) -> None:
        self._tools.close()

    def _save_findings(self) -> None:
        data = {
            "bugs": sorted(self._bugs),
            "findings": [f.model_dump(mode="json") for f in self._tools.findings],
        }
        tmp = self.findings_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.findings_path)


def build_server(session: ExamSession) -> Server[Any]:
    tools = [
        types.Tool(name=d["name"], description=d["description"], input_schema=d["input_schema"])
        for d in [SPEC_TOOL, *TOOL_DEFINITIONS]
    ]

    async def list_tools(
        _: ServerRequestContext[Any], __: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=tools)

    async def call_tool(
        _: ServerRequestContext[Any], params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        # The tool box is synchronous (in-process HTTP), so keep it off the event loop.
        output, is_error = await anyio.to_thread.run_sync(
            session.call, params.name, dict(params.arguments or {})
        )
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=output)], is_error=is_error
        )

    return Server(
        "qabench",
        version="0.1.0",
        instructions=INSTRUCTIONS,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )


def default_out_dir(results_root: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return results_root / f"{stamp}-mcp"


def serve_stdio(bugs: frozenset[str], out_dir: Path) -> None:
    session = ExamSession(bugs, out_dir)
    server = build_server(session)

    async def _main() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    try:
        anyio.run(_main)
    finally:
        session.close()
