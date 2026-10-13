# Packs, skills and hooks

## A pack of our own (roles, templates, skills, config to share)
`segmently-modules packs new <id> --role <role> --skill <skill> --description "<one line>" --dry-run`, then
without `--dry-run`: `.segmently-modules/packs/<id>/` with `pack.toml`, `roles/<role>.md` templates and
`skills/<skill>/SKILL.md`. A pack may also carry `[fields.*]`, `[[code_map]]` and
`[[hooks.post_sync]]`. `segmently-modules packs list --json` shows the packs in precedence order (lower
`priority` wins). Then `packs sync` copies its skills to the agents and `lint` checks it
(MS060–MS065).

## Skill copies are stale, missing or in conflict
`segmently-modules packs sync --dry-run`, then without `--dry-run`, refreshes the copies it made; a copy
edited locally is a conflict and is never overwritten — keep the edit by ejecting the skill
(below), or delete the copy and sync. CI: `segmently-modules packs sync --check --json`.

## Change a built-in skill for our team
`segmently-modules eject <skill> --dry-run`, then without `--dry-run`: a copy in
`.segmently-modules/overrides/skills/<skill>/` that `packs sync` uses from then on and the pack never
overwrites. Later upstream changes: `segmently-modules eject <skill> --diff --json`, take what you want by
hand, then `segmently-modules eject <skill> --rebase --dry-run` and without `--dry-run`. Back to the pack's
version: delete the directory, then `packs sync`.

## Run our own logic after a sync (a hook)
In `.segmently-modules/config.toml` or a pack:

```toml
[[hooks.post_sync]]
id = "notify-docs"
run = ["node", "./scripts/notify.mjs"]   # ./ is the pack's directory (team config: the root)
required = false                         # true: a failing hook makes sync exit 1
timeout_s = 60
```

It runs after `sync` maps a change (never with `--dry-run`), gets
`{changed_modules, changed_files, diff_range}` as JSON on stdin and may print
`{"proposals": [...], "messages": ["…"]}`; the messages reach the user through `module-sync`.
It reads a module's docs and fields with `segmently-modules show <module> --json`.
`segmently-modules hooks list --json` shows the hooks in effect; `enabled = false` with the same `id` turns
a pack's hook off.
