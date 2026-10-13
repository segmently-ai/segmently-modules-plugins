---
name: module-lint
description: Runs the module-system gate with ci (or lint when there is no base), explains every finding from its code, fixes what is safe to fix with the CLI verbs, leaves judgement calls to the user and runs the gate again until it is green or only judgement calls are left. Use when the user says "fix lint", "make ci pass", "why does the module check fail", or after a skill or a person reports module lint findings.
---

# module-lint

Get the module checks green: explain each finding in plain words, fix the mechanical ones, and
hand the ones that need a decision to the user with the options.

## When to use

- The Segmently Modules gate (the `ci` or the `lint` verb) fails, locally or in CI.
- The user asks what a finding means or how to fix it.
- Another skill finished and its check reported findings it did not cause.

## When not to use

- The findings are drift (MS050) after a code change: the docs need real updates — use
  `module-sync`.
- A doc is over its size budget (MS030 / MS031 / MS032) and still too long once its dated
  history and reference sections moved into a supplementary doc (the trim, see the lint codes):
  that is a split — use `module-split`.
- You need context on a module, not a fix: use `module-scout`.

## Scope

Writes: registry fields through the `registry` verb and small doc fixes (a missing section, a
stale path) — only for the findings it fixes. It never edits a `*.legacy.md` file, never
changes code, never changes the team config or a pack without asking, and never commits.

If `segmently-modules` is not found, tell the user how to install it — the `segmently-modules` plugin for Claude Code, `uv tool install git+https://github.com/segmently-ai/segmently-modules.git`, or `pipx install git+https://github.com/segmently-ai/segmently-modules.git` — and stop until it runs.

## Steps

1. Run the gate.

   ```bash
   segmently-modules ci --base <base> --json
   segmently-modules lint --json
   ```

   When the work sits on a branch, run `ci`: it always runs `lint`, `drift` and `coverage`.
   Its `<base>` is the commit the branch grew from, as `git merge-base <target> HEAD` prints
   it — not the target branch's name, whose newer commits would turn up as drift of this work.
   With no branch to compare, plain `lint`. Findings with module `*` concern the config, packs
   or routing rules, not one module.

2. Explain every finding: its code, module and message, in one line of plain words. The
   meaning and the usual fix of every code are in [references/lint-codes.md](references/lint-codes.md).

3. Fix the safe ones — a mechanical fix with no decision in it:

   ```bash
   segmently-modules registry set <module> name '"<module>"' --json
   segmently-modules registry remove <module> keywords '""' --json
   ```

   - A value lint rejects is also refused by the writer (exit 2 naming the rule): read the
     message, correct the value.
   - A doc path that points at a moved file: check where the file is now, then correct the
     path (`segmently-modules registry set <module> context_files '<the corrected object>' --json`).
   - A frozen `*.legacy.md` that was changed (MS051): restore it from git — never edit it
     further.
   - A link whose target moved (MS041 naming where the file is now, e.g. "fix the ../ depth"):
     correct the link in the doc.

4. Leave the judgement calls to the user, each with the options you see: a `status` outside
   the configured list (which one? the message lists them), a relation to another module
   (which one? which relation?), a keyword shared by many modules, overlapping routing rules
   (which rule wins?), an undeclared or deprecated field, a pack finding (the pack's owner
   decides), budgets (split or trim?).

5. Run the gate again (step 1). Repeat until it passes or only judgement calls remain.

6. Report: fixed (code · module · what changed), left for the user (code · module · the
   options), and the final gate status. Ask the user to review and commit.

## Gates

It fixes only what needs no decision; everything else stops at the user with the options.
It asks before touching the team config or a pack.

## Exit codes

`0` ok · `1` = findings at or above the fail level (the normal case here: read them) · `2` = a
usage or config error, or a refused write: read stderr, fix the input.
