"""Pipeline verbs. `context` answers "what should this role read before planning this task";
`discover` answers "which modules will this change touch, and which docs follow along".
Both are deterministic (keywords, code pointers, code_map, paths) — agents add judgment."""
import errno
import functools
import os
import re
import sys
from pathlib import Path

from segmently_modules.changes import changed_files, map_files, missing_files
from segmently_modules.config import enabled_roles
from segmently_modules.match import match_modules, near_lines, near_misses
from segmently_modules.output import EXIT_OK, UsageError, emit
from segmently_modules.registry import as_dict
from segmently_modules.query import show_target
from segmently_modules.semantic import NO_CARDS_NOTE, TOP_ZERO, add_match_flag, ranked, resolve, skipped
from segmently_modules.workspace import Workspace

_PATHLIKE = re.compile(r"(?<![\w/.-])((?:\.{0,2}/)?[\w.-]+(?:/[\w.-]+)+)")
UPDATE_ROLES = ("developer", "qa")  # a modified module's developer + qa docs follow the code


def read_input(source: str) -> bytes:
    """The bytes of the file `source`, or of stdin for `-` — never decoded by the locale (a text
    stream a caller swapped in for stdin is encoded back as UTF-8, a lone surrogate included).
    OSError when it cannot be read (stdin closed at start: EBADF)."""
    if source != "-":
        return Path(source).read_bytes()
    stream = sys.stdin
    if stream is None:  # fd 0 was closed at start
        raise OSError(errno.EBADF, os.strerror(errno.EBADF))
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        return buffer.read()
    return stream.read().encode("utf-8", "surrogatepass")


def task_text(args) -> str:
    """The task text: `--task`, or `--task-file FILE|-` read as bytes and decoded as strict
    UTF-8 whatever the locale (`cannot read <path>: <reason>`, `<stdin>` for `-`). A FILE's
    newlines are translated as a text-mode read does (CRLF and a lone CR become LF);
    stdin's are not."""
    if args.task_file:
        source = str(args.task_file)
        name = "<stdin>" if source == "-" else source
        try:
            text = read_input(source).decode("utf-8")
        except OSError as e:
            raise UsageError(f"cannot read {name}: {e.strerror or e}") from None
        except UnicodeDecodeError:
            raise UsageError(f"cannot read {name}: not valid UTF-8") from None
        if source != "-":  # universal newlines, as `read_text` gave them before
            text = text.replace("\r\n", "\n").replace("\r", "\n")
    else:
        text = args.task or ""
    if not text.strip():
        raise UsageError("give the task: --task TEXT or --task-file FILE ('-' = stdin)")
    return text


def _rows(ws, text: str, top: int | None) -> list[dict]:
    cfg = ws.config["match"]
    return match_modules(ws.registry.modules, text, cfg, cfg["top"] if top is None else top,
                         cfg["min_score"])


def _mode_rows(ws, text: str, mode: str, notes: list[str], top: int | None):
    """(rows, notes) of a `semantic` / `hybrid` run: the agent is asked once (P8.1 S3); rows None
    when the agent part was skipped (the keyword run then stands as it is)."""
    if skipped(notes):  # hybrid without its agent part: the plain lexical run, plus the note
        return None, notes
    cfg = ws.config["match"]
    return ranked(ws, text, mode, notes, cfg["top"] if top is None else top, cfg["min_score"])


def build_context(ws, text: str, role: str | None, all_roles: bool, top: int | None,
                  rows: list[dict] | None = None) -> dict:
    """`rows`: the rows of a non-lexical mode (None = keyword routing)."""
    modules, read, seen = [], [], set()
    for row in (_rows(ws, text, top) if rows is None else rows):
        _, shown = show_target(ws, row["module"], role, all_roles)
        modules.append({**row, "read": shown["read"], "code": shown["code"],
                        "code_globs": shown["code_globs"]})
        for r in shown["read"]:
            if r["path"] not in seen:
                seen.add(r["path"])
                read.append({"module": row["module"], **r})
    cfg = ws.config["match"]
    near = near_misses(ws.registry.modules, text, cfg, cfg["top"] if top is None else top,
                       cfg["min_score"]) if rows is None else []
    return {"task": text, "role": role, "all_roles": all_roles, "modules": modules, "read": read,
            "near_misses": near}


def _mentioned_paths(ws, text: str) -> list[str]:
    """Path-like tokens in free text, made safe before they ever reach a filesystem check:
    a relative mention that escapes the repo (`..`) is dropped; an absolute mention is
    rewritten to a repo-relative posix path when it resolves inside `ws.root`, and dropped
    otherwise — no absolute path survives to be joined onto `ws.root` downstream."""
    paths = set()
    for m in _PATHLIKE.finditer(text):
        raw = Path(m.group(1))
        if raw.is_absolute():
            try:
                rel = raw.resolve().relative_to(ws.root)
            except ValueError:
                continue  # outside the repo — dropped, like a ".." escape
            paths.add(rel.as_posix())
        else:
            posix = Path(os.path.normpath(raw)).as_posix()
            if not posix.startswith(".."):
                paths.add(posix)
    return sorted(paths)


def split_children(ws, module: str) -> list[dict]:
    """The children of a split module, registry order: {module "p/c", description (its own, ''
    when it has none), doc (its universal doc path, '' when unset)}; [] for an unsplit one."""
    entry = as_dict(ws.registry.modules.get(module))
    out = []
    for child, sub in as_dict(entry.get("submodules")).items():
        sub = as_dict(sub)
        desc, doc = sub.get("description"), as_dict(sub.get("context_files")).get("universal")
        out.append({"module": f"{module}/{child}",
                    "description": desc if isinstance(desc, str) else "",
                    "doc": doc if isinstance(doc, str) else ""})
    return out


def build_discover(ws, text: str | None, files: list[str], top: int | None,
                   missing: list[str] = (), rows: list[dict] | None = None) -> dict:
    """`text` None = no task: the change alone decides (no keyword scoring, `score` null).
    `missing` = the listed changed files that are not on disk. `rows`: the rows of a
    non-lexical mode (None = keyword routing)."""
    by_module: dict[str, dict] = {}

    def slot(module: str) -> dict:
        return by_module.setdefault(module, {"module": module,
                                             "score": 0 if text is not None else None,
                                             "keywords": [], "sources": [],
                                             "touched_files": []})

    task_rows = (_rows(ws, text, top) if rows is None else rows) if text is not None else []
    for row in task_rows:
        s = slot(row["module"])
        s.update(score=row.get("score"), keywords=row.get("keywords", []))
        for src in row.get("sources", ["keyword"]):
            s["sources"].append(src)
        if "confidence" in row:
            s["confidence"] = row["confidence"]
    mentioned = _mentioned_paths(ws, text) if text is not None else []
    touched = map_files(ws, files)
    in_text = map_files(ws, mentioned)
    for source, mapping in (("diff", touched), ("path", in_text)):
        for module, hit in mapping["modules"].items():
            s = slot(module)
            if source not in s["sources"]:
                s["sources"].append(source)
            s["touched_files"] += [f for f in hit["files"] if f not in s["touched_files"]]
    targets_of: dict[str, list] = {f: [] for f in files}
    for module, hit in touched["modules"].items():
        for f in hit["files"]:
            targets_of[f].append(module)
    roles = [r for r in UPDATE_ROLES if r in enabled_roles(ws.config)]
    out = []
    rank = {r["module"]: i for i, r in enumerate(task_rows)} if rows is not None else None
    for module in sorted(by_module, key=(lambda m: (-(by_module[m]["score"] or 0), m)) if
                         rank is None else (lambda m: (rank.get(m, len(rank)), m))):
        s = by_module[module]
        s["usage"] = "modify" if s["touched_files"] else "reference"
        docs = []
        for role in (roles if s["usage"] == "modify" else [None]):
            _, shown = show_target(ws, module, role, False)
            docs += [r["path"] for r in shown["read"] if r["path"] not in docs]
        s["docs_to_read"] = docs
        s["docs_to_update"] = docs if s["usage"] == "modify" else []
        children = split_children(ws, module) if s["usage"] == "modify" else []
        if children:  # the skill picks the child the change is in
            s["children"] = children
        out.append(s)
    outside = sorted(set(touched["unmapped"]) | {f for f in in_text["unmapped"]
                                                  if (ws.root / f).exists()})
    usage = [m["usage"] for m in out]
    return {"task": text, "modules": out,
            "files": [{"path": f, "modules": sorted(targets_of[f])} for f in sorted(targets_of)],
            "files_outside_modules": outside, "missing_files": list(missing),
            "summary": {"total_modules": len(out), "by_usage": {
                "modify": usage.count("modify"), "reference": usage.count("reference")}}}


def register(sub, common) -> None:
    c = sub.add_parser("context", parents=[common],
                       help="files a role should read before planning a task")
    _task_args(c)
    c.add_argument("--role")
    c.add_argument("--all-roles", action="store_true")
    c.add_argument("--top", type=int)
    add_match_flag(c)
    c.set_defaults(func=run_context)
    d = sub.add_parser("discover", parents=[common],
                       help="modules a change touches (modify/reference) and their docs",
                       description="Modules a change touches (modify/reference) and the docs "
                                   "to read and update. Give --task and/or --from-diff / "
                                   "--files; without a task there is no keyword scoring.")
    _task_args(d, required=False)
    src = d.add_mutually_exclusive_group()
    src.add_argument("--from-diff", metavar="A..B")
    src.add_argument("--files", nargs="+", action="extend", metavar="PATH")
    d.add_argument("--top", type=int)
    add_match_flag(d)
    d.set_defaults(func=run_discover)


def _task_args(p, required: bool = True) -> None:
    g = p.add_mutually_exclusive_group(required=required)
    g.add_argument("--task")
    g.add_argument("--task-file", type=Path)


def run_context(args) -> int:
    if args.top is not None and args.top < 0:
        raise UsageError("--top must be >= 0")
    ws = Workspace.from_args(args)
    roles = enabled_roles(ws.config)
    if args.role and args.role not in roles:
        raise UsageError(f"unknown role '{args.role}' (roles: {', '.join(roles)})")
    mode, notes = resolve(ws, args.match)
    text = task_text(args)
    if mode == "lexical":  # a lexical run adds nothing: byte-identical to before P8.1
        data = build_context(ws, text, args.role, args.all_roles, args.top)
    else:
        rows, notes = _mode_rows(ws, text, mode, notes, args.top)
        data = {**build_context(ws, text, args.role, args.all_roles, args.top, rows),
                "mode": mode, "notes": notes}
    top = ws.config["match"]["top"] if args.top is None else args.top
    emit("context", data, args.json, functools.partial(_render_context, top=top))
    return EXIT_OK


def run_discover(args) -> int:
    if args.top is not None and args.top < 0:
        raise UsageError("--top must be >= 0")
    has_task = args.task is not None or args.task_file is not None
    if not has_task and not (args.from_diff or args.files):
        raise UsageError("give the task (--task TEXT or --task-file FILE), the change "
                         "(--from-diff A..B or --files PATH …), or both")
    ws = Workspace.from_args(args)
    mode, notes = resolve(ws, args.match) if has_task else ("lexical", [])
    files = changed_files(ws.root, diff_range=args.from_diff, files=args.files) \
        if (args.from_diff or args.files) else []
    text = task_text(args) if has_task else None
    rows = None
    if mode != "lexical" and has_task:
        rows, notes = _mode_rows(ws, text, mode, notes, args.top)
    data = build_discover(ws, text, files, args.top,
                          missing_files(ws.root, files) if args.files else [], rows)
    if mode != "lexical":
        data = {**data, "mode": mode, "notes": notes}
    # --from-diff REF (no range) compares the working tree with REF: the text says so
    ref = args.from_diff if args.from_diff and ".." not in args.from_diff else None
    emit("discover", data, args.json, functools.partial(_render_discover, ref=ref))
    return EXIT_OK


def _render_context(d, top: int | None = None) -> None:
    if not d["modules"] and d.get("mode") == "semantic":  # only the agent chose (P8.1)
        if top == 0:  # the agent was not asked
            print(TOP_ZERO)
        elif NO_CARDS_NOTE not in d["notes"]:
            print("no module matched (the agent chose no module; try rephrasing the task)")
    elif not d["modules"]:
        print("no module matched (try domain terms, or: segmently-modules list)")
        for line in near_lines(d["near_misses"]):
            print(line)
    for m in d["modules"]:  # why each module matched: its keywords found in the task
        why = f"(score {m['score']})" if "score" in m else f"(confidence {m['confidence']:.2f})"
        detail = ', '.join(m.get('keywords', [])) or m.get('reason', '')
        print(f"{m['module']:<28} {'matched':<30} {detail} {why}")
    for r in d["read"]:
        mark = "" if r["exists"] else "  (MISSING ON DISK)"
        print(f"{r['module']:<28} {r['label']:<30} {r['path']}{mark}")
    for m in d["modules"]:
        for c in m["code"] + m["code_globs"]:
            print(f"{m['module']:<28} {'code':<30} {c}")
    for n in d.get("notes", []):
        print(n)


def _render_discover(d, ref: str | None = None) -> None:
    """`ref`: the single ref of `--from-diff REF` — its `diff` source is labelled `diff
    (working tree vs REF)`."""
    for m in d["modules"]:
        score = f"score {m['score']:<3} " if m["score"] is not None else \
            (f"confidence {m['confidence']:.2f} " if "confidence" in m else "")
        sources = [f"diff (working tree vs {ref})" if s == "diff" and ref else s
                   for s in m["sources"]]
        print(f"{m['usage']:<9} {m['module']:<30} {score}via {', '.join(sources)}")
        for doc in m["docs_to_update"]:
            print(f"          update {doc}")
        for c in m.get("children", []):
            print(f"          child  {c['module']}  {c['description']}  ({c['doc']})")
    for f in d["files"]:
        print(f"file      {f['path']} -> {', '.join(f['modules']) or '(no module)'}")
    for f in d["files_outside_modules"]:
        print(f"outside   {f}")
    for f in d["missing_files"]:
        print(f"not on disk: {f} (typo? a deleted file still maps)")
    for n in d.get("notes", []):
        print(n)
