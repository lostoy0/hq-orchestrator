# hq-orchestrator: HQ (headquarters) mode

[中文](README.md) | English

Brings a Projects-like way of working to regular sessions (local CLI or cloud sessions both work): the main session coordinates, and sub-sessions do the execution.

## What's included
```
.claude-plugin/plugin.json        plugin manifest
.claude-plugin/marketplace.json   for installing with /plugin marketplace add
skills/hq/SKILL.md                core workflow: recon → plan → pick model → pick location → control concurrency → dispatch → monitor → review and merge → report
skills/hq/references/runtimes.md  specifics of each dispatch channel
skills/hq/references/brief-template.md  task brief template and delivery format for sub-sessions
skills/hq/scripts/resources.sh    resource probing (Linux/cgroup/macOS); outputs how many more local tasks can be started
PROMPT.md                         condensed prompt to paste directly when the plugin is not installed
```

## Installation

**Option 1: personal skill (simplest locally)**
```bash
mkdir -p ~/.claude/skills && cp -r skills/hq ~/.claude/skills/hq
```
After installing, type `/hq <goal>` in any project to use it.

**Option 2: install as a plugin** (first push this directory to your own GitHub repository, or keep it at some local path)
```
/plugin marketplace add <local path or owner/repo>
/plugin install hq-orchestrator@hq-orchestrator-marketplace
```
After installing, invoke it with `/hq-orchestrator:hq <goal>`.

**Option 3: use in cloud sessions**
The cloud container does not have your machine's `~/.claude`, so the skill has to live in the project repository:
```bash
mkdir -p .claude/skills && cp -r <this directory>/skills/hq .claude/skills/hq && git add .claude/skills/hq
```
After committing, cloud sessions started from this repository can use `/hq`. You can also install via the marketplace from Option 2 inside a cloud session.

## Usage example
```
/hq Add CSV export to the api service, with tests and docs; frontend changes must be run end-to-end on my machine
```
The main session first presents a plan (task table, model and thinking depth for each task, run location, concurrency). Dispatch only starts after you confirm. You can check progress at any time by asking, or by reading `.hq/LEDGER.md` directly.

## Design highlights
- **Difficulty tiers**: tasks are scored on 5 dimensions and grouped into five tiers, T0 to T4, mapping to haiku/low through opus/high. After a failure, first revise the task brief before considering a higher tier.
- **Run-location routing**: tasks that need local resources always run locally; long tasks that can run in parallel go to the cloud; small tasks run in-process.
- **Resource protection**: resources are checked before every dispatch, and dispatch is controlled at three levels: GREEN/YELLOW/RED. Each sub-session is given a build parallelism limit. At RED, the most recently started heavy task is stopped.
- **Quality control**: briefs must be complete, deliveries must include verification output, the main session re-runs the acceptance commands itself, and high-risk changes get a separate independent reviewer.
- **Recoverable**: all state is written to the ledger, so work can continue after context compression or a session restart.

## Known limitations
- Whether the local CLI can create cloud sub-sessions directly depends on the CLI version (see channel D in runtimes.md). Monitoring these sub-sessions is weaker. When you need strong monitoring, put the main session in the cloud and handle local tasks through "connect computer".
- In-process sub-agents share the same machine as the main session. Resource protection can only control dispatch pacing and cannot limit processes that sub-agents start themselves. So the parallelism limits in task briefs matter.
- The difficulty tier table is an empirical default. You can adjust it in step 2 of SKILL.md based on your account and actual experience.
