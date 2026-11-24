# agentic-qa-bench

[![CI](https://github.com/samiaco99/agentic-qa-bench/actions/workflows/ci.yml/badge.svg)](https://github.com/samiaco99/agentic-qa-bench/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)
![Claude](https://img.shields.io/badge/Agent-Claude%20API-D97757)
![mypy](https://img.shields.io/badge/mypy-strict-2A6DB2)

**How do you know your AI tester is right?** This project answers that with numbers. It
runs an exploratory QA agent against an API with **seeded defects**, and scores every bug
report with a deterministic **differential-replay oracle**. The output is a scorecard with
recall, precision, reproducibility, severity accuracy, and cost.

## Why this project exists

An earlier prototype of mine read a Jira ticket, asked an LLM to test SauceDemo, and wrote
a diagnostic report. That report flagged a **HIGH-severity defect**: opening the cart URL
without a session showed the login page. That is the app's intended auth redirect.

The report looked convincing, and nothing in the pipeline could tell it was wrong. Generating
tests and reports with AI is the easy part. The senior-level problem is **measuring whether
the agent's output is true**, so you can compare models, prompts, and costs with evidence
instead of vibes.

## How it works

```mermaid
flowchart LR
    spec[spec.md] --> agent
    subgraph agent [QA agent - Claude API]
      direction TB
      h[http_request] --- r[replay_steps] --- b[report_bug]
    end
    agent -- explores --> sut["Target API<br/>(build with seeded bugs)"]
    agent -- findings + repro steps --> scorer
    subgraph scorer [Differential replay oracle]
      direction TB
      c1[replay on clean build] --> c2{same trace?}
      c2 -- yes --> fp[false positive]
      c2 -- no --> at[replay on each single-bug build<br/>-> attribute to seeded bugs]
    end
    scorer --> card[scorecard.md + result.json]
```

1. **Target.** A small ticketing API (FastAPI) with 20 defects that can be switched on.
   The agent never sees which ones are on.
   - **Core tier (12):** IDOR, promo abuse, rounding, oversell, a state-machine hole, a
     boundary off by one, and similar bugs. The direct test of the broken rule exposes
     them.
   - **Deep tier (8):** the direct test of the rule passes. These bugs need extra state or
     two rules together: a logout that kills the wrong session, idempotency keys leaking
     across users, refunds that ignore the discount, prices rewritten after an admin
     change.
2. **Decoys.** Six behaviours the spec requires that look like bugs, for example an admin
   reading any order, or an old token still working after a new login. Reporting one is a
   false positive, and the scorecard names the trap.
3. **Agent.** Claude gets only the product spec and three tools: explore with HTTP
   requests, dry-run a reproduction on a fresh instance, and file a structured bug report.
4. **Oracle.** The app is deterministic, so replaying a finding's steps on the clean build
   and on the buggy build gives identical responses unless a seeded bug is involved.
   Replaying on single-bug builds tells *which* bug a finding demonstrates. Replaying a
   false positive on builds where one decoy is flipped tells *which* trap it fell into. No
   LLM judge is involved.
5. **Scorecard.** Recall overall and per tier, precision, decoys taken, F1, invalid
   repros, duplicates, severity agreement, tokens, and estimated cost, as Markdown and
   JSON.

Design details and threats to validity: [docs/benchmark-design.md](docs/benchmark-design.md).

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

pytest                              # no API key needed
qabench score tests/fixtures/sample-findings.json   # score sample findings offline
```

Run the built-in agent (uses the Claude API and costs money):

```bash
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env         # git-ignored; or export the variable
qabench run --max-cost 1.50                        # Claude Opus 5.5, effort high, all bugs
qabench run --model claude-sonnet-5-5 --effort medium --max-turns 40 --max-cost 0.75
qabench run --bugs deep --max-cost 0.50            # only the deep tier switched on
qabench run --bugs none                            # clean build: measures hallucinated bugs
```

`--max-cost` stops the session once the estimated spend reaches the cap. The agent is
warned at 80% so it can file what it has. Each run writes
`results/<timestamp>-<model>-<effort>/` with `scorecard.md`, `result.json`, and
`transcript.jsonl` (every tool call, for auditing).

### Any MCP agent can take the exam

`qabench mcp` serves the same tools over MCP (stdio), plus `read_specification`. Claude
Code, IDE agents, or local models can then sit the exam with no API key on the benchmark
side. Every report is written to `findings.json` as it happens, and you score it the same
way:

```bash
qabench score results/<stamp>-mcp/findings.json --agent "Claude Code" --save
```

The agent must be isolated from this repository, or it can read the answers. See
[docs/mcp-mode.md](docs/mcp-mode.md).

## Commands

| Command | Purpose |
| --- | --- |
| `qabench run [--model] [--effort] [--bugs] [--max-turns] [--max-cost]` | Run the built-in agent against a build and score it. `--bugs`: `all`, `none`, `core`, `deep`, or IDs |
| `qabench mcp [--bugs] [--out]` | Serve the exam over MCP for any MCP-capable agent |
| `qabench score FILE [--bugs] [--agent] [--save]` | Score saved findings without calling the API |
| `qabench bugs` | List the seeded bugs and decoys (spoilers) |
| `qabench spec` | Print the specification the agent receives |
| `qabench serve [--bugs] [--port]` | Serve the target API locally for manual or Playwright testing |

## Results

Costs are estimates from token counts ([`pricing.py`](src/qabench/pricing.py)). Every
run, with its scorecard, findings, and tool-call transcript, is in
[`results/published/`](results/published/), one folder per exam version.

### Exam v0.2 (24 November 2026)

All 20 seeded bugs enabled, the six decoys in place, the default 60-turn budget. Runs:
[`results/published/v0.2/`](results/published/v0.2/).

| Agent | Runs | Bugs found | Core tier | Deep tier | Precision | Decoys taken | Severity agreement | Est. cost per run | Time per run |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Claude Sonnet 5.5, effort high | 1 | 15/20 | 11/12 | 4/8 | 15/15 | 0/6 | 85% | $0.43 | 136 s |
| Claude Haiku 5.5, effort medium | 3 | 10, 11, 12 of 20 | 8, 8, 9 of 12 | 2, 3, 3 of 8 | 100% in each run | 0/6 in each run | 78–91% | $0.02 | 82–98 s |

What the numbers say:

- **v0.2 separates models that v0.1 could not.** Sonnet dropped from 10/10 to 15/20, and
  found half of the deep tier. The gap to Haiku widened, from 80–90% against 100% on
  v0.1, to 50–60% against 75% on v0.2.
- **The deep tier works as designed, and agent summaries overstate coverage.** Sonnet's
  own summary lists "login, logout and token revocation" and "the `sales_closed`
  checks" as tested with no problems. It ran the direct test of each rule, which passes,
  and missed the deep bug behind both (`logout-revokes-wrong-session`,
  `closed-sales-bypass-with-promo`). Reading an agent's summary is not the same as
  measuring its coverage.
- **Three bugs were missed by every run:** `closed-sales-bypass-with-promo`,
  `sold-out-events-hidden`, and the core-tier `events-pagination-overlap`, which five of
  six v0.1 runs had found. The transcripts show why. Every agent fetched the event list as
  one page of 50 to look up IDs, then tested only the paging bounds, never two adjacent
  pages. With a spec twice as long, pagination lost attention.
- **Precision stayed at 100%, and no run took a decoy.** In this setup Claude models fail
  by missing bugs, not by inventing them. The decoys are there to catch agents and prompts
  that over-report, which these four runs did not.
- **Cost versus quality.** Sonnet found 3 to 5 more bugs than Haiku, at about 20 times
  the cost per run.

One Sonnet run and three Haiku runs are a small sample. Opus 5.5 and a clean-build
baseline have not been run on v0.2 yet.

### Exam v0.1 (24 November 2026)

Ten seeded bugs, all enabled, no deep tier, no decoys. The exam is preserved at git tag
[`v0.1.0`](https://github.com/samiaco99/agentic-qa-bench/tree/v0.1.0), so these runs
([`results/published/v0.1/`](results/published/v0.1/)) can be re-scored exactly.

| Agent | Runs | Bugs found | Precision | Severity agreement | Est. cost per run | Time per run |
| --- | --- | --- | --- | --- | --- | --- |
| Claude Opus 5.5, effort high | 1 | 10/10 | 10/10 | 90% | $0.62 | 189 s |
| Claude Sonnet 5.5, effort high | 1 | 10/10 | 10/10 | 80% | $0.22 | 81 s |
| Claude Haiku 5.5, effort medium | 3 | 8, 8, 9 of 10 | 100% in each run | 50–88% | $0.01–0.02 | 65–88 s |

Clean-build baseline: Haiku 5.5 tested the build with **no** bugs for 86 tool calls and
filed **0** reports.

What the numbers say:

- **No false positives in six runs.** That includes the clean build. My SauceDemo
  prototype had no specification and no way to check a reproduction before reporting.
  Here the agent has both, and every report it filed was real. Six runs is a small sample.
- **The exam is too easy for frontier models.** Sonnet and Opus both scored 100%. At that
  ceiling the benchmark cannot rank them on finding bugs. It only separates them on cost
  (Opus cost about 3× as much) and on severity judgment. A benchmark only earns trust
  when someone checks whether it still discriminates. This is why v0.2 adds the deep tier
  and the decoys.
- **Single runs mislead.** Haiku missed a different set of bugs in each run:
  `discount-exceeds-subtotal` and `not-found-error-contract` in the first,
  `events-pagination-overlap` and `order-quantity-upper-bound` in the second, and only
  `order-quantity-upper-bound` in the third.
- **Cost versus quality.** Haiku found 80–90% of the bugs, with no false reports, at
  about 1/40 of the cost of an Opus run.

The verdict types are defined in [docs/benchmark-design.md](docs/benchmark-design.md).
[`tests/fixtures/sample-findings.json`](tests/fixtures/sample-findings.json) is a
hand-written v0.2 file with one example of each verdict. Two of its false positives repeat
the SauceDemo mistake. One reports a required `401` as a defect. The other calls the
admin's spec-granted read access a critical security hole, and the scorer blames it on
the `admin-reads-any-order` decoy.

## Project structure

```text
src/qabench/
  target/      system under test: FastAPI app, deterministic store, spec.md,
               bug registry (bugs.py) and decoy registry (decoys.py)
  agent/       tool definitions, prompts, and the agentic loop
  mcp_server.py  the same exam served over MCP
  repro.py     reproduction steps and the deterministic replay engine
  scoring.py   differential-replay oracle and metrics
  report.py    Markdown and JSON scorecards
  pricing.py   token-cost estimates
  cli.py       qabench command
tests/         oracle, seeded-bug, and decoy validity; scoring, replay, and loop tests
docs/          benchmark design and threats to validity
```

## Key design decisions

- **Test the test.** The suite proves the oracle before trusting it. The clean build
  conforms to the spec. Every seeded bug is observable, isolated (no bug masks or
  impersonates another), and still visible with all bugs on. Every decoy trap is a false
  positive on every bug build and is blamed on exactly one decoy. The canonical repros
  score 100%.
- **Measure the failure you care about.** My SauceDemo prototype failed by reporting
  intended behaviour as a bug. Decoys turn that failure into a number, and the flipped
  builds name which trap the agent fell into.
- **Versioned exams.** Scores from different exam versions are not comparable, so the
  version is stored in every result file, `qabench score` warns on a mismatch, and each
  version is tagged in git.
- **Deterministic oracle over LLM-as-judge.** Differential replay is reproducible, free to
  re-run, and cannot be talked into agreeing with the agent.
- **Reproducibility is scored.** A report a developer cannot replay counts against the
  agent, even if the bug is real.
- **The agent cannot see the answers.** It runs fully in-process with no network, gets only
  the spec, and its tools never reveal which bugs are on.
- **Agent-agnostic.** The same tools are served to the built-in API agent and over MCP,
  so different agents are graded by the same oracle on the same exam.
- **A hand-written agent loop.** It enforces a hard turn budget and a cost cap, accounts
  tokens on every turn, logs every tool call for audit, and stops cleanly on refusals or
  truncated turns.
  It uses prompt caching, adaptive thinking with a configurable effort, and server-side
  refusal fallbacks where the model supports them.
- **CI without secrets.** Lint, strict typing, tests, and an offline scoring run happen on
  every push. Agent evals run as a manual workflow, because each run costs money.

## CI

- **[ci.yml](.github/workflows/ci.yml)** runs on push and pull requests. It runs ruff,
  `mypy --strict`, and pytest on Python 3.12–3.14, then scores the sample findings into
  the job summary.
- **[eval.yml](.github/workflows/eval.yml)** is started manually with a model, effort, bug
  set, and turn budget. It needs the `ANTHROPIC_API_KEY` secret, publishes the scorecard
  to the job summary, and uploads the run as an artifact.

## Roadmap

- [x] **Clean-build noise baseline.** Haiku 5.5 filed 0 reports on the bug-free build.
- [x] **A harder exam (v0.2).** Frontier models saturated v0.1. v0.2 adds a deep tier of
      eight bugs that need state sequences, a second user or session, or two interacting
      rules, plus six decoys to stress precision.
- [ ] **Validated test generation.** The agent turns confirmed findings into pytest
      regression tests. A test is accepted only if it passes on the clean build and fails
      on the buggy one, which is mutation testing applied to AI-written tests.
- [ ] **Repeated-run comparisons.** N runs per model and effort on v0.2, Opus 5.5
      included, reported as mean and spread, plus a quality-versus-cost frontier.
- [ ] **UI target.** Browser exploration through Playwright, with the same oracle applied
      to UI-level traces.

## Known limitations

A single run is an anecdote, because LLM agents are non-deterministic. v0.1 was saturated
by frontier models. The first v0.2 runs discriminate, but four runs from two models are
a small sample, and Opus 5.5 has not been run on v0.2. No run has taken a decoy yet. A
false positive is blamed on a decoy by what its repro does, not by what its text claims.
A genuine defect in the clean build would be scored as a false positive. The bug and
decoy registries are public, so models trained later could be contaminated. More detail
is in [docs/benchmark-design.md](docs/benchmark-design.md#threats-to-validity).

## License

MIT
