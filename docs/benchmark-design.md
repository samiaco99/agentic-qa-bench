# Benchmark design

How `agentic-qa-bench` decides whether an AI QA agent was right, and why the numbers can
be trusted (and where they can't).

## The question

"The agent found 9 bugs" means nothing on its own. A useful evaluation has to answer:

1. **Recall** — of the defects that really exist, how many did it find?
2. **Precision** — of the defects it reported, how many are real?
3. **Actionability** — can a developer reproduce each report?
4. **Cost** — what did it spend to get there?

Answering 1 requires knowing the real defects in advance. Answering 2 without a human
triaging every report requires an oracle. This benchmark gets both by construction.

## Seeded defects (ground truth)

The target is a small ticketing API (`src/qabench/target/`) where each defect is a switch:
`create_app({"order-idor", "oversell-by-one"})` builds an instance with exactly those
bugs. `create_app()` is the **clean build**. The registry in `target/bugs.py` records each
bug's category and severity, plus a **canonical reproduction**. The agent sees none of it.
It only gets `spec.md` and three tools.

The ten bugs cover the risk areas a senior tester is expected to probe:

| Category | Bug |
| --- | --- |
| Security | IDOR on `GET /orders/{id}` |
| Business rule | single-use promo can be reused |
| Calculation | half-up rounding truncated; fixed discount not capped at subtotal |
| Inventory | cancel does not restock; availability off by one (oversell) |
| State machine | cancelled order can be cancelled again |
| Validation / boundary | quantity 7 accepted (max 6) |
| Functional | pagination overlap between pages |
| Contract | 404 body ignores the error envelope |

## Differential replay (the oracle)

Every finding must carry `repro_steps`: HTTP steps that start from a fresh instance, with
`capture` and `{{var}}` templates for tokens and IDs. Because the app is deterministic
(seeded data, sequential IDs, counter-derived tokens), two fresh instances that receive
the same steps return byte-identical responses **unless a seeded bug changes behaviour**.

For each finding the scorer (`scoring.py`):

1. Replays the steps on the build under test. If a template variable cannot be resolved,
   the verdict is **invalid_repro**: nobody could act on that report.
2. Replays them on the clean build. Identical trace means **false_positive**: the reported
   behaviour is what the specification-conforming app does.
3. Otherwise it is **confirmed**. The scorer then replays the steps on each *single-bug*
   build, and every bug whose build diverges from clean is attributed to the finding. A
   finding can demonstrate several bugs, or none individually (two bugs interacting).

A confirmed finding whose bugs were all already credited is counted as a **duplicate**.

No LLM is used to judge, so scores are deterministic, free to recompute, and re-scorable
later with `qabench score result.json`.

## Metrics

| Metric | Definition |
| --- | --- |
| Recall | seeded bugs with at least one attributed finding / seeded bugs in the build |
| Precision | confirmed findings / all findings |
| F1 | harmonic mean of the two |
| Duplicates | confirmed findings that add no new bug |
| Severity agreement | among confirmed findings attributed to exactly one bug, share whose severity matches the registry |
| Cost | tokens per category, priced with `pricing.py` (estimate) |

## Testing the test

The benchmark is only as good as its oracle, so the suite checks the oracle itself:

- `test_target_spec.py` — the clean build conforms to `spec.md`. If it did not, correct
  agent reports would be scored as false positives.
- `test_seeded_bugs.py` — for every bug, the canonical repro (a) diverges from clean,
  (b) diverges on *no other* single-bug build, so bugs do not mask or impersonate each
  other, and (c) still diverges with all bugs enabled.
- `test_scoring.py` — the canonical repros score 100% precision, recall, and severity
  agreement; a hand-written findings file covering every verdict scores exactly as expected.

## Threats to validity

- **Ceiling effect (observed).** In the first runs Claude Sonnet 5.5 and Claude Opus 5.5
  both found 10/10 with no false positives. A saturated exam cannot rank agents on
  bug-finding, only on cost and severity judgment. v0.2 needs harder defects.
- **Run-to-run variance.** LLM agents are non-deterministic. A single run is an anecdote;
  compare configurations over repeated runs and report the spread.
- **Unseeded defects.** If the agent finds a genuine defect in the clean build, the oracle
  scores it as a false positive. Read false positives before trusting precision; a real
  one is a bug in the benchmark and should become a fix plus a new test.
- **Observable-only oracle.** Replay compares HTTP responses. A defect that only changes
  internal state is invisible until a later step reads that state; the canonical repros
  show how (e.g. reading `remaining` after a cancel).
- **Contamination.** The bug registry is public. Rotating or private bug sets would be
  needed to compare models trained after this repository was published.
- **Small target.** Ten bugs in five endpoints measure methodology, not scale. Wider
  coverage comes from more targets, not more bugs in this one.
