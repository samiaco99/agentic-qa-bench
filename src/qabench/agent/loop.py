"""The agentic loop.

A hand-written loop rather than the SDK tool runner, because the harness needs per-turn
control: a hard turn budget, token accounting on every response, an audit log of each
tool call, and a clean stop on refusals or truncated turns.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, cast

import anthropic
from anthropic.types.beta import BetaMessage, BetaTextBlock, BetaToolUseBlock

from qabench.agent.prompts import BUDGET_WARNING, KICKOFF, SYSTEM_PROMPT
from qabench.agent.tools import TOOL_DEFINITIONS, ToolBox, ToolError
from qabench.findings import Finding
from qabench.pricing import Usage
from qabench.target import load_spec

if TYPE_CHECKING:
    from anthropic.types.beta import BetaMessageParam

Effort = Literal["low", "medium", "high", "xhigh", "max"]

# Models that accept server-side refusal fallbacks (``fallbacks: "default"``).
FALLBACK_MODELS = frozenset(
    {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
)
FALLBACK_BETA = "server-side-fallback-2026-07-01"
BUDGET_WARNING_AT = 8
COST_WARNING_SHARE = 0.8
TOOL_LOG_PREVIEW = 600


@dataclass(frozen=True)
class AgentConfig:
    model: str = "claude-opus-5-5"
    effort: Effort = "high"
    max_turns: int = 60
    max_tokens: int = 16000
    # Hard stop on estimated spend; needs a model listed in pricing.PRICES.
    max_cost_usd: float | None = None


@dataclass
class AgentRun:
    config: AgentConfig
    findings: list[Finding] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    turns: int = 0
    tool_calls: int = 0
    stop_reason: str = "not_started"
    served_by: set[str] = field(default_factory=set)
    summary: str = ""
    duration_s: float = 0.0
    tool_log: list[dict[str, Any]] = field(default_factory=list)


def run_agent(client: anthropic.Anthropic, config: AgentConfig, bugs: frozenset[str]) -> AgentRun:
    run = AgentRun(config=config)
    started = time.monotonic()
    # Assistant turns are appended exactly as returned (thinking and fallback blocks
    # included), so the history stays append-only and replays cleanly.
    messages: list[dict[str, Any]] = [{"role": "user", "content": KICKOFF}]

    with ToolBox(bugs) as tools:
        try:
            while True:
                if run.turns >= config.max_turns:
                    run.stop_reason = "turn_budget_exhausted"
                    break
                response = _create(client, config, messages)
                run.turns += 1
                _account(run, response)

                if response.stop_reason == "refusal":
                    run.stop_reason = "refusal"
                    break
                tool_uses = [b for b in response.content if isinstance(b, BetaToolUseBlock)]
                if response.stop_reason == "max_tokens":
                    # A tool call cut off mid-input must not run.
                    run.stop_reason = "max_tokens"
                    break
                if not tool_uses:
                    run.stop_reason = response.stop_reason or "end_turn"
                    run.summary = "\n".join(
                        b.text for b in response.content if isinstance(b, BetaTextBlock)
                    )
                    break

                messages.append({"role": "assistant", "content": response.content})
                # Tools of an already-paid turn still run, so its bug reports are kept.
                results: list[dict[str, Any]] = [_execute(run, tools, b) for b in tool_uses]
                warning = _budget_warning(run)
                if warning:
                    results.append({"type": "text", "text": warning})
                messages.append({"role": "user", "content": results})
                if _over_cost_budget(run):
                    run.stop_reason = "cost_budget_exhausted"
                    break
        except anthropic.APIError as exc:
            run.stop_reason = f"api_error: {type(exc).__name__}: {exc}"
        finally:
            run.findings = list(tools.findings)
            run.duration_s = round(time.monotonic() - started, 1)
    return run


def _create(
    client: anthropic.Anthropic, config: AgentConfig, messages: list[dict[str, Any]]
) -> BetaMessage:
    fallback: dict[str, Any] = (
        {"betas": [FALLBACK_BETA], "fallbacks": "default"}
        if config.model in FALLBACK_MODELS
        else {}
    )
    # Annotated because **fallback widens the overload match to Any.
    response: BetaMessage = client.beta.messages.create(
        model=config.model,
        max_tokens=config.max_tokens,
        system=[
            {"type": "text", "text": SYSTEM_PROMPT},
            {"type": "text", "text": "# Specification\n\n" + load_spec()},
        ],
        tools=cast("Any", TOOL_DEFINITIONS),
        messages=cast("list[BetaMessageParam]", messages),
        output_config={"effort": config.effort},
        # Automatic caching: the system prompt, spec and growing history are re-read
        # every turn, so each turn reads the previous turn's prefix from cache.
        cache_control={"type": "ephemeral"},
        **fallback,
    )
    return response


def _budget_warning(run: AgentRun) -> str | None:
    turns_left = run.config.max_turns - run.turns
    if turns_left <= BUDGET_WARNING_AT:
        return BUDGET_WARNING.format(left=f"{turns_left} model turns")
    cap = run.config.max_cost_usd
    cost = run.usage.estimated_cost(run.config.model)
    if cap is not None and cost is not None and cost >= cap * COST_WARNING_SHARE:
        return BUDGET_WARNING.format(left="less than 20% of the cost budget")
    return None


def _over_cost_budget(run: AgentRun) -> bool:
    cap = run.config.max_cost_usd
    cost = run.usage.estimated_cost(run.config.model)
    return cap is not None and cost is not None and cost >= cap


def _account(run: AgentRun, response: BetaMessage) -> None:
    usage = response.usage
    run.usage.input_tokens += usage.input_tokens
    run.usage.output_tokens += usage.output_tokens
    run.usage.cache_creation_input_tokens += usage.cache_creation_input_tokens or 0
    run.usage.cache_read_input_tokens += usage.cache_read_input_tokens or 0
    run.served_by.add(response.model)


def _execute(run: AgentRun, tools: ToolBox, block: BetaToolUseBlock) -> dict[str, Any]:
    run.tool_calls += 1
    try:
        output, is_error = tools.call(block.name, block.input), False
    except ToolError as exc:
        output, is_error = str(exc), True
    run.tool_log.append(
        {
            "turn": run.turns,
            "tool": block.name,
            "input": block.input,
            "is_error": is_error,
            "output_preview": output[:TOOL_LOG_PREVIEW],
        }
    )
    return {"type": "tool_result", "tool_use_id": block.id, "content": output, "is_error": is_error}
