---
name: module-split
description: Splits an oversized module into two to six child modules. Analyses the module's docs section by section, proposes the children with a section-to-child table per doc and what stays in the parent, and stops for confirmation. Then freezes each split doc as a legacy copy, creates the children with create, moves the sections word for word, rewrites the parent as an index, routes the code and validates with lint. Use when lint reports a module doc over its size budget, or the user says "split this module", "too big", "break X into submodules".
---

# module-split

Turn one module whose docs outgrew their budget into a parent index plus children without
losing a line: every moved section lands verbatim in one child, the originals stay frozen next
to the new docs, and routing keeps working.

## When to use

- Lint reports MS030 (a module doc past the split signal) or MS031 (past the hard stop) for
  the module, or `module-sync` proposed the split.
- The user asks to split, decompose or break a module into submodules.
- A split module needs a child added, a child rebalanced, or its sizes reported.

## When not to use

- The module is under the signals: refuse (step 1) — moving detail into its role docs is a
  `module-sync` job — unless the user explicitly overrides.
- The doc is long because of dated history ("Sprint N additions", checkpoints), API dumps or
  checklists: move those into a supplementary doc first (`module-lint`); split only what is
  still too long after that.
- A brand-new area is not a split: use `module-create`.

## Scope

Writes: frozen `*.legacy.md` copies of the docs it splits, the new children (docs and registry
entries, through the `create` verb), the parent's module doc and role docs (rewritten as an
index and baselines), and routing rules for the children's code (the `code-map add` verb). A
`*.legacy.md` file is written once, as a byte copy, and never edited afterwards. It never
changes the parent's keywords, never edits code, and never commits.

If `segmently-modules` is not found, tell the user how to install it — the `segmently-modules` plugin for Claude Code, `uv tool install git+https://github.com/segmently-ai/segmently-modules.git`, or `pipx install git+https://github.com/segmently-ai/segmently-modules.git` — and stop until it runs.

## Steps

- **already-split** — add a child, rebalance, report sizes → `references/already-split.md`
- **shapes** — index, baselines, child docs (steps 5–6) → `references/shapes.md`
- **check** — checks, report (steps 8–9) → `references/check.md`

1. Analyse.

   ```bash
   segmently-modules show <module> --all-roles --json
   segmently-modules lint --json
   segmently-modules related <module> --json
   segmently-modules code-map files <module> --json
   ```

   - The result has `submodules`: follow `references/already-split.md`. Never split again.
   - No MS030 / MS031 for the module: refuse, name the signal it is under and suggest moving
     detail into the role docs; go on only when the user explicitly overrides.
   - Outline each doc in `read[]` — every level-two and level-three heading · first–last line ·
     length · topic in a few words — under the doc's total length.
   - Group sections by cohesion (what changes together, what one task would touch), then hold
     the groups against the code: separate `code-map files` paths → separate children.

2. Propose, then **stop**.

   - Three to six children (two only with the reason stated): name (lowercase words joined by
     `-`), one-line scope, keywords taken from the parent's (at least one each), expected lines.
   - For every doc to split — the module doc and each role doc — a table: section · lines ·
     target (a child, or the parent).
   - What stays in the parent: module-wide rules, shared tables, anything other modules link to,
     and every section a tool or another module reads from the parent doc. What stays in each
     parent role doc: the module-wide baseline.
   - Per child, the roles without area content: no doc for them (the parent's covers it).

   Wait for the user's confirmation. Apply every correction (merge, rename, re-scope) and show
   the table again before writing anything.

3. Freeze. For each doc you will split, copy it byte for byte to a sibling named
   `<name>.legacy.md` — for example `MODULE.md` → `MODULE.legacy.md`, `roles/qa.md` →
   `roles/qa.legacy.md`. If such a file exists already, stop: an earlier split left it, and it
   is never overwritten. From here on the legacy copies are read, never edited.

4. Create the children, one command per child, with only the roles whose docs receive sections:

   ```bash
   segmently-modules create <child> --parent <module> --non-interactive --description "<scope>" --keywords "<k1, k2>" --no-standard-roles --role <role> --json
   ```

5. Move the sections verbatim — no rewording — into the child docs `create` wrote, replacing
   their template prompts; fix relative links for the new directory depth.

6. Rewrite the parent (`references/shapes.md`): its module doc becomes the index, each split
   role doc the baseline for that role. The parent's keywords stay unchanged: never remove one (tasks that match them
   still land on the parent and its routing table).

7. Route the code: for each child whose code has its own paths,

   ```bash
   segmently-modules code-map add <rule id> --glob "<glob>" --module <module>/<child> --exclusive --dry-run
   segmently-modules code-map add <rule id> --glob "<glob>" --module <module>/<child> --exclusive --json
   ```

   `--exclusive` keeps a broader rule of the parent from claiming the same files.

8. Validate.

   ```bash
   segmently-modules lint --json
   segmently-modules lint --changed --base HEAD --json
   segmently-modules show <module> --json
   ```

   Check every item of `references/check.md` and fix what fails.

9. Report as `references/check.md` says. Ask the user to review and commit.

## Gates

- After the proposal (step 2): **STOP** until the user confirms the children and the tables.
  Nothing is written before that.
- Before each routing rule (step 7): show the dry run.

## Exit codes

`0` ok · `1` from `lint` = findings (fix what the split caused) · `2` = a refused input or a
config error: read stderr, fix, run again.
