"""Proposals queue. During a pipeline run agents never edit the registry or module docs;
they queue proposals (`<proposals_dir>/<run_id>-<agent>.json`, schema `segmently-modules.proposal/1`).
One step applies them under the registry lock:

- Every item is revalidated at apply time (not just at propose time): the module must still
  exist, and a doc item's path must still resolve inside its module's own directory, never a
  submodule's directory, the module's registry entry file, or a frozen `*.legacy.md` snapshot.
- The WHOLE apply shares one apply-start snapshot: `set` / `unset` / `doc_write` carry
  `base_sha256` (the entry or file as the agent saw it at propose time), compared against the
  registry/file state as it was when this apply started — not against another file's edits made
  earlier in the same apply. A mismatch rejects that one item; others still apply.
- Within one apply, two files touching the same key (field or doc) conflict: the first
  (file-name order) applies, a later CHECKED item on the same key is rejected naming the file
  that touched it first. Items inside ONE file never conflict with each other.
- `append` / `remove` / `doc_append` merge safely (no base check, never rejected for conflict),
  so a checked `set` that lands after another file's merge on the same key is rejected — it
  would otherwise silently drop the merge.
- If an item's op would not change anything against the current state, it is reported `noop`
  before either check runs — a re-run after a crash between commit and archive is idempotent.
- Every queue file involved is locked for the whole apply (registry lock, then queue-file locks
  in sorted name order) and re-read under its lock; a file that vanished since listing (applied
  or rejected concurrently) is simply skipped. Processed files move to `<proposals_dir>/done/`
  with per-item results.
"""
import copy
import json
import os
import re
from contextlib import ExitStack
from pathlib import Path

from segmently_modules.output import UsageError
from segmently_modules.store import atomic_write, file_lock, file_sha256, open_store, utc_now
from segmently_modules.writers import (OPS as FIELD_OPS, apply_field_op, check_doc_key_paths, entry_for,
                            entry_sha256)

SCHEMA = "segmently-modules.proposal/1"
DOC_OPS = ("doc_write", "doc_append")
CHECKED_OPS = {"set", "unset", "doc_write"}
SAFE_ID = re.compile(r"[A-Za-z0-9._-]+")  # run ids, agents, hook ids: always fullmatch()


def check_safe_id(label: str, value: str) -> None:
    """Refuse an id that is not a plain file-name token (it becomes part of a queue file name)."""
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise UsageError(f"{label} {value!r} may only contain letters, digits, '.', '_', '-'")


def proposals_dir(ws) -> Path:
    return ws.root / ws.config["paths"]["proposals_dir"]


def module_dir(ws, module: str) -> Path:
    parent, _, child = module.partition("/")
    base = ws.root / ws.config["paths"]["modules_dir"] / parent
    return base / "submodules" / child if child else base


def check_doc_path(ws, module: str, doc: str) -> Path:
    """A doc proposal may only touch one markdown file inside its own module directory: never
    the module directory itself, a submodule's directory (each child is its own target), the
    module's registry entry file, or a frozen `*.legacy.md` snapshot (case-insensitive)."""
    _, _, child = module.partition("/")
    modules_root = (ws.root / ws.config["paths"]["modules_dir"]).resolve()
    home = module_dir(ws, module).resolve()
    path = (ws.root / doc).resolve()

    def outside() -> UsageError:
        return UsageError(f"doc '{doc}' is outside module '{module}' "
                          f"({home.relative_to(ws.root)})")

    if modules_root not in home.parents:  # e.g. module ".." resolves home above modules_root
        raise outside()
    if home != path and home not in path.parents:
        raise outside()
    if not child:
        rel = path.relative_to(home)
        if rel.parts and rel.parts[0].casefold() == "submodules":
            raise outside()  # a parent never writes into a child's own directory (case-folded:
                             # `SUBMODULES` bypasses this on a case-insensitive filesystem too)
    if path == home:
        raise UsageError(f"doc '{doc}' must be a file inside module '{module}'")
    if path.name.lower().endswith(".legacy.md"):
        raise UsageError(f"doc '{doc}' is a frozen legacy snapshot and is never edited")
    if path.name == ws.config["paths"]["module_entry"]:
        raise UsageError(f"doc '{doc}' is the module's registry entry — use field ops")
    if path.suffix.lower() != ".md":
        raise UsageError(f"doc '{doc}' is not a markdown doc (.md)")
    return path


def join_blocks(current: str, text: str) -> str:
    """doc_append: `text` after the existing content, separated by exactly one blank line
    (trailing blank lines of the doc and leading blank lines of the block collapse)."""
    lines = current.split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    block = text.split("\n")
    while block and not block[0].strip():
        block.pop(0)
    body = "\n".join(block)
    return "\n".join(lines) + "\n\n" + body if lines else body


def make_item(ws, op: str, module: str, reason: str, field: str | None = None,
              doc: str | None = None, value=None) -> dict:
    """Validate one proposal item against the CURRENT state and stamp its base hash."""
    if not reason:
        raise UsageError("a proposal needs --reason")
    raw = ws.registry.raw
    entry_for(raw, module)  # unknown module / child -> UsageError
    if op in FIELD_OPS:
        if not field:
            raise UsageError(f"{op} proposals need --field")
        apply_field_op(copy.deepcopy(raw), ws.fields, op, module, field, value,  # validates
                       vocab=ws.config["registry"])
        check_doc_key_paths(field, op, value, ws.exists)  # context_files.<key>: on disk
        return {"op": op, "module": module, "field": field, "value": value, "reason": reason,
                "base_sha256": entry_sha256(raw, module)}
    if op in DOC_OPS:
        if not doc:
            raise UsageError(f"{op} proposals need --doc")
        if not isinstance(value, str):
            raise UsageError(f"{op} proposals need text (--value or --value-file)")
        path = check_doc_path(ws, module, doc)
        return {"op": op, "module": module, "doc": doc, "value": value, "reason": reason,
                "base_sha256": file_sha256(path)}
    raise UsageError(f"unknown op '{op}' (ops: {', '.join(FIELD_OPS + DOC_OPS)})")


def add_proposal(ws, run_id: str, agent: str, item: dict) -> Path:
    return add_proposals(ws, run_id, agent, [item])


def add_proposals(ws, run_id: str, agent: str, items: list[dict]) -> Path:
    """Queue `items` under `<run_id>-<agent>.json` in ONE locked atomic write: all or nothing."""
    check_safe_id("run id", run_id)
    check_safe_id("agent", agent)
    path = proposals_dir(ws) / f"{run_id}-{agent}.json"
    with file_lock(path):
        doc = (json.loads(path.read_text(encoding="utf-8")) if path.exists() else
               {"schema": SCHEMA, "run_id": run_id, "agent": agent, "created_at": utc_now(),
                "items": []})
        for item in items:
            doc["items"].append({"id": str(len(doc["items"]) + 1), **item})
        atomic_write(path, json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    return path


def _read_proposal(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise UsageError(f"{path}: not a valid proposal file: {e}") from e
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise UsageError(f"{path}: not a {SCHEMA} file")
    return doc


def pending(ws, run_id: str | None = None) -> list[tuple[Path, dict]]:
    """Every queued proposal file (optionally one run's), by name; an unreadable file is exit 2
    `cannot read <path>: <reason>`."""
    d = proposals_dir(ws)
    out = []
    for path in sorted(d.glob("*.json")) if d.is_dir() else []:
        try:
            doc = _read_proposal(path)
        except OSError as e:
            raise UsageError(f"cannot read {ws.rel(path)}: {e.strerror or e}") from None
        if run_id is None or doc.get("run_id") == run_id:
            out.append((path, doc))
    return out


def _apply_item(ws, raw: dict, start_raw: dict, docs: dict, touched: dict, file_name: str,
                item: dict) -> dict:
    """Apply one item to the in-memory registry / pending doc writes; return its result.
    `raw` is mutated for applied field ops; `docs` collects pending doc writes, keyed like
    conflict tracking by the case-folded path (key -> (path, text), the path being the first
    spelling seen), so case-variant spellings of one doc build on each other's edit instead of
    re-reading the original; `touched` records, per key, which queue file names already
    applied a change to it in this apply (conflict tracking)."""
    result = {"id": item.get("id"), "op": item.get("op"), "module": item.get("module")}
    try:
        op, module = item["op"], item["module"]
        entry_for(raw, module)  # unknown module / child -> UsageError, for every op
        if op in FIELD_OPS:
            field, value = item["field"], item.get("value")
            # `context_files.<key>` shares its conflict key with `context_files` itself
            key = ("field", module, field.partition(".")[0])
            vocab = ws.config["registry"]
            check_doc_key_paths(field, op, value, ws.exists)
            if not apply_field_op(copy.deepcopy(raw), ws.fields, op, module, field, value,
                                  vocab=vocab):
                return {**result, "status": "noop"}
            if op in CHECKED_OPS:
                others = touched.get(key, set()) - {file_name}
                if others:
                    return {**result, "status": "rejected",
                            "reason": f"conflicts with {sorted(others)[0]} in this apply"}
                if entry_sha256(start_raw, module) != item.get("base_sha256"):
                    return {**result, "status": "rejected",
                            "reason": f"'{module}' changed since the proposal was made"}
            apply_field_op(raw, ws.fields, op, module, field, value, vocab=vocab)
            touched.setdefault(key, set()).add(file_name)
            return {**result, "status": "applied"}
        path = check_doc_path(ws, module, item["doc"])
        key = ("doc", str(path).casefold())  # conflict tracking and pending writes are
                                             # case-insensitive: two case-variant paths to one
                                             # file conflict and share one pending write
        if key in docs:
            path, current = docs[key]  # keep writing through the first spelling seen
        else:
            current = path.read_text(encoding="utf-8") if path.exists() else None
        if op == "doc_write":
            new = item["value"]
        elif op == "doc_append":
            text = item["value"]
            if current is not None and text.strip() and text.strip() in current:
                return {**result, "status": "noop"}
            new = join_blocks(current or "", text)
        else:
            raise UsageError(f"unknown op '{op}'")
        if not new.endswith("\n"):
            new += "\n"
        if new == current:
            return {**result, "status": "noop"}
        if op == "doc_write":
            others = touched.get(key, set()) - {file_name}
            if others:
                return {**result, "status": "rejected",
                        "reason": f"conflicts with {sorted(others)[0]} in this apply"}
            if file_sha256(path) != item.get("base_sha256"):
                return {**result, "status": "rejected",
                        "reason": f"'{item['doc']}' changed since the proposal was made"}
        docs[key] = (path, new)
        touched.setdefault(key, set()).add(file_name)
        return {**result, "status": "applied"}
    except (UsageError, KeyError, TypeError) as e:
        return {**result, "status": "rejected", "reason": f"invalid item: {e}"}


def apply_proposals(ws, run_id: str | None = None, dry_run: bool = False) -> dict:
    """Apply every pending proposal file (optionally one run), in file-name order, under the
    registry lock plus a lock on every queue file involved (held for the whole apply)."""
    store = open_store(ws)
    report = {"files": [], "summary": {"applied": 0, "noop": 0, "rejected": 0},
              "dry_run": dry_run}
    with store.locked():
        files = pending(ws, run_id)
        if not files:
            return report
        with ExitStack() as stack:
            for path, _ in files:
                stack.enter_context(file_lock(path))
            live = [(path, _read_proposal(path)) for path, _ in files if path.exists()]
            if not live:
                return report
            registry = store.load()
            start_raw = copy.deepcopy(registry.raw)
            raw = copy.deepcopy(registry.raw)
            docs: dict[tuple, tuple[Path, str]] = {}
            touched: dict[tuple, set] = {}
            for path, doc in live:
                results = [_apply_item(ws, raw, start_raw, docs, touched, path.name, item)
                           for item in doc.get("items", [])]
                for r in results:
                    report["summary"][r["status"]] += 1
                report["files"].append({"file": path.name, "run_id": doc.get("run_id"),
                                        "agent": doc.get("agent"), "results": results})
            if dry_run:
                return report
            store.commit(registry, raw)
            for path, text in docs.values():
                atomic_write(path, text)
            results_by_file = {f["file"]: f["results"] for f in report["files"]}
            for path, doc in live:
                _archive(path, doc, results_by_file[path.name])
    return report


def _archive(path: Path, doc: dict, results: list, reason: str | None = None) -> None:
    done = path.parent / "done"
    done.mkdir(exist_ok=True)
    record = {**doc, "processed_at": utc_now(), "results": results}
    if reason:
        record["rejected_reason"] = reason
    atomic_write(done / path.name, json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    os.unlink(path)


def reject_run(ws, run_id: str, reason: str) -> list[str]:
    if not reason:
        raise UsageError("rejecting proposals needs --reason")
    store = open_store(ws)
    with store.locked():
        files = pending(ws, run_id)
        if not files:
            raise UsageError(f"no pending proposals for run '{run_id}'")
        rejected = []
        with ExitStack() as stack:
            for path, _ in files:
                stack.enter_context(file_lock(path))
            for path, _ in files:
                if not path.exists():
                    continue
                doc = _read_proposal(path)
                results = [{"id": i.get("id"), "op": i.get("op"), "module": i.get("module"),
                            "status": "rejected", "reason": reason} for i in doc.get("items", [])]
                _archive(path, doc, results, reason)
                rejected.append(path.name)
    return rejected
