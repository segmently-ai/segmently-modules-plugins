# plan: a goal that takes several skills

Step 2 of `module-assistant` for a goal bigger than one skill — "get our module docs in shape",
"set up the CI gate", "split our biggest modules", "add a security role everywhere and fill it".

1. **The goal** the invocation names, else the user's words. When "done" is unclear, ask one
   question: what must be true at the end (lint clean, every module has a qa doc, CI fails on
   drift, …).

2. **Read the state** (read-only, only what the goal touches): `segmently-modules next --json`,
   `segmently-modules list --json`, `segmently-modules lint --json`, `segmently-modules roles list --json`,
   `segmently-modules coverage --json`, `segmently-modules code-map list --json`, `segmently-modules templates list --json`.

3. **Compose the plan in phases.** Each step: what, why, the skill or the command, its input
   (module, role, goal), what it writes, who confirms, and the check that proves it done. A
   step's exact commands and rules: the matching file of the table in `references/how-to.md`
   (e.g. the gate and drift: `references/how-to/upkeep.md`). Order:
   - set up or adopt first (`references/start.md`) — nothing else works before it;
   - lint errors before the writers: every later step builds on a registry that lints clean;
   - declarations before docs: a role, a field or a template the later steps rely on;
   - a split (`module-split`) before syncing or filling the docs of the module being split;
   - mapping code (`segmently-modules code-map add <id> --pattern '<dir>/{module}/**' --dry-run`) before
     drift and coverage checks mean anything;
   - the CI gate last: `segmently-modules ci --base <base> --json` locally (`<base>`: where the work
     branched off, `git merge-base <target> HEAD`), green, then the CI job.

4. **Show the plan short, in plain words:** at most four phases, one line per step (what
   changes) and one line for each phase's check; the questions you need, at most three. Commands,
   a step's inputs, what it writes, the effort, what you left out: when the user asks or when the
   step runs. Wait for the OK.

5. **Carry it out phase by phase.** Hand each judgement step to its skill; run the mechanical
   ones. After each phase run its check and `segmently-modules next --json`; report, and continue only
   while the plan holds — a surprise (a refused write, more modules than expected) stops for a
   new OK.
