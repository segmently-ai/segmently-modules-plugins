"""`segmently-modules sync-instructions`: what to bring up to date in the module docs after a change —
read-only. Exactly one of:

  --from-diff A..B   the change of a git range      (`discover`'s mapping, drift MS050 + MS051)
  --files PATH…      a list of changed files        (`discover`'s mapping, drift MS050)
  --module M…        named modules, no change set   (usage `modify`, their existing docs)

Per module: `docs_to_update` (what `discover` lists for the change; with `--module`, every doc
`show --all-roles` lists that exists, `*.legacy.md` excluded), `drift` (the `lint --changed`
checks of the change for that module), `fields` (every field of the module's scope with a
`sync_hint`, from all layers) and `proposals_pending` (queued proposal items for the module)."""
from __future__ import annotations

from dataclasses import asdict

from segmently_modules.changes import changed_files, diff_names, missing_files
from segmently_modules.lint import drift_findings
from segmently_modules.output import EXIT_OK, UsageError, emit
from segmently_modules.pipeline import build_discover, split_children
from segmently_modules.proposals import pending
from segmently_modules.query import show_target
from segmently_modules.workspace import Workspace


def register(sub, common) -> None:
    p = sub.add_parser("sync-instructions", parents=[common],
                       help="what to update in the module docs after a change (read-only)",
                       description="Per module a change touches (--from-diff A..B, --files "
                                   "PATH …) or per named module (--module M …): the docs to "
                                   "update, the drift findings (MS050; MS051 with --from-diff), "
                                   "every field with a sync_hint and the queued proposals. "
                                   "Writes nothing.")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--from-diff", metavar="A..B", help="git range of the change")
    src.add_argument("--files", nargs="+", action="extend", metavar="PATH", help="changed files (no git needed)")
    src.add_argument("--module", action="append", dest="modules", metavar="M",
                     help="a module or module/child (repeatable): its docs and field hints")
    p.set_defaults(func=run)


def _fields(ws, module: str) -> list[dict]:
    scope = "submodule" if "/" in module else "module"
    return [{"name": d.name, "type": list(d.type), "description": d.description,
             "sync_hint": d.sync_hint}
            for d in ws.fields.values() if d.sync_hint and scope in d.scope]


def _queued(ws) -> dict[str, int]:
    counts: dict[str, int] = {}
    for _, doc in pending(ws):
        for item in doc.get("items", []):
            if isinstance(item, dict) and isinstance(item.get("module"), str):
                counts[item["module"]] = counts.get(item["module"], 0) + 1
    return counts


def _module_docs(ws, target: str) -> list[str]:
    code, shown = show_target(ws, target, None, True)
    if code != EXIT_OK:  # a pointer stub: not a registry module
        raise UsageError(f"unknown module '{target}' (a pointer stub)")
    docs: list[str] = []
    for r in shown["read"]:
        if r["exists"] and not r["path"].endswith(".legacy.md") and r["path"] not in docs:
            docs.append(r["path"])
    return docs


def build(ws, diff_range: str | None, files: list[str] | None,
          modules: list[str] | None) -> dict:
    queued = _queued(ws)

    def row(module: str, docs: list[str], drift: list, children: list = ()) -> dict:
        out = {"module": module, "usage": "modify", "docs_to_update": docs}
        if children:  # a split parent: the skill picks the child the change is in
            out["children"] = list(children)
        out.update(drift=[{k: v for k, v in asdict(f).items() if k != "module"} for f in drift],
                   fields=_fields(ws, module), proposals_pending=queued.get(module, 0))
        return out

    if modules:
        return {"modules": [row(m, _module_docs(ws, m), [], split_children(ws, m)) for m in dict.fromkeys(modules)],
                "files_outside_modules": []}
    changed = changed_files(ws.root, diff_range=diff_range, files=files)
    frozen = ([f for f in diff_names(ws.root, diff_range, "--diff-filter=MD")
               if f.endswith(".legacy.md")] if diff_range else [])
    found = build_discover(ws, None, changed, None,
                           missing_files(ws.root, changed) if files else [])
    drift, _ = drift_findings(ws, changed, frozen)
    rows = []
    for m in found["modules"]:
        own = [f for f in drift if (f.path in m["touched_files"] if f.path
                                    else f.module == m["module"])]
        rows.append(row(m["module"], m["docs_to_update"], own, m.get("children", ())))
    return {"modules": rows, "files_outside_modules": found["files_outside_modules"]}


def run(args) -> int:
    ws = Workspace.from_args(args)
    data = build(ws, args.from_diff, args.files, args.modules)
    emit("sync-instructions", data, args.json, _render)
    return EXIT_OK


def _render(d) -> None:
    if not d["modules"]:
        print("nothing to sync")
    for m in d["modules"]:
        print(f"{m['module']}  {m['usage']}")
        for doc in m["docs_to_update"]:
            print(f"  update  {doc}")
        for c in m.get("children", []):
            print(f"  child   {c['module']}  {c['description']}  ({c['doc']})")
        for f in m["drift"]:
            print(f"  drift   {f['code']} {f['path'] or f['message']}")
        for f in m["fields"]:
            print(f"  field   {f['name']} — {f['sync_hint']}")
        if m["proposals_pending"]:
            print(f"  queued  {m['proposals_pending']} proposal item(s) — segmently-modules proposals list")
    for f in d["files_outside_modules"]:
        print(f"outside   {f}")
