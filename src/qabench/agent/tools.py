"""The agent's tool surface: explore, dry-run a repro, file a bug.

The agent only ever talks to the in-process app, so it cannot reach the network, and it
never sees which bugs are enabled - the ``bugs`` set stays on this side of the boundary.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from qabench.findings import Finding, Severity
from qabench.repro import HttpMethod, ReproStep, Trace, run_repro
from qabench.target import create_app

MAX_BODY_CHARS = 4000

_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]

_STEP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "method": {"type": "string", "enum": _METHODS},
        "path": {"type": "string", "description": "Path and query, e.g. /orders/{{oid}}"},
        "headers": {"type": "object", "additionalProperties": {"type": "string"}},
        "body": {"description": "JSON request body. Omit when the request has no body."},
        "capture": {
            "type": "object",
            "additionalProperties": {"type": "string"},
            "description": (
                "Save values from this step's JSON response for later steps: "
                '{"varName": "dotted.path"}, e.g. {"tok": "token"} or {"oid": "id"}. '
                "Reference them later as {{varName}} in path, headers, or body."
            ),
        },
    },
    "required": ["method", "path"],
    "additionalProperties": False,
}

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "http_request",
        "description": (
            "Send one HTTP request to the Matchday Tickets API and get back the status code "
            "and JSON body. State persists across calls in this session, so orders you create "
            "stay created. Use relative paths such as /events?page=2."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "method": {"type": "string", "enum": _METHODS},
                "path": {"type": "string"},
                "headers": {"type": "object", "additionalProperties": {"type": "string"}},
                "body": {"description": "JSON request body. Omit when there is none."},
            },
            "required": ["method", "path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "replay_steps",
        "description": (
            "Dry-run a candidate reproduction on a brand-new API instance that has only the "
            "seed data - nothing from your session exists there. Returns every step's status "
            "and body so you can check the repro shows the problem before reporting it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"steps": {"type": "array", "items": _STEP_SCHEMA, "minItems": 1}},
            "required": ["steps"],
            "additionalProperties": False,
        },
    },
    {
        "name": "report_bug",
        "description": (
            "File one defect: a behaviour that violates a rule in the specification. "
            "repro_steps must reproduce it on a fresh instance (log in inside the steps and "
            "use capture/{{var}} for tokens and IDs). Report each distinct defect once."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "One-line summary of the defect."},
                "severity": {"type": "string", "enum": [s.value for s in Severity]},
                "category": {
                    "type": "string",
                    "description": "e.g. security, validation, calculation, business-rule, "
                    "inventory, state, functional, contract.",
                },
                "spec_rule": {"type": "string", "description": "The violated spec rule, quoted."},
                "expected": {"type": "string"},
                "actual": {"type": "string"},
                "repro_steps": {"type": "array", "items": _STEP_SCHEMA, "minItems": 1},
            },
            "required": [
                "title",
                "severity",
                "category",
                "spec_rule",
                "expected",
                "actual",
                "repro_steps",
            ],
            "additionalProperties": False,
        },
    },
]


class _HttpRequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: HttpMethod
    path: str = Field(pattern=r"^/")
    headers: dict[str, str] = Field(default_factory=dict)
    body: Any = None


class _ReplayInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: list[ReproStep] = Field(min_length=1, max_length=20)


class ToolError(Exception):
    """Raised for bad tool input; the loop returns it to the model as an error result."""


class ToolBox:
    def __init__(self, bugs: Iterable[str]) -> None:
        self._bugs = frozenset(bugs)
        self._session = TestClient(create_app(self._bugs), raise_server_exceptions=False)
        self.findings: list[Finding] = []

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> ToolBox:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def call(self, name: str, raw_input: Any) -> str:
        try:
            if name == "http_request":
                return self._http_request(_HttpRequestInput.model_validate(raw_input))
            if name == "replay_steps":
                return self._replay(_ReplayInput.model_validate(raw_input).steps)
            if name == "report_bug":
                return self._report(Finding.model_validate(raw_input))
        except ValidationError as exc:
            raise ToolError(f"invalid input for {name}: {exc.errors(include_url=False)}") from exc
        raise ToolError(f"unknown tool: {name}")

    def _http_request(self, req: _HttpRequestInput) -> str:
        res = self._session.request(
            req.method,
            req.path,
            headers=req.headers,
            json=req.body if req.body is not None else None,
        )
        try:
            body: Any = res.json()
        except ValueError:
            body = res.text
        return _clip(json.dumps({"status": res.status_code, "body": body}))

    def _replay(self, steps: list[ReproStep]) -> str:
        return _clip(_trace_json(run_repro(lambda: create_app(self._bugs), steps)))

    def _report(self, finding: Finding) -> str:
        self.findings.append(finding)
        trace = run_repro(lambda: create_app(self._bugs), list(finding.repro_steps))
        note = (
            "WARNING: the repro hit unresolved variables on a fresh instance; it will not "
            "reproduce for a developer. Fix the steps and report again."
            if trace.has_replay_error
            else "Replay on a fresh instance below."
        )
        return _clip(f"Recorded as finding #{len(self.findings)}. {note}\n{_trace_json(trace)}")


def _trace_json(trace: Trace) -> str:
    return json.dumps([{"status": s.status, "body": s.body} for s in trace.steps])


def _clip(text: str) -> str:
    if len(text) <= MAX_BODY_CHARS:
        return text
    return text[:MAX_BODY_CHARS] + f"... [truncated {len(text) - MAX_BODY_CHARS} chars]"
