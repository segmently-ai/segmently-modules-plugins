"""Field-level registry edits, validated by field definitions. Pure functions over the raw
registry document; persistence is the store's job (segmently_modules.store)."""
import difflib
import hashlib
import json
import posixpath
import re

from segmently_modules.fields import FieldDef, value_matches
from segmently_modules.output import UsageError
from segmently_modules.rules import edge_problems, status_problem

OPS = ("set", "append", "remove", "unset")
STRUCTURAL = {"name", "submodules"}  # renames and children go through create/split, not field ops


def entry_for(raw: dict, target: str) -> tuple[dict, str]:
    """The registry entry for `module` or `module/child`, and its scope."""
    parent, _, child = target.partition("/")
    entry = raw["modules"].get(parent)
    if not isinstance(entry, dict):
        raise UsageError(f"unknown module '{parent}'")
    if not child:
        return entry, "module"
    sub = (entry.get("submodules") or {}).get(child) if isinstance(entry.get("submodules"),
                                                                    dict) else None
    if not isinstance(sub, dict):
        raise UsageError(f"'{child}' is not a submodule of '{parent}'")
    return sub, "submodule"


def entry_sha256(raw: dict, target: str) -> str:
    """Content hash of one entry (proposals use it as their optimistic-concurrency base)."""
    entry, _ = entry_for(raw, target)
    return hashlib.sha256(json.dumps(entry, ensure_ascii=False).encode("utf-8")).hexdigest()


def _field_def(fields: dict[str, FieldDef], field: str, scope: str) -> FieldDef:
    if field in STRUCTURAL:
        raise UsageError(f"'{field}' is structural and cannot be edited as a field")
    fdef = fields.get(field)
    if fdef is None:
        raise UsageError(f"unknown field '{field}' (declare [fields.{field}] in config or a pack)")
    if fdef.deprecated:
        raise UsageError(f"field '{field}' is deprecated: {fdef.deprecated}")
    if scope not in fdef.scope:
        raise UsageError(f"field '{field}' is not allowed on {scope} entries "
                         f"(scope: {', '.join(fdef.scope)})")
    return fdef


def _check(fdef: FieldDef, value) -> None:
    if not value_matches(fdef, value):
        raise UsageError(f"value {value!r} does not match field '{fdef.name}' type "
                         f"{' | '.join(fdef.type)}")


def _check_rules(field: str, op: str, value, raw: dict, vocab: dict) -> None:
    """Refuse a value lint would report as an ERROR for this field (shared rules: segmently_modules.rules).
    `append` checks the appended item, `set` every item; `remove`/`unset` never refuse."""
    problems = []
    if field == "status":
        problem = status_problem(value, vocab["statuses"])
        problems = [problem] if problem else []
    elif field == "related_modules":
        edges = ([("appended edge", value)] if op == "append" else
                 [(f"related_modules[{i}]", e) for i, e in enumerate(value)])
        problems = [(code, f"{where}: {message}") for where, edge in edges
                    if isinstance(edge, dict)
                    for code, message in edge_problems(edge, raw["modules"], vocab["relations"])]
    if problems:
        raise UsageError(f"field '{field}': "
                         + "; ".join(f"{message} (lint {code})" for code, message in problems))


def apply_field_op(raw: dict, fields: dict[str, FieldDef], op: str, target: str,
                   field: str, value=None, *, vocab: dict) -> bool:
    """Apply one operation in place. Returns True when the document changed.
    set: replace the value · append: add one item to an array (no-op if present) ·
    remove: drop every equal item from an array · unset: delete the field.
    `vocab` = the `[registry]` config (statuses, relations) the value rules check."""
    if op not in OPS:
        raise UsageError(f"unknown op '{op}' (ops: {', '.join(OPS)})")
    entry, scope = entry_for(raw, target)
    if field.startswith(DOC_KEY_PREFIX):
        return _doc_key_op(entry, target, op, field[len(DOC_KEY_PREFIX):], value)
    fdef = _field_def(fields, field, scope)
    if op == "set":
        _check(fdef, value)
        _check_rules(field, op, value, raw, vocab)
        if entry.get(field, object()) == value:
            return False
        entry[field] = value
        return True
    if op == "unset":
        if scope in fdef.required:
            raise UsageError(f"'{field}' is required on {scope} entries and cannot be unset")
        if field not in entry:
            return False
        del entry[field]
        return True
    current = entry.get(field, [])
    if not isinstance(current, list):
        raise UsageError(f"field '{field}' on '{target}' is not an array; use set")
    if op == "append":
        _check_rules(field, op, value, raw, vocab)
        if value in current:
            return False
        new = current + [value]
    else:  # remove
        new = [item for item in current if item != value]
        if new == current:
            return False
    _check(fdef, new)
    entry[field] = new
    return True


DOC_KEY_PREFIX = "context_files."


def check_doc_key_paths(field: str, op: str, value, exists) -> None:
    """Refuse a `context_files.<key>` write whose new path is missing on disk (lint MS004);
    `exists` = the workspace's path test. Writers and proposals both check it."""
    for path in doc_key_paths(field, op, value):
        if isinstance(path, str) and path.strip() and not exists(path):
            raise UsageError(f"{field}: {path} is missing on disk (lint MS004) — write the doc "
                             f"first")


def _outside_repo(path: str) -> bool:
    p = posixpath.normpath(path.replace("\\", "/"))
    return p.startswith("/") or bool(re.match(r"[A-Za-z]:", p)) or p == ".." or \
        p.startswith("../")


def doc_key_paths(field: str, op: str, value) -> list[str]:
    """The doc paths a `context_files.<key>` write adds (`set`, `append`) — each must exist on
    disk, as lint MS004 requires; none for any other field or op."""
    if not field.startswith(DOC_KEY_PREFIX) or op not in ("set", "append"):
        return []
    return [value] if isinstance(value, str) else list(value) if isinstance(value, list) else []


def _doc_key_op(entry: dict, target: str, op: str, key: str, value) -> bool:
    """One `context_files.<key>` write: `universal` is one path (`set` / `unset`); any other key
    but `roles` (`roles add` / `roles skip` write those) is one path or a list of paths — `set`
    replaces it, `append` adds a path (a single path becomes a list), `remove` drops it (the key
    goes when no path is left), `unset` deletes the key. A key that holds a map is edited with
    `registry set TARGET context_files '<object>'`."""
    field = DOC_KEY_PREFIX + key
    if not key or "." in key:
        raise UsageError(f"'{field}' names no key: write context_files.<key>, e.g. "
                         f"context_files.supplementary")
    if key == "roles":
        raise UsageError("role docs are written by segmently-modules roles add ROLE TARGET (and marked not "
                         "needed by segmently-modules roles skip), not by registry")
    cf = entry.get("context_files", {})
    if not isinstance(cf, dict):
        raise UsageError(f"context_files of '{target}' is not an object — fix it first "
                         f"(segmently-modules lint)")
    current = cf.get(key)
    if isinstance(current, dict):
        raise UsageError(f"{field} of '{target}' is a map; edit it with segmently-modules registry set "
                         f"{target} context_files '<object>'")
    if key == "universal" and op in ("append", "remove"):
        raise UsageError(f"{field} is one path; use set")

    def path(v) -> bool:
        return isinstance(v, str) and bool(v.strip())

    if op in ("set", "append"):  # a path that is already there can always be removed
        for v in value if isinstance(value, list) else [value]:
            if path(v) and _outside_repo(v):
                raise UsageError(f"{field}: {v} is outside the repository — a doc path is "
                                 f"relative to the root")

    if op == "unset":
        if key not in cf:
            return False
        del cf[key]
        return True
    if op == "set":
        ok = path(value) or (key != "universal" and isinstance(value, list) and value
                             and all(path(v) for v in value) and len(set(value)) == len(value))
        if not ok:
            raise UsageError(f"{field} takes a doc path" + ("" if key == "universal" else
                             " or a list of distinct doc paths") + f", got {value!r}")
        if current == value:
            return False
        cf[key] = value
        entry["context_files"] = cf
        return True
    if not path(value):
        raise UsageError(f"{op} {field} takes one doc path, got {value!r}")
    items = [] if current is None else [current] if isinstance(current, str) else list(current)
    if op == "append":
        if value in items:
            return False
        cf[key] = items + [value]
        entry["context_files"] = cf
        return True
    new = [i for i in items if i != value]
    if new == items:
        return False
    if new:
        cf[key] = new
    else:
        del cf[key]
    return True


def unified_diff(before: str, after: str, label: str) -> str:
    return "".join(difflib.unified_diff(before.splitlines(keepends=True),
                                        after.splitlines(keepends=True),
                                        fromfile=f"a/{label}", tofile=f"b/{label}"))
