# segmently-modules-qa

The Segmently Modules acceptance-criteria skills: a task's criteria before the code, and a module's acceptance baseline.

The `qa` pack of Segmently Modules as a plugin: `qa-acceptance`, `qa-acceptance-baseline`. It needs the `segmently-modules` plugin (the segmently-modules command line and the core skills).

## Install

- Claude Code: `claude plugin marketplace add segmently-ai/segmently-modules-plugins#stable`, then `claude plugin install segmently-modules-qa@segmently-modules` (it installs `segmently-modules` too).
- Codex: `codex plugin marketplace add segmently-ai/segmently-modules-plugins --ref stable`, then `codex plugin add segmently-modules@segmently-modules` and `codex plugin add segmently-modules-qa@segmently-modules` — Codex has no plugin dependencies, so add both — and install the CLI first, at the plugins' version: `uv tool install git+https://github.com/segmently-ai/segmently-modules.git@v0.3.0` (or `pipx install git+https://github.com/segmently-ai/segmently-modules.git@v0.3.0`).
- Cursor, Gemini CLI, GitHub Copilot: there is no plugin for them — install the CLI, set Segmently Modules up in the repository (`segmently-modules init` enables the `core` pack; or set `[packs] builtin` in `.segmently-modules/config.toml`), then run `segmently-modules packs sync --agent cursor` (`--agent gemini`, `--agent copilot`): it copies the skills into `.agents/skills/`; these agents need the default `"repo"` delivery.

Then run `/reload-plugins` in Claude Code, or start a new session: an agent picks a newly installed plugin up only then (Codex: a new session).

The `dev` channel: `#dev` / `--ref dev` and the marketplace `segmently-modules-dev` (e.g. `segmently-modules-qa@segmently-modules-dev`).

In a repository whose agents get the built-in skills from these plugins, set `builtin_delivery = "plugin"` under `[packs]` in `.segmently-modules/config.toml`: `segmently-modules packs sync` then copies none of them and removes the copies it made (with the default `"repo"` delivery and the plugin, an agent sees each built-in skill twice). Cursor, Gemini CLI and Copilot need `"repo"` (the default).
