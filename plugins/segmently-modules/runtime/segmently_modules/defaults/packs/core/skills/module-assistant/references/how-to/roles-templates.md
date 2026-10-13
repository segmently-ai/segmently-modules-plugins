# Roles and templates

## Change the template a role's docs are written from
`segmently-modules templates list --json` shows, per template, the layer that wins here: `override`,
`role-template:<pack>`, `pack:<pack>`, `engine`, or `engine-fallback` (the generic `_role.md`
for a role with no file of its own). `segmently-modules templates override roles/<role>.md --dry-run`, then
without `--dry-run`, copies the winning one to `.segmently-modules/overrides/templates/roles/<role>.md`;
edit that copy — it wins from then on (an existing override is never replaced). Keep the
placeholders the copied file already uses (the module's title, name, description, status,
keywords and parent, the role and its description): `create` and `roles add` fill them in.

A template only shapes NEW docs (`create`, `roles add`); existing docs are never rewritten. To
bring existing docs to the new shape: list them (`segmently-modules roles list --json`, the role's `docs`),
then add the new sections module by module from each module's code and docs, after the user's
OK — never overwrite what someone wrote. Undo: delete the override file.

For several repositories: put the template in a team pack instead
(`<pack>/templates/roles/<role>.md`, or the role's `template` key in its `pack.toml`).

## Change the MODULE.md template
The same: `segmently-modules templates override MODULE.md --dry-run`, then without `--dry-run`; edit
`.segmently-modules/overrides/templates/MODULE.md`.

## Add a role to every module
The `module-roles` skill: it declares the role when it is new (a `[roles.<name>]` table with
`order`, `standard = true` and a one-line `description` in `.segmently-modules/config.toml`), shows
`segmently-modules roles add <role> --all --dry-run`, writes the docs and fills them.

## A role only some modules need
`[roles.<name>]` with `standard = false` and `applies_when = "<tag>"`; `create … --tag <tag>`
scaffolds its doc; for existing modules `segmently-modules roles add <role> <module> --dry-run`, then
without `--dry-run`.

## A module that does not need a role
Some modules have nothing for a role to say — a backend module and the designer, a build tool
and the product owner. Mark it once instead of writing an empty doc:
`segmently-modules roles skip <role> <module>… --note "<why>" --dry-run`, then without `--dry-run`. The
registry then holds `false` (or `{"skip": "<why>"}` with the note) for that role: `next` stops
asking for the doc, `roles add <role> --all` leaves the module alone, `show --role <role>` says
the role is not needed and why. Ask the user which modules before marking them, and keep the
why in the note — one line in their words. A module that has the doc is refused: delete the
doc first, after the user's OK. A role no module needs: `enabled = false` in its table instead.

## The module needs the role after all
`segmently-modules roles add <role> <module> --dry-run`, then without `--dry-run`: it writes the doc in
place of the mark; fill it from the module's code and docs.

## See the roles and who lacks a doc
`segmently-modules roles list --json` — every role, its `docs` and `missing` modules; a child without its
own doc is `inherited` (the parent's covers it); `skipped` = the modules marked as not needing
it. Hide a role: `enabled = false` in its table.
