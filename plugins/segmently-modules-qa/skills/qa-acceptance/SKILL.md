---
name: qa-acceptance
description: Writes the acceptance criteria of one task before any code is written. Finds the touched modules with discover, reads their qa and qa_acceptance docs, flags problems in the task itself, splits it into sub-tasks, applies equivalence partitioning, boundary values, decision tables or state transitions, and writes prerequisites PRE-NNN and criteria AC-NNN in Given, When, Then form, reusing existing baseline criteria by id. Shows them in the conversation; a file only at a path the user names. Use when the user asks for acceptance criteria, a test plan or a definition of done for a task.
---

# qa-acceptance

Say, before the code exists, what "done" means for one task: measurable criteria that
prove every part of it works, that do not contradict each other, and that point at the
modules' baselines instead of repeating them.

The criteria come before the code (acceptance-test-driven): derive them from the task and the
module docs, never from a new implementation; write every **Then** as the expected behaviour.
The Part B scenarios are the spec for the tests written next — tests for new behaviour fail
until the work is done — and the work is done when every PRE and AC passes.

## When to use

- A task is agreed and the user wants its acceptance criteria, test plan or definition of done.
- A reviewer asks "how will we know this works?" before implementation starts.
- A planning flow's "acceptance criteria" step: the criteria are shown, and the plan waits for
  the user's OK or additions.

## When not to use

- The criteria are for a whole module (what must never break), not one task: use
  `qa-acceptance-baseline`.
- You need the modules and files the task touches, not criteria: use `module-discover`.
- A UI change needs mocks or a design review: use `designer`.

## Scope

Writes: nothing by default — the criteria are shown in the conversation; a Markdown file only
at a path the user names. It never edits code, module docs or a `*.legacy.md` file, and never
commits.

If `segmently-modules` is not found, tell the user how to install it — the `segmently-modules` plugin for Claude Code, `uv tool install git+https://github.com/segmently-ai/segmently-modules.git`, or `pipx install git+https://github.com/segmently-ai/segmently-modules.git` — and stop until it runs.

## Steps

Each step names the file it follows:

- **method** — the ten test dimensions and their enforcement matrix, risk → depth, the
  decomposition rules, criterion quality, coverage first, the self-check and the Quality Score
  → `references/method.md`
- **techniques** — how each technique derives the conditions, with examples
  → `references/techniques.md`
- **output** — the Part A template, the verification values and the Part B scenarios
  → `references/output.md`

1. Read the task: what is built or changed and why, what "done" looks like, and the moving
   parts (components, data flows, user interactions, integration points, interfaces).

2. Find the modules, at most 10: the ones the task names; then the keyword search — put the
   task text in a temporary file outside the repository, then

   ```bash
   segmently-modules discover --task-file <file> --match lexical --json
   ```

   — and the owners of any file the task names (`segmently-modules discover --files <path> --json`).
   Keep the `modify` modules and the `reference` modules whose docs really bear on the task.

3. Read what the modules already guarantee and how they are tested.

   ```bash
   segmently-modules show <module> --role qa_acceptance --json
   segmently-modules show <module> --role qa --json
   ```

   The `qa_acceptance` doc is the module's baseline (criteria with ids, P0 / P1 / P2); the `qa`
   doc says how the module is tested — its runner, selectors, test accounts, and where its
   coverage map is. A split module: the child the task touches — its own doc plus the parent's
   (the `parent baseline` row) — never every child. A baseline that is an index linking
   per-block files: only the block files the task touches. Read the flows of the `po`,
   `architect` and module docs too (`references/method.md`, decomposition rule 1). A missing
   doc (`exists: false`, or exit 2 "unknown role" when the `qa` pack is not enabled): work from
   the module's other docs and say so.

4. Check the task before writing criteria — non-contradiction (with itself and with a baseline
   criterion), logical coherence, completeness (implicit validation, error states,
   permissions), alignment with how users expect such a feature to behave, and ambiguity (two
   developers would build two things). List each issue as a spec issue: what is unclear, the
   risk, a proposed resolution.

5. Split the task into sub-tasks (functional, data, UI, integration, side effects) by the
   decomposition rules of `references/method.md` and fill its dimension enforcement check. For
   each sub-task pick the technique that fits and derive the conditions
   (`references/techniques.md`):

   - **equivalence partitioning** — input classes that behave alike, one case each;
   - **boundary value analysis** — the values at and just past each limit;
   - **decision table** — every combination of conditions that changes the outcome;
   - **state transition** — every allowed and every refused move between states;
   - **pairwise**, **use case** and **error guessing** — many parameters, an actor's flows,
     known fault patterns.

   Give each sub-task a risk (critical, high, medium, low) from its impact and likelihood; the
   risk sets the depth (`references/method.md`).

6. Write the criteria.

   - Prerequisites `PRE-NNN`: quick checks that the ground is ready (a service answers, a
     fixture exists), each with the check and the expected result.
   - Criteria `AC-NNN`, each with a **Title**, its **Sub-task**, **Technique**, **Risk** and
     **Verification** (`unit`, `e2e` or `manual`, as `references/output.md` says): **Given** a
     starting state, **When** one action, **Then** an observable result — an exact value,
     message, status code or file, never "works correctly".
   - In five categories: Functional Correctness, Completeness, Edge Cases, Error Handling and
     Regression Safety.
   - Coverage first: behaviour a baseline criterion already covers and the task does not
     change is referenced by id (`baseline-ref: <module> AC-007` in Regression Safety) instead
     of restating it; behaviour the task changes gets a new criterion, and the old baseline id
     goes into "Baseline Updates Needed". Regression Safety lists every P0 criterion of the
     touched modules that the task could affect.

7. Close the loop: every sub-task has at least one criterion; no two criteria contradict;
   every sub-task has a criterion from a technique of step 5, not only judgement; and if every
   criterion passed, the task would really be done. Then run the self-verification of
   `references/method.md`. Fix any gap before showing anything, and name the fixes in the Gap
   Analysis.

8. Write Part B: one runnable scenario per `e2e` criterion, coverage first against the coverage
   map the `qa` doc names, in the format it names (`references/output.md`).

9. Show the document — Part A in the shape of `references/output.md`, then Part B — in the
   conversation, and wait for the user's OK or additions before the work it defines starts. A
   path the user named: write the file there too, say where, and ask the user to review and
   commit it.

## Gates

- A spec issue that blocks a criterion (two readings that lead to different tests): ask which
  reading is meant, with your recommendation.
- After step 9: the user's OK or additions; the criteria are the definition of done for the
  work that follows.

## Exit codes

`0` ok · `2` from `discover` or `show` = a usage or config error: read stderr (an unknown role
means the `qa` pack is not enabled here — step 3).
