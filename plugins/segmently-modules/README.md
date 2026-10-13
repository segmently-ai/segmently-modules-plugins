# segmently-modules

Module-registry skills for coding agents — find, read, update, create, split and lint module docs, start them from existing code or adopt a registry — with the segmently-modules CLI they run.

The `core` pack of Segmently Modules as a plugin: `module-adopt`, `module-assistant`, `module-create`, `module-discover`, `module-init`, `module-lint`, `module-research`, `module-roles`, `module-scout`, `module-split`, `module-sync`. It also carries the segmently-modules command line those skills run: `bin/segmently-modules` runs the engine in `runtime/` with Python 3.11 or newer (or `uv`); set `SEGMENTLY_MODULES_PYTHON` to choose the interpreter. It ships the read-only `module-chooser` agent (`segmently-modules:module-chooser`, Claude Code) that the skills hand a `segmently-modules choose` work order; every plugin update replaces it, so change how modules are chosen with `segmently-modules templates override choose/rules.md`. It also ships the agents `module-discover-agent`, `module-research-agent` and `module-scout-agent` (`segmently-modules:<name>`): each one runs its skill in the agent's own context and returns the skill's output.

## Install

- Claude Code: `claude plugin marketplace add segmently-ai/segmently-modules-plugins#stable`, then `claude plugin install segmently-modules@segmently-modules`.
- Codex: `codex plugin marketplace add segmently-ai/segmently-modules-plugins --ref stable`, then `codex plugin add segmently-modules@segmently-modules`. Codex puts no plugin command on PATH, so install the CLI first, at the plugin's version: `uv tool install git+https://github.com/segmently-ai/segmently-modules.git` (or `pipx install git+https://github.com/segmently-ai/segmently-modules.git`). Codex reads no plugin agents: `segmently-modules setup` and `segmently-modules packs sync --agent codex` write the three skills' agents to `.codex/agents/` in the repository.
- Cursor, Gemini CLI, GitHub Copilot: there is no plugin for them — install the CLI, set Segmently Modules up in the repository (`segmently-modules init` enables the `core` pack; or set `[packs] builtin` in `.segmently-modules/config.toml`), then run `segmently-modules packs sync --agent cursor` (`--agent gemini`, `--agent copilot`): it copies the skills into `.agents/skills/`; these agents need the default `"repo"` delivery.

The `dev` channel: `#dev` / `--ref dev` and the marketplace `segmently-modules-dev` (e.g. `segmently-modules@segmently-modules-dev`).

In a repository whose agents get the built-in skills from these plugins, set `builtin_delivery = "plugin"` under `[packs]` in `.segmently-modules/config.toml`: `segmently-modules packs sync` then copies none of them and removes the copies it made (with the default `"repo"` delivery and the plugin, an agent sees each built-in skill twice); it still writes Codex's three agent files in `.codex/agents/`. Cursor, Gemini CLI and Copilot need `"repo"` (the default).
