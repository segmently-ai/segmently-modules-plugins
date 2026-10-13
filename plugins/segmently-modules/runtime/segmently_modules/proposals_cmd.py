import json
import os
import sys
from pathlib import Path

from segmently_modules.output import EXIT_FINDINGS, EXIT_OK, UsageError, emit
from segmently_modules.proposals import (DOC_OPS, add_proposal, apply_proposals, make_item, pending,
                              reject_run)
from segmently_modules.store import utc_now
from segmently_modules.workspace import Workspace
from segmently_modules.writers import OPS as FIELD_OPS


def register(sub, common) -> None:
    p = sub.add_parser("propose", parents=[common],
                       help="queue a registry/doc change (applied later by proposals apply)")
    p.add_argument("--module", required=True, help="module or module/child")
    p.add_argument("--op", required=True, choices=FIELD_OPS + DOC_OPS)
    p.add_argument("--field", help="field ops: the registry field")
    p.add_argument("--doc", help="doc ops: repo-relative path of a .md doc inside the module's "
                                  "own directory (e.g. modules/<m>/roles/developer.md)")
    p.add_argument("--value", help="field ops: JSON value; doc ops: text")
    p.add_argument("--value-file", type=Path, help="doc ops: read the text from a file ('-' = stdin)")
    p.add_argument("--reason", required=True)
    p.add_argument("--run-id", default=os.environ.get("SEGMENTLY_MODULES_RUN_ID"))
    p.add_argument("--agent", default=os.environ.get("SEGMENTLY_MODULES_AGENT", "cli"))
    p.set_defaults(func=run_propose)

    q = sub.add_parser("proposals", parents=[common], help="list, apply or reject queued proposals")
    q.add_argument("action", choices=("list", "apply", "reject"))
    q.add_argument("--run-id", help="only this run (required for reject)")
    q.add_argument("--reason", help="reject: why")
    q.add_argument("--dry-run", action="store_true", help="apply: report results, write nothing")
    q.set_defaults(func=run_proposals)


def _value(args):
    if args.op in DOC_OPS:
        if args.value_file is not None:
            if str(args.value_file) == "-":
                return sys.stdin.read()
            try:
                return args.value_file.read_text(encoding="utf-8")
            except OSError as e:
                raise UsageError(f"{args.value_file}: cannot read: {e}") from None
        return args.value
    if args.op == "unset":
        return None
    if args.value is None:
        raise UsageError(f"{args.op} proposals need --value (JSON)")
    try:
        return json.loads(args.value)
    except json.JSONDecodeError as e:
        raise UsageError(f"--value is not valid JSON ({e.msg}); quote strings: '\"text\"'") from None


def run_propose(args) -> int:
    ws = Workspace.from_args(args)
    run_id = args.run_id or utc_now().replace(":", "").replace("-", "")
    item = make_item(ws, args.op, args.module, args.reason, field=args.field, doc=args.doc,
                     value=_value(args))
    path = add_proposal(ws, run_id, args.agent, item)
    data = {"file": str(path.relative_to(ws.root)), "run_id": run_id, "agent": args.agent,
            "item": item}
    emit("propose", data, args.json, lambda d: print(f"queued {d['item']['op']} "
                                                      f"{d['item']['module']} -> {d['file']}"))
    return EXIT_OK


def run_proposals(args) -> int:
    ws = Workspace.from_args(args)
    if args.action == "list":
        rows = [{"file": p.name, "run_id": d.get("run_id"), "agent": d.get("agent"),
                 "created_at": d.get("created_at"), "items": len(d.get("items", []))}
                for p, d in pending(ws, args.run_id)]
        emit("proposals", rows, args.json, _render_list)
        return EXIT_OK
    if args.action == "reject":
        if not args.run_id:
            raise UsageError("reject needs --run-id")
        files = reject_run(ws, args.run_id, args.reason)
        emit("proposals", {"rejected_files": files}, args.json,
             lambda d: print("\n".join(f"rejected  {f}" for f in d["rejected_files"])))
        return EXIT_OK
    report = apply_proposals(ws, args.run_id, args.dry_run)
    emit("proposals", report, args.json, _render_apply)
    return EXIT_FINDINGS if report["summary"]["rejected"] else EXIT_OK


def _render_list(rows) -> None:
    for r in rows:
        print(f"{r['file']:<48} {r['items']:>3} item(s)  {r['created_at']}")
    print(f"\n{len(rows)} pending file(s)")


def _render_apply(d) -> None:
    for f in d["files"]:
        print(f"{f['file']}")
        for r in f["results"]:
            why = f"  — {r['reason']}" if r.get("reason") else ""
            print(f"  {r['status']:<8} #{r['id']} {r['op']} {r['module']}{why}")
    s = d["summary"]
    prefix = "dry run: " if d["dry_run"] else ""
    print(f"\n{prefix}{s['applied']} applied, {s['noop']} no-op, {s['rejected']} rejected")
