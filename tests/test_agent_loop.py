"""Loop behaviour with a scripted fake client - no API key or network needed."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast

import anthropic
from anthropic.types.beta import BetaMessage, BetaTextBlock, BetaToolUseBlock, BetaUsage

from qabench.agent import AgentConfig, run_agent
from qabench.target.bugs import ALL_BUG_IDS, BUGS


def _message(content: list[Any], stop_reason: str, model: str = "claude-opus-5-5") -> BetaMessage:
    return BetaMessage.model_construct(
        id="msg_test",
        type="message",
        role="assistant",
        model=model,
        content=content,
        stop_reason=stop_reason,
        stop_sequence=None,
        usage=BetaUsage.model_construct(
            input_tokens=100,
            output_tokens=20,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=50,
        ),
    )


def _tool(tool_id: str, name: str, tool_input: dict[str, Any]) -> BetaToolUseBlock:
    return BetaToolUseBlock.model_construct(
        type="tool_use", id=tool_id, name=name, input=tool_input
    )


class FakeClient:
    """Mimics ``client.beta.messages.create`` and records every request."""

    def __init__(self, responses: Iterator[BetaMessage]) -> None:
        self._responses = responses
        self.requests: list[dict[str, Any]] = []
        self.beta = self
        self.messages = self

    def create(self, **kwargs: Any) -> BetaMessage:
        # Snapshot the history: the loop keeps appending to the same list.
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return next(self._responses)


def _client(*responses: BetaMessage) -> anthropic.Anthropic:
    return cast(anthropic.Anthropic, FakeClient(iter(responses)))


def test_full_session_collects_findings_and_usage() -> None:
    repro = [step.model_dump() for step in BUGS["not-found-error-contract"].canonical_repro]
    client = _client(
        _message(
            [_tool("t1", "http_request", {"method": "GET", "path": "/events/9999"})], "tool_use"
        ),
        _message(
            [
                _tool(
                    "t2",
                    "report_bug",
                    {
                        "title": "404 body ignores the error envelope",
                        "severity": "low",
                        "category": "contract",
                        "spec_rule": "Every error response has ... this body shape",
                        "expected": '{"error": {...}}',
                        "actual": '{"detail": "Not Found"}',
                        "repro_steps": repro,
                    },
                ),
                _tool("t3", "http_request", {"method": "GET", "path": "no-slash"}),
            ],
            "tool_use",
        ),
        _message([BetaTextBlock.model_construct(type="text", text="Done.")], "end_turn"),
    )

    run = run_agent(client, AgentConfig(max_turns=30), ALL_BUG_IDS)

    assert run.stop_reason == "end_turn"
    assert (run.turns, run.tool_calls, run.summary) == (3, 3, "Done.")
    assert [f.title for f in run.findings] == ["404 body ignores the error envelope"]
    assert run.usage.input_tokens == 300
    assert run.usage.cache_read_input_tokens == 150
    assert [e["is_error"] for e in run.tool_log] == [False, False, True]
    assert '"detail": "Not Found"' in run.tool_log[0]["output_preview"]

    fake = cast(FakeClient, client)
    first = fake.requests[0]
    assert first["fallbacks"] == "default"
    assert first["output_config"] == {"effort": "high"}
    assert first["cache_control"] == {"type": "ephemeral"}
    # Both tool results of turn 2 go back together in a single user message.
    last_user = fake.requests[2]["messages"][-1]
    assert [b["tool_use_id"] for b in last_user["content"]] == ["t2", "t3"]


def test_turn_budget_stops_the_loop_and_warns_the_agent() -> None:
    def forever() -> Iterator[BetaMessage]:
        while True:
            yield _message(
                [_tool("t", "http_request", {"method": "GET", "path": "/events"})], "tool_use"
            )

    client = cast(anthropic.Anthropic, FakeClient(forever()))
    run = run_agent(client, AgentConfig(max_turns=2), frozenset())

    assert (run.stop_reason, run.turns) == ("turn_budget_exhausted", 2)
    warning = cast(FakeClient, client).requests[1]["messages"][-1]["content"][-1]
    assert warning["type"] == "text"
    assert "1 model turns left" in warning["text"]


def test_refusal_stops_without_running_tools() -> None:
    client = _client(
        _message([_tool("t", "http_request", {"method": "GET", "path": "/events"})], "refusal")
    )
    run = run_agent(client, AgentConfig(), frozenset())
    assert (run.stop_reason, run.tool_calls) == ("refusal", 0)


def test_models_without_server_fallback_do_not_send_it() -> None:
    client = _client(_message([BetaTextBlock.model_construct(type="text", text="ok")], "end_turn"))
    run_agent(client, AgentConfig(model="claude-haiku-5-5"), frozenset())
    request = cast(FakeClient, client).requests[0]
    assert "fallbacks" not in request
    assert "betas" not in request


def test_cost_cap_stops_after_running_the_paid_turns_tools() -> None:
    def forever() -> Iterator[BetaMessage]:
        while True:
            yield _message(
                [_tool("t", "http_request", {"method": "GET", "path": "/events"})], "tool_use"
            )

    # Each fake turn costs (100*4 + 20*20 + 50*0.2) / 1e6 = $0.00081 on Opus 5.5 pricing.
    client = cast(anthropic.Anthropic, FakeClient(forever()))
    run = run_agent(client, AgentConfig(max_turns=60, max_cost_usd=0.002), frozenset())

    assert run.stop_reason == "cost_budget_exhausted"
    assert (run.turns, run.tool_calls) == (3, 3)
    # From 80% of the cap onwards the agent is told to wrap up.
    warning = cast(FakeClient, client).requests[2]["messages"][-1]["content"][-1]
    assert "cost budget" in warning["text"]
