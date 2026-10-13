import os

from segmently_modules.changes import changed_files, map_files, missing_files
from segmently_modules.hooks import run_hooks
from segmently_modules.output import EXIT_FINDINGS, EXIT_OK, emit
from segmently_modules.proposals import apply_proposals, check_safe_id
from segmently_modules.store import utc_now
from segmently_modules.workspace import Workspace


def register(sub, common) -> None:
    p = sub.add_parser("sync", parents=[common],
                       help="map changed files to modules, run post_sync hooks, apply proposals")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--from-diff", metavar="A..B", help="git range of the change")
    src.add_argument("--files", nargs="+", action="extend", metavar="PATH", help="changed files (no git needed)")
    p.add_argument("--apply-proposals", action="store_true",
                   help="apply pending proposals at the end (incl. ones queued by hooks): "
                        "every pending run unless --run-id / $SEGMENTLY_MODULES_RUN_ID is given")
    p.add_argument("--run-id", default=os.environ.get("SEGMENTLY_MODULES_RUN_ID"),
                   help="run id for hook proposals; with --apply-proposals, apply only this run")
    p.add_argument("--dry-run", action="store_true",
                   help="map only: no hooks run, proposals previewed, nothing written")
    p.set_defaults(func=run)


def run(args) -> int:
    if args.run_id:  # refused up front: never after hooks already ran
        check_safe_id("run id", args.run_id)
    ws = Workspace.from_args(args)
    run_id = args.run_id or utc_now().replace(":", "").replace("-", "")
    files = changed_files(ws.root, diff_range=args.from_diff, files=args.files)
    mapping = map_files(ws, files)
    targets = list(mapping["modules"])
    data = {"run_id": run_id, "diff_range": args.from_diff, "changed_files": files,
            "modules": [{"module": t, **mapping["modules"][t]} for t in targets],
            "unmapped": mapping["unmapped"],
            "missing_files": missing_files(ws.root, files) if args.files else [],
            "hooks": None, "proposals": None, "dry_run": args.dry_run}
    failed = False
    if not args.dry_run:
        payload = {"changed_modules": targets, "changed_files": files,
                   "diff_range": args.from_diff}
        data["hooks"] = run_hooks(ws, "post_sync", payload, run_id)
        failed = data["hooks"]["failed_required"]
    if args.apply_proposals:
        report = apply_proposals(ws, args.run_id, dry_run=args.dry_run)
        data["proposals"] = report
        failed = failed or report["summary"]["rejected"] > 0
    emit("sync", data, args.json, _render)
    return EXIT_FINDINGS if failed else EXIT_OK


def _render(d) -> None:
    for m in d["modules"]:
        print(f"{m['module']:<32} {', '.join(m['via']):<36} {len(m['files'])} file(s)")
    if d["unmapped"]:
        print(f"unmapped: {len(d['unmapped'])} file(s) — e.g. {d['unmapped'][0]}")
    for f in d["missing_files"]:
        print(f"not on disk: {f} (typo? a deleted file still maps)")
    for h in (d["hooks"] or {}).get("hooks", []):
        extra = f" — {h['error']}" if h.get("error") else ""
        print(f"hook {h['id']}: {h['status']}{extra}")
        for msg in h["messages"]:
            print(f"  {msg}")
    if d["proposals"]:
        s = d["proposals"]["summary"]
        print(f"proposals: {s['applied']} applied, {s['noop']} no-op, {s['rejected']} rejected")
