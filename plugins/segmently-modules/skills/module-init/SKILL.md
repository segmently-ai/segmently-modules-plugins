---
name: module-init
description: Starts Segmently Modules from an existing codebase that has no module registry yet. Maps the code into candidate modules and stops for the user to confirm them, has one writer per module document its code (subagents, or itself one module at a time), reconciles the registry, measures how well tasks route, and stops again before anything lands in the repository. Use when the user asks to set up, bootstrap or generate module docs for an existing repository, or to continue an interrupted init.
---

# module-init

Take a repository that has code but no module registry to a working setup — a registry, one doc
set per module, code routing rules, the agents' block — through Segmently Modules' `init`. The engine keeps
the state in `<config_dir>/init/`; this skill supplies the judgement and the two stops where the
user decides.

## When to use

- The repository has code and no modules yet, and the user wants module docs for it.
- An init was started earlier (by a person, a pipeline or another session) and the user
  says "continue", "resume" or "finish the init".

## When not to use

- The repository already has a registry and module docs written by other tooling: use
  `module-adopt`.
- One new module in a repository that already has modules: use `module-create`.
- An oversized module must become children: use `module-split`.

## Scope

Writes: the proposal at gate 3 (only the edits the user asked for), the work items' staging
docs through its writers, the staging registry's keywords, and — after the user's yes at gate 7
— what the finish step writes (the module docs, the registry, the code-map rules, the
agents' block). It never edits code, never edits a `*.legacy.md` file, never touches a module
that was already in the registry, and never commits: the user reviews and commits.

If `segmently-modules` is not found, tell the user how to install it — the `segmently-modules` plugin for Claude Code, `uv tool install git+https://github.com/segmently-ai/segmently-modules.git`, or `pipx install git+https://github.com/segmently-ai/segmently-modules.git` — and stop until it runs.

## Steps

1. **Where are we?** Run `segmently-modules init status --json` first and continue from the recorded phase
   (its `next` names the step). Without a state, start at step 2. A module already in the
   registry when the fan-out ran shows as `done (existing)`: it is kept as it is.

2. **Map the code.**

   ```bash
   segmently-modules init map --json
   ```

   It writes `<config_dir>/init/proposal.json`. Present the candidates in a short table —
   name, paths, confidence, the rationale in a few words — then the `hints` (`merge`, `split`;
   a `split` with `children`: offer them, grouped by feature) and the `unassigned` code files.
   The seed keywords are already filtered (no npm scope, no
   token of 3 characters or fewer).

3. **STOP — gate 3.** Ask the user which candidates to keep, merge, split, rename or exclude.
   Apply exactly those merges, splits, renames and exclusions to `proposal.json` (`include`,
   `name`, `paths`), nothing else, then confirm:

   ```bash
   segmently-modules init confirm --json
   ```

   Exit 2 lists every problem at once (a name that breaks the rule, a glob that matches no
   file, two candidates claiming one file): fix them with the user and confirm again. After the
   fan-out starts, the module set is fixed (only `segmently-modules init map --restart --json` starts over).

4. **Write the work items.**

   ```bash
   segmently-modules init fanout --json
   ```

   One work item per confirmed module in `<config_dir>/init/work/<module>.json`, each with the
   `prompt` its writer follows. `init status` shows each module's status.

5. **Have every module written.** Claim items with `segmently-modules init next --json` — never
   dispatch an item you did not claim. With subagents: claim at most `max_parallel` items
   (`[init] max_parallel`, 4 by default) and dispatch one subagent per item, each given its work
   item path (`path` in the result) and told to follow the item's `prompt` and write only into
   its `staging_dir`; claim the next item as one finishes. Without subagents, loop yourself:
   claim, read the module's code, write its files, check, claim the next. After each writer:

   ```bash
   segmently-modules init done <module> --json
   ```

   Exit 1 names each problem of the staging output (a missing doc, an unfilled placeholder, a
   path that does not exist, a symbol not in its row's file, too few keywords, an edge to an
   unknown module): have the same writer fix them while it has the context, then check again.
   A claim whose `item` has `previous_problems` (an earlier attempt was refused) goes to the
   writer with them: give a subagent those problems together with its work item path — the
   work item file does not hold them — and tell it to fix them first; without subagents, the
   claim result's `item.prompt` already ends with them.
   An item that stays wrong: tell the user. The detailed rules for writers are in
   `references/phases.md`.

6. **Reconcile.**

   ```bash
   segmently-modules init reconcile --json
   ```

   It adds the import edges, gives a keyword several new modules share to the one with the most
   files and removes it only from the modules whose code never mentions it (no negative
   keyword), drops a keyword no holder's code mentions (`dropped`: show them in one line), and
   lists the `judgement` items it will not decide. Ask the user about each
   keyword tie (whether one module owns the word) and each keyword that could not be removed
   without dropping a module below the keyword minimum;
   report the duplicate names with their file:line (the user decides later whether code
   moves). By default a tied keyword stays on every module that holds it, since routing ranks
   the modules by their other words too; only when the user names one owner, remove the word
   from the other modules' `keywords` — never as a negative keyword. Apply the user's keyword
   answers to `<config_dir>/init/staging/registry.json`.

7. **Measure routing.** Get the task writer's prompt:

   ```bash
   segmently-modules eval routing --prompt --json
   ```

   Have a subagent that never shows the keywords — it gets only this prompt — write the tasks
   as JSON into `<config_dir>/init/routing-tasks.json`. Without subagents, write them yourself
   from the prompt alone, before you look at any keyword. Then verify:

   ```bash
   segmently-modules init verify --json
   ```

8. **Fix what verify found.** Lint findings: fix the staging docs or the staging registry.
   Invented components (a path that does not exist, a symbol not in its file): remove or
   correct them in the staging docs. `keywords` rows (too many words, a generic word): trim
   them in the staging registry, `unused_keywords` first. Routing misses below the threshold:
   change keywords, never the tasks — at most 2 rounds; after that, report the remaining
   misses. Each round, in this order:
   - First, a missed module that was already in the registry (`done (existing)`): it is never
     changed in the staging registry — the finish step refuses that. Ask the user, change it in
     the registry itself, then run `segmently-modules init reconcile --force --json`. It rebuilds the
     staging registry from the writers' files, so a keyword edit made there before it is lost.
   - Then improve the keywords of the missed NEW modules in the staging registry (the words
     the missed tasks used).
   - Then verify again.

9. **STOP — gate 7.** Show the verify summary: lint counts, invented components, the hit rate
   and its misses, the first-place rate, the judgement items still open. End that message
   with one direct yes/no
   question — "Shall I run segmently-modules init finish now?" — and wait for the answer: naming the next
   command is not asking. Only on a yes:

   ```bash
   segmently-modules init finish --json
   ```

   It moves the docs into place, writes the registry, the code-map rules and the agents' block.
   Show its `git_add` line and ask the user to review and commit. Never commit yourself.

## Gates

- Gate 3 (step 3): nothing is written into `work/` before the user confirmed the candidates.
- Gate 7 (step 9): nothing lands in the modules dir, the registry or the config before the
  user's yes.
- The finish step refuses a verify that has not passed, or a staging tree changed since:
  run `segmently-modules init verify --json` again; use `--force` only when the user asks for it.

## Exit codes

`0` ok · `1` findings: `init done` problems, a verify or eval that did not pass — fix and run
again · `2` a refused step (the wrong phase, a bad proposal, a conflict): read stderr, it names
the step to run.
