"""Command line entry point: ``qabench run | mcp | score | bugs | spec | serve``."""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import get_args

from qabench.agent.loop import AgentConfig, Effort
from qabench.findings import FindingsFile
from qabench.pricing import PRICES
from qabench.report import render_markdown, to_json
from qabench.scoring import score
from qabench.target import EXAM_VERSION, load_spec
from qabench.target.bugs import BUGS, parse_bug_selection
from qabench.target.decoys import DECOYS

BUGS_HELP = "all | none | core | deep | comma-separated bug IDs"


def main(argv: list[str] | None = None) -> int:
    # Windows consoles and pipes may default to cp1252; agent summaries can hold any Unicode.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="qabench", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="run the built-in Claude API agent and score it")
    run_p.add_argument("--model", default=AgentConfig.model)
    run_p.add_argument("--effort", default=AgentConfig.effort, choices=get_args(Effort))
    run_p.add_argument("--bugs", default="all", help=BUGS_HELP)
    run_p.add_argument("--max-turns", type=int, default=AgentConfig.max_turns)
    run_p.add_argument("--max-cost", type=float, help="stop once estimated spend reaches USD")
    run_p.add_argument("--out", type=Path, default=Path("results"))

    mcp_p = sub.add_parser("mcp", help="serve the exam over MCP (stdio) for any MCP agent")
    mcp_p.add_argument("--bugs", default="all", help=BUGS_HELP)
    mcp_p.add_argument("--out", type=Path, help="output folder (default: results/<stamp>-mcp)")

    score_p = sub.add_parser("score", help="score saved findings without calling the API")
    score_p.add_argument("findings", type=Path)
    score_p.add_argument("--bugs", help="override the bug set recorded in the file")
    score_p.add_argument("--agent", help="label for the agent, shown in the scorecard")
    score_p.add_argument("--save", action="store_true", help="write scorecard next to the file")

    sub.add_parser("bugs", help="list seeded bugs and decoys (spoilers)")
    sub.add_parser("spec", help="print the specification the agent receives")

    serve_p = sub.add_parser("serve", help="run the target API locally for manual testing")
    serve_p.add_argument("--bugs", default="none")
    serve_p.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)
    match args.command:
        case "run":
            return _run(args)
        case "mcp":
            return _mcp(args)
        case "score":
            return _score(args)
        case "bugs":
            print(f"Exam v{EXAM_VERSION}: {len(BUGS)} seeded bugs\n")
            for bug in BUGS.values():
                print(f"{bug.id:32} {bug.tier:5} {bug.severity:9} {bug.category:14} {bug.title}")
            print(f"\n{len(DECOYS)} decoys (spec-required behaviour that looks like a bug)\n")
            for decoy in DECOYS.values():
                print(f"{decoy.id:32} {decoy.title}")
            return 0
        case "spec":
            print(load_spec())
            return 0
        case "serve":
            return _serve(args)
    return 2


def load_dotenv(path: Path) -> None:
    """Minimal .env support: KEY=VALUE lines; never overrides variables already set."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def _run(args: argparse.Namespace) -> int:
    import anthropic

    from qabench.agent import run_agent

    load_dotenv(Path(".env"))
    if args.max_cost is not None and args.model not in PRICES:
        print(f"--max-cost needs a priced model; {args.model} is not in pricing.PRICES")
        return 2
    bugs = parse_bug_selection(args.bugs)
    config = AgentConfig(
        model=args.model,
        effort=args.effort,
        max_turns=args.max_turns,
        max_cost_usd=args.max_cost,
    )
    budget = f", cost cap ${config.max_cost_usd:.2f}" if config.max_cost_usd else ""
    print(f"Running {config.model} (effort {config.effort}{budget}) on {len(bugs)} seeded bugs...")

    run = run_agent(anthropic.Anthropic(max_retries=4), config, bugs)
    card = score(run.findings, bugs)

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out_dir: Path = args.out / f"{stamp}-{config.model}-{config.effort}"
    out_dir.mkdir(parents=True, exist_ok=True)
    markdown = render_markdown(card, run)
    (out_dir / "scorecard.md").write_text(markdown, encoding="utf-8")
    (out_dir / "result.json").write_text(json.dumps(to_json(card, run), indent=2), "utf-8")
    with (out_dir / "transcript.jsonl").open("w", encoding="utf-8") as fh:
        for entry in run.tool_log:
            fh.write(json.dumps(entry) + "\n")

    print(markdown)
    print(f"Saved to {out_dir}")
    return 0 if not run.stop_reason.startswith("api_error") else 1


def _mcp(args: argparse.Namespace) -> int:
    from qabench.mcp_server import default_out_dir, serve_stdio

    out_dir = args.out or default_out_dir(Path("results"))
    # stdout carries the MCP protocol: anything human-readable goes to stderr.
    print(f"qabench MCP exam: findings -> {out_dir / 'findings.json'}", file=sys.stderr)
    serve_stdio(parse_bug_selection(args.bugs), out_dir)
    return 0


def _score(args: argparse.Namespace) -> int:
    data = FindingsFile.model_validate_json(args.findings.read_text(encoding="utf-8"))
    produced_on = data.exam or "0.1"
    if produced_on != EXAM_VERSION:
        print(
            f"warning: these findings come from exam v{produced_on} but are scored against "
            f"exam v{EXAM_VERSION}; reproduce old scores from git tag v{produced_on}.0",
            file=sys.stderr,
        )
    bugs = parse_bug_selection(args.bugs) if args.bugs else parse_bug_selection(",".join(data.bugs))
    card = score(data.findings, bugs)
    markdown = render_markdown(card, agent=args.agent)
    print(markdown)
    if args.save:
        folder = args.findings.parent
        (folder / "scorecard.md").write_text(markdown, encoding="utf-8")
        result = {"agent": args.agent, **to_json(card)}
        (folder / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"Saved scorecard.md and result.json to {folder}")
    return 0


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from qabench.target import create_app

    uvicorn.run(create_app(parse_bug_selection(args.bugs)), port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
