"""`segmently-modules coverage`: how much of the repository maps to a module. The file set is every
git-tracked file plus every new file git does not ignore (root-relative, limited to the root),
narrowed by `[coverage] include` (default `["**"]`) and `exclude` globs. The modules dir, the
config dir, the registry file and its `.lock`, the proposals dir and dotfiles / dot-directories
at any level never count. Mapping = `sync`'s mapping (docs, code_pointer fields, `[[code_map]]`
rules)."""
from pathlib import PurePosixPath

from segmently_modules.changes import glob_to_regex, map_files, repo_files, require_work_tree
from segmently_modules.output import EXIT_FINDINGS, EXIT_OK, UsageError, emit
from segmently_modules.workspace import Workspace

DEFAULT_INCLUDE = ["**"]  # in code, not in defaults/config.toml: arrays merge by appending
UNMAPPED_SHOWN = 20


def percent(share: float) -> float:
    """share (3 decimals) as a percentage with 1 decimal — exact for a 3-decimal share, so
    0.29 compares as 29.0, never as 28.999999999999996."""
    return round(share * 100, 1)


def _engine_owned(ws):
    """A predicate: the path lies in the modules dir, the proposals dir or the config dir, or
    is the registry file or its `.lock` — never counted, before any other rule."""
    paths = ws.config["paths"]
    skip = [PurePosixPath(paths[k]).as_posix() + "/" for k in ("modules_dir", "proposals_dir")]
    registry = PurePosixPath(paths["registry"]).as_posix()
    engine_files = {registry, registry + ".lock"}
    try:
        config_rel = ws.config_dir.relative_to(ws.root).as_posix()
        if config_rel != ".":
            skip.append(config_rel + "/")
    except ValueError:  # config dir outside the root: none of its files are listed anyway
        pass
    return lambda path: path.startswith(tuple(skip)) or path in engine_files


def _dotted(path: str) -> bool:
    return any(part.startswith(".") for part in path.split("/"))


def counted_files(ws, files: list[str]) -> list[str]:
    cfg = ws.config.get("coverage") or {}
    include = [glob_to_regex(g) for g in cfg.get("include") or DEFAULT_INCLUDE]
    exclude = [glob_to_regex(g) for g in cfg.get("exclude") or []]
    owned = _engine_owned(ws)

    def counts(path: str) -> bool:
        if _dotted(path) or owned(path):
            return False
        return any(rx.match(path) for rx in include) and not any(rx.match(path) for rx in exclude)

    return [f for f in files if counts(f)]


def dotfiles_left_out(ws, files: list[str]) -> int:
    """The files only the dot rule keeps out of `total` (a dotfile or a file in a
    dot-directory, at any level) — the engine's own paths are left out first."""
    owned = _engine_owned(ws)
    return sum(1 for f in files if _dotted(f) and not owned(f))


def coverage_report(ws, files: list[str]) -> dict:
    counted = counted_files(ws, files)
    mapping = map_files(ws, counted)
    total, mapped = len(counted), len(counted) - len(mapping["unmapped"])
    # rounded DOWN to 3 decimals, so the share never overstates (round() would turn 1999 of
    # 2000 mapped into 1.0 / 100 % while one file is still unmapped)
    share = mapped * 1000 // total / 1000 if total else 1.0
    return {"total": total, "mapped": mapped, "share": share,
            "modules": {t: len(m["files"]) for t, m in mapping["modules"].items()},
            "unmapped": mapping["unmapped"]}


def register(sub, common) -> None:
    p = sub.add_parser("coverage", parents=[common],
                       help="share of the repository's files that map to a module; "
                            "lists the unmapped ones")
    p.add_argument("--fail-under", type=float, metavar="PCT",
                   help="exit 1 when less than PCT %% of the files map to a module")
    p.set_defaults(func=run)


def run(args) -> int:
    if args.fail_under is not None and not 0 <= args.fail_under <= 100:
        raise UsageError("--fail-under must be between 0 and 100")
    ws = Workspace.from_args(args)
    require_work_tree(ws.root, "coverage")
    files = repo_files(ws.root)
    data = coverage_report(ws, files)
    failed = args.fail_under is not None and percent(data["share"]) < args.fail_under
    dotfiles = dotfiles_left_out(ws, files)  # text only: the JSON shape stays as it is
    emit("coverage", data, args.json, lambda d: _render(d, args.fail_under, failed, dotfiles))
    return EXIT_FINDINGS if failed else EXIT_OK


def _render(d, fail_under, failed, dotfiles: int = 0) -> None:
    for target, n in d["modules"].items():
        print(f"{target:<36} {n:>5} file(s)")
    print(f"mapped {d['mapped']} of {d['total']} file(s): share {d['share']} "
          f"({percent(d['share'])} %)")
    if dotfiles:
        print(f"{dotfiles} dotfile(s) not counted (dotfiles and dot-directories never count)")
    if d["unmapped"]:
        print("unmapped:")
        for f in d["unmapped"][:UNMAPPED_SHOWN]:
            print(f"  {f}")
        if len(d["unmapped"]) > UNMAPPED_SHOWN:
            print(f"  … {len(d['unmapped']) - UNMAPPED_SHOWN} more")
    if failed:
        print(f"coverage {percent(d['share'])} % is below --fail-under {fail_under:g} %")
