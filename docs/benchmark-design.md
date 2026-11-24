# Benchmark design

How `agentic-qa-bench` decides whether an AI QA agent was right, and why the numbers can
be trusted (and where they can't). This describes exam **v0.2**. Exam v0.1 is preserved
at git tag [`v0.1.0`](https://github.com/samiaco99/agentic-qa-bench/tree/v0.1.0).

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
bug's tier, category, and severity, plus a **canonical reproduction**. The agent sees none
of it. It only gets `spec.md` and three tools.

### Why v0.2 has tiers

In v0.1, Claude Sonnet 5.5 and Claude Opus 5.5 both found 10 of 10 bugs. Every v0.1 bug
showed up on the **direct test** of the rule it broke: test "quantity at most 6" with 7
and the bug appears. A frontier model tests every rule in a short spec, so it found
everything, and a saturated exam cannot rank agents.

v0.2 keeps those bugs and adds a second tier:

- **core** (12 bugs): the direct test of the violated rule exposes the bug.
- **deep** (8 bugs): the direct test of the rule **passes**. Exposing the bug needs extra
  state (a second session or user, a cancelled order, a sold-out event, an admin change)
  or a second rule in play.

The tier is defined by the shape of the bug, not by how often agents miss it, so it does
not depend on any particular model.

| Bug | Tier | The direct test that passes | What exposes it |
| --- | --- | --- | --- |
| `logout-revokes-wrong-session` | deep | log in, log out, token is rejected | two sessions: logging out of one kills the other |
| `closed-sales-bypass-with-promo` | deep | order a closed event, get `409` | the same order with a promo code |
| `ticket-limit-counts-cancelled` | deep | 6 + 3 tickets is rejected | cancel, then buy again up to the limit |
| `idempotency-key-not-user-scoped` | deep | replaying your own key returns your order | a second user reusing the same key |
| `idempotent-replay-reserves-again` | deep | the replay returns the same order | checking `remaining` after the replay |
| `order-price-not-snapshotted` | deep | an admin price change updates the event | reading an order placed before the change |
| `sold-out-events-hidden` | deep | the event list is complete | selling an event out, then listing |
| `refund-ignores-discount` | deep | a cancel refunds total minus fee | cancelling an order that used a promo |

The core tier adds `fan-can-update-event` (security) and `fee-cap-ignored` (calculation
boundary) to the ten v0.1 bugs. They cover the areas a senior tester is expected to
probe:

| Category | Core bugs |
| --- | --- |
| Security | IDOR on `GET /orders/{id}`; fan can use the admin event update |
| Business rule | single-use promo can be reused |
| Calculation | half-up rounding truncated; fixed discount not capped; fee not capped |
| Inventory | cancel does not restock; availability off by one (oversell) |
| State machine | cancelled order can be cancelled again |
| Validation / boundary | quantity 7 accepted (max 6) |
| Functional | pagination overlap between pages |
| Contract | 404 body ignores the error envelope |

## Decoys (precision traps)

Precision is easy to keep at 100% when every odd-looking behaviour is a real bug. v0.2
adds **decoys**: behaviour the spec explicitly requires that a careless tester would call
a bug. Reporting one is a false positive. It is the failure that motivated this project: a
report that called an intended auth redirect a HIGH-severity defect.

| Decoy | The spec requires | A careless tester expects |
| --- | --- | --- |
| `earlier-tokens-stay-valid` | earlier tokens stay valid after a new login | a new login ends older sessions |
| `promo-codes-case-sensitive` | `fan10` is not `FAN10` | codes match in any case |
| `admin-reads-any-order` | admins can read every order | only the owner can read an order |
| `foreign-order-is-404` | someone else's order is `404`, never `403` | `403` for an order that exists |
| `page-past-end-is-empty` | a page after the last is `200` with no items | `404` for a missing page |
| `idempotent-replay-returns-200` | a replayed order returns `200` | every successful create returns `201` |

Each decoy is also a switch, in the other direction: `create_app(flip_decoys={id})` builds
an app that does what the careless tester expects. Flipped builds are used only by the
scorer. No agent is ever served one.

## Differential replay (the oracle)

Every finding must carry `repro_steps`: HTTP steps that start from a fresh instance, with
`capture` and `{{var}}` templates for tokens and IDs. Because the app is deterministic
(seeded data, sequential IDs, counter-derived tokens), two fresh instances that receive
the same steps return byte-identical responses **unless a seeded bug changes behaviour**.

For each finding the scorer (`scoring.py`):

1. Replays the steps on the build under test. If a template variable cannot be resolved,
   the verdict is **invalid_repro**: nobody could act on that report.
2. Replays them on the clean build. Identical trace means **false_positive**: the reported
   behaviour is what the specification-conforming app does. The scorer then replays the
   steps on each *flipped-decoy* build. A decoy whose flipped build diverges from clean is
   the trap the report fell into.
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
| Recall by tier | the same, for the core and deep tiers separately |
| Precision | confirmed findings / all findings |
| F1 | harmonic mean of the two |
| Decoys taken | decoys with at least one false positive attributed to them |
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
- `test_decoys.py` — for every decoy, the trap repro (a) is a false positive on the
  all-bugs build and on every single-bug build, so falling for a decoy never scores as a
  real bug, and (b) diverges on its own flipped build and on no other, so the scorecard
  blames the right trap.
- `test_scoring.py` — the canonical repros score 100% precision, recall, and severity
  agreement; each decoy trap is a false positive blamed on its own decoy; a hand-written
  findings file covering every verdict scores exactly as expected.

## Versioning

`EXAM_VERSION` (in `target/__init__.py`) changes whenever the spec, the seed data, or the
registries change, because scores from different exam versions are not comparable. It is
written into `result.json` and `findings.json`. `qabench score` warns when a file comes
from another version. Each version is tagged in git (`v0.1.0`, `v0.2.0`, ...) so old
results can be reproduced exactly.

## Threats to validity

- **Ceiling effect.** v0.1 was saturated by frontier models (both found 10/10). The deep
  tier is the response. Whether v0.2 discriminates is an empirical question that only
  repeated runs answer. If frontier models also saturate the deep tier, v0.3 needs harder
  bugs again.
- **Decoy attribution is behavioural.** A false positive is blamed on a decoy when its
  repro *exercises* the decoy's behaviour, not when the report's text *claims* it. Each
  flipped build changes one narrow behaviour, so this rarely misfires, but read the
  report before quoting a decoy hit.
- **Run-to-run variance.** LLM agents are non-deterministic. A single run is an anecdote;
  compare configurations over repeated runs and report the spread.
- **Session budget.** v0.2 has twice the spec surface of v0.1 under the same turn budget,
  so recall also measures prioritisation within a time-box. Report the turn and cost
  budget with every result.
- **Unseeded defects.** If the agent finds a genuine defect in the clean build, the oracle
  scores it as a false positive. Read false positives before trusting precision; a real
  one is a bug in the benchmark and should become a fix plus a new test.
- **Observable-only oracle.** Replay compares HTTP responses. A defect that only changes
  internal state is invisible until a later step reads that state; the canonical repros
  show how (e.g. reading `remaining` after a cancel).
- **Contamination.** The bug and decoy registries are public. Rotating or private sets
  would be needed to compare models trained after this repository was published.
- **Small target.** Twenty bugs in nine endpoints measure methodology, not scale. Wider
  coverage comes from more targets, not more bugs in this one.
