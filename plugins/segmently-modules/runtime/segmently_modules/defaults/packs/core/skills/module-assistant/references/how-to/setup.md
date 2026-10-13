# Set up, upgrade, agents, packs, the agents' block

## Set Segmently Modules up in a repository
`segmently-modules setup --dry-run`, then the same without `--dry-run` (add `--agent claude --agent codex`
and `--target CLAUDE.md` style flags for other agents or files): the starter config
(`.segmently-modules/config.toml` with `[packs] builtin = ["core"]`), an empty registry, the `.gitignore`
lines, the skill copies and the agents' block. A second run writes nothing. Existing code with no
registry: then `module-init`. A registry other tooling wrote: `module-adopt` instead of a fresh
setup. Undo: delete what it created (the dry run lists it).

## Choose the agents that get the skills
`[packs] agents = ["claude", "codex"]` in `.segmently-modules/config.toml`, then
`segmently-modules packs sync --dry-run` and the same without `--dry-run`. Or per run:
`segmently-modules packs sync --dry-run --agent claude --agent codex`. claude reads `.claude/skills/`; codex,
cursor, gemini and copilot read `.agents/skills/`. Remove copies:
`segmently-modules packs sync --remove --agent cursor --dry-run` (an edited copy stays).

## Enable the qa or ui pack
`[packs] builtin = ["core", "qa", "ui"]` in `.segmently-modules/config.toml`; then `segmently-modules packs sync --json`
and `segmently-modules agents-md --json --target CLAUDE.md` (each instruction file). `qa` adds the
`qa_acceptance` role and the acceptance criteria skills; `ui` adds the `designer` role and skill.
Undo: remove the id, sync again.

## Skills from the plugin instead of copies in the repository
`[packs] builtin_delivery = "plugin"`: the Segmently Modules plugins provide the built-in skills and
`packs sync` removes the copies it made (an edited copy is a conflict and stays). Default
`"repo"`: `packs sync` copies them. Per agent: `builtin_delivery = { claude = "plugin", codex =
"repo" }` — Claude Code from the plugin, Codex as copies.

## The agents' block in CLAUDE.md / AGENTS.md
`segmently-modules agents-md --dry-run --target CLAUDE.md`, then without `--dry-run`. Only the text between
`<!-- segmently-modules:begin v1 -->` and `<!-- segmently-modules:end -->` is written; the rest of the file is never
touched. Its text comes from the `agents-md.md` template
(`segmently-modules templates override agents-md.md --dry-run`, then without it, to change it). CI:
`segmently-modules agents-md --check --json --target CLAUDE.md`.

## After upgrading Segmently Modules
`segmently-modules next --json` names what the upgrade brought: stale skill copies (`packs sync`), a stale
block (`agents-md`), a new standard role (`module-roles`). An old registry shape:
`segmently-modules migrate --dry-run`, then without `--dry-run`.
