"""`segmently-modules code-map`: the `[[code_map]]` rules and the files they route.

  list [--module TARGET]  the effective rules (every layer merged); with --module only the
                          rules that route files to TARGET (a module or `parent/child`)
  add ID …                append ONE rule to the team config `<config_dir>/config.toml`:
                          append mode, one write, never a rewrite (comments, mode, symlinks and
                          the file's newline style stay); the combined text is re-parsed and
                          validated first, so a refused add writes nothing. Rules are edited or
                          removed by hand.
  files TARGET            every repository file (git-tracked + new, not ignored; no coverage
                          filters) that maps to TARGET, with its mapping sources per file:
                          `docs`, `code_pointer:<field>`, `code_map:<id>`"""
import json
import tomllib

from segmently_modules.changes import repo_files, require_work_tree, routes, rule_routes_to, target_names
from segmently_modules.config import discover_packs, read_toml, validate_layer
from segmently_modules.output import EXIT_OK, UsageError, emit
from segmently_modules.registry import as_list
from segmently_modules.workspace import Workspace

ACTIONS = ("list", "add", "files")


def register(sub, common) -> None:
    p = sub.add_parser("code-map", parents=[common],
                       help="list, add or check [[code_map]] rules (which files map to a module)",
                       description="list: the effective [[code_map]] rules (--module TARGET: "
                                   "only those routing files to TARGET). add ID: append one "
                                   "rule to <config_dir>/config.toml — --pattern P (with a "
                                   "{module} segment) or --glob G (repeatable) with --module M; "
                                   "edit or remove rules by hand. files TARGET: every "
                                   "repository file that maps to TARGET and how (docs, "
                                   "code_pointer:<field>, code_map:<id>); needs git.")
    p.add_argument("action", choices=ACTIONS)
    p.add_argument("name", nargs="?", metavar="ID|TARGET",
                   help="add: the new rule's id · files: a module or parent/child")
    p.add_argument("--module", metavar="TARGET",
                   help="list: only the rules that route files to TARGET · add: the rule's "
                        "module (required with --glob; overrides a pattern's capture)")
    p.add_argument("--pattern", help="add: a glob with a {module} segment, e.g. 'src/{module}/**'")
    p.add_argument("--glob", action="append", dest="globs", metavar="GLOB",
                   help="add: a glob routed to --module (repeatable)")
    p.add_argument("--exclusive", action="store_true",
                   help="add: a file this rule routes is mapped ONLY by exclusive rules")
    p.add_argument("--shared", action="store_true",
                   help="add: the files this rule routes belong to other modules too, on purpose "
                        "(lint MS053 does not report its overlaps)")
    p.add_argument("--dry-run", action="store_true", help="add: show the block, write nothing")
    p.set_defaults(func=run)


def check_target(ws, target: str) -> str:
    """`target` when it names a registry module or child; else exit 2 with the closest names."""
    targets = target_names(ws.registry.modules)
    if target not in targets:
        near = sorted(t for t in targets if target.lower() in t.lower())
        hint = f" — closest: {', '.join(near[:5])}" if near else ""
        raise UsageError(f"unknown module '{target}'{hint}")
    return target


def rule_rows(config: dict, target: str | None = None) -> list[dict]:
    """The effective rules, optionally only those that route files to `target`."""
    return [{"id": r["id"], "module": r.get("module"), "pattern": r.get("pattern"),
             "globs": r.get("globs"), "exclusive": r.get("exclusive") is True}
            for r in as_list(config.get("code_map"))
            if isinstance(r, dict) and "id" in r and (target is None or rule_routes_to(r, target))]


def _toml_string(value: str) -> str:
    """A TOML basic string: JSON's escapes are valid TOML escapes; DEL must be escaped too."""
    return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")


def _defined_in(ws, rule_id: str) -> str | None:
    """The layer file that already defines a `[[code_map]]` rule with this id, if any
    (root-relative when it lies inside the root)."""
    def has(rules) -> bool:
        return any(isinstance(r, dict) and r.get("id") == rule_id for r in as_list(rules))

    for pack in discover_packs(ws.config_dir):
        if has(pack["data"].get("code_map")):
            return f"pack {pack['id']} ({ws.rel(pack['path'])})"
    for name in ("config.toml", "config.user.toml"):
        path = ws.config_dir / name
        if path.exists() and has(read_toml(path).get("code_map")):
            return ws.rel(path)
    return None


def add_rule(ws, rule_id, pattern: str | None, globs: list[str] | None, module: str | None,
             exclusive: bool, dry_run: bool, shared: bool = False) -> dict:
    """Append one `[[code_map]]` rule to the team config; every refusal writes nothing."""
    if not rule_id:
        raise UsageError("code-map add: id must be a non-empty string")
    if (pattern is None) == (not globs):
        raise UsageError("code-map add: give --pattern or --glob (not both): --pattern P with a "
                         "{module} segment, or --glob G (repeatable) with --module M")
    for glob in [pattern] if pattern is not None else globs:
        if glob.startswith(("./", "/")) or glob.endswith("/"):
            raise UsageError(f'glob "{glob}": paths are root-relative and a directory needs '
                             f'/** — e.g. src/tasks/**')
    if globs and module is None:
        raise UsageError("code-map add: --glob needs --module (the module the files belong to)")
    team = ws.config_dir / "config.toml"
    if not team.exists():
        raise UsageError(f"{team} does not exist — run `segmently-modules init` first")
    if module is not None and module not in target_names(ws.registry.modules):
        raise UsageError(f"code-map add: '{module}' is not a registry module or child "
                         f"(segmently-modules list shows the modules)")
    owner = _defined_in(ws, rule_id)
    if owner:
        raise UsageError(f"code_map rule '{rule_id}' is already defined in {owner}; a repeated "
                         f"id would deep-merge into that rule — edit it by hand instead")
    rule = {"id": rule_id}
    if module is not None:
        rule["module"] = module
    if pattern is not None:
        rule["pattern"] = pattern
    else:
        rule["globs"] = list(globs)
    if exclusive:
        rule["exclusive"] = True
    if shared:
        rule["shared"] = True
    validate_layer({"code_map": [rule]}, team)  # the actionable pattern error, types
    lines = ["[[code_map]]"] + [
        f"{key} = " + ("[" + ", ".join(_toml_string(g) for g in value) + "]"
                       if isinstance(value, list) else "true" if value is True
                       else _toml_string(value))
        for key, value in rule.items()]
    text = team.read_bytes().decode("utf-8")
    nl = "\r\n" if "\r\n" in text else "\n"  # keep the file's own newline style
    lead = "" if not text else nl if text.endswith("\n") else nl + nl
    appended = lead + nl.join(lines) + nl
    try:
        layer = tomllib.loads(text + appended)
        validate_layer(layer, team)
        payload = appended.encode("utf-8")
    except (tomllib.TOMLDecodeError, UsageError, UnicodeEncodeError) as e:
        raise UsageError(f"appending the rule would make {team} invalid ({e}); nothing "
                         f"written") from None
    if [r for r in as_list(layer.get("code_map"))
            if isinstance(r, dict) and r.get("id") == rule_id] != [rule]:
        raise UsageError(f"appending the rule would make {team} invalid (it does not read back "
                         f"as written); nothing written")
    try:
        shown = team.relative_to(ws.root).as_posix()
    except ValueError:
        shown = str(team)
    if not dry_run:
        try:
            with open(team, "ab") as fh:  # append mode, one write: never a rewrite
                fh.write(payload)
        except OSError as e:
            raise UsageError(f"cannot write {shown}: {e.strerror}; nothing written") from None
    return {"id": rule_id, "file": shown, "block": "\n".join(lines) + "\n", "dry_run": dry_run}


def files_of(ws, target: str) -> dict:
    """Every repository file that maps to `target`, with its sources, in path order."""
    require_work_tree(ws.root, "code-map files")
    per_file: dict[str, list] = {}
    for path, routed_to, via in routes(ws, repo_files(ws.root)):
        if routed_to == target:
            vias = per_file.setdefault(path, [])
            if via not in vias:
                vias.append(via)
    return {"target": target, "files": [{"path": p, "via": v} for p, v in per_file.items()],
            "total": len(per_file)}


def run(args) -> int:
    ws = Workspace.from_args(args)
    if args.action == "add":
        if args.name is None:
            raise UsageError("code-map add needs an ID (the new rule's id)")
        data = add_rule(ws, args.name, args.pattern, args.globs, args.module, args.exclusive,
                        args.dry_run, shared=args.shared)
        emit("code-map", data, args.json, _render_add)
        return EXIT_OK
    if args.pattern is not None or args.globs or args.exclusive or args.shared or args.dry_run:
        raise UsageError("--pattern, --glob, --exclusive, --shared and --dry-run apply to "
                         "code-map add")
    if args.action == "list":
        if args.name is not None:
            raise UsageError("code-map list takes no TARGET (filter with --module TARGET)")
        target = None if args.module is None else check_target(ws, args.module)
        emit("code-map", rule_rows(ws.config, target), args.json, _render_list)
        return EXIT_OK
    if args.name is None:
        raise UsageError("code-map files needs a TARGET (a module or parent/child)")
    if args.module is not None:
        raise UsageError("code-map files takes no --module (the TARGET is the module)")
    emit("code-map", files_of(ws, check_target(ws, args.name)), args.json, _render_files)
    return EXIT_OK


def _render_list(rows) -> None:
    if not rows:
        print("no [[code_map]] rules")
    for r in rows:
        where = r["pattern"] if r["pattern"] is not None else ", ".join(r["globs"] or [])
        flag = "  exclusive" if r["exclusive"] else ""
        print(f"{r['id']:<24} {r['module'] or '{module}':<24} {where}{flag}")


def _render_add(d) -> None:
    print(f"{'would append to' if d['dry_run'] else 'appended to'} {d['file']}:")
    print(d["block"], end="")


def _render_files(d) -> None:
    for f in d["files"]:
        print(f"{f['path']}  ({', '.join(f['via'])})")
    print(f"{d['total']} file(s) map to {d['target']}")
