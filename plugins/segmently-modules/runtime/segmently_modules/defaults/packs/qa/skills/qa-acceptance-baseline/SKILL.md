---
name: qa-acceptance-baseline
description: Creates or refreshes a module's acceptance baseline, the qa_acceptance role doc that says what must never break, as P0, P1 and P2 criteria with stable AC-NNN ids in Given, When, Then form. Reads every doc and the code of the module through Segmently Modules, confirms its understanding, the requirements and the criteria with the user block by block, continues from the highest existing id and never renumbers. Use when the user asks for a module's acceptance baseline, regression criteria, or to refresh them after the module changed.
argument-hint: "[module] [scenario] [block]"
arguments: module scenario block
---

# qa-acceptance-baseline

Write down, for one module, the behaviour that must keep working — as criteria with ids that
never change, so task-level criteria (`qa-acceptance`) and tests can point at them.

## When to use

- A module has no acceptance baseline yet, and the user wants one.
- A module changed and its baseline must catch up (new behaviour, changed behaviour, retired
  behaviour).
- A module's baseline grew too large to review as one file, or one block of a split baseline
  must be written.

## When not to use

- The criteria are for one task, not the whole module: use `qa-acceptance`.
- You only need to know how the module is tested today: use `module-scout` with the `qa` role.
- The module's other docs are out of date: use `module-sync` first — the baseline is built
  from them.

## Scope

Writes: the module's `qa_acceptance` doc, and its entry in the module's registry
`context_files` when the doc is new. The entry is also written for a doc that is on disk and that
the registry does not list, and a new doc is never written over it. In the block route, also its
per-block files next to the doc. It never edits code or another doc, never edits a
`*.legacy.md` file, and never commits.

If `segmently-modules` is not found, tell the user how to install it — the `segmently-modules` plugin for Claude Code, `uv tool install git+https://github.com/segmently-ai/segmently-modules.git`, or `pipx install git+https://github.com/segmently-ai/segmently-modules.git` — and stop until it runs.

## Steps

**Route.** Take the scenario named by the invocation (`$scenario`) when one is given, else by
the user's words, and its file below: read it, then follow it — its steps are step 6.

- **create** — the module has no acceptance baseline yet ("write", "create", "start" one)
  → `references/create.md`
- **refresh** — the module changed and its baseline must catch up ("refresh", "update" it —
  new, changed or retired behaviour) → `references/refresh.md`
- **block** — the baseline is an index of per-block files, or is to become one, or a block is
  named (`$block`, or `--block <category>/<name>` in the user's words) → `references/block.md`

If a `segmently-modules` command exits 1 or 2, read `references/exit-codes.md`.

Before step 1 read `references/method.md` (the ten dimensions, risk, decomposition, criterion
quality, coverage first, the self-check, the Quality Score) and `references/techniques.md`.
The doc is written in English, whatever the conversation's language. At any gate the user may
send corrections or screenshots: take them in and present the gate again before moving on.

1. Load the module. It is the one the invocation names (`$module`), else the user's words;
   none named: list the modules (`segmently-modules list --json`) and ask.

   ```bash
   segmently-modules show <module> --all-roles --json
   segmently-modules show <module> --role qa_acceptance --json
   segmently-modules code-map files <module> --json
   ```

   A `role:qa_acceptance` row with `exists: true` is the doc to refresh; read it and note the
   highest `AC-NNN` in it.

   A `child role:qa_acceptance` row with `exists: true` is a split child's own doc: refresh it
   the same way. A `parent baseline role:qa_acceptance` row is the parent's doc, not this
   module's.

   Without a `role:qa_acceptance` or `child role:qa_acceptance` row with `exists: true` (a
   `parent baseline` row does not count), run
   `segmently-modules roles add qa_acceptance <module> --dry-run --json`,
   which writes nothing, and read its status. Status `registered` means the module's
   `roles/qa_acceptance.md` is on disk and the registry does not list it: that file is the doc
   to refresh, so read it, note the highest `AC-NNN` in it, take the refresh route and never
   write a new doc over it. Status `exists` means the registry lists a doc that is on disk:
   refresh it, so read it and note the highest `AC-NNN` in it. Status `created` means there is
   no doc: take the create route. Status `missing` means the registry lists a path with no
   file: the create route writes the doc at that path and adds no second registry entry.

2. Read every doc of the module fully and skim its code files for the interfaces the docs name
   (entry points, commands, messages, limits). Read the module's existing baseline first when
   refreshing: catalogue its criteria per block.

3. **Gate 1 — understanding.** Present: the docs read (each doc Y/N with its line count, the
   code files scanned); what the module does and why (3–5 sentences: purpose, how it works,
   the key data flow, its role in the system); an **Integration & Dependencies** table (what
   it needs from which module, which module uses it for what); its main flows as numbered
   steps; its functional blocks, each with key components and a risk; the rules its docs state
   (MANDATORY, FORBIDDEN, CRITICAL); the **dimension enforcement check** of
   `references/method.md`, one row per block; the edge cases and gotchas you found; spec issues
   and anything the docs and the code disagree on. Wait for "ok" or corrections.

4. For each functional block:

   - list its requirements — API contracts, architecture rules, data flows, integration
     points, edge cases, business rules, error scenarios, user interactions — each as
     `REQ-NNN: <requirement> [source: <file> > <section>]` with its technique, risk and
     dimensions, each traced to a doc line or a code file — **Gate 2**: present the block's
     requirements table and its dimension coverage (a dimension with no requirement is named
     as a gap), and wait for the user to confirm the list;
   - write its criteria: one per condition the technique produces (`references/techniques.md`:
     equivalence partitioning, boundary values — ±1 for critical and high —, decision table,
     state transition, pairwise, use case, error guessing); **Given** / **When** / **Then** with
     an observable result; each criterion with its **REQ**, **Technique**, **Risk**,
     **Dimension** and **Verification** (`unit`, `e2e` or `manual`: tests are planned from it);
     P0 for critical and high risk, P1 for medium, P2 for low — **Gate 3**: present them with
     the block's P0 / P1 / P2 totals and wait for the user to confirm the criteria.

   For a large module, batch the criteria of several blocks into one Gate 3; never skip Gate 2.
   Up to 8 blocks: Gate 3 per block; 9–15: batches of 3–5 blocks; 16 or more, or when the user
   asks for all at once: one review with a P0 / P1 / P2 table per block.

5. Assemble, after the last block: run the self-verification and the minimum per dimension of
   `references/method.md` and add criteria where one fails; the gap analysis (every REQ has a
   criterion, every criterion traces to a REQ, every architecture rule has a criterion, no
   contradictions, the ten dimensions covered or N/A); the Regression Risks (one per
   architecture rule and per spec issue: what breaks if it is violated, the criteria that catch
   it); the full requirements inventory (per-block tables, never a subset). **Final
   confirmation**: present the totals (requirements, P0 / P1 / P2, dimensions, architecture
   rules covered) and the gaps, and wait for the user's "ok".

6. Write the doc. Follow the scenario's file (the Route above). The shape is the template's:
   Summary, Priority Matrix, then per block its requirements and P0 / P1 / P2, then
   Architecture Rule Coverage, Regression Risks, Specification Issues, Dimension Coverage
   Matrix, Gap Analysis, Quality Score and Retired.

7. Check it.

   ```bash
   segmently-modules lint --json
   segmently-modules show <module> --role qa_acceptance --json
   ```

   No finding for the doc; the `role:qa_acceptance` row exists. Report the criteria added,
   changed and retired per priority, and ask the user to review and commit.

## Gates

Three, never skipped: Gate 1 (understanding), Gate 2 (each block's requirements), Gate 3 (the
criteria, per block or per batch). Nothing is written before Gate 3 of the last block.
The final confirmation of step 5 comes before the write too.
