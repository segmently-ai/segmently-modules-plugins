# Segmently Modules plugins

The plugin marketplace of Segmently Modules for Claude Code and Codex: branch `stable` for releases,
`dev` for every change before one. The engine, its docs and its issues:
https://github.com/segmently-ai/segmently-modules.

<!-- segmently-modules:begin -->
## Segmently Modules

### What it is for

An AI coding agent is an excellent worker with amnesia and a memory of limited size. Segmently Modules solves both problems:

1. it writes the notes for starting work on any part of the project — a specific page or a server feature;
2. it finds the notes a task needs before the work starts;
3. it brings the notes up to date when the work is done;
4. it keeps the notes per role, so the agent reads only the notes it needs right now: its memory is limited.

The plugins: `segmently-modules` (the core skills and the `segmently-modules` command line), `segmently-modules-ui` (the designer skill) and `segmently-modules-qa` (the acceptance-criteria skills). This branch: `dev`, segmently-modules 0.2.1-dev.h34b91151. The engine, its docs and its issues: https://github.com/segmently-ai/segmently-modules.

### Install with one prompt

Paste the block for your agent into a fresh session. It checks git and Python, installs the plugin and stops: an agent picks a newly installed plugin up only after a reload — `/reload-plugins` in Claude Code — or in a new session (Codex), and the prompt then hands you the first request.

**Claude Code**

```text
Set up Segmently Modules for Claude Code on this machine, then stop and tell me to restart.

Marketplace: segmently-ai/segmently-modules-plugins#stable. Plugin: segmently-modules@segmently-modules.

Run the steps in order and show me the exact output of every command:
1. git --version and python3 --version — git must answer, and Python must be 3.9 or newer. On macOS, if either one asks for the command line developer tools, run xcode-select --install, ask me to finish the installer it opens, then run both again. If Python is still missing or older than 3.9, tell me how to get Python 3.9 or newer on this operating system and stop there.
2. claude plugin marketplace add segmently-ai/segmently-modules-plugins#stable --scope user
   claude plugin install segmently-modules@segmently-modules --scope user
   If the marketplace is already there, run claude plugin marketplace update segmently-modules and then claude plugin update segmently-modules@segmently-modules --scope user.
3. claude plugin list — the output must name segmently-modules. If it does not, say so plainly and do not continue.
4. Do not use the skills yet: Claude Code picks a newly installed plugin up only after /reload-plugins or in a new session. Tell me the setup is done, then ask me to run /reload-plugins (or restart Claude Code) in the repository I want to work on, and to paste the request below there.

The request to paste then:
"Use the module-assistant skill to set Segmently Modules up in this repository:
- it has a module registry another tool or team already wrote: adopt it with the module-adopt skill;
- it has code but no module registry: run segmently-modules setup, then map the code into modules and write their notes with the module-init skill;
- it is a new repository: run segmently-modules setup, then the module-create skill for the first module.
segmently-modules setup also adds the Segmently Modules section to CLAUDE.md and AGENTS.md, so every session knows the skills and the module system."
```

**Codex**

```text
Set up Segmently Modules for Codex on this machine, then stop and tell me to restart.

Marketplace: segmently-ai/segmently-modules-plugins on ref stable. Plugin: segmently-modules@segmently-modules.

Run the steps in order and show me the exact output of every command:
1. git --version and python3 --version — git must answer, and Python must be 3.9 or newer. On macOS, if either one asks for the command line developer tools, run xcode-select --install, ask me to finish the installer it opens, then run both again. If Python is still missing or older than 3.9, tell me how to get Python 3.9 or newer on this operating system and stop there.
2. npm install -g @segmently/modules, then segmently-modules --version — it must print segmently-modules and a version. Without npm, run uv tool install git+https://github.com/segmently-ai/segmently-modules.git instead.
3. codex plugin marketplace add segmently-ai/segmently-modules-plugins --ref stable
   codex plugin add segmently-modules@segmently-modules
   If the marketplace is already there, run codex plugin marketplace upgrade segmently-modules and then codex plugin add segmently-modules@segmently-modules again.
4. List the installed plugins and show me that segmently-modules is among them. If it is not, say so plainly and do not continue.
5. Do not use the skills yet: Codex picks a newly installed plugin up only in a new session. Tell me the setup is done, then ask me to restart Codex in the repository I want to work on, and to paste the request below there.

The request to paste then:
"Use the module-assistant skill to set Segmently Modules up in this repository:
- it has a module registry another tool or team already wrote: adopt it with the module-adopt skill;
- it has code but no module registry: run segmently-modules setup, then map the code into modules and write their notes with the module-init skill;
- it is a new repository: run segmently-modules setup, then the module-create skill for the first module.
segmently-modules setup also adds the Segmently Modules section to CLAUDE.md and AGENTS.md, so every session knows the skills and the module system."
```

Nothing goes into `CLAUDE.md` by hand: `segmently-modules setup` (the first request above runs it) adds a short "Module docs (Segmently Modules)" section to `CLAUDE.md` (Claude Code) and `AGENTS.md` (Codex, Cursor, Copilot; Gemini CLI reads `GEMINI.md`). It tells every session to read a task's notes before the work (`segmently-modules context`), to bring them up to date after it (`segmently-modules sync-instructions`, the `module-sync` skill), to start module work with `segmently-modules next`, and it lists the skills. `segmently-modules agents-md` refreshes the section; the text around it stays yours.

### Install by hand

- Claude Code: `claude plugin marketplace add segmently-ai/segmently-modules-plugins#stable`, then `claude plugin install segmently-modules@segmently-modules` (and `segmently-modules-ui@segmently-modules`, `segmently-modules-qa@segmently-modules`).
- Codex: install the command line first — `npm install -g @segmently/modules`, `uv tool install git+https://github.com/segmently-ai/segmently-modules.git` or `pipx install git+https://github.com/segmently-ai/segmently-modules.git` (the engine's `main`, which the dev channel follows; for the stable plugins add `@v` and their version) — then `codex plugin marketplace add segmently-ai/segmently-modules-plugins --ref stable` and `codex plugin add segmently-modules@segmently-modules`.
- The dev channel: `#dev` / `--ref dev` and the marketplace `segmently-modules-dev`.

Then run `/reload-plugins` in Claude Code, or start a new session: an agent picks a newly installed plugin up only then (Codex: a new session).
<!-- segmently-modules:end -->
