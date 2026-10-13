from segmently_modules.hooks import EVENTS, hooks_for
from segmently_modules.output import EXIT_OK, emit
from segmently_modules.workspace import Workspace


def register(sub, common) -> None:
    p = sub.add_parser("hooks", parents=[common], help="list the effective hooks per event")
    p.add_argument("action", choices=("list",))
    p.set_defaults(func=run)


def run(args) -> int:
    ws = Workspace.from_args(args)
    rows = [{"event": e, "id": h["id"], "owner": h.get("owner", "config"),
             "enabled": h.get("enabled", True), "required": h.get("required", False),
             "run": h.get("run", [])} for e in EVENTS for h in hooks_for(ws.config, e)]
    emit("hooks", rows, args.json, _render)
    return EXIT_OK


def _render(rows) -> None:
    for r in rows:
        flags = ("on" if r["enabled"] else "off") + (" required" if r["required"] else "")
        print(f"{r['event']:<10} {r['id']:<20} {r['owner']:<12} {flags}")
    if not rows:
        print("no hooks")
