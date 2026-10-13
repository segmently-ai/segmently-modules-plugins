import copy

from segmently_modules.migrations import all_migrations
from segmently_modules.output import EXIT_OK, UsageError, emit
from segmently_modules.store import open_store, serialize
from segmently_modules.workspace import Workspace
from segmently_modules.writers import unified_diff


def register(sub, common) -> None:
    p = sub.add_parser("migrate", parents=[common], help="upgrade old registry shapes in place")
    p.add_argument("--only", metavar="ID", help="run one migration (e.g. 001)")
    p.add_argument("--dry-run", action="store_true", help="print the diff, write nothing")
    p.set_defaults(func=run)


def migrate(raw: dict, only: str | None) -> list[dict]:
    migrations = all_migrations()
    if only and only not in {m.ID for m in migrations}:
        raise UsageError(f"unknown migration '{only}' (known: {', '.join(m.ID for m in migrations)})")
    done = []
    for m in migrations:
        if (only and m.ID != only) or not m.applies(raw):
            continue
        done.append({"id": m.ID, "description": m.DESCRIPTION, "notes": m.apply(raw)})
    return done


def run(args) -> int:
    ws = Workspace.from_args(args)
    store = open_store(ws)
    if args.dry_run:
        before = store.load().raw
        after = copy.deepcopy(before)
        applied = migrate(after, args.only)
        data = {"applied": applied, "dry_run": True,
                "diff": unified_diff(serialize(before), serialize(after),
                                     ws.config["paths"]["registry"])}
    else:
        with store.edit() as reg:
            applied = migrate(reg.raw, args.only)
        data = {"applied": applied, "dry_run": False}
    emit("migrate", data, args.json, _render)
    return EXIT_OK


def _render(d) -> None:
    if not d["applied"]:
        print("nothing to migrate")
    for m in d["applied"]:
        print(f"{'would apply' if d['dry_run'] else 'applied'} {m['id']}: {m['description']}")
        for note in m["notes"]:
            print(f"  {note}")
    if d["dry_run"] and d.get("diff"):
        print(d["diff"])
