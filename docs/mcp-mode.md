# Taking the exam over MCP

`qabench mcp` serves the exam as an MCP server over stdio. Any MCP-capable agent can sit
it: Claude Code, an IDE agent, or a local model behind an MCP client. The benchmark side
needs no API key.

The server exposes four tools:

| Tool | Purpose |
| --- | --- |
| `read_specification` | The product spec, the only source of truth |
| `http_request` | Explore the API. State persists for the session |
| `replay_steps` | Dry-run a reproduction on a fresh instance |
| `report_bug` | File a defect with self-contained repro steps |

Each accepted `report_bug` rewrites `findings.json` in the output folder, and every call
is appended to `transcript.jsonl`. An interrupted session can still be scored.

## Isolation comes first

The bug registry lives in this repository. An agent that can read files, run shell
commands, or browse can open `src/qabench/target/bugs.py` and copy the answers. That
would be a cheating run, not a measurement. Run the agent:

- from an **empty folder** outside this repository,
- with **only the qabench MCP tools**: no built-in file, shell, web, or subagent tools,
- with **no other MCP servers** loaded.

## Claude Code (headless)

The flags below are taken from the Claude Code CLI documentation (`cli-reference`,
`headless`, `permissions`). Check them against your installed version.

1. Create the MCP config `C:\exam\qabench-mcp.json`, pointing at this repo's virtualenv:

   ```json
   {
     "mcpServers": {
       "qabench": {
         "command": "C:/path/to/agentic-qa-bench/.venv/Scripts/qabench.exe",
         "args": ["mcp", "--bugs", "all", "--out", "C:/path/to/agentic-qa-bench/results/claude-code-run1"]
       }
     }
   }
   ```

2. Verify the isolation first. Run a trivial prompt with
   `--output-format stream-json --verbose` and check the `system/init` event: `tools` must
   list only `mcp__qabench__*`, and `mcp_servers` must show `qabench` connected.

3. Run the exam from an empty folder (PowerShell):

   ```powershell
   New-Item -ItemType Directory -Force -Path C:\exam\empty | Out-Null
   Set-Location C:\exam\empty

   claude -p "You are taking a QA exam through the qabench MCP server. Call read_specification, test the API with http_request, dry-run each reproduction with replay_steps, and file every defect that violates the specification with report_bug, once per defect. Stop when you have covered the specification." `
     --mcp-config C:\exam\qabench-mcp.json `
     --strict-mcp-config `
     --restricted `
     --tools "" `
     --disallowedTools Agent PowerShell Bash Read Glob Grep Edit Write WebFetch WebSearch NotebookEdit `
     --allowedTools "mcp__qabench__*" `
     --permission-mode dontAsk `
     --max-turns 60 `
     --no-session-persistence `
     --output-format json
   ```

   - `--strict-mcp-config` loads only the servers in `--mcp-config`.
   - `--tools ""` removes the built-in tools. The explicit `--disallowedTools` list is
     belt and braces. Read-only tools need no approval inside the working directory, so
     permission rules alone would not block them.
   - `--restricted` is documented for evaluation harnesses on a shared machine.
   - The JSON output reports `total_cost_usd` for the session.
   - Windows PowerShell 5.1 can drop empty-string arguments. If `--tools ""` seems
     ignored, use `pwsh` 7 and rely on the `system/init` check.

4. Score it:

   ```bash
   qabench score results/claude-code-run1/findings.json --agent "Claude Code (Opus 5.5)" --save
   ```

## Other agents

Point any MCP client at the same command (`qabench mcp --bugs all --out <folder>`), give
it the prompt above, and remove every tool that could reach this repository. Record the
agent and its settings in the `--agent` label, because the scorecard cannot see them.

## What MCP mode does not measure

The built-in API agent reports tokens, turns, and estimated cost for each run. An external
agent's usage is invisible to the server, so its scorecard has quality metrics only. Take
cost from the agent's own output (for example Claude Code's `total_cost_usd`).
