from segmently_modules.layout import build_index, split_registry
from segmently_modules.output import EXIT_FINDINGS, EXIT_OK, UsageError, emit
from segmently_modules.store import atomic_write, file_lock
from segmently_modules.workspace import Workspace


def register(sub, common) -> None:
    p = sub.add_parser("index", parents=[common], help="per-module layout: build or split the index")
    p.add_argument("action", choices=("build", "split"))
    p.add_argument("--check", action="store_true", help="build: exit 1 if the index is stale")
    p.add_argument("--dry-run", action="store_true", help="split: list the files, write nothing")
    p.set_defaults(func=run)


def run(args) -> int:
    ws = Workspace.from_args(args)
    if args.action == "build":
        return _build(ws, args)
    return _split(ws, args)


def _build(ws, args) -> int:
    if ws.config["paths"]["registry_layout"] != "per-module":
        raise UsageError('index build needs [paths] registry_layout = "per-module"')
    index = ws.root / ws.config["paths"]["registry"]
    with file_lock(index):
        text, stale = build_index(ws.root, ws.config)
        written = stale and not args.check
        if written:
            atomic_write(index, text)
    data = {"index": ws.config["paths"]["registry"], "stale": stale, "written": written,
            "check": args.check}
    emit("index", data, args.json, _render_build)
    return EXIT_FINDINGS if (args.check and stale) else EXIT_OK


def _split(ws, args) -> int:
    files = split_registry(ws.root, ws.config)
    if not args.dry_run:
        for path, text in files:
            atomic_write(path, text)
    data = {"files": [str(p.relative_to(ws.root)) for p, _ in files], "dry_run": args.dry_run,
            "next": 'set [paths] registry_layout = "per-module" in .segmently-modules/config.toml'}
    emit("index", data, args.json, _render_split)
    return EXIT_OK


def _render_build(d) -> None:
    if d["check"]:
        print(f"{d['index']}: {'STALE — run: segmently-modules index build' if d['stale'] else 'up to date'}")
    else:
        print(f"{d['index']}: {'rebuilt' if d['written'] else 'up to date'}")


def _render_split(d) -> None:
    verb = "would write" if d["dry_run"] else "wrote"
    for f in d["files"]:
        print(f"{verb}  {f}")
    print(f"next: {d['next']}")
