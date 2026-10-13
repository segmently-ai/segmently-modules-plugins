---
name: module-sync
description: Brings module docs and registry fields in line with a work session — what it decided, rejected, discovered and changed. Takes the session's knowledge first and the code change second, asks sync-instructions which docs to update, prints findings and a proposal per module, edits docs, keywords and links, runs the sync hooks and checks with ci. Autonomous, it asks only in four ambiguous cases and never commits. Use at the end of a session that changed module code or revealed module knowledge, when the user says "sync the session", "sync the docs", or a CI drift check fails.
---

# module-sync

## When to use

- A session changed module code or revealed module knowledge (a decision, a gotcha, a rule found
  while debugging); the gate reports drift (MS050); the user asks to sync the session or the docs.

## When not to use

- Nothing was done or learned yet: use `module-scout` or `module-discover`.
- The work needs a new module: use `module-create` first.
- A module doc grew too long (lint MS030 / MS031): use `module-split`.
- Only lint findings need fixing: use `module-lint`.
- A role is new, and the existing modules lack its doc: use `module-roles`.

## Scope

Writes: the docs of the modules the session touched or made untrue, and their registry fields
(the `registry` verb or queued proposals). It never edits a `*.legacy.md` file, never hand-edits a
role doc another skill owns (it flags it), never edits code, never commits, and never touches
another module unless the user asks. Temporary files go outside the repository.

If `segmently-modules` is not found, tell the user how to install it — the `segmently-modules` plugin for Claude Code, `uv tool install git+https://github.com/segmently-ai/segmently-modules.git`, or `pipx install git+https://github.com/segmently-ai/segmently-modules.git` — and stop until it runs.

## Steps

The session is the primary source; the change in git confirms it and finds missed modules.

- **session** — what to take from the conversation (step 1) → `references/session.md`
- **placement** — which doc gets what; checks; queued writes (steps 6–7) → `references/placement.md`
- **report** — findings, proposals, final report (steps 5, 10) → `references/report.md`

1. Extract the session's knowledge (`references/session.md`): the plan goal, decisions with the
   rejected alternatives, discoveries, patterns, gotchas, new cross-module dependencies and
   critical rules, each mapped to a module.

2. Pin the change. `<base>` is where the work branched off: `git merge-base <target> HEAD`,
   `<target>` being the branch it merges into (ask when unclear) — never the target itself (its
   later commits would drag in untouched modules). Committed work is `<base>..HEAD`;
   uncommitted work is the files `git diff --name-only <base>` prints plus the new ones
   `git ls-files --others --exclude-standard` prints, all to `--files` (never a directory). No
   code changed: `<base>` is `HEAD`, and step 3 takes `--module`.

   Before you edit, save the gate: `segmently-modules ci --base <base> --json > <ci file>` (outside the
   repository; ignore its exit code).

3. Ask Segmently Modules what to update — always, a session without a code change too.

   ```bash
   segmently-modules sync-instructions --from-diff <base>..HEAD --json
   segmently-modules sync-instructions --files <path> <path> --json
   segmently-modules sync-instructions --module <module> --module <module> --json
   ```

   `--module`: the modules step 1 mapped that the change does not show. Per module row:
   `docs_to_update`; `children` on a split parent: pick the child the change is in
   and update its doc too (it clears the parent's MS050); `drift` (MS050 = code changed, no doc;
   MS051 = a frozen snapshot was touched — restore it from git, never "fix" it); `fields` with
   their `sync_hint`; `proposals_pending` (changes already queued). Report `files_outside_modules`
   (no module owns them: `module-create` or a routing rule).

4. Find the modules whose docs describe what changed (the code map misses one that only documents
   it). Search as `references/choose.md` says.
   Each candidate whose docs describe the change joins the modules to update, with the docs the
   search listed.

5. Before any edit, print in your reply — the user audits the run from it
   (`references/report.md`):
   - **Findings**: each session item (kind · module · fact); the modules to update, why, their
     files; files outside every module;
   - **Proposal: <module>**, one per module: each doc's change and target; registry changes.

   Then apply without waiting. Interactive mode (the user asked for it): stop after the
   findings, then ask `ok / skip / edit` per module.

6. Only after that print, write each module's docs as `references/placement.md` says: the session's items and the
   change, each in the doc its readers look in. Add what they introduced, correct what they made
   untrue, remove nothing still true. Short, factual, linked to code paths, never copied code.

7. Update the registry fields the hints point at.

   ```bash
   segmently-modules registry append <module> keywords '"<new word>"' --json
   segmently-modules related <module> --json
   segmently-modules registry append <module> related_modules '{"module": "<other>", "relation": "<relation>", "description": "<why>"}' --json
   ```

   - `keywords`: most changes add none. Add one only for a new feature, command or concept that
     people will name in later tasks and that no keyword or the description covers yet — never a
     code identifier (a class, function, file or variable name: code search finds those), never
     one per task. Keywords only grow; a split parent keeps all of them — never remove one from it.
   - `related_modules`, a refused write, queued changes: `references/placement.md`.

8. Run the team's sync hooks (the second form for uncommitted work). Skip this step when step 7 ran
   `sync --apply-proposals` (it ran them).

   ```bash
   segmently-modules sync --from-diff <base>..HEAD --json
   segmently-modules sync --files <path> <path> --json
   ```

   Report every hook message. A failed required hook (exit 1): stop, never bypass it.

9. Check: `segmently-modules ci --base <base> --baseline <ci file> --json`. Its steps (`lint`, `drift`,
   `coverage`) should pass or be report-only; a `known` finding predates your edits: report it, but
   fix one the change caused (a moved or deleted path). Fix what your updates caused and rerun.

10. Report as `references/report.md` says (the plan goal, the budget action items, your
    decisions and questions among it). Ask the user to review and commit.

## Gates

Autonomous by default: it decides, applies and records each decision in the report. It stops and
asks only when:

1. an update fits two children of a split module equally well;
2. new work may be a new top-level module or a child of an existing one;
3. the change contradicts a claim in the docs that nobody confirmed in this session (rewrite the
   claim, or only flag the drift?);
4. the only home for the new text is a `*.legacy.md` file — never edited; ask where it should go
   instead.

Interactive mode adds the stops of step 5.

## Exit codes

`0` ok · `1` = findings, a failed `ci` step or hook, a rejected proposal: read and act · `2` = a
usage or config error, a refused write: read stderr, fix the input, run again once.
