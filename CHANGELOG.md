<!-- segmently-modules:changelog:begin -->
## segmently-modules

- 0.3.0 (stable): engine ceccd55
  ### Added
  - `eval routing` and `init verify` say how precise the routing is, not only whether the module is among the first three: `top1_hit_rate`, `mean_matched` (the modules a task matched on average) and, per module, `top1_hits` and `unused_keywords` (no task matched the keyword and no code file of the module holds it). None of them fails a run.
  - `init verify` checks the keywords of every new module: more distinct words than `[create] max_keywords` (40) or a generic word fails it (`keywords` in `verify.json`).
  - lint MS023 (info): a keyword is a generic word — the CRUD verbs, `user`, `screen`, `app`, `module`, `test` and the words `create` warned about before, any form, plus `[create] generic_keywords`; never a word of the module's own name.
  - `init map` gives a candidate with more lines of code than `[init] split_hint_lines` (10000) a `split` hint listing its subdirectories with their lines (`children`).
  ### Changed
  - The READMEs say what Segmently Modules is for — an AI coding agent is an excellent worker with amnesia and a memory of limited size, and the notes solve both: written for any part of the project, found before a task, updated after it, kept per role — in a section of its own, and carry a one-prompt install for Claude Code and for Codex (paste it into a fresh session; it sets the machine up and stops: the agent picks the plugin up after `/reload-plugins` in Claude Code, or in a new session). The prompt's first request names the way in — adopt an existing registry (`module-adopt`), or `segmently-modules setup` and then `module-init` for code without one, `module-create` for a new repository — and a note says what `setup` adds to `CLAUDE.md` and `AGENTS.md`, so nothing is written there by hand. The by-hand install lines name the reload too. The engine's README, the core plugin's README, the plugin marketplace's README section and the npm README share the text; the core plugin's and the marketplace's descriptions say it in one line. The Codex install lines take the command line from npm first.
  - Routing ignores word endings: a keyword and a task word match when one is a form of the other (`save`, `saves`, `saved`, `saving`; `entry`, `entries`), so one form of a word is enough. A module that lists several forms scores the word once, so registries written with every form keep their scores. `[match] normalize = "none"` keeps the exact matching of 0.2.1.
  - The init writer's prompt asks for at most `[create] max_keywords` words that point to this module and no other — one form per word, no generic word, nothing another module owns, no word for the developer's own tools — and lists the other modules of the repository. `init done` refuses more than `max_keywords` distinct words and warns about generic keywords.
  - `create` no longer asks for the missing plural: it says when a keyword is a form of another one, and warns about generic words in any form and about more than `max_keywords` words (the plural hint stays under `normalize = "none"`).
  - `init reconcile` drops a keyword no holder's code holds from every module that holds it (as far as the keyword minimum allows; `dropped` in `reconcile.json`) and treats the forms of one word held by different modules as one collision. On the 76 ties of a real run this drops 68 words and leaves the 8 real disputes. The evidence stays a listed form, whole, in a file's path or text: counting every form and the parts of identifiers made generic verbs look owned by most modules.
  - The refusal of a root that still holds `.modsys/` stays, though 0.2.0 said it would go in this release: teams are still moving from modsys, and without it an un-migrated checkout would be read with the engine defaults. It goes once the old repositories are archived.
  ### Fixed
  - A backticked path with a space or a `#` in it (`…/Custom cells/Row.swift`, `…/onboarding-v#1-47.json`) is checked as the path it names when it exists — `init done`, `init verify` and lint MS040 cut it or skipped it before.
  - The README's one-prompt install no longer has a line starting with the command's name inside its text block, which broke the docs test on `main`.
- 0.2.1 (stable): engine 650996a
  ### Added
  - npm: `tools/build_npm.py` builds the package `@segmently/modules` — the command line on macOS and Linux with `npm install -g @segmently/modules` or `npx @segmently/modules`. It carries the engine and the plugin's launcher and runs with the Python 3.9 or newer it finds; Node runs nothing. Publishing is a maintainer's step after a release ([docs/releasing.md](docs/releasing.md#npm)).
  ### Changed
  - Python 3.9 or newer (was 3.11): the `python3` of macOS's Command Line Tools (3.9, the package that brings git) runs the command line and the plugins, so a Mac needs no other Python. On Python 3.9 and 3.10 the TOML reader is tomli 2.3.2, vendored unchanged under `segmently_modules/_vendor/` (MIT) — the reader that became Python's own `tomllib` in 3.11, which 3.11 and newer keep using.
  - The plugin launcher (`bin/segmently-modules`) also looks for `python3.10` and `python3.9`, and runs the engine through `python -c` instead of `python -P` (3.11+), to the same effect: the working directory never shadows the plugin's engine.
- 0.2.0 (stable): engine eb89f2a
  ### Added
  - The repository is public under the MIT license: `LICENSE`, `CONTRIBUTING.md` (how to run the tests, the skill-text rules, pull requests) and `SECURITY.md` (private reports, the trust model). The README installs over https from the public repositories, pinned to the latest release; a stable release moves the pin.
  - The plugins' Claude Code manifests name their homepage, repository and license; the plugin READMEs and the marketplace README carry the real install lines.
  ### Changed
  - Renamed: modsys is now Segmently Modules. Every surface of the old name changes at once:
    - the command `modsys` → `segmently-modules` (also the `argparse` prog and the `segmently-modules: error: …` / `segmently-modules: note: …` prefixes on stderr);
    - the Python distribution → `segmently-modules`, the import package and `python -m` → `segmently_modules`;
    - the config directory `.modsys/` → `.segmently-modules/` (`config.toml`, `packs/`, `overrides/`, `config.user.toml`, `proposals/`, `init/`), and the `init --open-pr` branch → `segmently-modules/init`;
    - the environment variables `MODSYS_*` → `SEGMENTLY_MODULES_*` (same suffixes);
    - the JSON envelope and file schema ids `modsys.<verb>/1` → `segmently-modules.<verb>/1` (also `.managed/1`, `.ejected/1`, `.proposal/1`, `.init-state/1`, `.init-proposal/1`, `.init-preflight/1`); the data shapes are unchanged;
    - the agents' block markers → `<!-- segmently-modules:begin v1 -->` / `<!-- segmently-modules:end -->` under `## Module docs (Segmently Modules)`;
    - the managed-copy markers → `.segmently-modules-managed` / `.segmently-modules-ejected`, and a managed Codex agent's first line → `# segmently-modules-managed: …`;
    - the plugins → `segmently-modules`, `segmently-modules-ui`, `segmently-modules-qa`; the marketplaces → `segmently-modules` (stable) and `segmently-modules-dev`; the skills → `/segmently-modules:<skill>`, the chooser agent → `segmently-modules:module-chooser`;
    - the plugin launcher → `bin/segmently-modules` (`SEGMENTLY_MODULES_PYTHON`).
  - The lint codes stay `MS001`…`MS069`, so a `ci --baseline` key and a doc that names a code need nothing.
  - A root that holds `.modsys/` and no `.segmently-modules/` is refused (exit 2) with the rename command, so an un-migrated checkout is never read with the engine defaults; an explicit `--config-dir` is accepted. The refusal goes in 0.3.0.
  - `[budgets] pack_split_signal` default 60000 → 64000 (the longer name grows every skill text).
  - The skill descriptions name the verbs without the product name (`Runs discover …`, `with ci (or lint …)`).
  ### Upgrading from modsys 0.1.x
  0. With modsys 0.1.x still installed: apply or drop pending proposals (`modsys sync --apply-proposals`) and finish or drop an `init` run in progress — their files carry the old schema ids, which 0.2.0 does not read.
  1. Install the `segmently-modules` command line and plugins (README → Install), then remove the old ones: `claude plugin uninstall modsys@modsys`, `claude plugin marketplace remove modsys`, `uv tool uninstall modsys`.
  2. `git mv .modsys .segmently-modules`; in `.gitignore` rename the `.modsys/` lines.
  3. Delete every skill copy that holds a `.modsys-managed` file and every `.codex/agents/*.toml` whose first line starts with `# modsys-managed:`, then run `segmently-modules packs sync`. An ejected skill keeps its copy: rename its `.modsys-ejected` record (under `.segmently-modules/overrides/skills/<skill>/`) to `.segmently-modules-ejected` and set its `schema` to `segmently-modules.ejected/1`.
  4. In each instruction file with a managed block, rename `<!-- modsys:begin v1 -->` to `<!-- segmently-modules:begin v1 -->` and `<!-- modsys:end -->` to `<!-- segmently-modules:end -->`, then run `segmently-modules agents-md`.
  5. Rename `MODSYS_*` variables (your shell, CI, hooks) to `SEGMENTLY_MODULES_*`; skills are now `/segmently-modules:<skill>`, the chooser agent `segmently-modules:module-chooser`.
  6. A pipeline that checks `schema` reads `segmently-modules.<verb>/1`; write a new `ci --baseline` file.
<!-- segmently-modules:changelog:end -->
