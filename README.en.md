# hq-orchestrator: HQ (headquarters) mode

[中文](README.md) | English

Brings a Projects-like way of working to regular sessions (Claude Code, Codex and others, local or cloud): **the main session coordinates, and sub-sessions do the execution**. The main session records data for every run, and `/hq-retro` reviews that data so the plugin gets more accurate with use.

> **Optimization goal**: first pass the quality gate (no drift + adequate verification + few issues), then minimize total wall time, then minimize cost.

**Contents**

| Getting started | Using it | Configuration | Reference |
|---|---|---|---|
| [What it solves](#what-it-solves)<br>[Quick start](#quick-start)<br>[Command cheat sheet](#command-cheat-sheet) | [Basic use](#basic-use)<br>[Standing mode](#standing-mode-keep-one-session-as-the-coordinator)<br>[Stage skills](#stage-skills-from-idea-to-launch)<br>[Autonomy and stop conditions](#autonomous-execution-and-stop-conditions) | [Authorization settings](#authorization-settings)<br>[Assist workers](#assist-workers-the-main-model-takes-the-hard-tasks-codex--kimi-take-the-easier-ones)<br>[W channel and cross-vendor workers](#w-channel-and-cross-vendor-workers) | [Installation](#installation)<br>[Upgrading and uninstalling](#upgrading-and-uninstalling)<br>[Retros and data](#retros-and-data)<br>[Supported hosts](#supported-hosts)<br>[Design highlights](#design-highlights)<br>[Repository layout](#repository-layout)<br>[Self-test](#self-test)<br>[Open items](#open-items-and-on-machine-verification-checklist)<br>[Known limitations](#known-limitations) |

---

## What it solves

Handing a big goal to a single session tends to drift, run serially and fill the context. `/hq` keeps the main session to coordination only:

1. **Decide whether splitting is worth it**: work expected to take under about 30 minutes, or that is tightly coupled, is done directly.
2. **Break it into a task graph**: shorten the critical path first, bundle small related tasks.
3. **Pick a model by difficulty**: each subtask is scored on 5 dimensions into a tier T0–T4, then mapped to a concrete model and thinking depth on the host.
4. **Throttle by resources**: CPU and memory are checked before each dispatch; work that does not fit locally waits or goes to the cloud.
5. **Review and merge**: a sub-session's result is merged only after review, followed by one full test run.
6. **Record and retro**: each run's usage and outcome go into `.hq/runs/`, and `/hq-retro` uses them to calibrate tiers.

**Maturity**: Claude Code is the primary host and has been used for real; the other hosts' adapters follow official docs and most have not been run on a real host yet. See [Supported hosts](#supported-hosts) and [Known limitations](#known-limitations).

## Quick start

**Claude Code** (as a plugin):
```
/plugin marketplace add lostoy0/hq-orchestrator
/plugin install hq-orchestrator@hq-orchestrator-marketplace
```

**Codex, OpenCode, Gemini CLI, Cursor, dsh** (one-line script that detects which tools you have):
```bash
curl -fsSL https://raw.githubusercontent.com/lostoy0/hq-orchestrator/v0.10.5/install.sh | bash -s -- --host auto
```

Start a new session and give it a goal:
```
/hq Add CSV export to the api service, with tests and docs
```
It sends you the plan (task table, tier and model for each task, run location, concurrency, estimated time) as a notification and **starts dispatching without waiting for confirmation**. Ask about progress at any time, or read `.hq/LEDGER.md`. After a few runs, run `/hq-retro`.

Other ways to install (in-project copies, cloud sessions, the Gemini extension and more) are under [Installation](#installation).

## Command cheat sheet

| Command | What it does |
|---|---|
| `/hq <goal>` | Coordinate one goal (one batch) |
| `/hq --stay [goal]` | Standing mode: this session keeps coordinating batch after batch until you say "exit standing mode" |
| `/hq --backlog R1` | Execute one release from the backlog `/hq-plan` produced |
| `/hq --assist codex <goal>` | Hand low- and mid-difficulty tasks to an assist worker for this run |
| `/hq --assist codex --save` | Save the assist settings for every project without starting a run; `--save-project` for this project only |
| `/hq --assist-show` | Show and validate the effective assist settings |
| `/hq-retro` | Review run data and make evidence-backed suggestions; `--export` exports anonymized data |
| `/hq-research`, `/hq-prd`, `/hq-design`, `/hq-arch`, `/hq-plan` | Stage skills: research, requirements, design, architecture, plan |
| `/hq-blueprint` | Run the stages above in one go and write a project blueprint |
| `/hq-launch` | Launch readiness check against a 46-item checklist |

Installed as a Claude Code plugin, the commands carry a prefix, such as `/hq-orchestrator:hq`.

---

## Basic use

```
/hq Add CSV export to the api service, with tests and docs; frontend changes must be run end-to-end on my machine
```

What one run does:

1. **Recon**: reads `.hq/PLAYBOOK.md` (this project's lessons and authorization), detects the host, the available channels and local resources.
2. **Plan**: breaks the goal into a task graph, writes it to the ledger `.hq/LEDGER.md` and sends you the plan as a notification.
3. **Dispatch**: picks a model per tier and throttles concurrency by resources; work that needs local resources runs locally, long parallel tasks go to the cloud.
4. **Monitor and re-tier**: a stuck sub-session is handed to a new session one tier higher that continues from its branch.
5. **Review and merge**: merges into the integration branch only after review, then runs the full tests; merging into the default branch and opening PRs ask you by default.
6. **Report and record**: reports the result and writes usage to `.hq/runs/`.

## Standing mode: keep one session as the coordinator

By default `/hq <goal>` handles one batch. To keep going batch after batch in the same session (for example, when the session already holds a lot of context and you don't want to start over), use standing mode:
```
/hq --stay Finish the CSV export first
```

- **No goal**: with just `/hq --stay`, it first explores the project (ledger, roadmap, TODOs, open issues, recent commits, test status and so on; for a large project it sends a read-only sub-task to look) and gives numbered recommendations with their sources, then waits for you: reply "do 1 and 3" to run only those, "go with the recommendation" to run all of them, or state your own goal. On entry it always waits for your choice and never starts on its own. If it finds no clear pending work, it lists what it checked and asks you for a goal.
- **Next batch**: just state the next goal, such as "next batch: add permission checks to the export". Each batch ends with a report whose last line says it is standing by for the next goal; asking questions in between does not exit.
- **Recommendations**: after each batch report it recommends the next batch (up to 5 items, each with its source, estimated tier and time), drawn from the ledger's backlog, unfinished items from the earlier conversation, the roadmap, TODOs, open issues and failing tests. When nothing actionable is left and the overall goal is met, it says plainly that all project tasks are done and lists the sources it checked. It does not invent work to fill the list; things that need keys, a deploy or your own action are listed separately. To have it keep going without waiting, say "continue automatically with the recommendations" (budget and stop conditions still apply).
- **Exit**: say "exit standing mode" or `/hq --stop`.

**Taking over a session that is already open**: a skill installed after a session started usually only shows up in `/hq` after you reopen the session. To avoid that, type this in the session (replace the path with your skill directory; `find ~/.claude ~/.agents -path '*hq/SKILL.md'` finds it):
```
Read ~/.claude/skills/hq/SKILL.md in full and take over this session in its standing mode: first write what we have already finished and decided into the ledger's takeover background, then wait for my goal.
```
In a session without file access, paste all of `PROMPT.md` and then say "standing".

Notes:
- The main session records the skill path in the `.hq/LEDGER.md` header (`skill_path`) and rereads the skill and the ledger after context compaction. If it ever starts doing the work itself instead of dispatching, say "reread SKILL.md and stay in standing mode".
- Sub-sessions cannot see the chat, so earlier progress goes into the ledger's takeover background. Even if you later have to open a new session, it can pick up by reading SKILL.md and the ledger.
- Each batch still starts by deciding whether orchestration is worth it, and small goals are done directly; to force dispatching, add "dispatch this batch too" to the goal.

## Stage skills: from idea to launch

`/hq` handles how to get the work done; stage skills handle what to make. They run on the same engine (ledger, tiers, dispatch, review and records are all shared). The overall design and roadmap are in `docs/design-stages.md` (in Chinese).

```
/hq-research a budgeting app for indie developers   # research competitors online (10 by default, 3 in depth), every claim sourced
/hq-research --n 6 --deep 2 --market global
/hq-prd                                   # write or complete the requirements doc from ideas, screenshots and the research report
/hq-prd --scope accounts --ask            # only the "accounts" module; ask key decisions first
/hq-design --platform ios --explore 3     # design system + a high-fidelity prototype you can click end to end; 3 style directions first
/hq-arch --stack nextjs,postgres          # architecture and detailed design, with overview diagrams and decision records
/hq-plan                                  # read requirements, design, tech docs and existing code; produce a release plan and task backlog
/hq-plan --release MVP solo developer, ship in two weeks
/hq --backlog R1                          # execute the first release from the backlog (or just say "execute R1")
/hq-blueprint a budgeting app for indie developers   # one command: research → requirements → design and architecture (in parallel) → plan, skipping finished stages
/hq-blueprint --until build --skip design  # go on to build the first release; skip design for a backend-only product
/hq-launch                                # check launch readiness against a 46-item checklist and give a verdict
```

### What each stage produces

| Skill | Output | Highlights |
|---|---|---|
| `/hq-research` | `docs/research/competitors.md` | Competitors are grouped as direct, indirect and substitutes; in-depth entries cover positioning, features, pricing, user numbers, user reviews, strengths and weaknesses; the report ends with a comparison matrix, pricing comparison, opportunities and "suggestions for the requirements". Every fact carries a source id, and the source table at the end has links and access dates; inferences are marked as such. Without web access it says so instead of passing off model memory as research; if you explicitly accept that, `--offline` writes a version marked unverified. In review, the researcher spot-checks 5 claims against their sources |
| `/hq-prd` | `docs/product/prd.md` | Target users, first-release scope and "not doing", each feature's user story, acceptance criteria and all UI states, non-functional requirements, monetization, success metrics and tracking, a launch-essentials table (sign-up and sign-in, password reset, account deletion, privacy policy and so on, 24 items, each marked included, not doing or not applicable), and a requirement index that `/hq-plan` reads directly. Without a research report it first runs a 5-competitor quick scan (`--no-research` skips it). An existing requirements doc is completed to the launch standard without deleting what you wrote; one in another format is left untouched and a new doc is written alongside. Reviewers: design, architecture, QA, plus security when accounts, payments or personal data are involved |
| `/hq-design` | `docs/design/` | A design system (tokens, components, interaction, copy, accessibility), a pages-and-flows doc, and a high-fidelity clickable prototype that opens offline. The prototype is built on a bundled starter kit: mock sign-in with demo accounts (new user, existing user, paying user, admin and so on), realistic mock data, empty, loading, error, no-permission and first-use states on every page, main flows (including sign-up and sign-in) that click through end to end, and a toolbar in the bottom-left to switch pages, states and accounts. `prototype-check.py` checks it statically and `prototype-walk.mjs` uses Playwright to screenshot every page in every state and run every flow; a designer role then reviews the screenshots. The default style is clear and modern, with an explicit list of "AI-looking" patterns to avoid. Reviewers: product, engineering, QA |
| `/hq-arch` | `docs/tech/architecture.md`, `detailed-design.md`, `adr/` | Constraints and quality attributes; six kinds of diagrams (system context, containers, components, data model, key-flow sequences, deployment) in Mermaid, drawn per `skills/hq-arch/diagram-style.md` (one layer per diagram, at most 15 nodes, subgraphs for boundaries, labeled edges, one color scheme); module responsibilities and requirement mapping; non-functional design; technology choices with decision records; risks to validate (which `/hq-plan` schedules as early research tasks). It defaults to mature, managed options one person can run. Reviewers: engineering, security, QA, plus ops when there are deployment or cost constraints |
| `/hq-plan` | `docs/plan/roadmap.md`, `docs/plan/backlog.json` | The roadmap is for people: releases, scope, release criteria, dependency graph, requirement coverage. The backlog is for `/hq`: each task's dependencies, owned files, acceptance criteria, verification level, and an estimated tier from the 5-dimension score. An existing docs directory in the project is reused. Tasks waiting on someone else's decision are marked `hold` and never dispatched; tasks that need a real device, a store account, a payment test account, a customer document or a manual check are marked `needs_human`, so the AI prepares scripts and a checklist and hands that step to you; external readiness is written as milestones (`milestones`, `ready_after`), and the critical path includes the wait. Reviewers: architect, engineer, QA (plus product when there is no requirements doc) |
| `/hq-blueprint` | `docs/blueprint.md` | Runs the stages above in one go. It first uses `stage-status.py` to see, for each stage, whether its outputs are complete, whether checks find errors and whether the upstream it was built on has changed, and runs only what is needed; when an upstream stage is rerun, downstream stages are brought in line. Design and architecture run in parallel. Every stage has to pass a check gate before the next starts. After the requirements stage, if big decisions such as the business model or target market are still open, it asks you once (`--no-pause` skips this). It ends with a project index summarizing each stage's outputs, decisions waiting for you and next steps |
| `/hq-launch` | `docs/launch/checklist.md` | 46 items across product completeness, quality, security, privacy and compliance, ops, growth, business and release. Anything a command can verify is actually run (full tests, build, dependency vulnerability audit, secret scan); every "pass" needs evidence, and an independent sub-session spot-checks 5 of them. The verdict follows fixed rules (go / go with conditions / no-go) and lists blockers and the items only you can confirm (company filings, store consoles, real payments). Missing materials are drafted: ops runbook, release notes, launch plan, store listing copy, and draft privacy policy, terms and refund policy (marked as needing review by a legal professional; not legal advice). It never deploys or publishes |

### Rules shared by every stage

- **Review**: several roles review in parallel. Findings are blocker, major or minor; at most 2 rounds by default, the second only checks blockers and majors, and anything still open at the limit goes to you, so it never loops. Role cards are in `skills/hq/references/roles/`.
- **Decisions**: made on its own in the order "compliance and security baseline > user value and experience > business viability > technical simplicity > cost". Decisions that cannot be undone (pricing and business model, brand naming, target market, legal risk) are yours, but they do not block writing: it writes with the recommended option, records the decision as pending, and asks you once at the end of the stage (with `--ask`, before writing). A document with pending decisions cannot be marked approved. Other assumptions are listed for you at the same time.
- **Checks**: `skills/hq/scripts/backlog-check.py` checks the backlog mechanically (unique ids, no dependency cycles, tier matches score, every P0 requirement covered by a task, no task depending on a task on hold, and a critical path that honours external milestones); `skills/hq/scripts/doc-check.py prd|research|arch|launch` checks requirements docs, research reports and architecture docs (architecture: every chapter's diagram present, node counts, shared color scheme, module fields, every requirement mapped to a module, ADR format; the rest: fields present, all UI states written, requirement index matches the body, every launch-essentials row decided, every cited source in the source table, enough sources per competitor).
- **Loop**: when `/hq` executes it re-scores tasks against the current code and records the planned tier; the `metrics.py` report has a "3e planned vs actual tier" section that `/hq-retro` uses to calibrate planning.
- **Projects that already have documents**: when a project already has requirements, a prototype, a technical design or a plan (made by another tool, or in the team's own format), nothing is started from scratch. `stage-status.py --discover` finds those documents across the repository and writes an artifact map, `hq-artifacts.json`; each stage gives foreign-format documents an **adoption review** that judges content against its completion standard rather than format, keeping the project's own ids. Frozen documents only get change proposals for you to decide on; unfrozen ones get gaps filled in place, in their own structure. A foreign plan is imported by `/hq-plan` into `backlog.json` with its ids kept, so `/hq --backlog` can execute it; a later change to the source plan is flagged for re-import.
- **Not invoked automatically**: stage skills are heavy, so in Claude Code they set `disable-model-invocation` and run only when you type the command; on other hosts the skill description ("use only when the user types it explicitly") is the fallback.

## Autonomous execution and stop conditions

- The main session decides technical approach, models, task split and retries on its own, and logs each decision in the ledger's "Decisions" section.
- It stops to ask you only in three cases, batching the questions into one message with a recommended option for each, while continuing unaffected work:
  1. it needs a password, key, account or payment, or needs you to act in a UI or on your own computer;
  2. an irreversible action or one that affects others, without prior authorization: deleting data or branches, deploying, force-pushing, publishing externally, exceeding the budget;
  3. the requirement is ambiguous, still undecidable after research, and a wrong guess would cost more than about an hour of rework.
- Pushing `hq/*` branches and merging into `hq/integration` are automatic by default; merging into the default branch and opening PRs ask by default.

---

## Authorization settings

Set once in the "Authorization" section of the project's `.hq/PLAYBOOK.md` (created from `skills/hq/references/playbook-template.md` on the first `/hq` run); you are not asked again each time:
```yaml
merge_default: ask        # ask | auto-if-gates-pass: auto-merge into the default branch when all quality gates pass
open_pr: ask              # ask | auto
budget_usd: 20            # spending cap per run; stops to ask before exceeding it
remote_concurrency: 4     # cap on concurrent remote sessions (default 4); changes concurrency only, never tiers
max_subtasks: 12          # max subtasks per batch (default 12)
autonomy: auto            # auto | confirm-plan: with confirm-plan, the plan waits for your confirmation before dispatch
worker_clis: []           # cross-vendor workers: any of codex/claude/opencode/gemini/cursor; empty (off) by default
runs_persist: off         # off | branch | commit: whether run records are saved into the repository; asked once in the cloud if unset
assist: …                 # assist workers, see the next section; best set with commands
cost_weight: …            # quota cost per billing party; decides how far to round up when difficulty is uncertain
```

## Assist workers: the main model takes the hard tasks, Codex / Kimi take the easier ones

Off by default. When a large goal splits into many subtasks, the host can keep the hard, important tasks and hand well-specified low- and mid-difficulty tasks to a cheaper model, then review the result itself. This saves host quota and adds parallelism. **The host is whatever host and model hq is running in** (Claude Code, Codex, Gemini CLI and so on), not necessarily Claude.

### How it works

- **Routing** (`skills/hq/calibration.md` rule 10): a task goes to an assist worker only if its tier is ≤ `max_tier` (default T2), its risk is low, its requirements are clear, one command can tell whether it is right, and it is not a prerequisite such as a shared interface. T3/T4, architecture, security, data, concurrency, migrations, unknown root causes and all reviews stay with the host.
- **Review**: assist output is always reviewed by the host, with no "one tier lower" discount; changes over about 150 lines also get an independent review.
- **Failure**: after one failure the host takes over from the worker's branch one tier higher. An assist worker that is **unavailable** (CLI will not start, not logged in, rate-limited, missing key) is disabled at once; one that fails **twice in a row** or reaches `max_failures` (default 2) is disabled too. Once every assist worker is disabled, **the host does all remaining tasks itself** without stopping to ask, and says so once in its report.
- **Measuring it**: task records gain an `assist` field; section "3d" of the `metrics.py` report compares first-pass and take-over rates per tier, and `/hq-retro` uses it to suggest lowering `max_tier` or dropping a worker.
- **Caveats**: assist workers run on the W channel on this machine (or the cloud container) and use local CPU and memory; in a cloud session the CLI must be installed, the API host allowed and the key configured, otherwise everything stays with the host. Retries on an external model eat into the savings, so tasks of uncertain difficulty are not handed out.

### What you can configure

| Item | Notes |
|---|---|
| Platform (profile) | `codex` (works once the codex CLI is installed; models are read automatically); `kimi` and other third-party APIs go through the `claude` CLI and need an `env_file` (see `skills/hq/references/hosts/kimi.md`, **compiled from public docs, not run on a real machine**); `opencode`, `gemini` and `cursor` CLIs also work. Several profiles are tried in order; when one is disabled the next is used |
| Tiers | Only **T0–T2** can go to an assist worker (`max_tier` is at most T2); T3, T4 and all reviews **always stay with the host**, using the host's own mapping (Claude Code: haiku/sonnet/opus, see section 3 of `skills/hq/references/hosts/claude-code.md`) |
| Model and effort per tier | Each profile's `models` and `effort` are set per T0, T1, T2; codex may leave them empty and get a suggestion from the local model catalog; an unset effort means the tier default for codex (T0/T1 low, T2 medium) and no `--effort` for other CLIs |
| Relation to the host | Settings are not per host: in Claude Code the list is used as is; inside Codex, `codex` is the host itself, is skipped, and the next profile (for example kimi) is used |
| Precedence | user-level `~/.hq/config.yaml` (every project) < `assist` in the project's `.hq/PLAYBOOK.md` (that project only) < this run's `/hq --assist …` flags, **field by field**: a project that only changes the T2 model keeps everything else from the user level |

### For one run

```
/hq --assist codex,kimi <goal>            # this run, in order of preference
/hq --assist kimi --assist-max T1 <goal>  # hand out only T0–T1
/hq --assist off <goal>                   # off for this run
```

### Set once, keeps working

**Case 1: one setting for every project (global)**. In any project with hq installed, open a session and type:
```
/hq --assist codex --save
```
It only saves (no run): writes `~/.hq/config.yaml`, fills the codex models per tier from the local `codex debug models`, then lists each tier's model and effort. To pick some tiers yourself:
```
/hq --assist codex --assist-models T0=gpt-6-luna,T1=gpt-6.2-sol,T2=gpt-6.2-astra --assist-effort T2=high --save
```
To add Kimi as a second worker (first create `~/.hq/env/kimi.env` with mode 600, see section 4 of `hosts/kimi.md`):
```
/hq --assist kimi --assist-cli claude --assist-env-file ~/.hq/env/kimi.env --assist-models T0=<model>,T1=<model>,T2=<model> --save
/hq --assist codex,kimi --save
```
Plain language works too, e.g. "from now on use codex as the assist worker, T2 on gpt-6.2-astra with high effort, save globally".

**Case 2: one project only**. Open a session in that project and use `--save-project` instead of `--save`; it writes that project's `.hq/PLAYBOOK.md` and overrides only what you set:
```
/hq --assist codex --assist-max T1 --save-project                    # this project hands out T0–T1 only
/hq --assist codex --assist-models T2=gpt-6.2-astra --save-project   # another T2 model here, the rest from the global setting
/hq --assist off --save-project                                      # assist off for this project
```

**Show and validate**: `/hq --assist-show` lists the effective list, each tier's model and effort, and which layer each value comes from, and checks that the models are still in codex's catalog, that the efforts are supported and that `env_file` has mode 600.

### From a terminal instead

The commands map one to one (`set --scope user` = `--save`, `set --scope project --project <path>` = `--save-project`). The script is `scripts/assist-config.py` in the hq skill directory; find it first:
```bash
S=$(find ~/.claude/skills ~/.claude/plugins ~/.agents/skills "$PWD/.claude/skills" -path '*hq/scripts/assist-config.py' 2>/dev/null | head -1); echo "$S"
```

| Command | What it does |
|---|---|
| `python3 "$S" models` | Models available to the local codex, their supported efforts and retirement dates |
| `python3 "$S" suggest` | Suggested T0–T4 mapping |
| `python3 "$S" set --scope user --use codex --auto-models` | Turn on codex globally, models filled from the suggestion |
| `python3 "$S" set --scope user --profile codex --models T2=gpt-6.2-astra --effort T2=high` | Change one tier globally |
| `python3 "$S" set --scope project --project ~/code/my-app --max-tier T1` | Change one project only |
| `python3 "$S" show --project ~/code/my-app` | Effective settings for that project and where each comes from |
| `python3 "$S" check --project ~/code/my-app` | Validate models, efforts and `env_file` |

**Notes**
- Reading the global file needs hq v0.10.5 or later in the project. An older per-project copy (`.claude/skills/hq`) ignores `~/.hq/config.yaml`; upgrade it first: `./install.sh --update --scope project --project-dir <path>`.
- The codex suggestion is inferred from keywords in the model descriptions (the catalog has no price field); check `show` after saving and fix a tier with `--assist-models` if needed. `--auto-models` never overwrites a tier you set.
- The config holds only the `env_file` path; keys stay in that file, and the script never reads or prints its contents.
- Kimi is best reached through the `claude` CLI pointed at its Anthropic-compatible API; `cli-worker.sh --env-file` injects the endpoint and key into that worker process only and never logs the values.

## W channel and cross-vendor workers

Off by default. `skills/hq/scripts/cli-worker.sh` runs a CLI worker in the background in a separate git worktree (`.hq/worktrees/<id>`, branch `hq/<id>`); any host with a shell can use it:
```bash
cli-worker.sh start --id t2 --cli codex|claude|opencode|gemini|cursor --model <m> [--effort <e>] --brief <brief file> [--sandbox read-only|workspace-write]
cli-worker.sh status|stop|usage --id t2      # JSON output
cli-worker.sh list
```
- **Turning it on**: using a CLI from a different vendor than the host as a worker (cross-vendor) requires `worker_clis` (e.g. `[codex, claude]`) in the Authorization section of `.hq/PLAYBOOK.md`. The host's own CLI (e.g. `--cli gemini` on a Gemini CLI host) needs no authorization, and is how Cursor and Gemini CLI hosts get tiers to apply.
- **Sandbox**: defaults to `workspace-write`. `danger-full-access` disables all protection and **requires `--allow-dangerous` as well**; otherwise it is refused with exit code 2.
- **Per CLI**: commands and sandbox mapping are in the W section of `skills/hq/references/runtimes.md`. The opencode, gemini and cursor backends are written from docs and source and tested only with fake CLIs, **not run on a real machine**; opencode and cursor have no workspace-only sandbox, so `workspace-write` also allows shell.
- **Usage**: `usage` computes tokens with the common definition (input + output + cache_write, excluding cache_read).

---

## Installation

### Which method

| Your situation | Recommended |
|---|---|
| Only Claude Code, locally | [Claude Code plugin](#claude-code-plugin), or the [one-line script](#one-line-script-recommended-works-for-every-host) with `--host claude` |
| Codex, OpenCode, Cursor, dsh, or several tools together | [One-line script](#one-line-script-recommended-works-for-every-host) with `--host auto` |
| Only Gemini CLI | [Gemini extension](#gemini-extension) |
| Claude Code cloud sessions, or pinning the version inside a project | [Install into the project repository](#cloud-sessions-and-in-project-copies) |
| No scripts | [Manual copy](#manual-copy) or [`npx skills add`](#community-installer) |

### One-line script (recommended, works for every host)

```bash
curl -fsSL https://raw.githubusercontent.com/lostoy0/hq-orchestrator/v0.10.5/install.sh | bash -s -- --host auto
```
When not run from inside the repository, the script first uses git to download the `v0.10.5` tag to `~/.hq-orchestrator/v0.10.5`, then installs. With a clone of this repository, run `./install.sh` directly. Full help: `./install.sh --help`.

**Common commands**

```bash
./install.sh --host auto                                   # detect your tools, install to the personal directory
./install.sh --host claude --scope project                 # install into the current project only
./install.sh --host codex --with-agents --model-map auto   # Codex, with tier templates built from the local models
./install.sh --list                                        # see where it would install; writes nothing
./install.sh --host auto --dry-run                         # print what it would do; writes nothing
./install.sh --update                                      # upgrade installed copies
./install.sh --uninstall                                   # remove installed copies
```

**Options**

| Option | What it does | Example |
|---|---|---|
| `--host <hosts>` | Which tools to install for, comma-separated. `auto` detects; `all` means every one; choose from `claude`, `codex`, `dsh`, `opencode`, `cursor`, `gemini`; `both` is the old spelling for `claude,codex` | `--host auto`<br>`--host claude,codex` |
| `--scope user\|project` | `user` (default) installs to the personal directory, usable in every project; `project` installs into one project | `--scope project` |
| `--project-dir <path>` | With `--scope project`, the project to install into; defaults to the current directory | `--scope project --project-dir ~/code/my-app` |
| `--layout minimal\|per-host` | `minimal` (default) installs only into the fewest directories that cover the chosen tools; `per-host` uses each tool's own directory | `--host claude,codex --layout per-host` |
| `--with-agents` | Also install the tier sub-agent templates `hq-t0…hq-t4` (codex, opencode and gemini have templates) | `--host codex --with-agents` |
| `--model-map <map>` | Fill in models while generating templates, for one host only; codex and gemini take model names, opencode takes `provider/model[#effort]`; codex accepts `auto` | `--model-map auto`<br>`--model-map 'T0=<model>,T3=<model>'` |
| `--with-codex-agents` | Old spelling: install only the Codex templates, whatever `--host` says | `--host claude --with-codex-agents` |
| `--dry-run` | Print what would be done, write nothing | `--host auto --dry-run` |
| `--force` | Overwrite existing targets (by default it refuses, exit code 3) | `--host claude --force` |
| `--list` | Show detected tools, installed copies and the install plan; writes nothing | `--list --scope project` |
| `--update` | Update copies this script installed to the current version | `--update --scope project --project-dir ~/code/my-app` |
| `--uninstall` | Remove copies this script installed (only those with an install record) | `--uninstall` |

**Environment variables**

| Variable | What it does | Example |
|---|---|---|
| `HQ_REF` | Which tag or branch the one-line install downloads; defaults to `v0.10.5` | `HQ_REF=main` |
| `HQ_CACHE_DIR` | Download cache directory; defaults to `~/.hq-orchestrator` | `HQ_CACHE_DIR=/tmp/hq` |
| `HQ_REPO_URL` | Which git repository to download from; defaults to this one | `HQ_REPO_URL=https://example.com/fork.git` |
| `DSH_HOME` | dsh's home directory; defaults to `~/.dsh` | `DSH_HOME=~/tools/dsh` |
| `CODEX_AGENTS_DIR`, `OPENCODE_AGENTS_DIR`, `GEMINI_AGENTS_DIR` | Where to put the sub-agent templates instead | `CODEX_AGENTS_DIR=~/tmp/agents` |

**Where it installs**: `--host auto` detects installed tools by command (`claude`, `codex`, `opencode`, `cursor-agent`, `gemini`) or config directory (`~/.claude`, `~/.codex`, `~/.dsh`, `~/.config/opencode`, `~/.cursor`, `~/.gemini`). Many tools read the same directory, so by default the skills go only into the fewest directories that cover the chosen tools, and no tool sees two copies; for all tools that is just two:

| Directory (personal / project) | Read by |
|---|---|
| `~/.agents/skills` / `<project>/.agents/skills` | codex, dsh, opencode, gemini |
| `~/.claude/skills` / `<project>/.claude/skills` | claude, opencode, cursor |
| Tool-specific directory (used when installing for one tool) | `${DSH_HOME:-~/.dsh}/skills`, `~/.config/opencode/skills`, `~/.cursor/skills`, `~/.gemini/skills` (project scope: `skills/` under `.dsh/`, `.opencode/`, `.cursor/`, `.gemini/`) |

OpenCode reads both of the first two, so with Claude Code and Codex both installed it sees two copies of the skill and loads one by its own rules.

**Tier sub-agent templates** (`--with-agents`): make T0–T4 actually use different models on the host. Codex goes to `~/.codex/agents/*.toml`, OpenCode to `~/.config/opencode/agents/*.md`, Gemini CLI to `~/.gemini/agents/*.md` (project scope: `<project>/.codex/agents/`, `<project>/.opencode/agents/`, `<project>/.gemini/agents/`). `--model-map` generates templates with real models on the spot; without it, Codex templates hold placeholders (must be replaced) and OpenCode and Gemini templates set no model (inherit the parent session's model, so tiers do not apply).
```bash
./install.sh --host codex --with-agents --model-map auto
./install.sh --host opencode --with-agents --model-map 'T0=<p/small>,T1=<p/mid>,T2=<p/mid>,T3=<p/best>,T4=<p/best>'
```

**Install records and exit codes**: it only copies files and changes no config; all targets are checked first, so it never installs halfway. Each copy gets a `.hq-install.json` (version, source, hosts); personal scope also writes `~/.hq/skill-path` so the skill can find its scripts. Exit codes: 0 success; 2 invalid arguments; 3 target exists (add `--force`, or use `--update`); 4 nothing to act on (no tool detected, nothing to update or remove); 5 download failed.

**After installing**: Codex usage in `hosts/codex.md`; dsh first-run steps in `hosts/dsh.md`; OpenCode in `hosts/opencode.md`; Gemini CLI in `hosts/gemini.md`; Cursor in `hosts/generic.md`.

### Claude Code plugin

```
/plugin marketplace add lostoy0/hq-orchestrator      # or a local path
/plugin install hq-orchestrator@hq-orchestrator-marketplace
```
Then invoke them with `/hq-orchestrator:hq <goal>` and `/hq-orchestrator:hq-retro`.

### Gemini extension

Simplest if you only use Gemini CLI; includes `/hq`, `/hq-retro` and the stage commands:
```bash
gemini extensions install https://github.com/lostoy0/hq-orchestrator --ref v0.10.5
```
The extension holds only the skills and commands, not the sub-agent templates (the same repository is also a Claude Code plugin, and Claude Code would load a root `agents/` as its own sub-agents). For tiers to apply, also run `./install.sh --host gemini --with-agents --model-map 'T0=…,…,T4=…'`; if that also installs the skills, Gemini CLI prefers the user-directory copy over the extension's, and the script says so.

### Community installer

Covers 70+ agent tools, skills only:
```bash
npx skills add lostoy0/hq-orchestrator                    # pick tools interactively
npx skills add lostoy0/hq-orchestrator -a opencode -a cursor
```
Whether it copies `scripts/` and `references/` in full is unverified; without the scripts, resource probing and the W channel do not work, so use the one-line script in that case.

### Manual copy

```bash
mkdir -p ~/.claude/skills && cp -r skills/hq skills/hq-retro skills/hq-plan skills/hq-prd skills/hq-research skills/hq-arch skills/hq-design skills/hq-blueprint skills/hq-launch ~/.claude/skills/
```
Then type `/hq <goal>` and `/hq-retro` in any project. A manual copy has no install record, so `--update` skips it.

### Cloud sessions and in-project copies

Each cloud session clones the repository into a fresh container and **cannot see your machine's `~/.claude`**; nothing installed locally carries over, including plugins installed with `/plugin install` on your machine. In testing, a cloud session gets skills and plugins from two places: `.claude/skills/` committed to the target project's repository, and plugins enabled for your claude.ai account or organization.

**Recommended (verified in the cloud): copy the skills into the project repository and commit them.**
```bash
./install.sh --host claude --scope project --project-dir <project path>
```
After committing `.claude/skills/`, cloud sessions started from this repository can use `/hq` and `/hq-retro`, and the helper scripts (such as `scripts/resources.sh`) run as well. It needs no network or marketplace and pins the version, but every project holds its own copy to upgrade.

**Alternative: account- or organization-level plugin.** Enable it for your account or organization in the claude.ai plugin directory (the plugin has to be in your organization's directory first, which may need an admin).

> ⚠️ **Do not rely on declaring the plugin in the project's `.claude/settings.json` for the cloud.** Declaring `hq-orchestrator@hq-orchestrator-marketplace` with `extraKnownMarketplaces` + `enabledPlugins` was tested in 2026-11: cloud sessions **do not install the plugin and report no error**, and `hq-orchestrator:hq` is missing from the skill list. If you set it up that way from another guide and it does not work, this is why; use the approach above instead.

You could also run `install.sh` from the environment's setup script or a SessionStart hook on every session, but this is untested and reinstalls every time; the approach above is usually simpler.

`.hq/` (the ledger, run records and retro reports) is not committed by default, so it is lost when the cloud container is reclaimed. To retro across cloud sessions, set `runs_persist: branch` in `.hq/PLAYBOOK.md`; see [Retros and data](#retros-and-data).

### Avoiding duplicate installs

| Situation | Effect | Recommendation |
|---|---|---|
| A personal copy on your machine (`~/.claude/skills/hq`) plus an in-project copy committed in the project | Locally, this project sees two `/hq` skills with the same name, possibly at different versions | Check versions with `./install.sh --list`; keeping both on the same version is simplest |
| Both a personal copy and the plugin on your machine | Locally you get both `/hq` and `/hq-orchestrator:hq`; the model may pick either one, the two versions drift apart over time, and the plugin copy looks up its helper scripts via `~/.hq/skill-path` first, so it may run the personal copy's older scripts | Pick one: if you only use the plugin, remove the personal copy with `./install.sh --uninstall`; if you develop it locally, keep it and call `/hq` explicitly while debugging |

The ledger and run records (`.hq/`, `~/.claude/hq/runs/`) are unaffected: both copies write to the same place. If you are unsure how it was installed locally, run `./install.sh --list` and `ls ~/.claude/skills ~/.claude/plugins`.

## Upgrading and uninstalling

First check what you have: `./install.sh --list` shows each installed copy with its path and version (from the copy's `.hq-install.json`). Then upgrade the same way you installed:

| Install method | How to upgrade |
|---|---|
| One-line script | `curl -fsSL https://raw.githubusercontent.com/lostoy0/hq-orchestrator/v0.10.5/install.sh \| bash -s -- --update` |
| One-line script (cloned repository) | `git pull`, then `./install.sh --update`; for project scope add `--scope project --project-dir <path>` |
| Claude Code plugin | `/plugin marketplace update hq-orchestrator-marketplace`, then update `hq-orchestrator` from `/plugin`; for a marketplace added from a local path, `git pull` in that directory first |
| Gemini extension | `gemini extensions update hq-orchestrator` |
| `npx skills add` | Run the same command again to overwrite |
| Manual copy | Get the new version and run the `cp -r` command again (it overwrites the old files) |
| In-project copy | `./install.sh --update --scope project --project-dir <path>`, then commit |

Notes:

- `--update` updates copies to the version of **the script you are running**; it does not check online for a newer one. Get the new script first (the one-line command with the new tag, or `git pull`).
- Skills added in a new version (such as `hq-plan` in v0.6.0, `hq-blueprint` and `hq-launch` in v0.9.0): `--update` installs them next to each updated `hq`.
- `--update` only touches copies with an install record. Copies installed by v0.3 or earlier, or copied by hand, are skipped with a notice; reinstall once with `./install.sh --host <host> --force` and `--update` will handle them from then on.
- `--update` **does not update sub-agent templates** (`hq-t0…t4` installed with `--with-agents`). When a release changes them (see `CHANGELOG.md`), reinstall with your original flags plus `--force`: `./install.sh --host <host> --with-agents [--model-map '…'] --force`. `--force` overwrites templates you edited by hand.
- Start a new session after upgrading so the host picks up the new skills.

**Uninstalling**: `./install.sh --uninstall` (for project scope add `--scope project --project-dir <path>`) removes only copies this script installed and recorded. Remove the plugin with `/plugin`, the Gemini extension with `gemini extensions uninstall hq-orchestrator`.

---

## Retros and data

### Improvement loop: record → retro → change the plugin

1. **Record**: when each task and each run ends, the main session appends a line to `.hq/runs/<run_id>.jsonl` (format in `metrics-schema.md`, including `host`; local runs also keep a copy in `~/.claude/hq/runs/`, which the Codex host uses too). Cost is measured mainly by `cost_usd`; `tokens` excludes cache reads.
2. **Retro**: after roughly 5 runs or 20 tasks, the main session reminds you to run `/hq-retro`. It produces a metrics report with `metrics.py`, first checks earlier changes against their acceptance metrics in `CHANGELOG.md`, then has an independent sub-agent draft evidence-backed suggestions (a pattern must appear in at least 3 tasks or 2 runs). Project-specific lessons go straight into `.hq/PLAYBOOK.md`.
3. **Change the plugin**: suggestions about the plugin itself need your approval. The report ends with a prompt you copy into a session on the hq-orchestrator repository; it edits the files, runs the tests, adds a "pending verification" entry to `CHANGELOG.md` and bumps the patch version. The next retro verifies the change and reverts it if it missed its target.

### Saving run records

The PLAYBOOK's `runs_persist`:

| Value | What happens | For |
|---|---|---|
| `off` | Records stay in local `.hq/runs/` (local runs also copy to `~/.claude/hq/runs/`) | Local-only use |
| `branch` | After each batch, `runs-persist.sh save branch` writes the records under `runs/` on a dedicated `hq/runs` branch and pushes it; append-only, safe with several sessions writing at once, never touches the working tree or the current branch | Cloud (recommended; `/hq` asks once at the end of the first cloud run) |
| `commit` | `runs-persist.sh save commit` commits only the record files to the current branch, pushed with the batch | Automatic fallback when `hq/runs` cannot be pushed |

`/hq-retro` first runs `runs-persist.sh fetch` to copy the `hq/runs` records into `.hq/runs-archive/`, then summarizes them with the local records (each run counted once). `hq/runs` is a separate history branch; do not merge it into other branches.

### Sharing data to improve the plugin

Entirely voluntary, never uploaded automatically:

1. Run `/hq-retro --export`. It uses `metrics.py --export-anon` to export a whitelist: only enum and number fields such as tier, model, channel, duration, cost and pass rates are kept; all free text (task titles, goals, notes, verification output) and project names are removed, run ids are hashed, and timestamps are cut to dates. The whitelist is in `metrics-schema.md`.
2. The export is shown to you in full and saved to `.hq/retro/export-<date>.json`.
3. If you want to share it, open an issue with the [retro-data template](https://github.com/lostoy0/hq-orchestrator/issues/new?template=retro-data.md) and paste it. Issues are public; review the content once more before posting.

`/hq-retro` mentions this only once, at the end of the first retro report (tracked by `share_hint` in the PLAYBOOK).

---

## Supported hosts

`SKILL.md` only uses abstract capabilities (spawn_worker, monitor, ...); each host's concrete calls live under `skills/hq/references/hosts/`.

| Host | Host doc | Status |
|---|---|---|
| Claude Code (local CLI, cloud sessions, desktop, IDE) | `hosts/claude-code.md` | Primary host, used in practice since v0.2 |
| Codex CLI | `hosts/codex.md` + `adapters/codex/` | Agent format and directories checked against official docs; `codex exec` and the model catalog verified on a real machine; native sub-agents **not run on a real machine** |
| **DeepSeek Harness (dsh) · recommended DeepSeek path** | `hosts/dsh.md` | Native host: `subagent` sets provider/model/reasoning effort per call; **only the official docs were read, not run on a real machine** |
| DeepSeek backend · path 2: Claude Code with DeepSeek | `hosts/deepseek.md` | Tiers collapse to flash/pro; cloud sub-sessions (B) still use Claude models |
| DeepSeek backend · path 3: Codex with DeepSeek | `hosts/deepseek.md` + `hosts/codex.md` | Config example from official summaries, to be tested |
| **OpenCode (V2)** | `hosts/opencode.md` + `adapters/opencode/` | Native host: `hq-t0…t4` sub-agents each carry `provider/model#variant`, so tiers apply per task; **only the official docs were read, not run on a real machine** |
| **Gemini CLI** | `hosts/gemini.md` + `adapters/gemini/` + `gemini-extension.json` | Native host: `hq-t0…t4` sub-agents each carry a `model` (no reasoning-effort setting, tiers differ by model only); installable as a Gemini extension; **only the official docs were read, not run on a real machine** |
| Cursor | `hosts/generic.md` | Basic support: skill directories registered from the official docs, **not run on a real machine**; with a shell, use the W channel, otherwise **degraded mode** (the main session executes serially itself with the same plan, ledger and quality gates). Native sub-agent adapters are planned in `docs/design-more-hosts.md` |
| Other tools that support SKILL.md | `hosts/generic.md` | Same as above; installable with `npx skills add` |
| Kimi (assist worker, not a host) | `hosts/kimi.md` | Takes T0–T2 tasks over the W channel; **compiled from public docs, not run on a real machine** |

## Design highlights

- **Orchestrate or not**: orchestration has a fixed overhead, so small tasks do not get sub-sessions.
- **Parallelism serves total wall time**: shorten the critical path first; bundle small related tasks, and split only large tasks whose files do not overlap.
- **Difficulty tiers**: scored on 5 dimensions in `calibration.md` into abstract tiers T0–T4, then mapped per host to concrete models (on Claude Code, haiku/low through opus/high). Tier choice includes the cost of failing and redoing; when difficulty is unclear, research first.
- **Round up when unsure** (`calibration.md` rule 9): Codex, dsh and DeepSeek backends have cheaper quotas and go up a full tier; Claude Code raises only the thinking depth by one level by default, and a full tier when the task is ambiguous or high-risk (adjust with `cost_weight` in the PLAYBOOK).
- **Tiers depend only on difficulty, never on concurrency** (rule 11): when you ask to "run as many as possible", or there are many tasks, tight resources or quota, or rate limits, HQ runs fewer at once or queues them; it never lowers a model or thinking depth to fit more workers. It only does so when you explicitly say lower models are fine in order to run more, and even then data, security, top-tier tasks and all reviews stay put by default.
- **Dynamic re-tiering**: sub-sessions send a checkpoint on out-of-scope derived work, unexpected difficulty or repeated failure; a stuck task is handed to a new session one tier higher that continues from its branch. No downgrade handoffs.
- **Run-location routing**: tasks that need local resources always run locally; long tasks that can run in parallel go to the cloud; small tasks run in-process.
- **Resource protection**: resources are checked before every dispatch, and dispatch is controlled at three levels: GREEN/YELLOW/RED (UNKNOWN when some readings cannot be read, treated like YELLOW: at most one more). Each sub-session is given a build parallelism limit. At RED, the most recently started heavy task is stopped.
- **Quality control**: three quality gates; verification is graded by risk into doc/code/high/e2e, the main session re-runs acceptance commands itself only for high, and a full test run happens once after merging; high-risk or large changes get a separate independent reviewer.
- **Recoverable**: all state is written to the ledger, so work can continue after context compression or a session restart.

## Repository layout

```
Plugin and extension manifests
  .claude-plugin/plugin.json             Claude Code plugin manifest (v0.10.5)
  .claude-plugin/marketplace.json        for installing with /plugin marketplace add
  gemini-extension.json                  Gemini CLI extension manifest: the whole repository installs with gemini extensions install
  commands/*.toml                        the Gemini extension's /hq, /hq-retro and stage commands (Claude Code does not read .toml)

Core skills /hq and /hq-retro
  skills/hq/SKILL.md                     core workflow: orchestrate or not → recon → plan → pick tier → pick location → control concurrency → dispatch → monitor and re-tier → review and merge → record data → report
  skills/hq/calibration.md               tier calibration: 5-dimension scoring, T0–T4 tiers, adjustment rules (retros only tune this file)
  skills/hq-retro/SKILL.md               /hq-retro: checks earlier changes, makes evidence-backed suggestions, generates a prompt for changing the plugin

Stage skills
  skills/hq-research/                    competitor research (template.md is the report format)
  skills/hq-prd/                         requirements doc (template.md is the doc format)
  skills/hq-design/                      design system and high-fidelity clickable prototype (prototype-starter/ is the starter kit)
  skills/hq-arch/                        architecture, detailed design and decision records (diagram-style.md is the diagram guide)
  skills/hq-plan/                        release plan and task backlog with estimated tiers
  skills/hq-blueprint/                   runs the stages in one go
  skills/hq-launch/                      launch check: 46-item checklist, verdict, drafted launch materials

Reference docs (skills/hq/references/)
  runtimes.md                            abstract capabilities, general rules for dispatch channels (A/B/C/D/W) and host index
  hosts/*.md                             per-host capability table, tier mapping, install/invocation, open items; kimi.md is an assist worker
  brief-template.md                      task brief template for sub-sessions (with verification level and checkpoints) and delivery format
  metrics-schema.md                      run-data format (JSONL, v1) and usage definitions
  playbook-template.md                   template for the project playbook .hq/PLAYBOOK.md (including authorization settings)
  roles/*.md                             role cards (product, design, architecture, engineering, QA, security, research, ops, legal, growth, business)
  stages/common.md                       shared rules for stage skills: output layout, ids and traceability, modes, review protocol, decision order
  backlog-schema.md                      format of the backlog.json plan

Scripts (skills/hq/scripts/)
  resources.sh                           resource probing (Linux/cgroup/macOS); outputs how many more local tasks can be started
  cli-worker.sh, backends/*.sh           W channel: runs each CLI in the background in a separate git worktree; one backend file per CLI
  assist-config.py                       assist worker settings: reads the codex model catalog, suggests tiers, writes user or project settings, validates
  metrics.py                             summarizes run data into a metrics report (read-only); --export-anon exports a whitelisted anonymized copy
  runs-persist.sh                        saves run records into the repository (dedicated hq/runs branch or the current branch) and fetches them back
  backlog-check.py                       backlog checker (read-only): ids, dependencies, tier vs score, requirement coverage, tasks on hold, critical path
  doc-check.py                           requirements doc, research report, architecture and launch checklist checker (read-only)
  prototype-check.py, prototype-walk.mjs static check and walk-through of clickable prototypes (walk-through needs Playwright; both adopt foreign prototypes)
  stage-status.py                        reports each stage's outputs: complete or not, check results, stale or not (read-only)
  fetch-page.py                          fetches a page's text with curl through the session proxy (when the host's own fetch tool cannot reach sites)

Adapters and installation
  install.sh                             one-command install: detects tools, copies the skills into the smallest covering set of directories, supports --list/--update/--uninstall
  adapters/hosts.tsv, skill-dirs.tsv     host registry and skill directory registry (add a line for a new host)
  adapters/tiers.tsv, render.sh          tier registry and template generator (single source for sub-agent templates)
  adapters/agent-dirs.tsv                install directories for sub-agent templates
  adapters/codex/, opencode/, gemini/    each host's generated hq-t0…hq-t4 sub-agent templates

Docs, tests and repository housekeeping
  PROMPT.md                              condensed prompt to paste directly when the plugin is not installed
  CHANGELOG.md                           reason, acceptance metric and verification status of every change
  docs/design-stages.md                  design draft and roadmap for stage skills (in Chinese)
  docs/design-more-hosts.md              design draft and roadmap for more hosts (in Chinese)
  tests/                                 self-tests for the scripts (fake CLIs in tests/fixtures/)
  .github/                               issue templates, PR checklist, CI (all self-tests on Linux and macOS)
  LICENSE, CONTRIBUTING.md, SECURITY.md  license, contribution guide, private security reports
```

## Self-test

```bash
for t in tests/test_*.sh; do bash "$t" || echo "FAILED: $t"; done
python3 -m unittest discover tests
```
- `test_cli_worker.sh` uses the fake `codex`, `claude`, `opencode`, `gemini` and `cursor-agent` under `tests/fixtures/fake-cli/` to test argument assembly and usage parsing; it never calls the real CLIs.
- `resources.sh` accepts `HQ_FAKE_CORES`, `HQ_FAKE_LOAD1`, `HQ_FAKE_MEM_TOTAL_MB` and similar environment variables to inject simulated readings, covering the GREEN/YELLOW/RED cases; `HQ_FAKE_UNREADABLE=cores,mem_total,…` simulates unreadable readings (UNKNOWN).

## Open items and on-machine verification checklist

dsh and some other tools cannot be installed in this repository's development environment, so the items below need testing on your machine. Please record results in the project's `.hq/PLAYBOOK.md` (host mapping) or open an issue.

**To be verified** (details in section 5 of each host doc):
- Codex: whether the agent templates actually load; the concurrency-limit config name; whether `codex cloud` honors model/effort; monitoring, stopping and usage of native sub-agents.
- dsh: where the desktop app's sub-agent model-routing setting is; the concurrency-limit config key; the non-interactive CLI command (whether it can be a W-channel worker); the range of `reasoning_effort`; how to read usage and cost; how to stop a sub-agent; the tool name for Schedule.
- DeepSeek (paths 2 and 3): whether `CLAUDE_CODE_EFFORT_LEVEL=max` overrides the per-tier effort hq sets; whether `ANTHROPIC_DEFAULT_OPUS_MODEL` can be set to `deepseek-v4-pro`; whether `deepseek-flash` and `deepseek-v4-flash` are equivalent.
- Claude Code: the flags for starting cloud tasks from the local CLI (channel D).
- OpenCode: whether the `hq-t*` sub-agents are recognized and each tier's `model#variant` resolves; how to stop a sub-agent; token/cost fields in `opencode session export`; permission prompts when several background sub-agents run at once.
- W backends: run `start/status/usage/stop` once each with `opencode run`, `gemini -p` and `cursor-agent -p` on your machine; check the flags are accepted and `usage` returns tokens (cursor's usage field names are unknown); whether gemini can run shell commands under `auto_edit`.
- Gemini CLI: whether `gemini extensions install` works and `/hq` activates the skill; whether the `hq-t*` sub-agents load and their models apply; whether several sub-agent calls in one turn run in parallel; how to read sub-agent usage; after installing the Claude Code plugin, `commands/*.toml` must not show up as commands.
- Cursor, Gemini CLI: after `--host auto`, whether each tool discovers and triggers the hq skill; whether Cursor also reads `~/.agents/skills`; whether `npx skills add` brings `scripts/` and `references/` along.

**Codex smoke test**:
```bash
codex --version
./install.sh --host codex --with-agents --model-map auto                       # builds ~/.codex/agents/hq-t*.toml from the local model catalog
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

- Codex native sub-agents, dsh, the DeepSeek backend and OpenCode/Cursor/Gemini CLI have no real-machine run data yet; see the previous section. Cursor only has basic support for now, so tiers do not apply; OpenCode and Gemini CLI sub-agents share the main session's working directory, so hq creates a worktree first for code-changing tasks.
- Whether the local CLI can create cloud sub-sessions directly depends on the CLI version (see channel D in runtimes.md). Monitoring these sub-sessions is weaker. When you need strong monitoring, put the main session in the cloud and handle local tasks through "connect computer".
- In-process sub-agents share the same machine as the main session. Resource protection can only control dispatch pacing and cannot limit processes that sub-agents start themselves. So the parallelism limits in task briefs matter.
- In-process sub-agents only report a token total that cannot be split out from cache reads, so `tokens` is left empty for those tasks; cost comparisons rely mainly on `cost_usd` from cloud sub-sessions.
- The tier table is an empirical default. You can adjust it in `skills/hq/calibration.md` based on your account and actual experience; adjusting it from data via `/hq-retro` is preferred.

---

## License and commercial use

This project is licensed under the [Apache License 2.0](LICENSE) with the [Commons Clause](https://commonsclause.com/) condition. The summary below is informal; **the [LICENSE](LICENSE) text governs**.

- **Anyone can use it for free**: individuals, companies internally, commercial projects. You may modify it and redistribute it free of charge, as long as you keep the license text and copyright notice and include the Commons Clause condition.
- **No selling**: you may not sell this project (or works derived from it), or charge for a product or service whose value derives mainly from it, including paid hosting, consulting and support.
- **The author is not bound by this**: the author may sell it, list it on plugin or skill marketplaces and charge for support. To work together or buy services, contact the author through [Issues](https://github.com/lostoy0/hq-orchestrator/issues).
- **Not "open source" in the OSI sense**: because of the restriction above, this project is source-available.

See [CONTRIBUTING.md](CONTRIBUTING.md) for contributing and [SECURITY.md](SECURITY.md) for security reports.
