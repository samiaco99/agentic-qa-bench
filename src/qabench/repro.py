"""Reproduction steps and the deterministic replay engine.

A reproduction is a list of HTTP steps executed against a *fresh* in-process app instance.
Steps can capture values from a response (``capture``) and reference them later with
``{{name}}`` templates, so a repro never depends on IDs or tokens from an earlier session.

Replay never raises on application behaviour: anything the app does (including a 500)
is recorded in the trace, because the trace is what the oracle compares.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field

HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]

_TEMPLATE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
_WHOLE_TEMPLATE = re.compile(r"^\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}$")

# Status used in a trace when a step could not be sent (e.g. an unresolved variable).
REPLAY_ERROR_STATUS = 0


class ReproStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    method: HttpMethod
    path: str = Field(pattern=r"^/", description="Path plus optional query string.")
    headers: dict[str, str] = Field(default_factory=dict)
    body: Any = None
    capture: dict[str, str] = Field(
        default_factory=dict,
        description="Variable name -> dotted path into the JSON response, e.g. 'items.0.id'.",
    )


@dataclass(frozen=True)
class StepResult:
    status: int
    body: Any

    @property
    def is_replay_error(self) -> bool:
        return self.status == REPLAY_ERROR_STATUS


@dataclass(frozen=True)
class Trace:
    steps: tuple[StepResult, ...]

    def observable(self) -> tuple[tuple[int, Any], ...]:
        return tuple((s.status, _freeze(s.body)) for s in self.steps)

    @property
    def has_replay_error(self) -> bool:
        return any(s.is_replay_error for s in self.steps)

    def differs_from(self, other: Trace) -> bool:
        return self.observable() != other.observable()


class UnresolvedVariableError(Exception):
    pass


def lookup_path(data: Any, dotted: str) -> Any:
    current = data
    for part in dotted.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            raise KeyError(dotted)
    return current


def render(value: Any, variables: dict[str, Any]) -> Any:
    """Substitute ``{{name}}`` templates. A string that is exactly one template keeps the
    variable's original type, so ``"eventId": "{{eid}}"`` stays an integer."""
    if isinstance(value, str):
        whole = _WHOLE_TEMPLATE.match(value)
        if whole:
            return _resolve(whole.group(1), variables)
        return _TEMPLATE.sub(lambda m: str(_resolve(m.group(1), variables)), value)
    if isinstance(value, list):
        return [render(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: render(item, variables) for key, item in value.items()}
    return value


def run_repro(app_factory: Callable[[], FastAPI], steps: list[ReproStep]) -> Trace:
    """Execute ``steps`` against a brand-new app instance and return the observed trace."""
    variables: dict[str, Any] = {}
    results: list[StepResult] = []
    with TestClient(app_factory(), raise_server_exceptions=False) as client:
        for step in steps:
            try:
                path = render(step.path, variables)
                headers = render(step.headers, variables)
                body = render(step.body, variables)
            except UnresolvedVariableError as exc:
                results.append(StepResult(REPLAY_ERROR_STATUS, {"replayError": str(exc)}))
                continue

            response = client.request(
                step.method,
                path,
                headers=headers,
                json=body if step.body is not None else None,
            )
            parsed = _parse_body(response.content, response.headers.get("content-type", ""))
            results.append(StepResult(response.status_code, parsed))

            for name, dotted in step.capture.items():
                try:
                    variables[name] = lookup_path(parsed, dotted)
                except KeyError:
                    variables.pop(name, None)
    return Trace(tuple(results))


def _resolve(name: str, variables: dict[str, Any]) -> Any:
    if name not in variables:
        raise UnresolvedVariableError(f"unresolved variable: {name}")
    return variables[name]


def _parse_body(content: bytes, content_type: str) -> Any:
    if not content:
        return None
    if "json" in content_type:
        try:
            return json.loads(content)
        except ValueError:
            pass
    return content.decode("utf-8", errors="replace")


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple(sorted((k, _freeze(v)) for k, v in value.items()))
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value
