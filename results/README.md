# Results

`qabench run` writes one folder per run: `<UTC timestamp>-<model>-<effort>/` with

- `scorecard.md` — the human-readable scorecard
- `result.json` — metrics, verdicts, findings, token usage (re-scorable with `qabench score`)
- `transcript.jsonl` — every tool call the agent made, for auditing

Local runs are git-ignored. Copy runs worth publishing into `results/published/`.
