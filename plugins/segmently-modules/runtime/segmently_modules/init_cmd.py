"""`segmently-modules init`: set segmently-modules up in a repository — a starter `<config_dir>/config.toml` (every
key commented out, with worked examples), an empty registry (the single file, or the
per-module index) and the `.gitignore` lines for the files the engine creates. Only what is
missing is created (an existing `.gitignore` gets only its missing lines, appended in the
file's own newline style and through a symlink to its target); a second run changes nothing.
Root: `--root`, else the git top-level of the current directory, else the current directory.

Actions (`segmently_modules.init_flow`, `segmently_modules.init_work`): `map` (the starter files that are missing,
then preflight and map; stops at gate 3), `confirm` (gate 3), `status`, `resume`, `fanout` (one
work item per confirmed module), `next` (claim one), `done MODULE` (check its staging output),
`run --executor CMD` (every pending item through one command), `reconcile` (the staging
registry), `eval-tasks --executor CMD` (the routing tasks), `verify` (lint, invented components,
routing), `finish [--open-pr]` (gate 7: the docs and the registry written) — one envelope
`segmently-modules.init/1` each."""
from __future__ import annotations

import functools
import subprocess
import sys
from pathlib import Path

from segmently_modules.changes import git_env
from segmently_modules.config import REGISTRY_LAYOUTS, load_config
from segmently_modules.fields import load_field_defs
from segmently_modules.layout import build_index
from segmently_modules.merge import merge
from segmently_modules.output import EXIT_FINDINGS, EXIT_OK, UsageError, emit
from segmently_modules.store import serialize
from segmently_modules.workspace import CONFIG_DIR, Workspace, refuse_legacy_config

_HEADER = '''\
## segmently-modules team config — commit it. Every key is optional: uncomment what you need (only
## [packs] builtin is set). Layers (later wins): engine defaults -> built-in packs ([packs]
## builtin) -> packs (.segmently-modules/packs/<id>/pack.toml) -> this file -> .segmently-modules/config.user.toml
## (personal; add it to .gitignore). Tables merge key by key; arrays ADD to the lower layers (an
## override never removes a default). Every key: docs/configuration.md in the segmently-modules repository.

'''
_PATHS = {
    "single": '''\
## Where the registry and the module docs live (defaults shown).
# [paths]
# modules_dir = "modules"
# registry = "modules/registry.json"
# registry_layout = "single"         # "per-module": one module.json per module + a generated index
''',
    "per-module": '''\
## Where the registry and the module docs live. Per-module layout: each module's entry is
## <modules_dir>/<name>/module.json; the registry file is a generated index (segmently-modules index build).
[paths]
registry_layout = "per-module"
# modules_dir = "modules"
# registry = "modules/registry.json"
''',
}
_BODY = '''
## Vocabulary that lint and the registry writers check.
# [registry]
# statuses = ["active", "draft", "planned", "temporary"]
# relations = ["depends-on", "complements", "implemented-in", "shares-contract", "superseded-by"]

## `segmently-modules create` answer limits.
# [create]
# min_keywords = 5                   # a child module needs 1
# description_min = 20
# description_max = 200

## Wire code to modules. sync, discover, lint --changed (MS050), coverage and the code_globs of
## show / context all use these rules. Globs: ** any path, * one segment, ? one character.
## Add a rule with `segmently-modules code-map add` (it appends to this file), or write it by hand.
##
## A pattern's {module} is ONE path segment naming a top-level module: src/catalog/x.py -> catalog.
# [[code_map]]
# id = "src"
# pattern = "src/{module}/**"
##
## globs route files to one module, or to a child named "parent/child".
# [[code_map]]
# id = "catalog-search"
# module = "catalog/search"
# globs = ["src/catalog/search/**", "api/search_*.py"]
##
## exclusive: a file matched and routed by an exclusive rule is mapped ONLY by the exclusive
## rules that route it. Layered repos: a feature's repository file belongs to the feature, not to
## the shared persistence module whose broader rule also matches it.
# [[code_map]]
# id = "catalog-repository"
# module = "catalog"
# globs = ["app/db/repositories/catalog.py"]
# exclusive = true

## Or list code per module in the registry: declare a code_pointer field, then
##   segmently-modules registry set catalog code_paths '["src/catalog/", "lib/isbn.py"]'
# [fields.code_paths]
# type = "string[]"
# kind = "code_pointer"
# scope = ["module", "submodule"]
# description = "Source files or directories of the module"

## Hooks that `segmently-modules sync` runs after it maps a change (argv; ./ = relative to the root).
## A hook reads the event as JSON on stdin and may print {"proposals": [...], "messages": [...]}.
# [[hooks.post_sync]]
# id = "notify"
# run = ["python3", "./tools/notify_owners.py"]
# required = false

## `segmently-modules coverage`: which files count (git-tracked + new, not ignored). The modules dir, this
## directory and dotfiles never count.
# [coverage]
# include = ["**"]
# exclude = ["docs/**"]

## `segmently-modules ci`: one gate — lint, drift since base, coverage. Put the team's defaults here so CI
## runs a bare `segmently-modules ci` (a flag still overrides any key).
# [ci]
# base = "origin/main"
# fail_on = "warning"
# coverage_fail_under = 80

## Packs: a team's roles, doc templates and agent skills (docs/writing-a-pack.md in the segmently-modules
## repository). Create one with `segmently-modules packs new ID --role NAME --skill NAME`; `segmently-modules packs
## sync` copies the skills into these agents' skill directories when no --agent is given.
## builtin: the engine's own packs (docs/skills.md) — "core" = the module skills (scout,
## discover, research, sync, create, split, lint, init, adopt); "ui" = a designer role and a UI
## review skill; "qa" = an acceptance-baseline role and acceptance-criteria skills.
[packs]
builtin = ["core"]                   # or ["core", "ui", "qa"]
# agents = ["claude", "codex"]
'''
_VERBS = {"created": ("created", "would create"), "updated": ("updated", "would update"),
          "exists": ("exists", "exists")}


def starter_config(layout: str) -> str:
    """The starter team config: enables the built-in `core` pack and sets nothing else except a
    non-default registry layout."""
    return _HEADER + _PATHS[layout] + _BODY


ACTIONS = ("map", "confirm", "status", "resume", "fanout", "next", "done", "run", "reconcile",
           "eval-tasks", "verify", "finish")
FORCE_ACTIONS = ("reconcile", "eval-tasks", "verify", "finish")
PR_ACTIONS = ("finish", "resume")
BRANCH = "segmently-modules/init"
EXECUTOR_ACTIONS = ("run", "resume", "eval-tasks")
NON_INTERACTIVE_ACTIONS = ("run", "resume", "finish")  # the others never prompt (SI-25)


def register(sub, common) -> None:
    p = sub.add_parser("init", parents=[common],
                       help="set up segmently-modules here: starter config, empty registry, .gitignore lines "
                            "(map|confirm|fanout|next|done|run|reconcile|eval-tasks|verify|"
                            "finish|status|resume: start from existing code)",
                       description="Without an action: the starter config, an empty registry and "
                                   "the .gitignore lines. map: those, then preflight and map of "
                                   "the existing code into <config_dir>/init/proposal.json "
                                   "(stops at gate 3; refused when the registry has modules). "
                                   "confirm: gate 3 — validate the edited proposal and freeze "
                                   "it. fanout: one work item per confirmed module "
                                   "(<config_dir>/init/work/). next: claim the next pending "
                                   "module (its work item and prompt). done MODULE: check the "
                                   "files written into its staging directory. run --executor "
                                   "CMD: run every pending item through CMD ([init] "
                                   "max_parallel at a time). reconcile: the staging registry — "
                                   "edges, keyword collisions, duplicates. eval-tasks --executor "
                                   "CMD: CMD writes the routing tasks from the routing prompt. "
                                   "verify: lint, invented components and the routing hit rate "
                                   "over the staging tree. finish: gate 7 — move the staging "
                                   "docs into the modules dir, write the registry, the code-map "
                                   "rules and the agents' block (never commits; --open-pr: a "
                                   "branch, one commit and a pull request). status: the phases, "
                                   "the modules and the next step. resume: re-run an "
                                   "interrupted phase and continue.")
    p.add_argument("action", nargs="?", metavar="ACTION",
                   help=f"{', '.join(ACTIONS)} (none: the starter files only)")
    p.add_argument("module", nargs="?", metavar="MODULE",
                   help="done: the module whose staging output to check")
    p.add_argument("--executor", metavar="CMD",
                   help="run, resume, eval-tasks: the command that writes one module's docs, or "
                        "the routing tasks (split like a shell line, never run by a shell; "
                        "stdin: the prompt)")
    p.add_argument("--non-interactive", action="store_true",
                   help="run, resume, finish: never wait for a person")
    p.add_argument("--force", action="store_true",
                   help="reconcile: rebuild the staging registry from entry.json, discarding "
                        "edits made to it; eval-tasks: write the tasks again; verify: measure a "
                        "tasks file written by hand although the last eval-tasks run was "
                        "refused; finish: even when verify has not passed or the routing tasks "
                        "were refused (recorded)")
    p.add_argument("--agents-md", action="append", dest="agents_md", metavar="FILE",
                   help="finish: an instruction file for the managed block (repeatable; "
                        "default: CLAUDE.md and AGENTS.md when they exist)")
    p.add_argument("--open-pr", action="store_true",
                   help="finish, resume: commit on a new branch, push it and open a pull request "
                        "(gh)")
    p.add_argument("--base", help="--open-pr: the pull request's base (default: the current "
                                  "branch)")
    p.add_argument("--branch", help=f"--open-pr: the new branch (default: {BRANCH})")
    p.add_argument("--layout", choices=REGISTRY_LAYOUTS,
                   help="registry layout for a new setup (default: the configured one, else single)")
    p.add_argument("--dry-run", action="store_true", help="report what would change, write nothing")
    p.add_argument("--restart", action="store_true",
                   help="map: clear <config_dir>/init/ and start over")
    p.set_defaults(func=run)


def init_root(arg) -> Path:
    """`--root`, else the git top-level of the current directory, else the current directory
    (not `find_root`: a fresh repository has no marker yet)."""
    if arg is not None:
        root = Path(arg).resolve()
        if not root.is_dir():
            raise UsageError(f"--root {arg} is not a directory")
        return root
    cwd = Path.cwd().resolve()
    try:
        proc = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
                              capture_output=True, encoding="utf-8", errors="replace",
                              env=git_env())
    except OSError:  # git is not installed
        return cwd
    top = proc.stdout.strip()
    return Path(top).resolve() if proc.returncode == 0 and top else cwd


def ignore_lines(root: Path, config_dir: Path, config: dict) -> list[str]:
    """The `.gitignore` lines `init` keeps: the registry lock, the proposals dir and the init
    work directory (`init map`, when the config dir lies inside the root)."""
    wanted = [f"{config['paths']['registry']}.lock",
              config["paths"]["proposals_dir"].rstrip("/") + "/"]
    try:
        wanted.append((config_dir / "init").relative_to(root).as_posix() + "/")
        # the personal config holds the user's own settings: never committed (P8.1, ruling C1)
        wanted.append((config_dir / "config.user.toml").relative_to(root).as_posix())
    except ValueError:
        pass
    return wanted


def plan_init(root: Path, config_dir: Path, requested: str | None) -> tuple[str, list]:
    """(layout, [(path, status, new text or None)]); writes nothing."""
    config_path = config_dir / "config.toml"
    config = load_config(config_dir, root)
    current = config["paths"]["registry_layout"]
    layout = requested or current
    registry = root / config["paths"]["registry"]  # path is the same in either layout
    if layout != current:
        if config_path.exists() or layout == "single" or registry.exists():
            if layout == "per-module":
                how = (f"to convert the existing registry run `segmently-modules index split`, then set "
                       f"[paths] registry_layout = \"per-module\" in {config_path}")
            else:  # the per-module index already holds every entry: it becomes the registry
                how = (f"to go back to one registry file run `segmently-modules index build` (the index "
                       f"then holds every module entry), then set [paths] registry_layout = "
                       f"\"single\" in {config_path}; the <module>/"
                       f"{config['paths']['module_entry']} files are no longer read")
            raise UsageError(f"--layout {layout} conflicts with the configured registry_layout "
                             f"{current!r}; {how}")
        config = merge(config, {"paths": {"registry_layout": layout}})
    files = [(config_path, "exists", None) if config_path.exists()
             else (config_path, "created", starter_config(layout))]
    if registry.exists():
        files.append((registry, "exists", None))
    else:
        text = (build_index(root, config)[0] if layout == "per-module"
                else serialize({"modules": {}}))
        files.append((registry, "created", text))
    gitignore = root / ".gitignore"
    wanted = ignore_lines(root, config_dir, config)
    if not gitignore.exists():
        files.append((gitignore, "created", "\n".join(wanted) + "\n"))
    else:
        text = gitignore.read_bytes().decode("utf-8")
        have = {line.strip() for line in text.splitlines()}
        missing = [line for line in wanted if line not in have]
        if missing:  # "updated" carries only the text to APPEND, in the file's newline style
            nl = "\r\n" if "\r\n" in text else "\n"
            sep = "" if not text or text.endswith("\n") else nl
            files.append((gitignore, "updated", sep + nl.join(missing) + nl))
        else:
            files.append((gitignore, "exists", None))
    return layout, files


def _create(path: Path, text: str) -> None:
    """Create a NEW file (never replace one another process created in the meantime)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "x", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    except FileExistsError:
        raise UsageError(f"{path} appeared while init was running; run init again") from None


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def starter(root: Path, config_dir: Path, layout: str | None,
            dry_run: bool) -> tuple[str, list]:
    """Plain `init`: create what is missing (unless `dry_run`); (layout, [{path, status}])."""
    layout, files = plan_init(root, config_dir, layout)
    if not dry_run:
        for path, status, text in files:
            try:
                if status == "created":
                    _create(path, text)
                elif status == "updated":
                    with open(path, "ab") as fh:  # append: keeps the bytes, mode and a symlink
                        fh.write(text.encode("utf-8"))
            except OSError as e:
                raise UsageError(f"cannot write {_rel(root, path)}: {e.strerror or e}") from None
    return layout, [{"path": _rel(root, p), "status": s} for p, s, _ in files]


def _check_flags(args) -> None:
    action = args.action
    if action is not None and action not in ACTIONS:
        raise UsageError(f"unknown init action {action!r} (actions: {', '.join(ACTIONS)})")
    if action == "done" and not args.module:
        raise UsageError("init done needs the MODULE whose staging output to check")
    if args.module and action != "done":
        raise UsageError(f"init {action or '(no action)'} takes no MODULE")
    if action in ("run", "eval-tasks") and args.executor is None:
        raise UsageError(f'init {action} needs --executor "<command>"')
    if args.executor is not None and action not in EXECUTOR_ACTIONS:
        raise UsageError(f"--executor works with {', '.join(f'init {a}' for a in EXECUTOR_ACTIONS)}")
    if args.agents_md and action != "finish":
        raise UsageError("--agents-md works with init finish")
    if args.open_pr and action not in PR_ACTIONS:
        raise UsageError(f"--open-pr works with {', '.join(f'init {a}' for a in PR_ACTIONS)}")
    if (args.base is not None or args.branch is not None) and not args.open_pr:
        raise UsageError("--base and --branch work with --open-pr")
    if args.force and action not in FORCE_ACTIONS:
        raise UsageError(f"--force works with {', '.join(f'init {a}' for a in FORCE_ACTIONS)}")
    if args.non_interactive and action not in NON_INTERACTIVE_ACTIONS:
        raise UsageError(f"init {action or '(no action)'} never prompts: drop --non-interactive")
    if args.restart and action != "map":
        raise UsageError("--restart works with map only (segmently-modules init map --restart)")
    if args.layout and action not in (None, "map"):
        raise UsageError(f"--layout works with plain init and init map, not init {action}")
    if args.dry_run and action in ("status", "resume", "fanout", "next", "done", "run",
                                   "reconcile", "eval-tasks", "verify", "finish"):
        raise UsageError(f"init {action} takes no --dry-run (it never writes)"
                         if action == "status" else f"init {action} takes no --dry-run")


def run(args) -> int:
    _check_flags(args)
    root = init_root(args.root)
    refuse_legacy_config(root, args.config_dir)
    config_dir = Path(args.config_dir or root / CONFIG_DIR).resolve()
    if args.action is not None:
        return run_action(args, root, config_dir)
    layout, files = starter(root, config_dir, args.layout, args.dry_run)
    data = {"root": str(root), "layout": layout, "files": files, "dry_run": args.dry_run}
    emit("init", data, args.json,
         functools.partial(_render, populated=_populated(root, config_dir)))
    return EXIT_OK


def _populated(root: Path, config_dir: Path) -> bool:
    """The registry holds at least one module (an unreadable or missing one does not)."""
    try:
        return bool(Workspace.load(root, config_dir).registry.modules)
    except Exception:  # the hint is advice: a registry that cannot be read never fails init
        return False


def workspace(flow) -> Workspace:
    """The workspace the later phases read (templates, fields, the registry)."""
    return Workspace(flow.root, flow.config_dir, flow.config, load_field_defs(flow.config))


def module_rows(state: dict | None) -> dict:
    """{module: {status, attempts, error, existing?, problems?}} of the state (`init status`)."""
    return {m: dict(e) for m, e in sorted((state or {}).get("modules", {}).items())}


def run_action(args, root: Path, config_dir: Path) -> int:
    from segmently_modules.init_flow import RESTART, InitFlow  # the flow imports the phases
    from segmently_modules.init_run import Runner, executor_argv
    from segmently_modules.init_work import Work, counts
    flow = InitFlow(root, config_dir, load_config(config_dir, root))
    work = flow.rel(flow.work)
    if args.action == "map":
        flow.check_map(args.restart)
        _, files = starter(root, config_dir, args.layout, args.dry_run)
        if not args.dry_run:  # the starter config may have changed what the phases read
            flow = InitFlow(root, config_dir, load_config(config_dir, root))
        result = flow.map(args.restart, args.dry_run)
        proposal, state = result["proposal"], result["state"]
        data = {"action": "map", "root": str(root), "files": files,
                "preflight": f"{work}/preflight.json", "proposal": f"{work}/proposal.json",
                "candidates": [c["name"] for c in proposal["candidates"]],
                "unassigned": len(proposal["unassigned"]), "hints": len(proposal["hints"]),
                "phase": state["phase"] if state else None,
                "next": flow.next_step(state, work) if state else
                f"run segmently-modules init map without --dry-run to write {work}/",
                "dry_run": args.dry_run}
        hidden = proposal["unassigned"] and any(c["signals"]["manifest"]
                                                for c in proposal["candidates"])
        note = (f"note: {len(proposal['unassigned'])} code file(s) are outside every candidate "
                f"— a manifest in a fixture, docs site or functions folder can hide source "
                f"directories: add it to [init] exclude and run {RESTART}") if hidden else None
        emit("init", data, args.json, lambda d: _render_map(d, note))
        return EXIT_OK
    if args.action == "confirm":
        result = flow.confirm(args.dry_run)
        data = {"action": "confirm", "confirmed": f"{work}/confirmed.json", **result,
                "dry_run": args.dry_run}
        emit("init", data, args.json, _render_confirm)
        return EXIT_OK
    if args.action == "status":
        state = flow.load_state()
        data = {"action": "status", "phase": state["phase"] if state else None,
                "phases": flow.statuses(state), "next": flow.next_step(state, work),
                "modules": module_rows(state), "counts": counts(state) if state else
                counts({"modules": {}}), "pr": (state or {}).get("pr")}
        emit("init", data, args.json, _render_status)
        return EXIT_OK
    phase4 = Work(flow, workspace(flow))
    if args.action == "fanout":
        result = phase4.fanout()
        data = {"action": "fanout", "work": f"{work}/work/", "items": result["items"],
                "existing": result["existing"], "status": result["status"],
                "next": flow.next_step(result["state"], work)}
        emit("init", data, args.json, _render_fanout)
        return EXIT_OK
    if args.action == "next":
        item, tally = phase4.claim()
        data = {"action": "next", "item": item,
                "path": flow.rel(phase4.item_path(item["module"])) if item else None,
                "counts": tally}
        emit("init", data, args.json, _render_next)
        return EXIT_OK
    if args.action == "done":
        status, problems = phase4.done(args.module)
        data = {"action": "done", "module": args.module,
                "status": "done" if status == "already done" else status, "problems": problems,
                "message": "already done" if status == "already done" else None}
        for problem in problems:
            print(f"segmently-modules: {args.module}: {problem}", file=sys.stderr)
        emit("init", data, args.json, _render_done)
        return EXIT_FINDINGS if problems else EXIT_OK
    if args.action == "reconcile":
        from segmently_modules.init_reconcile import Reconcile
        result = Reconcile(phase4).run(args.force)
        state = result.pop("state")
        data = {"action": "reconcile", "staging_registry": f"{work}/staging/registry.json",
                "reconcile": f"{work}/reconcile.json", **result,
                "next": flow.next_step(state, work)}
        emit("init", data, args.json, _render_reconcile)
        return EXIT_OK
    if args.action in ("eval-tasks", "verify"):
        from segmently_modules.init_verify import Verify
        check = Verify(phase4)
        if args.action == "eval-tasks":
            result = check.eval_tasks(executor_argv(args.executor, root), args.force)
            state = result.pop("state")
            problems = result.pop("problems")
            for problem in problems:
                print(f"segmently-modules: eval-tasks: {problem}", file=sys.stderr)
            message = ("routing tasks exist — --force to regenerate"
                       if result["status"] == "exists" else None)
            data = {"action": "eval-tasks", **result, "message": message,
                    "next": flow.next_step(flow.load_state(), work)}
            emit("init", data, args.json, _render_eval_tasks)
            return EXIT_FINDINGS if problems else EXIT_OK
        result = check.run(args.force)
        state = result.pop("state")
        data = {"action": "verify", "verify": f"{work}/verify.json", **result,
                "next": flow.next_step(flow.load_state(), work)}
        emit("init", data, args.json, _render_verify)
        return EXIT_OK if result["passed"] else EXIT_FINDINGS
    if args.action == "finish":
        from segmently_modules.init_finish import Finish
        result = Finish(phase4).run(args.force, args.agents_md or [], args.open_pr, args.base,
                                    args.branch or BRANCH)
        return _report_finish(flow, work, result, args.json)
    if args.action == "run":
        runner = Runner(phase4, executor_argv(args.executor, root))
        phase4.reset()
        result = runner.run()
        return _report_run(flow, work, result, args.json)
    from segmently_modules.init_resume import Chain
    argv = executor_argv(args.executor, root) if args.executor is not None else None
    chain = Chain(flow, phase4, argv, args.non_interactive, args.open_pr, args.base,
                  args.branch or BRANCH)
    code = chain.run()
    if code != EXIT_OK:
        for message in chain.messages:
            print(f"segmently-modules: resume: {message}", file=sys.stderr)
    state = flow.load_state()
    data = {"action": "resume", "ran": chain.ran, "phase": state["phase"] if state else None,
            "next": flow.next_step(state, work), "message": "; ".join(chain.messages) or None}
    emit("init", data, args.json, _render_resume)
    return code


def _run_failures(result: dict) -> int:
    """The stderr lines of a run (failed modules, writes outside the work dir); its exit code."""
    for row in result["modules"]:
        if row["status"] == "failed":
            print(f"segmently-modules: {row['module']} failed: {row['error'].splitlines()[0]}",
                  file=sys.stderr)
    for path in result["outside"]:
        print(f"segmently-modules: wrote outside the staging dir: {path}", file=sys.stderr)
    failed = result["outside"] or any(r["status"] == "failed" for r in result["modules"])
    return EXIT_FINDINGS if failed else EXIT_OK


def _report_run(flow, work: str, result: dict, as_json: bool) -> int:
    from segmently_modules.init_work import counts
    code = _run_failures(result)
    state = flow.load_state()
    data = {"action": "run", "modules": result["modules"], "counts": counts(state),
            "outside": result["outside"], "failed": code != EXIT_OK,
            "next": flow.next_step(state, work)}
    emit("init", data, as_json, _render_run)
    return code


def _render_run(d) -> None:
    if not d["modules"]:
        print("nothing pending")
    for row in d["modules"]:
        error = f" {row['error'].splitlines()[0]}" if row["error"] else ""
        print(f"{row['status']:<8} {row['module']}  (attempt {row['attempts']}){error}")
    c = d["counts"]
    print(f"modules  {c['done']} done, {c['running']} running, {c['pending']} pending, "
          f"{c['failed']} failed")
    print(f"next: {d['next']}")


def _report_finish(flow, work: str, result: dict, as_json: bool) -> int:
    state, error = result.pop("state"), result.pop("error")
    if error:
        print(f"segmently-modules: the pull request is pending: {error} — retry with segmently-modules init resume "
              f"--open-pr", file=sys.stderr)
    nxt = flow.next_step(state, work)
    if not result["agents_md"]:
        nxt = (f"no CLAUDE.md or AGENTS.md got the block: segmently-modules agents-md --target CLAUDE.md "
               f"(init finish takes --agents-md CLAUDE.md); {nxt}")
    data = {"action": "finish", **result, "next": nxt}
    emit("init", data, as_json, _render_finish)
    return EXIT_FINDINGS if error else EXIT_OK


def _render_finish(d) -> None:
    print(f"moved         {len(d['moved'])} doc(s) into the modules dir")
    print(f"registry      {d['registry']}")
    if d["code_map"]:
        print(f"code-map      {', '.join(d['code_map'])}")
    for row in d["agents_md"]:
        print(f"agents-md     {row['status']} {row['path']}")
    if d["forced"]:
        print("forced        finished with --force (recorded in the state)")
    print(f"git add {' '.join(d['git_add'])}")
    if d["pr"]:
        print(f"pr            {d['pr']}")
    print(f"next: {d['next']}")


def _render_eval_tasks(d) -> None:
    if d["status"] == "exists":
        print(f"{d['message']} ({d['file']})")
    elif d["status"] == "written":
        print(f"wrote         {d['file']} ({d['tasks']} task(s), "
              f"{len(d['per_module'])} module(s))")
    else:
        print(f"not written   {d['file']} (the problems are on stderr)")
    print(f"next: {d['next']}")


def _render_verify(d) -> None:
    from segmently_modules.init_work import INVENTED  # the words init done uses too (SI-2)
    s = d["lint"]["summary"]
    print(f"lint          {s['error']} error(s), {s['warning']} warning(s), {s['info']} info")
    for f in d["lint"]["findings"]:
        if f["severity"] != "info":
            print(f"  {f['severity']:<8} {f['code']} {f['module']}: {f['message']}")
    print(f"invented      {len(d['invented'])} component(s)")
    for f in d["invented"]:
        print(f"  {f['doc']}:{f['line']}: {INVENTED[f['kind']]}: {f['token']}")
    if d["routing"] is None:
        print("routing: not measured")
    else:
        r = d["routing"]
        print(f"routing       hit rate {r['hit_rate']} ({r['hits']}/{r['tasks']}, top "
              f"{r['top']}; threshold {r['min_hit_rate']})")
        for row in r["per_module"]:
            for miss in row["misses"]:
                print(f"  miss  {row['module']}: \"{miss['task']}\" → "
                      f"{', '.join(miss['got']) or '(no module)'}")
    print(f"{'passed' if d['passed'] else 'FAILED':<13} {d['verify']}")
    print(f"next: {d['next']}")


def _render_reconcile(d) -> None:
    print(f"wrote         {d['staging_registry']}")
    print(f"wrote         {d['reconcile']}")
    added = sum(e["source"] == "imports" for e in d["edges"])
    print(f"edges         {len(d['edges'])} ({added} added from the imports)")
    for c in d["collisions"]:
        owner = c["owner"] or "a tie"
        removed = f"; removed from {', '.join(c['removed'])}" if c["removed"] else ""
        # a tie has no owner: nothing is kept and nothing removed
        kept = [m for m in c["others"] if c["owner"] and c["files"].get(m, 0) > 0]
        if kept:  # D14: the holders whose own files hold the keyword keep it
            removed += f"; kept by {', '.join(kept)} (their files hold it)"
        print(f"collision     '{c['keyword']}' — owner {owner}{removed}")
    for d_ in d["duplicates"]:
        where = ", ".join(f"{x['file']}:{x['line']}" for x in d_["definitions"])
        print(f"duplicate     {d_['name']} — {where}")
    print(f"judgement     {len(d['judgement'])} item(s) left to decide")
    print(f"next: {d['next']}")


def _render_map(d, note: str | None = None) -> None:
    for f in d["files"]:
        print(f"{_VERBS[f['status']][d['dry_run']]:<13} {f['path']}")
    verb = "would write" if d["dry_run"] else "wrote"
    print(f"{verb:<13} {d['preflight']}")
    print(f"{verb:<13} {d['proposal']}")
    print(f"candidates    {', '.join(d['candidates']) or '(none)'}")
    print(f"unassigned    {d['unassigned']} code file(s); hints {d['hints']}")
    if note:  # text only: code files outside every manifest unit
        print(note)
    print(f"next: {d['next']}")


def _render_confirm(d) -> None:
    verb = {"confirmed": "confirmed", "updated": "updated", "unchanged": "unchanged"}[d["status"]]
    if d["dry_run"] and d["status"] != "unchanged":
        verb = "would confirm"
    print(f"{verb:<13} {d['confirmed']} ({len(d['included'])} included, {len(d['excluded'])} "
          f"excluded)")
    print(f"modules       {', '.join(d['included'])}")


def _render_status(d) -> None:
    if not d["phases"]:
        print("no init state")
    for phase, status in d["phases"].items():
        print(f"{phase:<10} {status}")
    for module, entry in d["modules"].items():
        line = f"{module:<24} {entry['status']}"
        if entry.get("existing"):
            line += "  (existing)"
        if entry["status"] == "failed" or entry["attempts"] > 1:
            line += f"  (attempt {entry['attempts']})"
        if entry["error"]:
            line += f" {entry['error'].splitlines()[0]}"
        print(line)
    if d["modules"]:
        c = d["counts"]
        print(f"modules    {c['done']} done, {c['running']} running, {c['pending']} pending, "
              f"{c['failed']} failed")
    if d["pr"]:
        print(f"pr         {d['pr']}")
    print(f"next: {d['next']}")


def _render_fanout(d) -> None:
    print(f"{d['status']:<13} {d['work']} ({len(d['items'])} work item(s), "
          f"{len(d['existing'])} already in the registry)")
    print(f"modules       {', '.join(d['items'])}")
    print(f"next: {d['next']}")


def _render_next(d) -> None:
    c = d["counts"]
    if d["item"] is None:
        print(f"nothing pending ({c['done']} done, {c['running']} running, {c['failed']} "
              f"failed)")
        return
    print(f"claimed       {d['item']['module']}  (work item {d['path']})")
    print(d["item"]["prompt"], end="")


def _render_done(d) -> None:
    if d["problems"]:
        print(f"not done      {d['module']} ({len(d['problems'])} problem(s) on stderr)")
    else:
        print(f"{d['message'] or 'done':<13} {d['module']}")


def _render_resume(d) -> None:
    print(f"ran           {', '.join(d['ran'])}" if d["ran"] else "nothing to run")
    if d["message"]:
        print(d["message"])
    print(f"next: {d['next']}")


def _render(d, populated: bool = False) -> None:
    print(f"root: {d['root']}")
    for f in d["files"]:
        print(f"{_VERBS[f['status']][d['dry_run']]:<13} {f['path']}")
    print(f"layout: {d['layout']}")
    if populated:
        print("next: segmently-modules next")
        return
    print(f"next: segmently-modules create NAME --description \"…\" --keywords \"a, b, c, d, e\" (5 or "
          f"more); then wire code with segmently-modules code-map add ID --pattern 'src/{{module}}/**' "
          f"(rules land in {d['files'][0]['path']}) and check it with: segmently-modules coverage")
