# Registry fields and code mapping

## Add a field of our own to the registry
Declare it once in `.segmently-modules/config.toml` (or a team pack):

```toml
[fields.oncall_team]
type = "string"                 # string, bool, int, object, T[], map<string,T>
scope = ["module", "submodule"] # default "module"
description = "Who is paged for this module"
sync_hint = "Update it when the on-call rotation changes."
```

Other keys: `kind = "code_pointer"` (the values are code paths), `required`, `ask_on_create`,
`deprecated = "<migration hint>"`. Then lint checks it, `registry` writes it, `schema` includes
it and `segmently-modules show <module> --json` returns its value under `fields`. An undeclared field is
lint MS012 and cannot be written. The core fields (`name`, `description`, `status`, `keywords`,
`context_files`, `related_modules`, `submodules`, `negative_keywords`, `required_combinations`)
cannot be redeclared — only their `sync_hint`. An existing registry full of undeclared fields:
`segmently-modules adopt --dry-run --json` infers the declarations.

## Set a field's value
`segmently-modules registry set <module> <field> '<json>' --dry-run`, then without `--dry-run`; `append`,
`remove` and `unset` the same way. A child: `<module>/<child>`. The type is checked before
writing.

## Extra docs for a module
Any key in its `context_files` besides `universal` and `roles` — a path, a list or a map of
paths (`"docs": {"thesis": "…"}`): lint checks they exist, `show` and `context` list them.

## Map code to modules
A rule per code layout: `segmently-modules code-map add src --pattern 'src/{module}/**' --dry-run`, then
without `--dry-run` (it appends to `.segmently-modules/config.toml`). Fixed paths for one module:
`segmently-modules code-map add <id> --glob '<dir>/**' --module <module> --dry-run`. Per module instead: a
`code_pointer` field (`file_paths`, …). Check: `segmently-modules code-map files <module> --json` lists what
maps to it and how; `segmently-modules code-map list --json` lists the rules. Edit or remove a rule by hand.

## Files that belong to no module
`segmently-modules coverage --json` lists them. Map them (above) or leave them out: `[coverage] exclude =
["generated/**"]`. CI: `segmently-modules coverage --fail-under 80 --json`, or `[ci] coverage_fail_under`.
