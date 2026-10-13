# The init flow in detail

The init flow keeps everything in `<config_dir>/init/` (git-ignored).
`segmently-modules init status --json` shows each phase — `preflight`, `map`, `gate-map`, `fanout`,
`reconcile`, `eval-tasks`, `verify`, `finish` — and each module: `pending`, `running`, `done` or
`failed`.

## The files

| File | Written by | What it holds |
|---|---|---|
| `proposal.json` | `init map` | the candidates; edited at gate 3 |
| `confirmed.json` | `init confirm` | the confirmed proposal |
| `work/<module>.json` | `init fanout` | one work item: `module`, `paths`, `files`, `neighbours`, `roles`, `staging_dir`, `prompt` |
| `staging/<module>/` | the writers | `MODULE.md`, `roles/<role>.md` per role, `entry.json` |
| `staging/registry.json` | `init reconcile` | the registry `init finish` will write |
| `reconcile.json` | `init reconcile` | `edges`, `collisions`, `duplicates`, `judgement` |
| `routing-tasks.json` | a task writer, or `init eval-tasks` | `[{task, module}]` |
| `verify.json` | `init verify` | lint, invented components, routing, `passed` |

## A writer's brief

Give each writer its work item path and these rules (the item's `prompt` says the same):

- Read the module's code first: the files the work item lists.
- Write exactly `MODULE.md`, one `roles/<role>.md` per role of the item, and `entry.json` into
  the item's `staging_dir` — no other file, nothing outside it.
- `entry.json`: `description` (one sentence within the length limits of the prompt),
  `keywords` (at least the prompt's minimum, the words a developer would type in a task about
  this module, including the things and actions its `## Purpose` paragraph names even where
  the code names them differently — routing matches whole words without stemming, so single
  words with the plural and verb forms of the key nouns, and each key verb in every form tasks
  use: base, `-s`, `-ed`, `-ing`), optional `related_modules` edges to the neighbours.
- Name only what exists: every path in backticks exists, written from the repository root
  (never from a package, never an import specifier or a sibling doc's bare name); in the
  components table (`| Name | Path | Purpose |`) a `Name` in backticks is a symbol defined in
  that row's file.
- Fill every placeholder of the templates; leave no template placeholder behind.
- Under `## Purpose`, a paragraph in the writer's own words that stands without the
  description: the routing eval shows it to the task writer.

## Keeping the task writer blind

The routing eval measures whether the keywords route real tasks. The task writer sees only the
prompt of `segmently-modules eval routing --prompt --json`: each module's purpose paragraph and file list.
Never paste keywords, descriptions or the staging registry into its context, and never edit the
tasks to raise the hit rate — improve the keywords instead.

## When something is off

| Situation | What to do |
|---|---|
| `init done` exit 1 | the stderr lines name each problem — a path that does not exist or a symbol not in its row's file with the doc and line; the writer fixes them, check again |
| a claimed item has `previous_problems` | an earlier attempt (a CI run) was refused: the claim result's `item.prompt` ends with those problems, but the work item file does not hold them — give a subagent the problems together with its work item path, and have the writer fix them first |
| a subagent died mid-item | `segmently-modules init status --json` shows it `running`; `segmently-modules init resume --json` puts it back to `pending` (its staging cleared) |
| `init reconcile` exit 2: staging registry edited | keep the edits (verify reads them) — rebuild only on the user's word: `segmently-modules init reconcile --force --json` |
| a `keyword-tie` judgement item | by default the word stays on every module that holds it (routing ranks the modules by their other words too); only when the user names one owner, remove it from the other modules' `keywords` in `<config_dir>/init/staging/registry.json` — never as a negative keyword |
| `init eval-tasks` exit 1 | the refused file is in `routing-tasks.rejected.json`; the next step is `segmently-modules init eval-tasks --executor "<command>" --json` again |
| `init finish` exit 2: a directory or module appeared | someone created it by hand: ask the user, never overwrite — only moving the directory away clears it |
| `init finish` exit 2: the staging registry changes a module already in the registry | move that change into the registry itself (the user decides), then `segmently-modules init reconcile --force --json` — it rebuilds the staging registry, so the new modules' keyword edits come after it — and verify again |
| no subagents available | the sequential loop: `init next`, write, `init done`, one module at a time |

A pipeline without a person runs the same flow with an executor:
`segmently-modules init resume --non-interactive --executor "<command>" --json` — see the engine's
`docs/init.md`.
