# hq-orchestrator: HQ (headquarters) mode

[中文](README.md) | English

Brings a Projects-like way of working to regular sessions (local CLI or cloud sessions both work): the main session coordinates, and sub-sessions do the execution. The main session records data for every run, and `/hq-retro` reviews that data so the plugin gets more accurate with use.

**Optimization goal**: first pass the quality gate (no drift + adequate verification + few issues), then minimize total wall time, then minimize cost.

## What's included
```
.claude-plugin/plugin.json             plugin manifest (v0.2.0)
.claude-plugin/marketplace.json        for installing with /plugin marketplace add
skills/hq/SKILL.md                     core workflow: orchestrate or not → recon → plan → pick tier → pick location → control concurrency → dispatch → monitor and re-tier → review and merge → record data → report
skills/hq/calibration.md               tier calibration: 5-dimension scoring, T0–T4 tiers, adjustment rules (retros only tune this file)
skills/hq/references/runtimes.md       specifics of each dispatch channel, reading usage, wording for asking the user to switch models manually
skills/hq/references/brief-template.md task brief template for sub-sessions (with verification level and checkpoints) and delivery format
skills/hq/references/metrics-schema.md run-data format (JSONL, v1) and usage definitions
skills/hq/references/playbook-template.md template for the project playbook .hq/PLAYBOOK.md (including authorization settings)
skills/hq/scripts/resources.sh         resource probing (Linux/cgroup/macOS); outputs how many more local tasks can be started
skills/hq/scripts/metrics.py           summarizes run data into a metrics report (read-only)
skills/hq-retro/SKILL.md               /hq-retro: checks earlier changes, makes evidence-backed suggestions, generates a prompt for changing the plugin
CHANGELOG.md                           reason, acceptance metric and verification status of every change
PROMPT.md                              condensed prompt to paste directly when the plugin is not installed
tests/                                 self-tests for resources.sh and metrics.py
```

## Installation

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
```

## Improvement loop: record → retro → change the plugin
1. **Record**: when each task and each run ends, the main session appends a line to `.hq/runs/<run_id>.jsonl` (format in `metrics-schema.md`; local runs also keep a copy in `~/.claude/hq/runs/`). Cost is measured mainly by `cost_usd`; `tokens` excludes cache reads.
2. **Retro**: after roughly 5 runs or 20 tasks, the main session reminds you to run `/hq-retro`. It produces a metrics report with `metrics.py`, first checks earlier changes against their acceptance metrics in `CHANGELOG.md`, then has an independent sub-agent draft evidence-backed suggestions (a pattern must appear in at least 3 tasks or 2 runs). Project-specific lessons go straight into `.hq/PLAYBOOK.md`.
3. **Change the plugin**: suggestions about the plugin itself need your approval. The report ends with a prompt you copy into a session on the hq-orchestrator repository; it edits the files, runs the tests, adds a "pending verification" entry to `CHANGELOG.md` and bumps the patch version. The next retro verifies the change and reverts it if it missed its target.

## Design highlights
- **Orchestrate or not**: orchestration has a fixed overhead, so small tasks do not get sub-sessions.
- **Parallelism serves total wall time**: shorten the critical path first; bundle small related tasks, and split only large tasks whose files do not overlap.
- **Difficulty tiers**: scored on 5 dimensions in `calibration.md`; tiers T0 to T4 map to haiku/low through opus/high. Tier choice includes the cost of failing and redoing; when difficulty is unclear, research first.
- **Dynamic re-tiering**: sub-sessions send a checkpoint on out-of-scope derived work, unexpected difficulty or repeated failure; a stuck task is handed to a new session one tier higher that continues from its branch. No downgrade handoffs.
- **Run-location routing**: tasks that need local resources always run locally; long tasks that can run in parallel go to the cloud; small tasks run in-process.
- **Resource protection**: resources are checked before every dispatch, and dispatch is controlled at three levels: GREEN/YELLOW/RED. Each sub-session is given a build parallelism limit. At RED, the most recently started heavy task is stopped.
- **Quality control**: three quality gates; verification is graded by risk into doc/code/high/e2e, the main session re-runs acceptance commands itself only for high, and a full test run happens once after merging; high-risk or large changes get a separate independent reviewer.
- **Recoverable**: all state is written to the ledger, so work can continue after context compression or a session restart.

## Self-test
```bash
bash tests/test_resources.sh
python3 -m unittest discover tests
```
`resources.sh` accepts `HQ_FAKE_CORES`, `HQ_FAKE_LOAD1`, `HQ_FAKE_MEM_TOTAL_MB` and similar environment variables to inject simulated readings, covering the GREEN/YELLOW/RED cases.

## Known limitations
- Whether the local CLI can create cloud sub-sessions directly depends on the CLI version (see channel D in runtimes.md). Monitoring these sub-sessions is weaker. When you need strong monitoring, put the main session in the cloud and handle local tasks through "connect computer".
- In-process sub-agents share the same machine as the main session. Resource protection can only control dispatch pacing and cannot limit processes that sub-agents start themselves. So the parallelism limits in task briefs matter.
- In-process sub-agents only report a token total that cannot be split out from cache reads, so `tokens` is left empty for those tasks; cost comparisons rely mainly on `cost_usd` from cloud sub-sessions.
- The tier table is an empirical default. You can adjust it in `skills/hq/calibration.md` based on your account and actual experience; adjusting it from data via `/hq-retro` is preferred.
