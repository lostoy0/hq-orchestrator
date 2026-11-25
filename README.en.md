# hq-orchestrator: HQ (headquarters) mode

[中文](README.md) | English

Brings a Projects-like way of working to regular sessions (Claude Code or Codex, local or cloud): the main session coordinates, and sub-sessions do the execution. The main session records data for every run, and `/hq-retro` reviews that data so the plugin gets more accurate with use.

**Optimization goal**: first pass the quality gate (no drift + adequate verification + few issues), then minimize total wall time, then minimize cost.

## Supported hosts (v0.4)

`SKILL.md` only uses abstract capabilities (spawn_worker, monitor, ...); each host's concrete calls live under `skills/hq/references/hosts/`.

| Host | Host doc | Status |
|---|---|---|
| Claude Code (local CLI, cloud sessions, desktop, IDE) | `hosts/claude-code.md` | Primary host, used in practice since v0.2 |
| Codex CLI | `hosts/codex.md` + `adapters/codex/` | Agent format and directories checked against official docs (2026-11-25), **not run on a real machine** |
| **DeepSeek Harness (dsh) · recommended DeepSeek path** | `hosts/dsh.md` | Native host: `subagent` sets provider/model/reasoning effort per call; **only the official docs were read, not run on a real machine** |
| DeepSeek backend · path 2: Claude Code with DeepSeek | `hosts/deepseek.md` | Tiers collapse to flash/pro; cloud sub-sessions (B) still use Claude models |
| DeepSeek backend · path 3: Codex with DeepSeek | `hosts/deepseek.md` + `hosts/codex.md` | Config example from official summaries, to be tested |
| **OpenCode (V2)** | `hosts/opencode.md` + `adapters/opencode/` | Native host since v0.4.1: `hq-t0…t4` sub-agents each carry `provider/model#variant`, so tiers apply per task; **only the official docs were read, not run on a real machine** |
| **Gemini CLI** | `hosts/gemini.md` + `adapters/gemini/` + `gemini-extension.json` | Native host since v0.4.3: `hq-t0…t4` sub-agents each carry a `model` (no reasoning-effort setting, tiers differ by model only); installable as a Gemini extension with `/hq` and `/hq-retro` commands; **only the official docs were read, not run on a real machine** |
| Cursor (one-command install since v0.4) | `hosts/generic.md` | Basic support: skill directories registered from the official docs, **not run on a real machine**; with a shell, use the W channel, otherwise **degraded mode** (the main session executes serially itself with the same plan, ledger and quality gates). Native sub-agent adapters are planned in `docs/design-more-hosts.md` |
| Other tools that support SKILL.md | `hosts/generic.md` | Same as above; installable with `npx skills add` (see Installation) |

## What's included
```
.claude-plugin/plugin.json             plugin manifest (v0.4.5)
.claude-plugin/marketplace.json        for installing with /plugin marketplace add
skills/hq/SKILL.md                     core workflow: orchestrate or not → recon → plan → pick tier → pick location → control concurrency → dispatch → monitor and re-tier → review and merge → record data → report
skills/hq/calibration.md               tier calibration: 5-dimension scoring, T0–T4 tiers, adjustment rules (retros only tune this file)
skills/hq/references/runtimes.md       abstract capabilities, general rules for dispatch channels (A/B/C/D/W) and host index
skills/hq/references/hosts/*.md        per-host capability table, tier mapping, install/invocation, open items (claude-code / codex / dsh / opencode / deepseek / generic)
skills/hq/references/brief-template.md task brief template for sub-sessions (with verification level and checkpoints) and delivery format
skills/hq/references/metrics-schema.md run-data format (JSONL, v1) and usage definitions
skills/hq/references/playbook-template.md template for the project playbook .hq/PLAYBOOK.md (including authorization settings)
skills/hq/scripts/resources.sh         resource probing (Linux/cgroup/macOS); outputs how many more local tasks can be started
skills/hq/scripts/metrics.py           summarizes run data into a metrics report (read-only)
skills/hq/scripts/cli-worker.sh        W channel: runs the codex / claude / opencode / gemini / cursor CLI in the background in a separate git worktree
skills/hq/scripts/backends/*.sh        W channel per-CLI argument building and usage parsing (one file per CLI)
skills/hq-retro/SKILL.md               /hq-retro: checks earlier changes, makes evidence-backed suggestions, generates a prompt for changing the plugin
CHANGELOG.md                           reason, acceptance metric and verification status of every change
PROMPT.md                              condensed prompt to paste directly when the plugin is not installed
adapters/tiers.tsv                     tier registry: effort, model class and fitting tasks for T0–T4 (single source for sub-agent templates)
adapters/render.sh                     generates each host's hq-t0…hq-t4 templates from tiers.tsv; --model-map fills in models
adapters/agent-dirs.tsv                install directories for sub-agent templates
adapters/codex/                        Codex custom agent templates hq-t0…hq-t4 (generated, model names are placeholders)
adapters/opencode/                     OpenCode V2 sub-agent templates hq-t0…hq-t4 (generated, no model set by default)
adapters/gemini/                       Gemini CLI sub-agent templates hq-t0…hq-t4 (generated, no model set by default)
gemini-extension.json                  Gemini CLI extension manifest: the whole repository installs with gemini extensions install
commands/*.toml                        the Gemini extension's /hq and /hq-retro commands (Claude Code does not read .toml)
adapters/hosts.tsv                     host registry: which skill directories each tool reads and how to detect it (add a line for a new host)
adapters/skill-dirs.tsv                skill directory registry: personal and project paths
install.sh                             one-command install: detects tools, copies the skills into the smallest covering set of directories, supports --list/--update/--uninstall; changes no config
docs/design-more-hosts.md              design draft and roadmap for more hosts (v0.4.x, in Chinese)
tests/                                 self-tests for resources.sh, cli-worker.sh, install.sh and metrics.py
```

## Installation

**Option 0: one-line install (recommended, works for every host)**
```bash
curl -fsSL https://raw.githubusercontent.com/lostoy0/hq-orchestrator/v0.4.5/install.sh | bash -s -- --host auto
```
When not run from inside the repository, the script first uses git to download the `v0.4.5` tag to `~/.hq-orchestrator/v0.4.5`, then installs (`HQ_REF=<tag or branch>` picks another version). To look before running, download `install.sh` and use `--list` or `--dry-run`. With a clone of this repository, run `./install.sh` directly:
```bash
./install.sh --host auto|all|claude,codex,dsh,opencode,cursor,gemini [--scope user|project] [--project-dir <path>]
             [--layout minimal|per-host] [--with-agents [--model-map 'T0=…,…,T4=…']] [--force] [--dry-run]
./install.sh --list          # detected tools, existing copies and the install plan; writes nothing
./install.sh --update        # update copies this script installed to the current version
./install.sh --uninstall     # remove copies this script installed
```
- `--host auto` detects installed tools by command (`claude`, `codex`, `opencode`, `cursor-agent`, `gemini`) or config directory (`~/.claude`, `~/.codex`, `~/.dsh`, `~/.config/opencode`, `~/.cursor`, `~/.gemini`). `all` means every registered host; `both` is the old spelling for `claude,codex`.
- **Minimal layout (default)**: many tools read the same directory, so the skills go only into the fewest directories that cover the chosen tools, so no tool sees duplicates where avoidable. For all tools that is just two:

| Directory (personal / project) | Read by |
|---|---|
| `~/.agents/skills` / `<project>/.agents/skills` | codex, dsh, opencode, gemini |
| `~/.claude/skills` / `<project>/.claude/skills` | claude, opencode, cursor |
| Tool-specific directory (used when installing for one tool) | `${DSH_HOME:-~/.dsh}/skills`, `~/.config/opencode/skills`, `~/.cursor/skills`, `~/.gemini/skills` (project scope: `skills/` under `.dsh/`, `.opencode/`, `.cursor/`, `.gemini/`) |

  OpenCode reads both of the first two, so with Claude Code and Codex both installed it sees two copies of the skill and loads one by its own rules. `--layout per-host` installs into every tool's own directory instead (the v0.3 `--host all` behavior).
- `--with-agents`: also installs the chosen hosts' tier sub-agent templates `hq-t0…hq-t4`: Codex to `~/.codex/agents/*.toml`, OpenCode to `~/.config/opencode/agents/*.md`, Gemini CLI to `~/.gemini/agents/*.md` (project scope: `<project>/.codex/agents/`, `<project>/.opencode/agents/`, `<project>/.gemini/agents/`). Adding `--model-map 'T0=<model>,…,T4=<model>'` generates templates with real models on the spot (one host at a time; Codex and Gemini take model names, OpenCode takes `provider/model` and gets `#low/#medium/#high` appended). Without it, Codex templates hold placeholders (must be replaced) and OpenCode and Gemini templates set no model (inherit the parent session's model, so tiers do not apply). The old `--with-codex-agents` still works.
  ```bash
  ./install.sh --host opencode --with-agents --model-map 'T0=<p/small>,T1=<p/mid>,T2=<p/mid>,T3=<p/best>,T4=<p/best>'
  ```
- It only copies files and changes no config. Each copy gets a `.hq-install.json` (version, source, hosts); personal scope also writes `~/.hq/skill-path` so the skill can find its scripts. `--update`/`--uninstall` only touch copies with an install record (v0.3 installs have none; reinstall once with `--host … --force` to bring them in).
- Exit codes: 0 success; 2 invalid arguments; 3 target exists (add `--force`, or use `--update`); 4 nothing to act on (no tool detected, nothing to update or remove); 5 download failed. All targets are checked first, so it never installs halfway.
- Host notes: Codex usage in `hosts/codex.md`; dsh first-run steps in `hosts/dsh.md`; OpenCode in `hosts/opencode.md`; Gemini CLI in `hosts/gemini.md`; Cursor in `hosts/generic.md`.

**Option 0a: Gemini extension** (simplest if you only use Gemini CLI; includes `/hq` and `/hq-retro` commands)
```bash
gemini extensions install https://github.com/lostoy0/hq-orchestrator --ref v0.4.5
```
The extension holds only the skills and commands, not the sub-agent templates (the same repository is also a Claude Code plugin, and Claude Code would load a root `agents/` as its own sub-agents). For tiers to apply, also run `./install.sh --host gemini --with-agents --model-map 'T0=…,…,T4=…'`; if that also installs the skills, Gemini CLI prefers the user-directory copy over the extension's, and the script says so. Update with `gemini extensions update hq-orchestrator`.

**Option 0b: community installer** (covers 70+ agent tools, skills only)
```bash
npx skills add lostoy0/hq-orchestrator                    # pick tools interactively
npx skills add lostoy0/hq-orchestrator -a opencode -a cursor
```
Whether it copies `scripts/` and `references/` in full is unverified; without the scripts, resource probing and the W channel do not work, so use Option 0 in that case.

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

## Upgrading

First check what you have: `./install.sh --list` shows each installed copy with its path and version (from the copy's `.hq-install.json`). Then upgrade the same way you installed. The examples use `v0.4.5`; substitute the version you are upgrading to.

| Install method | How to upgrade |
|---|---|
| Option 0 (one-line install) | `curl -fsSL https://raw.githubusercontent.com/lostoy0/hq-orchestrator/v0.4.5/install.sh \| bash -s -- --update` |
| Option 0 (cloned repository) | `git pull`, then `./install.sh --update`; for project scope add `--scope project --project-dir <path>` |
| Option 0a (Gemini extension) | `gemini extensions update hq-orchestrator` |
| Option 0b (`npx skills add`) | Run the same `npx skills add` command again to overwrite |
| Option 1 (manual copy) | Get the new version and run the `cp -r` command again (it overwrites the old files) |
| Option 2 (plugin) | `/plugin marketplace update hq-orchestrator-marketplace`, then update `hq-orchestrator` from `/plugin`; for a marketplace added from a local path, `git pull` in that directory first |
| Option 3 (project repository) | Copy again into `.claude/skills/` and commit |

Notes:

- `--update` updates copies to the version of **the script you are running**; it does not check online for a newer one. Get the new script first (the one-line command with the new tag, or `git pull`).
- `--update` only touches copies with an install record. Copies installed by v0.3 or earlier, or copied by hand, are skipped with a notice; reinstall once with `./install.sh --host <host> --force` and `--update` will handle them from then on.
- `--update` **does not update sub-agent templates** (`hq-t0…t4` installed with `--with-agents`). When a release changes them (see `CHANGELOG.md`), reinstall with your original flags plus `--force`: `./install.sh --host <host> --with-agents [--model-map '…'] --force`. `--force` overwrites templates you edited by hand.
- Start a new session after upgrading so the host picks up the new skills.

## W channel and cross-vendor workers (off by default)

`skills/hq/scripts/cli-worker.sh` runs a CLI worker in the background in a separate git worktree (`.hq/worktrees/<id>`, branch `hq/<id>`); any host with a shell can use it:
```bash
cli-worker.sh start --id t2 --cli codex|claude|opencode|gemini|cursor --model <m> [--effort <e>] --brief <brief file> [--sandbox read-only|workspace-write]
cli-worker.sh status|stop|usage --id t2      # JSON output
cli-worker.sh list
```
- Each CLI's command and sandbox mapping is in the W section of `skills/hq/references/runtimes.md`. The opencode, gemini and cursor backends (v0.4.2) are written from docs and source and tested only with fake CLIs, **not run on a real machine**; opencode and cursor have no workspace-only sandbox, so `workspace-write` also allows shell.
- The sandbox defaults to `workspace-write`. `danger-full-access` disables all protection and **requires `--allow-dangerous` as well**; otherwise it is refused with exit code 2.
- `usage` computes tokens with the common definition (input + output + cache_write, excluding cache_read).
- Using a CLI from a different vendor than the host as a worker (cross-vendor) requires `worker_clis` (e.g. `[codex, claude]`) in the Authorization section of `.hq/PLAYBOOK.md`; **it is empty by default, i.e. off**. The host's own CLI (e.g. `--cli gemini` on a Gemini CLI host) needs no authorization, and is how Cursor and Gemini CLI hosts get tiers to apply.

## Usage example
```
/hq Add CSV export to the api service, with tests and docs; frontend changes must be run end-to-end on my machine
```
The main session first decides whether orchestration is worth it (work expected to take under about 30 minutes, or that is tightly coupled, is done directly). It then sends you the plan (task table, tier and model for each task, run location, concurrency, estimated time) as a notification and **starts dispatching without waiting for confirmation**. You can check progress at any time by asking, or by reading `.hq/LEDGER.md` directly.

## Standing mode: keep one session as the coordinator

By default `/hq <goal>` handles one batch. To keep going batch after batch in the same session (for example, when the session already holds a lot of context and you don't want to start over), use standing mode:
```
/hq --stay Finish the CSV export first
```
If you type just `/hq --stay` with no goal, it first explores the project (ledger, roadmap, TODOs, open issues, recent commits, test status and so on; for a large project it sends a read-only sub-task to look) and gives numbered recommendations with their sources, then waits for you: reply "do 1 and 3" to run only those, "go with the recommendation" to run all of them, or state your own goal. On entry it always waits for your choice and never starts on its own. If it finds no clear pending work, it lists what it checked and asks you for a goal.

After that, just state the next goal, such as "next batch: add permission checks to the export". Each batch ends with a report whose last line says it is standing by for the next goal; asking questions in between does not exit.

After each batch report it recommends the next batch (up to 5 items, each with its source, estimated tier and time). Sources are the ledger's backlog, unfinished items from the earlier conversation, and the project's roadmap, TODOs, open issues and failing tests. Reply with numbers ("do 1 and 3") to run only those, or "go with the recommendation" to run all of them. When nothing actionable is left and the overall goal is met, it says plainly that all project tasks are done and nothing more can be executed, and lists the sources it checked. It does not invent work to fill the list; things that need keys, a deploy or your own action are listed separately and do not count as actionable. To have it keep going on its recommendations without waiting, say "continue automatically with the recommendations" (budget and stop conditions still apply). Say "exit standing mode" or `/hq --stop` to end it.

**Taking over a session that is already open**: a skill installed after a session started usually only shows up in `/hq` after you reopen the session. To avoid that, type this in the session (replace the path with your skill directory; `find ~/.claude ~/.agents -path '*hq/SKILL.md'` finds it):
```
Read ~/.claude/skills/hq/SKILL.md in full and take over this session in its standing mode: first write what we have already finished and decided into the ledger's takeover background, then wait for my goal.
```
In a session without file access, paste all of `PROMPT.md` and then say "standing".

Notes:
- The main session records the skill path in the `.hq/LEDGER.md` header (`skill_path`) and rereads the skill and the ledger after context compaction. If it ever starts doing the work itself instead of dispatching, say "reread SKILL.md and stay in standing mode".
- Sub-sessions cannot see the chat, so earlier progress goes into the ledger's takeover background. Even if you later have to open a new session, it can pick up by reading SKILL.md and the ledger.
- Each batch still starts by deciding whether orchestration is worth it, and small goals are done directly; to force dispatching, add "dispatch this batch too" to the goal.

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
worker_clis: []           # cross-vendor workers: any of codex/claude/opencode/gemini/cursor; empty (off) by default
```

## Improvement loop: record → retro → change the plugin
1. **Record**: when each task and each run ends, the main session appends a line to `.hq/runs/<run_id>.jsonl` (format in `metrics-schema.md`, including `host`; local runs also keep a copy in `~/.claude/hq/runs/`, which the Codex host uses too). Cost is measured mainly by `cost_usd`; `tokens` excludes cache reads.
2. **Retro**: after roughly 5 runs or 20 tasks, the main session reminds you to run `/hq-retro`. It produces a metrics report with `metrics.py`, first checks earlier changes against their acceptance metrics in `CHANGELOG.md`, then has an independent sub-agent draft evidence-backed suggestions (a pattern must appear in at least 3 tasks or 2 runs). Project-specific lessons go straight into `.hq/PLAYBOOK.md`.
3. **Change the plugin**: suggestions about the plugin itself need your approval. The report ends with a prompt you copy into a session on the hq-orchestrator repository; it edits the files, runs the tests, adds a "pending verification" entry to `CHANGELOG.md` and bumps the patch version. The next retro verifies the change and reverts it if it missed its target.

## Design highlights
- **Orchestrate or not**: orchestration has a fixed overhead, so small tasks do not get sub-sessions.
- **Parallelism serves total wall time**: shorten the critical path first; bundle small related tasks, and split only large tasks whose files do not overlap.
- **Difficulty tiers**: scored on 5 dimensions in `calibration.md` into abstract tiers T0–T4, then mapped per host to concrete models (on Claude Code, haiku/low through opus/high). Tier choice includes the cost of failing and redoing; when difficulty is unclear, research first. Codex, dsh and DeepSeek backends have cheaper quotas, so when the tier is uncertain they round up one tier (`calibration.md` rule 9; adjust with `cost_weight` in the PLAYBOOK).
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
`test_cli_worker.sh` uses the fake `codex`, `claude`, `opencode`, `gemini` and `cursor-agent` under `tests/fixtures/fake-cli/` to test argument assembly and usage parsing; it never calls the real CLIs.
`resources.sh` accepts `HQ_FAKE_CORES`, `HQ_FAKE_LOAD1`, `HQ_FAKE_MEM_TOTAL_MB` and similar environment variables to inject simulated readings, covering the GREEN/YELLOW/RED cases.

## Open items and on-machine verification checklist

codex and dsh cannot be installed in this repository's development environment, so the items below need testing on your machine. Please record results in the project's `.hq/PLAYBOOK.md` (host mapping) or open an issue.

**To be verified** (details in section 5 of each host doc):
- Codex: the `-m`, `-c model_reasoning_effort=…` and `-s` flags of `codex exec`; whether the agent templates actually load; the concurrency-limit config name; whether `codex cloud` honors model/effort; monitoring, stopping and usage of native sub-agents.
- dsh: where the desktop app's sub-agent model-routing setting is; the concurrency-limit config key; the non-interactive CLI command (whether it can be a W-channel worker); the range of `reasoning_effort`; how to read usage and cost; how to stop a sub-agent; the tool name for Schedule.
- DeepSeek (paths 2 and 3): whether `CLAUDE_CODE_EFFORT_LEVEL=max` overrides the per-tier effort hq sets; whether `ANTHROPIC_DEFAULT_OPUS_MODEL` can be set to `deepseek-v4-pro`; whether `deepseek-flash` and `deepseek-v4-flash` are equivalent.
- Claude Code: the flags for starting cloud tasks from the local CLI (channel D).
- OpenCode (native host since v0.4.1): whether the `hq-t*` sub-agents are recognized and each tier's `model#variant` resolves; how to stop a sub-agent; token/cost fields in `opencode session export`; permission prompts when several background sub-agents run at once.
- New W backends (v0.4.2): run `start/status/usage/stop` once each with `opencode run`, `gemini -p` and `cursor-agent -p` on your machine; check the flags are accepted and `usage` returns tokens (cursor's usage field names are unknown); whether gemini can run shell commands under `auto_edit`.
- Gemini CLI (native host since v0.4.3): whether `gemini extensions install` works and `/hq` activates the skill; whether the `hq-t*` sub-agents load and their models apply; whether several sub-agent calls in one turn run in parallel; how to read sub-agent usage; after installing the Claude Code plugin, `commands/*.toml` must not show up as commands.
- Cursor (basic support in v0.4), Gemini CLI: after `--host auto`, whether each tool discovers and triggers the hq skill; whether Cursor also reads `~/.agents/skills`; whether `npx skills add` brings `scripts/` and `references/` along.

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
- The Codex adaptation, dsh, the DeepSeek backend and OpenCode/Cursor/Gemini CLI have no real-machine run data yet; see the previous section. Cursor only has basic support for now, so tiers do not apply; OpenCode and Gemini CLI sub-agents share the main session's working directory, so hq creates a worktree first for code-changing tasks.
- Whether the local CLI can create cloud sub-sessions directly depends on the CLI version (see channel D in runtimes.md). Monitoring these sub-sessions is weaker. When you need strong monitoring, put the main session in the cloud and handle local tasks through "connect computer".
- In-process sub-agents share the same machine as the main session. Resource protection can only control dispatch pacing and cannot limit processes that sub-agents start themselves. So the parallelism limits in task briefs matter.
- In-process sub-agents only report a token total that cannot be split out from cache reads, so `tokens` is left empty for those tasks; cost comparisons rely mainly on `cost_usd` from cloud sub-sessions.
- The tier table is an empirical default. You can adjust it in `skills/hq/calibration.md` based on your account and actual experience; adjusting it from data via `/hq-retro` is preferred.
