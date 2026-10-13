# Segmently Modules plugins

The plugin marketplace of Segmently Modules for Claude Code and Codex: branch `stable` for releases,
`dev` for every change before one. The engine, its docs and its issues:
https://github.com/segmently-ai/segmently-modules.

<!-- segmently-modules:begin -->
## Segmently Modules

Module-registry skills for coding agents and the `segmently-modules` command line: the plugins `segmently-modules`, `segmently-modules-ui` and `segmently-modules-qa`. This branch: `dev`, segmently-modules 0.2.0-dev.h7ea7c03a. The engine, its docs and its issues: https://github.com/segmently-ai/segmently-modules.

- Claude Code: `claude plugin marketplace add segmently-ai/segmently-modules-plugins#stable`, then `claude plugin install segmently-modules@segmently-modules` (and `segmently-modules-ui@segmently-modules`, `segmently-modules-qa@segmently-modules`).
- Codex: install the command line first — `uv tool install git+https://github.com/segmently-ai/segmently-modules.git` or `pipx install git+https://github.com/segmently-ai/segmently-modules.git` (the engine's `main`, which the dev channel follows; for the stable plugins add `@v` and their version) — then `codex plugin marketplace add segmently-ai/segmently-modules-plugins --ref stable` and `codex plugin add segmently-modules@segmently-modules`.
- The dev channel: `#dev` / `--ref dev` and the marketplace `segmently-modules-dev`.
<!-- segmently-modules:end -->
