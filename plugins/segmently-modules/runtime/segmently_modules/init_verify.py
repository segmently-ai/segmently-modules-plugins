"""`init eval-tasks` and `init verify` — phase 6 (D3), over the registry as `init finish` will
write it (`segmently_modules.init_overlay`), nothing moved.

  <config_dir>/init/routing-tasks.json  the routing tasks: `init eval-tasks --executor CMD` runs
                                        CMD once with the routing prompt on stdin and
                                        SEGMENTLY_MODULES_INIT_TASKS = this file's absolute path (the
                                        executor writes it), or someone writes it by hand from
                                        `segmently-modules eval routing --prompt`
  <config_dir>/init/routing-tasks.rejected.json  a tasks file `init eval-tasks` refused (not
                                        JSON, a module left out or unknown) or one an interrupted
                                        run left behind: moved aside, so the next step is
                                        `init eval-tasks` again (the phase stays `running`)
  <config_dir>/init/verify.json         {lint: {summary, findings}, invented, routing,
                                        keywords, staging_sha256, passed}

Verify runs four checks: lint (clean = no error and no warning; info is fine), the invented-
component check over the new modules' staging docs, the keywords of the new modules (more
distinct words than `[create] max_keywords` or a generic word fails — `keyword_findings`), and
the routing eval when the tasks file exists (`routing: null` — "not measured" — otherwise; it
also reports the first-place hit rate, the modules a task matches on average and each module's
unused keywords, which never fail it). The invented-component check: every
backticked repository path (MS040's rule: holds a `/`, no space, no `*`, no URL, no `<`, `{`,
`[` or leading `@`; `:line` and `#L…` cut — but a token that names an existing path as a whole
is that path, a space or a `#` in it included) exists inside the root — the staging docs count at
their final paths; an absolute path or one that climbs out with `..` never does —, and in a
table whose header has a `Symbol` or `Name` column AND a `Path` (or `File`) column, a cell of
the first holding one backticked identifier names a symbol that occurs, as a whole identifier,
in the file of the row's path cell (a table without both columns is not checked; a file that
cannot be read as text — a directory, unreadable, binary — is "no file to check"; a doc `init`
has planned but not written yet is not read); fenced code blocks and HTML comments are skipped.
`init done` runs the same check over one module's docs (`segmently_modules.init_work`). `staging_sha256`
pins what was verified (every file's path and bytes, every symlink's path and target text):
`init finish` refuses a staging tree that changed. Verify is refused while the last `init
eval-tasks` run was refused (the phase `running`; `--force` measures a tasks file written by
hand anyway) and for a symlinked staging dir of a new module. After `init finish` both actions
are refused."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from dataclasses import asdict
from pathlib import Path

from segmently_modules.eval_cmd import PER_MODULE, load_tasks, routing, routing_prompt
from segmently_modules.changes import target_names
from segmently_modules.init_overlay import overlay_workspace
from segmently_modules.init_run import tail
from segmently_modules.lint import component_path, lint_registry, severity_counts
from segmently_modules.output import UsageError
from segmently_modules.preflight import SNIFF
from segmently_modules.store import serialize
from segmently_modules.words import distinct_words, generic_keywords, normalizing

REJECTED = "routing-tasks.rejected.json"
REFUSED_TASKS = ("the routing tasks were refused — run segmently-modules init eval-tasks (or write the file "
                 "and use --force)")  # `init verify` and `init finish` while eval-tasks is running
_BACKTICK = re.compile(r"`([^`\n]+)`")
_FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
_SYMBOL = re.compile(r"`([A-Za-z_$][\w$]*)`")
_SEPARATOR = re.compile(r"^\s*\|?(\s*:?-{3,}:?\s*\|)+\s*:?-*:?\s*$")
TASKS = "routing-tasks.json"


def tree_sha(path) -> str:
    """sha256 over the tree below `path`, sorted by path: a file's relative path and bytes, a
    symlink's relative path and target text (never followed — a link added after verify
    changes it too)."""
    h = hashlib.sha256()
    found = []
    for top, dirs, files in os.walk(path) if path.is_dir() else []:  # never into a linked dir
        found += [Path(top) / name for name in dirs + files]
    for p in sorted(found):
        rel = p.relative_to(path).as_posix().encode("utf-8", "surrogateescape")
        if p.is_symlink():
            h.update(rel + b"\0symlink\0" + os.fsencode(os.readlink(p)) + b"\0")
        elif p.is_file():
            h.update(rel + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def inside(target: str) -> bool:
    """A root-relative path that stays inside the root (not absolute, no `..` out of it)."""
    norm = os.path.normpath(target)
    return not (os.path.isabs(target) or norm == ".." or norm.startswith("../"))


def cells(line: str) -> list[str]:
    body = line.strip()
    body = body[1:] if body.startswith("|") else body
    body = body[:-1] if body.endswith("|") else body
    return [c.strip() for c in body.split("|")]


def source_text(path) -> str | None:
    """The text of the file a component row names, or None when there is none to read: not a
    regular file (a directory; a FIFO is never opened), unreadable, or binary (a NUL in its
    first `SNIFF` bytes)."""
    try:
        if not stat.S_ISREG(os.stat(path).st_mode):
            return None
        data = Path(path).read_bytes()
    except OSError:
        return None
    return None if b"\0" in data[:SNIFF] else data.decode("utf-8", errors="replace")


def invented(ws, docs: dict) -> list[dict]:
    """{doc, line, kind: path | symbol | no-file, token} for every component a doc names that
    is not there; `docs` = {final path: the file to read, or its text when the caller has read
    it already (`init done`)}."""
    out = []

    def found(target: str) -> bool:  # a path with a space or a `#` is taken whole when it exists
        return inside(target) and ws.exists(target)

    for rel, path in sorted(docs.items()):
        text = path if isinstance(path, str) else path.read_text(encoding="utf-8",
                                                                  errors="replace")
        lines = text.splitlines()
        fence, comment, header = None, False, None
        for n, raw in enumerate(lines, 1):
            m = _FENCE.match(raw)
            if fence:
                if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                    fence = None
                continue
            if m:
                fence = m.group(1)
                continue
            text, rest = "", raw
            while rest:  # the parts of the line outside HTML comments
                if comment:
                    end = rest.find("-->")
                    if end < 0:
                        rest = ""
                    else:
                        comment, rest = False, rest[end + 3:]
                else:
                    start = rest.find("<!--")
                    if start < 0:
                        text, rest = text + rest, ""
                    else:
                        text, rest, comment = text + rest[:start], rest[start + 4:], True
            for token in _BACKTICK.findall(text):
                target = component_path(token, found)
                if target and not (inside(target) and ws.exists(target)):
                    out.append({"doc": rel, "line": n, "kind": "path", "token": target})
            if not text.lstrip().startswith("|"):
                header = None
                continue
            if _SEPARATOR.match(text):
                continue
            if n < len(lines) and _SEPARATOR.match(lines[n]):  # the header of a table
                names = [c.lower() for c in cells(text)]
                header = (next((i for i, c in enumerate(names) if c in ("symbol", "name")), None),
                          next((i for i, c in enumerate(names) if c in ("path", "file")), None))
                continue
            if header is None or header[0] is None or header[1] is None:
                continue  # not a components table: a Symbol / Name column AND a Path column
            row = cells(text)
            symbol = _SYMBOL.fullmatch(row[header[0]]) if header[0] < len(row) else None
            if not symbol:
                continue
            cell = row[header[1]] if header[1] < len(row) else ""
            target = next((p for t in _BACKTICK.findall(cell) if (p := component_path(t, found))),
                          None)
            if target and not inside(target):
                target = None  # outside the root: no file of the repository
            # a planned doc not written yet has no text to find the symbol in: the row is skipped
            # (only at init done — by init verify every planned doc is written)
            if target and ws.exists(target) and not os.path.lexists(ws.disk(target)):
                continue
            source = source_text(ws.disk(target)) if target and ws.exists(target) else None
            if target and ws.exists(target) and source is None:
                target = None  # a directory, unreadable or binary: no file to check
            if target is None:
                out.append({"doc": rel, "line": n, "kind": "no-file", "token": symbol.group(1)})
            elif source is not None:
                if not re.search(rf"(?<![\w$]){re.escape(symbol.group(1))}(?![\w$])", source):
                    out.append({"doc": rel, "line": n, "kind": "symbol",
                                "token": symbol.group(1)})
    return sorted(out, key=lambda f: (f["doc"], f["line"], f["kind"], f["token"]))


def keyword_findings(ws, modules: list[str]) -> list[dict]:
    """{module, words, max_keywords, generic} for every new module of `modules` whose
    keywords hold more distinct words than `[create] max_keywords` (forms of one word once) or
    a generic word (`words.generic_keywords`) — what MS020 / MS023 only report for a registry
    already in use fails a module `init` wrote (FoodMate init, 2026-10-14)."""
    cfg, out = ws.config, []
    most, normalize = cfg["create"]["max_keywords"], normalizing(cfg["match"])
    for name in modules:
        entry = ws.registry.modules.get(name)
        kws = entry.get("keywords") if isinstance(entry, dict) else None
        kws = [k for k in kws if isinstance(k, str)] if isinstance(kws, list) else []
        words, generic = distinct_words(kws, normalize), generic_keywords(cfg, name, kws)
        if words > most or generic:
            out.append({"module": name, "words": words, "max_keywords": most,
                        "generic": generic})
    return out


class Verify:
    def __init__(self, work):
        self.work, self.flow = work, work.flow
        self.tasks_path = self.flow.work / TASKS
        self.verify_path = self.flow.work / "verify.json"

    def require_reconcile(self) -> dict:
        state = self.work.require_fanout(self.flow.load_state())
        if state["phases"]["finish"]["status"] == "done":
            raise UsageError("already finished — see segmently-modules init status")
        if state["phases"]["reconcile"]["status"] != "done" or \
                not (self.work.staging / "registry.json").is_file():
            raise UsageError("reconcile has not run — run segmently-modules init reconcile first")
        return state

    def overlay(self, state: dict):
        return overlay_workspace(self.flow, self.work, state)

    def reject(self) -> None:
        """Move a refused (or half-written) tasks file aside: the next step is eval-tasks."""
        if os.path.lexists(self.tasks_path):
            rejected = self.flow.work / REJECTED
            try:
                os.replace(self.tasks_path, rejected)
            except OSError as e:
                raise UsageError(f"cannot write {self.flow.rel(rejected)}: "
                                 f"{e.strerror or e}") from None

    def eval_tasks(self, argv: list[str], force: bool) -> dict:
        """Run the executor once on the routing prompt; it writes the tasks file. A file the
        check refuses — and one an interrupted run left — is moved to `REJECTED`; a file that
        exists while the phase is not `running` is kept (`--force` regenerates it)."""
        state = self.require_reconcile()
        rel = self.flow.rel(self.tasks_path)
        interrupted = state["phases"]["eval-tasks"]["status"] == "running"
        if self.tasks_path.exists() and not force and not interrupted:
            return {"file": rel, "status": "exists", "tasks": None, "per_module": None,
                    "problems": [], "state": state}
        ws = self.overlay(state)
        modules, prompt = routing_prompt(ws, PER_MODULE)
        self.flow.mark(state, "eval-tasks", "running")
        if interrupted:  # a file left by a failed or interrupted run is never taken as is
            self.reject()
        try:
            self.tasks_path.unlink(missing_ok=True)
        except OSError as e:
            raise UsageError(f"cannot write {rel}: {e.strerror or e}") from None
        env = {**os.environ, "SEGMENTLY_MODULES_INIT_TASKS": str(self.tasks_path)}
        try:
            proc = subprocess.run(argv, input=prompt.encode("utf-8"), stdout=subprocess.DEVNULL,
                                  stderr=subprocess.PIPE, cwd=self.flow.root, env=env)
        except OSError as e:
            raise UsageError(f"executor {argv[0]} cannot run: {e.strerror or e}") from None
        except BaseException:  # Ctrl-C: whatever the executor wrote so far is not a tasks file
            self.reject()
            raise
        problems = []
        if proc.returncode != 0:
            problems.append(f"the executor exited {proc.returncode}: {tail(proc.stderr)}")
        elif not self.tasks_path.is_file():
            problems.append(f"{TASKS}: not written")
        else:
            problems += self.task_problems(set(modules))
        if problems:
            self.reject()
            return {"file": rel, "status": "failed", "tasks": None, "per_module": None,
                    "problems": problems, "state": state}
        tasks = json.loads(self.tasks_path.read_text(encoding="utf-8"))
        self.flow.mark(state, "eval-tasks", "done",
                       self.flow.sha(self.tasks_path.read_text(encoding="utf-8")))
        per = {m: sum(t["module"] == m for t in tasks) for m in modules}
        return {"file": rel, "status": "written", "tasks": len(tasks), "per_module": per,
                "problems": [], "state": state}

    def task_problems(self, modules: set[str]) -> list[str]:
        try:
            tasks = json.loads(self.tasks_path.read_bytes().decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return [f"{TASKS}: invalid JSON"]
        if not isinstance(tasks, list) or not tasks:
            return [f"{TASKS}: not a non-empty list of {{task, module}} objects"]
        out = [f"{TASKS}: task #{i} is not a {{task, module}} object"
               for i, t in enumerate(tasks, 1)
               if not isinstance(t, dict) or not isinstance(t.get("task"), str)
               or not t["task"].strip() or not isinstance(t.get("module"), str)]
        if out:
            return out
        named = {t["module"] for t in tasks}
        out += [f"unknown module '{m}'" for m in sorted(named - modules)]
        out += [f"no task for module '{m}'" for m in sorted(modules - named)]
        return out

    def run(self, force: bool = False) -> dict:
        """Verify the staging tree; refused while the last `init eval-tasks` run was refused
        (`force`: measure a tasks file written by hand anyway) and for a symlinked staging
        dir."""
        state = self.require_reconcile()
        if state["phases"]["eval-tasks"]["status"] == "running" and not force:
            raise UsageError(REFUSED_TASKS)
        linked = self.work.linked_staging(state)
        if linked:
            raise UsageError("; ".join(linked) + " — nothing verified")
        ws = self.overlay(state)
        findings = lint_registry(ws)
        lint = {"summary": severity_counts(findings), "findings": [asdict(f) for f in findings]}
        routed = None
        if self.tasks_path.is_file():
            targets = target_names(ws.registry.modules)
            try:
                tasks = load_tasks(self.tasks_path, targets, self.flow.rel(self.tasks_path))
            except UsageError as e:  # a hand-written file: say how to get a good one
                raise UsageError(f"{e} — fix it, or segmently-modules init eval-tasks --force") from None
            routed = routing(ws, tasks, 3, ws.config["init"]["routing_min_hit_rate"], targets)
        found = invented(ws, ws.overlay)
        clean = not (lint["summary"]["error"] or lint["summary"]["warning"])
        noisy = keyword_findings(ws, sorted(m for m, e in state["modules"].items()
                                            if not e.get("existing")))
        doc = {"lint": lint, "invented": found, "routing": routed, "keywords": noisy,
               "staging_sha256": tree_sha(self.work.staging),
               "passed": clean and not found and not noisy
               and (routed is None or routed["passed"])}
        self.flow.mark(state, "verify", "running")
        text = serialize(doc)
        self.flow.write(self.verify_path, text)
        self.flow.mark(state, "verify", "done", self.flow.sha(text))
        return {**doc, "state": state}
