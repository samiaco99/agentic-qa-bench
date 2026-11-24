"""Render a scorecard as Markdown (for humans and CI summaries) and JSON (for trends)."""

from __future__ import annotations

from typing import Any

from qabench.agent import AgentRun
from qabench.scoring import Scorecard, Verdict
from qabench.target.bugs import BUGS


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def render_markdown(card: Scorecard, run: AgentRun | None = None, agent: str | None = None) -> str:
    lines = ["# QA agent scorecard", ""]
    if agent:
        lines += [f"- **Agent:** {agent}", ""]
    if run is not None:
        cost = run.usage.estimated_cost(run.config.model)
        lines += [
            f"- **Model:** `{run.config.model}` (effort `{run.config.effort}`)"
            + (f", served by {', '.join(sorted(run.served_by))}" if run.served_by else ""),
            f"- **Session:** {run.turns} turns, {run.tool_calls} tool calls, "
            f"{run.duration_s}s, stopped on `{run.stop_reason}`",
            f"- **Tokens:** {run.usage.input_tokens:,} in, {run.usage.output_tokens:,} out, "
            f"{run.usage.cache_read_input_tokens:,} cache read, "
            f"{run.usage.cache_creation_input_tokens:,} cache write",
            f"- **Estimated cost:** {'n/a' if cost is None else f'${cost:.2f}'}",
            "",
        ]

    seeded = len(card.bugs_in_build)
    lines += [
        "| Metric | Value |",
        "| --- | --- |",
        f"| Recall (seeded bugs found) | {len(card.detected)}/{seeded} ({_pct(card.recall)}) |",
        f"| Precision (confirmed findings) | {card.count(Verdict.CONFIRMED)}/"
        f"{card.total_findings} ({_pct(card.precision)}) |",
        f"| F1 | {_pct(card.f1)} |",
        f"| False positives | {card.count(Verdict.FALSE_POSITIVE)} |",
        f"| Invalid repros | {card.count(Verdict.INVALID_REPRO)} |",
        f"| Duplicate reports | {card.duplicates} |",
        f"| Severity agreement | {_pct(card.severity_agreement)} |",
        "",
        "## Seeded bugs",
        "",
        "| Bug | Category | Severity | Found by |",
        "| --- | --- | --- | --- |",
    ]
    for bug_id in card.bugs_in_build:
        bug = BUGS[bug_id]
        found = card.detected.get(bug_id)
        by = ", ".join(f"#{i + 1}" for i in found) if found else "**missed**"
        lines.append(f"| `{bug_id}` | {bug.category} | {bug.severity} | {by} |")

    lines += ["", "## Findings", ""]
    if not card.scored:
        lines.append("_No findings reported._")
    else:
        lines += [
            "| # | Verdict | Severity | Title | Demonstrates |",
            "| --- | --- | --- | --- | --- |",
        ]
        for s in card.scored:
            demonstrates = ", ".join(f"`{b}`" for b in s.attributed_to) or (
                "bug interaction" if s.verdict is Verdict.CONFIRMED else "-"
            )
            if s.duplicate:
                demonstrates += " (duplicate)"
            title = s.finding.title.replace("|", "\\|")
            lines.append(
                f"| {s.index + 1} | {s.verdict} | {s.finding.severity} | {title} | {demonstrates} |"
            )
    if run is not None and run.summary:
        lines += ["", "## Agent summary", "", run.summary.strip()]
    return "\n".join(lines) + "\n"


def to_json(card: Scorecard, run: AgentRun | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "bugs": list(card.bugs_in_build),
        "score": {
            "recall": card.recall,
            "precision": card.precision,
            "f1": card.f1,
            "detected": {k: [i + 1 for i in v] for k, v in card.detected.items()},
            "missed": [b for b in card.bugs_in_build if b not in card.detected],
            "false_positives": card.count(Verdict.FALSE_POSITIVE),
            "invalid_repros": card.count(Verdict.INVALID_REPRO),
            "duplicates": card.duplicates,
            "severity_agreement": card.severity_agreement,
            "verdicts": [
                {"finding": s.index + 1, "verdict": s.verdict, "attributed_to": s.attributed_to}
                for s in card.scored
            ],
        },
        "findings": [s.finding.model_dump(mode="json") for s in card.scored],
    }
    if run is not None:
        data["run"] = {
            "model": run.config.model,
            "effort": run.config.effort,
            "max_turns": run.config.max_turns,
            "turns": run.turns,
            "tool_calls": run.tool_calls,
            "stop_reason": run.stop_reason,
            "served_by": sorted(run.served_by),
            "duration_s": run.duration_s,
            "usage": vars(run.usage),
            "estimated_cost_usd": run.usage.estimated_cost(run.config.model),
            "summary": run.summary,
        }
    return data
