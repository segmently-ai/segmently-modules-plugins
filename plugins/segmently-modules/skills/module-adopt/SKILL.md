---
name: module-adopt
description: Makes Segmently Modules read a module registry and module docs that another tool or team already wrote, without changing them. Runs adopt to infer the team config (paths, roles, fields, statuses, a code-map rule), explains each inference and its evidence, asks only what adopt never guesses, writes the config and shows the lint report grouped by code. Use when a repository already has a registry and wants Segmently Modules to work with it, or the user asks to adopt, import or take over an existing registry.
---

# module-adopt

Bring Segmently Modules to a registry that already exists: infer the config the engine needs to read it
as it is, with the user deciding what no inference can know. The registry and the module docs
stay exactly as they are.

## When to use

- The repository has a registry and module docs that other tooling or another team wrote, and
  no Segmently Modules config yet (or a config that does not read the registry cleanly).
- The user asks to adopt, import or take over an existing module registry.

## When not to use

- The repository has code but no registry yet: use `module-init`.
- Lint findings in a registry Segmently Modules already reads: use `module-lint`.
- One new module: use `module-create`.

## Scope

Writes: the team config that `adopt` writes — a new `<config_dir>/config.toml`, or
`<config_dir>/adopt.proposed.toml` when a config already exists — and, only on the user's yes,
the answers to the questions below in that file. It never edits the registry or a module doc,
never edits a `*.legacy.md` file, never edits an existing `config.toml` without a yes, and
never commits: the user reviews and commits.

If `segmently-modules` is not found, tell the user how to install it — the `segmently-modules` plugin for Claude Code, `uv tool install git+https://github.com/segmently-ai/segmently-modules.git`, or `pipx install git+https://github.com/segmently-ai/segmently-modules.git` — and stop until it runs.

## Steps

1. **See what adopt infers, writing nothing.**

   ```bash
   segmently-modules adopt --dry-run --json
   ```

   `data.config` is the TOML it would write; every key is followed by `# adopt:` lines with
   the evidence. Explain each inference with its evidence, in a few words each: the registry's
   path and layout, the roles (`order`, `standard`), the fields (`type`, `kind`, `scope`), the
   directories that are not modules, the timestamp key, the statuses and relation types the
   registry uses, the code-map rule or the commented-out suggestion, the doc budgets (commented
   out). `inferred.skipped` names the keys no type expresses: lint keeps reporting them.

2. **Write it.**

   ```bash
   segmently-modules adopt --json
   ```

   With no config yet, it creates `<config_dir>/config.toml` — a new file: adopt never edits
   an existing one, so nothing of the user's changes. Write it without waiting for the answers
   of step 4: the user asked for a config that reads the registry as it is. When a config
   already exists, it writes `<config_dir>/adopt.proposed.toml` instead: explain that file,
   then help the user merge what they want into `config.toml` by hand — edit `config.toml`
   only after the user says yes to each change — and delete the proposal afterwards.

3. **Show the lint report.**

   ```bash
   segmently-modules lint --json
   ```

   Run it: never report a lint result you did not run. Group the findings by code (count, one
   example each) and say what each code means. Fix nothing here: hand the fixes to
   `module-lint`, by name, and say which findings it can fix safely and which need a decision.

4. **Then ask what adopt never guesses** — only these, one at a time, and only when they
   apply:

   - a role's `applies_when`: should a tag (`create --tag <tag>`) scaffold that role's doc for
     new modules?
   - a field's `deprecated`: is any inferred field on its way out (and what replaces it)?
   - a budget: should a commented-out doc budget become active?

   Add each answer to the config only on the user's yes. When no one can answer now, list the
   open questions in the report: the config already reads the registry without them.

5. **Report** the file written, the answers applied (and the questions still open), the lint
   counts and the next steps from `data.next_steps` (for instance `segmently-modules init --json` for the
   `.gitignore` lines). Ask the user to review and commit.

## Gates

- Before step 2: the dry run is shown and explained.
- Every answer of step 4, and every edit of an existing `config.toml`: an explicit yes.

## Exit codes

`0` ok (adopt exits 0 whatever its lint report finds) · `1` from `lint` = findings: report them
by code · `2` = no registry, a registry that does not parse, a refused `--layout`: read stderr,
it names the fix.
