<!-- segmently-modules:changelog:begin -->
## segmently-modules

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
