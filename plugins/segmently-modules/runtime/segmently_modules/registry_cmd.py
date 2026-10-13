import copy
import json

from segmently_modules.output import EXIT_OK, UsageError, emit
from segmently_modules.store import open_store, serialize
from segmently_modules.workspace import Workspace
from segmently_modules.writers import OPS, apply_field_op, check_doc_key_paths, unified_diff


def register(sub, common) -> None:
    p = sub.add_parser("registry", parents=[common],
                       help="edit one registry field (validated by field definitions)")
    p.add_argument("op", choices=OPS)
    p.add_argument("target", help="module or module/child")
    p.add_argument("field", help="a declared field, or context_files.<key> for one doc key "
                                 "(e.g. context_files.supplementary)")
    p.add_argument("value", nargs="?", help="JSON value (quote strings: '\"text\"')")
    p.add_argument("--dry-run", action="store_true", help="print the diff, write nothing")
    p.set_defaults(func=run)


def parse_value(op: str, text: str | None):
    if op == "unset":
        if text is not None:
            raise UsageError("unset takes no value")
        return None
    if text is None:
        raise UsageError(f"{op} needs a JSON value")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise UsageError(f"value is not valid JSON ({e.msg}); quote strings: '\"text\"'") from None


def run(args) -> int:
    ws = Workspace.from_args(args)
    value = parse_value(args.op, args.value)
    check_doc_key_paths(args.field, args.op, value, ws.exists)
    store = open_store(ws)
    data = {"op": args.op, "target": args.target, "field": args.field,
            "dry_run": args.dry_run, "changed": False}
    if args.dry_run:
        before = store.load().raw
        after = copy.deepcopy(before)
        data["changed"] = apply_field_op(after, ws.fields, args.op, args.target, args.field, value,
                                         vocab=ws.config["registry"])
        data["diff"] = unified_diff(serialize(before), serialize(after), ws.config["paths"]["registry"])
    else:
        with store.edit() as reg:
            data["changed"] = apply_field_op(reg.raw, ws.fields, args.op, args.target,
                                             args.field, value, vocab=ws.config["registry"])
    emit("registry", data, args.json, _render)
    return EXIT_OK


def _render(d) -> None:
    if d["dry_run"]:
        print(d["diff"] or "no change")
        return
    state = "updated" if d["changed"] else "no change"
    print(f"{d['target']}.{d['field']}: {state}")
