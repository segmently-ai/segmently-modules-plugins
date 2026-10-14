from __future__ import annotations

import json
from pathlib import Path

from segmently_modules.changes import code_globs
from segmently_modules.config import enabled_roles
from segmently_modules.fields import CORE_FIELDS
from segmently_modules.output import EXIT_FINDINGS, EXIT_OK, UsageError, emit
from segmently_modules.registry import as_dict, as_list, context_paths, resolve_module_arg, stub_head
from segmently_modules.workspace import Workspace


def role_paths(cf: dict, role: str) -> list:
    val = as_dict(as_dict(cf).get("roles")).get(role)
    if isinstance(val, str):
        return [val]
    if isinstance(val, list):
        return list(val)
    return []


def skip_mark(value) -> bool:
    """A role value that says the target needs no doc for the role (`roles skip`): `false`, or
    `{"skip": NOTE}` with a non-blank string NOTE saying why."""
    return value is False or (isinstance(value, dict) and set(value) == {"skip"}
                              and isinstance(value["skip"], str) and bool(value["skip"].strip()))


def skip_note(value) -> str | None:
    """The note of a not-needed mark, None for a bare `false` (or for no mark)."""
    return value["skip"] if isinstance(value, dict) and skip_mark(value) else None


def _extras(cf: dict):
    """The docs beyond universal and roles, in every shape lint checks (`context_paths`): a
    string or an array reads as `key`, a map as `key.name`."""
    rest = {k: v for k, v in as_dict(cf).items() if k not in ("universal", "roles")}
    for label, p in context_paths(rest):
        if isinstance(p, str):
            yield label.removesuffix("[]"), p


def _stub_or_unknown(ws, name: str) -> tuple[int, dict]:
    stub = stub_head(ws.root, ws.config, name)
    if stub:
        return EXIT_FINDINGS, {"module": name, "stub": stub}
    near = [n for n in ws.registry.modules if name.lower() in n.lower()]
    hint = f" — closest: {', '.join(near[:5])}" if near else ""
    raise UsageError(f"unknown module '{name}'{hint}")


def _object(entry, label: str) -> dict:
    if not isinstance(entry, dict):
        raise UsageError(f"registry entry '{label}' is not an object")
    return entry


def show_module(ws, arg: str, role: str | None, all_roles: bool) -> tuple[int, dict]:
    """`show` for USER input: a module name, `module/child`, or a path into the modules dir;
    an argument that names an existing path outside the modules dir is refused as a file path."""
    modules_dir = ws.config["paths"]["modules_dir"]
    resolved = resolve_module_arg(arg, modules_dir)
    if resolved == arg and "/" in arg and (Path(arg).exists() or (ws.root / arg).exists()):
        raise UsageError(f"'{arg}' is a file path outside {modules_dir}/ — not a module; "
                         f"read it directly")
    return show_target(ws, resolved, role, all_roles)


def show_target(ws, target: str, role: str | None, all_roles: bool) -> tuple[int, dict]:
    """The read set of a `module[/child]` target the engine produced itself (match rows,
    changed-file mapping): no user-input path heuristics, so a code directory that happens to
    be spelled like `parent/child` never shadows the module."""
    modules = ws.registry.modules
    parent, _, child = target.partition("/")
    if parent not in modules:
        return _stub_or_unknown(ws, parent)
    entry = _object(modules[parent], parent)
    subs = as_dict(entry.get("submodules"))
    if child and child not in subs:
        raise UsageError(f"'{child}' is not a submodule of '{parent}' "
                         f"(children: {', '.join(subs) or 'none'})")
    sub = _object(subs[child], f"{parent}/{child}") if child else {}
    own = sub.get("description") if child else None  # a child shows its OWN description
    description = own if isinstance(own, str) and own else entry.get("description")
    keywords = (sub if child else entry).get("keywords")  # the target's OWN list
    result = {"module": f"{parent}/{child}" if child else parent,
              "status": entry.get("status"), "description": description,
              "keywords": [k for k in keywords if isinstance(k, str)]
              if isinstance(keywords, list) else [],  # garbage values are lint's job
              "read": [], "code": [], "code_globs": []}

    def add(label, path):
        if isinstance(path, str) and path:  # malformed paths are lint's job (MS004)
            result["read"].append({"label": label, "path": path,
                                   "exists": (ws.root / path).exists()})

    roles = enabled_roles(ws.config) if all_roles else ([role] if role else [])
    cf = as_dict(entry.get("context_files"))
    for r in roles:  # the roles the target needs no doc for (`roles skip`)
        held = as_dict(as_dict(sub.get("context_files") if child else cf).get("roles"))
        if child and r not in held:  # a child with no value of its own reads its parent's
            held = as_dict(cf.get("roles"))
        if r in held and skip_mark(held[r]):
            result.setdefault("not_needed", []).append({"role": r, "note": skip_note(held[r])})
    add("universal (parent INDEX)" if subs else "universal", cf.get("universal"))
    if child:
        ccf = as_dict(sub.get("context_files"))
        add(f"child universal ({child})", ccf.get("universal"))
        for r in roles:
            for p in role_paths(ccf, r):
                add(f"child role:{r}", p)
            for p in role_paths(cf, r):
                add(f"parent baseline role:{r}", p)
        for key, p in _extras(ccf):
            add(f"child {key}", p)
    else:
        for r in roles:
            for p in role_paths(cf, r):
                add(f"role:{r}", p)
        for key, p in _extras(cf):
            add(key, p)
        if subs:
            result["submodules"] = {c: (as_dict(s).get("description") or "")
                                    for c, s in subs.items()}
    for holder in ([sub, entry] if child else [entry]):  # a child: its own pointers first
        for name, fdef in ws.fields.items():
            if fdef.kind == "code_pointer" and holder.get(name):
                val = holder[name]
                for p in val if isinstance(val, list) else [val]:
                    if p not in result["code"]:
                        result["code"].append(p)
    own_entry = sub if child else entry  # the target's OWN values, like keywords
    result["fields"] = {k: v for k, v in own_entry.items()  # declared data; pointers are `code`
                        if k in ws.fields and k not in CORE_FIELDS
                        and ws.fields[k].kind != "code_pointer"}
    result["code_globs"] = code_globs(ws.config, result["module"])
    return EXIT_OK, result


def related_edges(ws, arg: str, relation: str | None) -> tuple[int, dict]:
    modules = ws.registry.modules
    target = resolve_module_arg(arg, ws.config["paths"]["modules_dir"])
    name, _, child = target.partition("/")
    if name not in modules:
        return _stub_or_unknown(ws, name)
    entry = _object(modules[name], name)
    sub = as_dict(entry.get("submodules")).get(child) if child else None
    if not isinstance(sub, dict):
        child, sub = "", {}  # a remainder that is no child: the parent answers, as before
    if relation and relation not in ws.config["registry"]["relations"]:
        raise UsageError(f"unknown relation '{relation}' "
                         f"(relations: {', '.join(ws.config['registry']['relations'])})")

    def edges(e: dict):  # malformed edges are lint's job (MS013); skip them here
        return [x for x in as_list(e.get("related_modules")) if isinstance(x, dict)
                and (not relation or x.get("relation") == relation)]

    inherited = bool(child) and not as_list(sub.get("related_modules"))
    fwd = edges(entry if inherited or not child else sub)
    rev = []
    for other, other_entry in modules.items():
        if other == name:
            continue
        for e in edges(as_dict(other_entry)):
            target = e.get("module")
            if isinstance(target, str) and target.partition("/")[0] == name:
                rev.append({"from": other, **e})
    data = {"module": f"{name}/{child}" if child else name, "edges": fwd, "reverse": rev}
    if inherited and fwd:  # the child declares none: these are the parent's edges
        data["inherited_from"] = name
    return EXIT_OK, data


def list_modules(ws, status: str | None) -> tuple[int, list]:
    rows = []
    for name, entry in ws.registry.modules.items():
        entry = as_dict(entry)  # a non-object entry is still listed (lint reports it)
        if status and entry.get("status") != status:
            continue
        desc = entry.get("description")
        rows.append({"module": name, "status": entry.get("status"),
                     "description": (desc if isinstance(desc, str) else "").split(". ")[0][:100],
                     "children": ",".join(as_dict(entry.get("submodules")))})
    return EXIT_OK, rows


def register(sub, common) -> None:
    s = sub.add_parser("show", parents=[common], help="resolve module[/child] to files to read")
    s.add_argument("module")
    s.add_argument("--role")
    s.add_argument("--all-roles", action="store_true")
    s.set_defaults(func=run_show)
    r = sub.add_parser("related", parents=[common], help="typed edges of a module (+ reverse)")
    r.add_argument("module")
    r.add_argument("--relation")
    r.set_defaults(func=run_related)
    li = sub.add_parser("list", parents=[common], help="one orientation line per module")
    li.add_argument("--status")
    li.set_defaults(func=run_list)


def run_show(args) -> int:
    ws = Workspace.from_args(args)
    roles = enabled_roles(ws.config)
    if args.role and args.role not in roles:
        raise UsageError(f"unknown role '{args.role}' (roles: {', '.join(roles)})")
    code, data = show_module(ws, args.module, args.role, args.all_roles)
    emit("show", data, args.json, _render_show)
    return code


def run_related(args) -> int:
    ws = Workspace.from_args(args)
    code, data = related_edges(ws, args.module, args.relation)
    emit("related", data, args.json, _render_related)
    return code


def run_list(args) -> int:
    ws = Workspace.from_args(args)
    code, rows = list_modules(ws, args.status)
    emit("list", rows, args.json, _render_list)
    return code


def _render_show(d) -> None:
    if "stub" in d:
        print(f"'{d['module']}' is a POINTER STUB (not in registry). Stub says:\n{d['stub']}")
        return
    print(f"{d['module']}  [{d['status']}]\n  {d['description']}")
    if d["keywords"]:
        print(f"  keys  {', '.join(d['keywords'])}")
    for r in d["read"]:
        mark = "" if r["exists"] else "  (MISSING ON DISK)"
        print(f"  read  {r['label']:<32} {r['path']}{mark}")
    for n in d.get("not_needed") or []:
        why = f" — {n['note']}" if n["note"] else ""
        print(f"  skip  role:{n['role']} not needed{why}")
    for c in d["code"] + d["code_globs"]:
        print(f"  code  {c}")
    for name, value in (d.get("fields") or {}).items():
        shown = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        print(f"  field {name:<32} {shown}")
    for c, desc in (d.get("submodules") or {}).items():
        print(f"  child {d['module']}/{c:<30} {desc}")


def _render_related(d) -> None:
    if "stub" in d:
        print(f"'{d['module']}' is a POINTER STUB. Stub says:\n{d['stub']}")
        return
    if "/" in d["module"]:  # a child: name it, and say whose edges these are
        print(f"module: {d['module']}")
        if d.get("inherited_from"):
            print(f"edges inherited from {d['inherited_from']}")
    print(f"forward edges — {len(d['edges']) or 'NONE'}:")
    for e in d["edges"]:
        print(f"  {str(e.get('relation')):<18} {str(e.get('module')):<38} {e.get('description')}")
    print(f"reverse edges — {len(d['reverse']) or 'NONE'}:")
    for e in d["reverse"]:
        print(f"  {str(e.get('relation')):<18} {e['from']:<38} {e.get('description')}")


def _render_list(rows) -> None:
    for r in sorted(rows, key=lambda r: r["module"]):
        kids = f"  [children: {r['children']}]" if r["children"] else ""
        print(f"{r['module']:<36} {str(r['status'] or ''):<9} {r['description']}{kids}")
    print(f"\n{len(rows)} modules")
