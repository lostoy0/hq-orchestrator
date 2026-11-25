# hq-orchestrator: HQ (headquarters) mode

[中文](README.md) | English

Brings a Projects-like way of working to regular sessions (Claude Code or Codex, local or cloud): the main session coordinates, and sub-sessions do the execution. The main session records data for every run, and `/hq-retro` reviews that data so the plugin gets more accurate with use.

**Optimization goal**: first pass the quality gate (no drift + adequate verification + few issues), then minimize total wall time, then minimize cost.

## Supported hosts (v0.3)

`SKILL.md` only uses abstract capabilities (spawn_worker, monitor, ...); each host's concrete calls live under `skills/hq/references/hosts/`.

| Host | Host doc | Status |
|---|---|---|
| Claude Code (local CLI, cloud sessions, desktop, IDE) | `hosts/claude-code.md` | Primary host, used in practice since v0.2 |
| Codex CLI | `hosts/codex.md` + `adapters/codex/` | Agent format and directories checked against official docs (2026-11-25), **not run on a real machine** |
| **DeepSeek Harness (dsh) · recommended DeepSeek path** | `hosts/dsh.md` | Native host: `subagent` sets provider/model/reasoning effort per call; **only the official docs were read, not run on a real machine** |
| DeepSeek backend · path 2: Claude Code with DeepSeek | `hosts/deepseek.md` | Tiers collapse to flash/pro; cloud sub-sessions (B) still use Claude models |
| DeepSeek backend · path 3: Codex with DeepSeek | `hosts/deepseek.md` + `hosts/codex.md` | Config example from official summaries, to be tested |
| Other tools that support SKILL.md (OpenCode, Gemini CLI, Cursor, ...) | none | With a shell, use the W channel; otherwise **degraded mode**: the main session executes serially itself with the same plan, ledger and quality gates |

## What's included
```
.claude-plugin/plugin.json             plugin manifest (v0.3.1)
.claude-plugin/marketplace.json        for installing with /plugin marketplace add
skills/hq/SKILL.md                     core workflow: orchestrate or not → recon → plan → pick tier → pick location → control concurrency → dispatch → monitor and re-tier → review and merge → record data → report
skills/hq/calibration.md               tier calibration: 5-dimension scoring, T0–T4 tiers, adjustment rules (retros only tune this file)
skills/hq/references/runtimes.md       abstract capabilities, general rules for dispatch channels (A/B/C/D/W) and host index
skills/hq/references/hosts/*.md        per-host capability table, tier mapping, install/invocation, open items (claude-code / codex / dsh / deepseek)
skills/hq/references/brief-template.md task brief template for sub-sessions (with verification level and checkpoints) and delivery format
skills/hq/references/metrics-schema.md run-data format (JSONL, v1) and usage definitions
skills/hq/references/playbook-template.md template for the project playbook .hq/PLAYBOOK.md (including authorization settings)
skills/hq/scripts/resources.sh         resource probing (Linux/cgroup/macOS); outputs how many more local tasks can be started
skills/hq/scripts/metrics.py           summarizes run data into a metrics report (read-only)
skills/hq/scripts/cli-worker.sh        W channel: runs codex exec / claude -p in the background in a separate git worktree
skills/hq-retro/SKILL.md               /hq-retro: checks earlier changes, makes evidence-backed suggestions, generates a prompt for changing the plugin
CHANGELOG.md                           reason, acceptance metric and verification status of every change
PROMPT.md                              condensed prompt to paste directly when the plugin is not installed
adapters/codex/                        Codex custom agent templates hq-t0…hq-t4 (tiers T0–T4, model names are placeholders)
install.sh                             copies the skills (and optionally the Codex agent templates) into each host's directories; changes no config
tests/                                 self-tests for resources.sh, cli-worker.sh, install.sh and metrics.py
```

## Installation

**Option 0: install.sh (works for Claude Code, Codex and dsh)**
```bash
./install.sh --host claude|codex|dsh|all [--scope user|project] [--project-dir <path>] [--with-codex-agents] [--force] [--dry-run]
```
| Host | Personal scope (`--scope user`, default) | Project scope (`--scope project`) |
|---|---|---|
| claude | `~/.claude/skills/{hq,hq-retro}` | `<project>/.claude/skills/` |
| codex | `~/.agents/skills/{hq,hq-retro}` | `<project>/.agents/skills/` |
| dsh | `${DSH_HOME:-~/.dsh}/skills/{hq,hq-retro}` | `<project>/.dsh/skills/` |
| all | all three of the above (`both` is the old spelling, equal to claude + codex, still accepted) | same |
| `--with-codex-agents` | `~/.codex/agents/hq-t*.toml` | `<project>/.codex/agents/` |

It only copies files and changes no config. Exit code 3 if a target exists (add `--force` to overwrite), 2 for invalid arguments; all targets are checked first, so it never installs halfway. After installing the agent templates you must replace their `model` placeholders as described in `adapters/codex/README.md`. How to invoke in Codex: see `hosts/codex.md`. dsh also reads `~/.agents/skills` and `<project>/.agents/skills`, so if you already installed with `--host codex` you do not need to install for dsh; first-run steps for dsh are in `hosts/dsh.md`.

**Option 1: personal skill (simplest locally)**
```bash
mkdir -p ~/.claude/skills && cp -r skills/hq skills/hq-retro ~/.claude/skills/
```
After installing, type `/hq <goal>` and `/hq-retro` in any project to use them.

**Option 2: install as a plugin** (first push this directory to your own GitHub repository, or keep it at some local path)
```
/plugin marketplace add <local path or owner/repo>
/plugin install hq-orchestrator@hq-orchestrator-marketplace
```
After installing, invoke them with `/hq-orchestrator:hq <goal>` and `/hq-orchestrator:hq-retro`.

**Option 3: use in cloud sessions**
The cloud container does not have your machine's `~/.claude`, so the skills have to live in the project repository:
```bash
mkdir -p .claude/skills && cp -r <this directory>/skills/hq <this directory>/skills/hq-retro .claude/skills/ && git add .claude/skills
```
After committing, cloud sessions started from this repository can use `/hq` and `/hq-retro`. You can also install via the marketplace from Option 2 inside a cloud session.

## W channel and cross-vendor workers (off by default)

`skills/hq/scripts/cli-worker.sh` runs `codex exec` or `claude -p` in the background in a separate git worktree (`.hq/worktrees/<id>`, branch `hq/<id>`); any host with a shell can use it:
```bash
cli-worker.sh start --id t2 --cli codex|claude --model <m> [--effort <e>] --brief <brief file> [--sandbox read-only|workspace-write]
cli-worker.sh status|stop|usage --id t2      # JSON output
cli-worker.sh list
```
- The sandbox defaults to `workspace-write`. `danger-full-access` (for claude: `--dangerously-skip-permissions`) disables all protection and **requires `--allow-dangerous` as well**; otherwise it is refused with exit code 2.
- `usage` computes tokens with the common definition (input + output + cache_write, excluding cache_read).
- Using a CLI from a different vendor than the host as a worker (cross-vendor) requires `worker_clis: [codex, claude]` in the Authorization section of `.hq/PLAYBOOK.md`; **it is empty by default, i.e. off**.

## Usage example
```
/hq Add CSV export to the api service, with tests and docs; frontend changes must be run end-to-end on my machine
```
The main session first decides whether orchestration is worth it (work expected to take under about 30 minutes, or that is tightly coupled, is done directly). It then sends you the plan (task table, tier and model for each task, run location, concurrency, estimated time) as a notification and **starts dispatching without waiting for confirmation**. You can check progress at any time by asking, or by reading `.hq/LEDGER.md` directly.

## Autonomous execution and stop conditions
- The main session decides technical approach, models, task split and retries on its own, and logs each decision in the ledger's "Decisions" section.
- It stops to ask you only in three cases, batching the questions into one message with a recommended option for each, while continuing unaffected work:
  1. it needs a password, key, account or payment, or needs you to act in a UI or on your own computer;
  2. an irreversible action or one that affects others, without prior authorization: deleting data or branches, deploying, force-pushing, publishing externally, exceeding the budget;
  3. the requirement is ambiguous, still undecidable after research, and a wrong guess would cost more than about an hour of rework.
- Pushing `hq/*` branches and merging into `hq/integration` are automatic by default; merging into the default branch and opening PRs ask by default.

## Authorization settings
Set once in the "Authorization" section of the project's `.hq/PLAYBOOK.md` (template: `skills/hq/references/playbook-template.md`); you are not asked again each time:
```yaml
merge_default: ask        # ask | auto-if-gates-pass: auto-merge into the default branch when all quality gates pass
open_pr: ask              # ask | auto
budget_usd: 20            # spending cap per run; stops to ask before exceeding it
autonomy: auto            # auto | confirm-plan: with confirm-plan, the plan waits for your confirmation before dispatch
worker_clis: []           # cross-vendor workers, e.g. [codex, claude]; empty (off) by default
```

## Improvement loop: record → retro → change the plugin
1. **Record**: when each task and each run ends, the main session appends a line to `.hq/runs/<run_id>.jsonl` (format in `metrics-schema.md`, including `host`; local runs also keep a copy in `~/.claude/hq/runs/`, which the Codex host uses too). Cost is measured mainly by `cost_usd`; `tokens` excludes cache reads.
2. **Retro**: after roughly 5 runs or 20 tasks, the main session reminds you to run `/hq-retro`. It produces a metrics report with `metrics.py`, first checks earlier changes against their acceptance metrics in `CHANGELOG.md`, then has an independent sub-agent draft evidence-backed suggestions (a pattern must appear in at least 3 tasks or 2 runs). Project-specific lessons go straight into `.hq/PLAYBOOK.md`.
3. **Change the plugin**: suggestions about the plugin itself need your approval. The report ends with a prompt you copy into a session on the hq-orchestrator repository; it edits the files, runs the tests, adds a "pending verification" entry to `CHANGELOG.md` and bumps the patch version. The next retro verifies the change and reverts it if it missed its target.

## Design highlights
- **Orchestrate or not**: orchestration has a fixed overhead, so small tasks do not get sub-sessions.
- **Parallelism serves total wall time**: shorten the critical path first; bundle small related tasks, and split only large tasks whose files do not overlap.
- **Difficulty tiers**: scored on 5 dimensions in `calibration.md` into abstract tiers T0–T4, then mapped per host to concrete models (on Claude Code, haiku/low through opus/high). Tier choice includes the cost of failing and redoing; when difficulty is unclear, research first.
- **Dynamic re-tiering**: sub-sessions send a checkpoint on out-of-scope derived work, unexpected difficulty or repeated failure; a stuck task is handed to a new session one tier higher that continues from its branch. No downgrade handoffs.
- **Run-location routing**: tasks that need local resources always run locally; long tasks that can run in parallel go to the cloud; small tasks run in-process.
- **Resource protection**: resources are checked before every dispatch, and dispatch is controlled at three levels: GREEN/YELLOW/RED. Each sub-session is given a build parallelism limit. At RED, the most recently started heavy task is stopped.
- **Quality control**: three quality gates; verification is graded by risk into doc/code/high/e2e, the main session re-runs acceptance commands itself only for high, and a full test run happens once after merging; high-risk or large changes get a separate independent reviewer.
- **Recoverable**: all state is written to the ledger, so work can continue after context compression or a session restart.

## Self-test
```bash
for t in tests/test_resources.sh tests/test_cli_worker.sh tests/test_install.sh; do echo "$t: $(bash $t | tail -1)"; done
python3 -m unittest discover tests
```
`test_cli_worker.sh` uses the fake `codex` and `claude` under `tests/fixtures/fake-cli/` to test argument assembly and usage parsing; it never calls the real CLIs.
`resources.sh` accepts `HQ_FAKE_CORES`, `HQ_FAKE_LOAD1`, `HQ_FAKE_MEM_TOTAL_MB` and similar environment variables to inject simulated readings, covering the GREEN/YELLOW/RED cases.

## Open items and on-machine verification checklist

codex and dsh cannot be installed in this repository's development environment, so the items below need testing on your machine. Please record results in the project's `.hq/PLAYBOOK.md` (host mapping) or open an issue.

**To be verified** (details in section 5 of each host doc):
- Codex: the `-m`, `-c model_reasoning_effort=…` and `-s` flags of `codex exec`; whether the agent templates actually load; the concurrency-limit config name; whether `codex cloud` honors model/effort; monitoring, stopping and usage of native sub-agents.
- dsh: where the desktop app's sub-agent model-routing setting is; the concurrency-limit config key; the non-interactive CLI command (whether it can be a W-channel worker); the range of `reasoning_effort`; how to read usage and cost; how to stop a sub-agent; the tool name for Schedule.
- DeepSeek (paths 2 and 3): whether `CLAUDE_CODE_EFFORT_LEVEL=max` overrides the per-tier effort hq sets; whether `ANTHROPIC_DEFAULT_OPUS_MODEL` can be set to `deepseek-v4-pro`; whether `deepseek-flash` and `deepseek-v4-flash` are equivalent.
- Claude Code: the flags for starting cloud tasks from the local CLI (channel D).

**After installing codex, run these to check the flags**:
```bash
codex --version
codex exec --help | grep -nE -- '-m|--model|-c|--config|-s|--sandbox|--json'   # check the flags cli-worker.sh uses
./install.sh --host codex --with-codex-agents                                  # then replace the model placeholders in ~/.codex/agents/hq-t*.toml
echo "Reply only OK" | codex exec -m <model> -c model_reasoning_effort=low -s read-only --json - | tail -3   # inspect the usage fields of turn.completed
cd <some git repo> && echo "List the files in the repo root" > /tmp/b.md
bash <path>/cli-worker.sh start --id smoke --cli codex --model <model> --effort low --brief /tmp/b.md --sandbox read-only
bash <path>/cli-worker.sh status --id smoke; bash <path>/cli-worker.sh usage --id smoke   # tokens should not be null
```
Ask codex to list the available agents and confirm hq-t0…hq-t4 are recognized.

**Run one small task in dsh** (DeepSeek path 1, recommended): `./install.sh --host dsh` (skip if codex is already installed), then:
- enable sub-agent model selection in the desktop app;
- run `list_subagent_models` and map T0–T4 to the returned routes per section 3 of `hosts/dsh.md`, writing them into `.hq/PLAYBOOK.md`;
- run `/hq` on a small task (one T0, one T3) and check that the model and reasoning effort sub-agents actually used match the tier mapping, and note whether usage can be read.

**Run one small task on the DeepSeek backend** (path 2): set the environment variables per `hosts/deepseek.md`, run `/hq` in a small repository with one T0 task and one T3 task, then check:
- the model sub-agents actually used: flash for T0, pro for T3 (do not set `CLAUDE_CODE_SUBAGENT_MODEL`);
- effort: run once with and once without `CLAUDE_CODE_EFFORT_LEVEL=max` and compare time and usage, to tell whether per-tier effort is overridden;
- usage: whether tokens in `.hq/runs/*.jsonl` match the DeepSeek console bill (cost_usd is computed at Claude prices and is not reliable).

## Known limitations
- The Codex adaptation, dsh and the DeepSeek backend have no real-machine run data yet; see the previous section.
- Whether the local CLI can create cloud sub-sessions directly depends on the CLI version (see channel D in runtimes.md). Monitoring these sub-sessions is weaker. When you need strong monitoring, put the main session in the cloud and handle local tasks through "connect computer".
- In-process sub-agents share the same machine as the main session. Resource protection can only control dispatch pacing and cannot limit processes that sub-agents start themselves. So the parallelism limits in task briefs matter.
- In-process sub-agents only report a token total that cannot be split out from cache reads, so `tokens` is left empty for those tasks; cost comparisons rely mainly on `cost_usd` from cloud sub-sessions.
- The tier table is an empirical default. You can adjust it in `skills/hq/calibration.md` based on your account and actual experience; adjusting it from data via `/hq-retro` is preferred.
