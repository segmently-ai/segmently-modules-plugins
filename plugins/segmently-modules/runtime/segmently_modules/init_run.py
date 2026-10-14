"""`init run --executor "<cmd>"` — phase 4 for CI (D1, driver 3): every pending work item runs
through one command, `[init] max_parallel` at a time.

The command is split with `shlex` (never a shell: `>`, `|` and `$HOME` are plain arguments);
its first word is looked up on PATH, or — when it holds a `/` — resolved against the root, and
checked before any item runs. Per item: stdin = the prompt (UTF-8, then EOF), cwd = the root,
the caller's environment plus SEGMENTLY_MODULES_INIT_MODULE, SEGMENTLY_MODULES_INIT_STAGING and SEGMENTLY_MODULES_INIT_WORK
(absolute paths); stdout is discarded. Exit 0 and a complete staging output (`init done`'s
check) -> `done`. Exit 0 and a refused output -> back to `pending` with its problems, and run
once more in this run through a normal claim (D3: one retry per module per run; the claim adds
the problems to the prompt; a stderr line `segmently-modules: <module>: refused — retrying once`); refused
again -> `failed`, `error` = the problems joined, `problems` = the list. Any other exit ->
`failed` at once, `error` = `exit <n>: ` + the last 20 lines of stderr (at most 2,000
characters), no retry. There is no timeout: stop a hung run with Ctrl-C (its children are
terminated — `STOP_S` seconds for all of them, then SIGKILL —, their items stay `running`) and
`init resume`. A module another driver claimed first (`init next`, a second `init run`) is left
to it, and so is one it put back or claimed again while its executor ran (nothing written: the
same attempt only). A git work tree is compared before and after (`git status`, file hashes; a
symlink by its target text, never followed; a rename's or copy's source path too): a change
outside `<config_dir>/init/` fails the run (exit 1) naming each path."""
from __future__ import annotations

import bisect
import contextlib
import hashlib
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from segmently_modules.changes import git_env, work_tree_error
from segmently_modules.init_work import CheckError
from segmently_modules.output import UsageError

TAIL_LINES, TAIL_CHARS = 20, 2000
POLL_S = 0.05
STOP_S = 5  # after Ctrl-C: the seconds all children get to exit on SIGTERM, then SIGKILL
CHUNK = 1 << 20


def pause() -> None:
    """The wait between two polls of the running executors (tests patch it)."""
    time.sleep(POLL_S)


def executor_argv(value: str | None, root: Path) -> list[str]:
    """The executor's argv, its first word checked (exit 2 before any item runs)."""
    if value is None or not value.strip():
        raise UsageError("--executor is empty")
    try:
        argv = shlex.split(value)
    except ValueError as e:
        raise UsageError(f"--executor: {e}") from None
    head = argv[0]
    if "/" in head:
        path = Path(head) if Path(head).is_absolute() else root / head
        if not path.is_file():
            raise UsageError(f"executor not found: {head}")
        if not os.access(path, os.X_OK):
            raise UsageError(f"executor is not executable: {head}")
        argv[0] = os.path.normpath(path)
    elif shutil.which(head) is None:
        raise UsageError(f"executor not found: {head}")
    return argv


def tail(data: bytes) -> str:
    """The last 20 lines of an output, at most 2,000 characters."""
    lines = data.decode("utf-8", errors="replace").splitlines()[-TAIL_LINES:]
    return "\n".join(lines)[-TAIL_CHARS:]


def changed_paths(root: Path) -> list[tuple[str, str]]:
    """(status code, root-relative path) of every change `git status --porcelain=v1 -z
    --untracked-files=all` reports — paths as they are (never quoted), a rename's or copy's
    source path as an entry of its own (in `-z` output it is the field after the new path),
    staged (column X) or in the work tree (column Y)."""
    proc = subprocess.run(["git", "-C", str(root), "status", "--porcelain=v1", "-z",
                           "--untracked-files=all"], capture_output=True, env=git_env())
    parts = proc.stdout.split(b"\0")
    out, i = [], 0
    while i < len(parts):
        entry = parts[i].decode("utf-8", "surrogateescape")
        i += 1
        if len(entry) < 4:
            continue
        code = entry[:2]
        out.append((code, entry[3:]))
        if ("R" in code or "C" in code) and i < len(parts):
            out.append((code, parts[i].decode("utf-8", "surrogateescape")))
            i += 1
    return out


def file_sha(path: Path) -> str | None:
    """sha256 of a file, read in chunks; a symlink's is that of its target text (never
    followed: a link to a FIFO or a huge file costs nothing); None for anything else."""
    try:
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            return "symlink:" + hashlib.sha256(os.fsencode(os.readlink(path))).hexdigest()
        if not stat.S_ISREG(mode):
            return None
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            while chunk := fh.read(CHUNK):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def outside_snapshot(root: Path, inside: str) -> dict | None:
    """{path: (git status code, sha256)} of every changed or untracked file outside `inside`
    (a root-relative directory) — the source of a rename or copy into `inside` included; None
    outside a git work tree."""
    if work_tree_error(root) is not None:
        return None
    return {path: (code, file_sha(root / path)) for code, path in changed_paths(root)
            if not (path == inside.rstrip("/") or path.startswith(inside))}


class Runner:
    """Runs the pending items of a `Work` through one executor."""

    def __init__(self, work, argv: list[str]):
        self.work, self.flow, self.argv = work, work.flow, argv
        self.max_parallel = work.ws.config["init"]["max_parallel"]
        self.retried: set[str] = set()  # the modules this run gave their one retry (D3)

    def start(self, module: str, item: dict) -> tuple:
        """Start the executor on a claimed work item: (process, stdin file, stderr file)."""
        stdin = tempfile.TemporaryFile()
        stdin.write(item["prompt"].encode("utf-8"))
        stdin.seek(0)
        stderr = tempfile.TemporaryFile()
        env = {**os.environ, "SEGMENTLY_MODULES_INIT_MODULE": module,
               "SEGMENTLY_MODULES_INIT_STAGING": str(self.work.staging_dir(module)),
               "SEGMENTLY_MODULES_INIT_WORK": str(self.work.item_path(module))}
        try:
            proc = subprocess.Popen(self.argv, stdin=stdin, stdout=subprocess.DEVNULL,
                                    stderr=stderr, cwd=self.flow.root, env=env)
        except OSError as e:
            stdin.close()
            stderr.close()
            raise UsageError(f"executor {self.argv[0]} cannot run: {e.strerror or e}") from None
        return proc, stdin, stderr

    def finish(self, module: str, proc, stdin, stderr) -> tuple[dict | None, bool]:
        """(the module's row, retry) once its executor exited. retry: the check refused its
        output for the first time in this run — it is `pending` again with its `problems`, for
        its one retry (D3), no row yet. A module put back or claimed again by another driver
        while its executor ran is that driver's now: nothing written, no row, no retry (the
        same attempt only, as `init done`)."""
        stderr.seek(0)
        err = stderr.read()
        stdin.close()
        stderr.close()
        problems = []
        if proc.returncode != 0:
            error = f"exit {proc.returncode}: {tail(err)}"
        else:
            try:
                problems = self.work.problems(module)
                error = "; ".join(problems) if problems else None
            except CheckError as e:  # no retry: the writer cannot fix what stopped the check
                error = f"the check could not run: {e}"
        retry = bool(problems) and module not in self.retried
        with self.flow.locked():
            state = self.flow.load_state()
            entry = state["modules"][module]
            if entry["status"] != "running" or entry["attempts"] != self.work.claimed.get(module):
                return None, False
            entry.update(status="pending" if retry else "failed" if error else "done",
                         error=error)
            if problems:  # kept for the next claim: the writer gets them (SI-7, SI-9)
                entry["problems"] = problems
            else:
                entry.pop("problems", None)
            self.flow.save_state(state)
        if retry:
            self.retried.add(module)
            print(f"segmently-modules: {module}: refused — retrying once", file=sys.stderr, flush=True)
            return None, True
        return {"module": module, **{k: entry[k] for k in ("status", "attempts", "error")}}, False

    def unclaimed(self, module: str, reason: str) -> dict | None:
        """The row of a module whose retry could not be claimed (`reason`: its staging dir a
        symlink or not removable, its work item missing, damaged or of the wrong shape):
        `failed`, `error` = the refused problems and the reason, `problems` kept for its next
        claim, `attempts` as the refused attempt left them — the other modules run on. A module
        another driver claimed or put back meanwhile is left to it (None)."""
        with self.flow.locked():
            state = self.flow.load_state()
            entry = state["modules"][module]
            if entry["status"] != "pending" or entry["attempts"] != self.work.claimed.get(module):
                return None
            refused = entry["error"] or "; ".join(entry.get("problems") or [])
            entry.update(status="failed", error=f"{refused}; the retry could not start: {reason}")
            self.flow.save_state(state)
        return {"module": module, **{k: entry[k] for k in ("status", "attempts", "error")}}

    def run(self) -> dict:
        """Every pending item, `max_parallel` at a time; the rows in name order, one per module
        (its last attempt in this run)."""
        self.retried = set()
        state = self.work.require_fanout(self.flow.load_state())
        pending = sorted(m for m, e in state["modules"].items() if e["status"] == "pending")
        inside = self.flow.rel(self.flow.work) + "/"
        before = outside_snapshot(self.flow.root, inside) if pending else None
        running: dict[str, tuple] = {}
        rows = []
        try:
            while pending or running:
                while pending and len(running) < self.max_parallel:
                    module = pending.pop(0)
                    try:
                        item, _ = self.work.claim(module)
                    except UsageError as e:
                        if module not in self.retried:  # a first claim: the run stops (P5b)
                            raise
                        row = self.unclaimed(module, str(e))  # its retry: only it fails
                        if row:
                            rows.append(row)
                        continue
                    if item is None:  # another driver claimed it first: it is theirs
                        continue
                    running[module] = self.start(module, item)
                finished = [m for m, (p, _, _) in running.items() if p.poll() is not None]
                for module in finished:
                    row, retry = self.finish(module, *running.pop(module))
                    if retry:  # its one retry: claimed again like any pending module
                        bisect.insort(pending, module)
                    elif row:
                        rows.append(row)
                if not finished:
                    pause()
        except BaseException:  # Ctrl-C: stop the children; their items stay running
            for proc, stdin, stderr in running.values():
                with contextlib.suppress(OSError):
                    proc.terminate()
            deadline = time.monotonic() + STOP_S  # one deadline for all of them
            for proc, stdin, stderr in running.values():
                try:
                    proc.wait(timeout=max(0.0, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                stdin.close()
                stderr.close()
            raise
        after = outside_snapshot(self.flow.root, inside) if before is not None else None
        outside = sorted(p for p in set(before or {}) | set(after or {})
                         if (before or {}).get(p) != (after or {}).get(p))
        rows.sort(key=lambda r: r["module"])
        return {"modules": rows, "outside": outside}
