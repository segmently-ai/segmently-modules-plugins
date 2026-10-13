---
name: module-roles
description: Adds a new role's doc to every existing module, or marks a module that does not need the role. Declares the role when it is undeclared, shows the plan with roles add --dry-run, writes the docs, fills each one from that module's code and docs, then checks lint and next. Use when the user says "add a role", "a new role for every module", "the upgrade brought a role", "this module does not need that role", or when next names roles add.
---

# module-roles

## When to use

- The team (or a newer Segmently Modules) added a role, and the existing modules lack its doc.
- The user asks to add a role to every module, or `segmently-modules next --json` names `roles add` for a role.
- The user says a module does not need a role, or needs it after all.

## When not to use

- A code change made the docs stale: use `module-sync`.
- The work needs a new module: use `module-create`.
- Only lint findings need fixing: use `module-lint`.

## Scope

Writes: one `roles/<role>.md` doc per registered module (a split module's children inherit the
parent's: `roles add --all` writes none for them; never over an existing doc), a not-needed mark
in the registry for a module the user says needs no doc, and the role's declaration in the team
config when it is undeclared. It never edits a `*.legacy.md`
file, never edits code, never commits; ask the user to review and commit. Temporary files go
outside the repository.

If `segmently-modules` is not found, tell the user how to install it — the `segmently-modules` plugin for Claude Code, `uv tool install git+https://github.com/segmently-ai/segmently-modules.git`, or `pipx install git+https://github.com/segmently-ai/segmently-modules.git` — and stop until it runs.

## Steps

When the team (or a newer Segmently Modules) adds a role, the existing modules lack its doc.

When `segmently-modules next --json` names the roles add command with --all for a role (the upgrade brought
the role), the role is declared already — start at step 1.

If `segmently-modules roles list --json` does not list the role, declare it first: a [roles.ROLE] table with
order, standard = true (every module gets the doc) and a one-line description in the team config,
.segmently-modules/config.toml, or in a pack the team owns — ask the user what the role is for when unclear.
Then continue with step 1.

1. `segmently-modules roles add ROLE --all --dry-run` — show the user the docs it would create or register and
   the registered ones missing on disk.
2. `segmently-modules roles add ROLE --all --json` — writes them, never over an existing doc; `--recreate`
   only for a registered doc whose file is gone.
3. Fill each new doc with what that role needs for that module, from its code and docs — one module
   at a time, never inventing components.
4. `segmently-modules lint --json` — fix what the new docs caused.
5. `segmently-modules next --json` — report what is left.

## A module that does not need the role

Some modules give a role nothing to say — a build tool and a product-owner role, a backend
module and a designer role. When step 1's plan lists such modules, name them and ask the user
whether they need the doc at all; before step 2, mark each one the user names:
`segmently-modules roles skip ROLE MODULE… --note "<why>" --dry-run`, then the same with `--json` instead
of `--dry-run` (the why in the user's words, one line). Step 2 then leaves those modules alone and
`next` stops asking for their doc. A module that has the doc is refused: delete the doc
first, after the user's OK.

The module needs the role after all: `segmently-modules roles add ROLE MODULE --json` writes the doc in place
of the mark; fill it as in step 3.

## Gates

Autonomous by default: it declares, writes and fills. It stops and asks only when the role is
undeclared and what it is for is unclear (the user says what the role covers, then it declares
the role), and before it marks a module as not needing the role (the user names the modules). Never fill a doc with a claim the module's code and docs do not support.

## Exit codes

`0` ok · `1` = findings left (`lint`) or a role that cannot be added: read the result and act ·
`2` = a usage or config error or a refused write: read stderr, fix the input, run again once.
