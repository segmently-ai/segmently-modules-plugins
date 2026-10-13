"""`segmently-modules init map|confirm|status|resume|…`: start from existing code — the init state machine.

The work directory is `<config_dir>/init/` (git-ignored by `segmently-modules init`):
  state.json      {schema: "segmently-modules.init-state/1", engine, started_at, phase, phases: {preflight,
                  map, gate-map, fanout, reconcile, eval-tasks, verify, finish: {status:
                  pending|running|done, started_at, finished_at, sha256}}, modules: {<module>:
                  {status: pending|running|done|failed, attempts, error, existing?, problems?}}}
                  — `problems`: the check's problems of an output `init run` refused, kept until
                  the module's next claim; `phase` = the phase most recently started, or
                  "finished" once `init finish` is done;
                  optional keys once used: `forced`, `pr`, `open_pr` (`segmently_modules.init_finish`);
                  `sha256` = the phase's output as written
                  (map's is how an edited proposal is recognised). A state that lacks phases at
                  the end of `PHASES` (written by an engine that had fewer: P5a wrote three)
                  reads them as pending; unknown phase and state keys are ignored
  state.json.lock the advisory lock every read-modify-write of the state takes
  preflight.json  phase 1 (`segmently_modules.preflight`)
  proposal.json   phase 2 (`segmently_modules.mapper`) — edit it at gate 3: `include`, `name`, `paths`
  confirmed.json  gate 3: the validated proposal, frozen by `init confirm` (refused once the
                  fan-out has started: `init map --restart` changes the module set)
  work/, staging/ phase 4 (`segmently_modules.init_work`); staging/registry.json and reconcile.json:
                  phase 5 (`segmently_modules.init_reconcile`); routing-tasks.json, verify.json: phase 6
                  (`segmently_modules.init_verify`; a refused tasks file: routing-tasks.rejected.json)
Every write is a temp file + an atomic rename, so an interrupted phase leaves no partial output:
a phase whose status is not `done` re-runs from its start (`init resume`, or `init map` again).
`map` and `confirm` never prompt."""
import contextlib
import hashlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

from segmently_modules import __version__, mapper, preflight
from segmently_modules.changes import glob_to_regex
from segmently_modules.create import NAME
from segmently_modules.output import UsageError
from segmently_modules.registry import load_registry
from segmently_modules.store import DEFAULT_LOCK_TIMEOUT_S, file_lock, serialize, utc_now

STATE_SCHEMA = "segmently-modules.init-state/1"
PHASES = ("preflight", "map", "gate-map", "fanout", "reconcile", "eval-tasks", "verify",
          "finish")
OUTPUTS = {"preflight": "preflight.json", "map": "proposal.json", "gate-map": "confirmed.json",
           "reconcile": "reconcile.json", "eval-tasks": "routing-tasks.json",
           "verify": "verify.json"}
TEST_STOP = "SEGMENTLY_MODULES_INIT_TEST_STOP"  # test seam: "<phase>" or "<phase>:renamed"
RESTART = "segmently-modules init map --restart"
STATUSES = ("pending", "running", "done")
MODULE_STATUSES = ("pending", "running", "done", "failed")
ENTRY_KEYS = ("status", "started_at", "finished_at", "sha256")
LOCK_TIMEOUT_S = DEFAULT_LOCK_TIMEOUT_S  # seconds a state writer waits for state.json.lock
STALE_TEMP_S = 5  # a temp file older than this is a crash's leftover, not a concurrent run's


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def pending() -> dict:
    return {"status": "pending", "started_at": None, "finished_at": None, "sha256": None}


def strings(value) -> bool:
    """A list of strings (a module entry's `problems`)."""
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def state_problem(state: dict) -> str | None:
    """Why `state` is not a valid init state, else None: `phases` must hold a leading run of
    `PHASES` (a later phase without an earlier one is invalid), each entry with the four keys
    and a status of `STATUSES`; `phase` is null or a string — the phase most recently started,
    or "finished" (written by `init finish`, with the `finish` phase done). A damaged optional
    `problems` names its own way out first: removing it."""
    phases = state.get("phases")
    if not isinstance(phases, dict):
        return "phases"
    held = [p for p in PHASES if p in phases]
    if held != list(PHASES[:len(held)]) or not held:
        return f"phase '{next(p for p in PHASES if p not in phases)}' is missing"
    for p in held:
        entry = phases[p]
        if not isinstance(entry, dict) or any(k not in entry for k in ENTRY_KEYS) \
                or entry["status"] not in STATUSES:
            return f"phase '{p}'"
    if not isinstance(state.get("phase", 0), (str, type(None))):
        return "phase"
    modules = state.get("modules")
    if not isinstance(modules, dict):
        return "modules"
    for name, entry in modules.items():
        if not isinstance(entry, dict) or entry.get("status") not in MODULE_STATUSES \
                or not isinstance(entry.get("attempts"), int) \
                or not isinstance(entry.get("error"), (str, type(None))):
            return f"module '{name}'"
        if not strings(entry.get("problems", [])):
            return (f"module '{name}': problems is not a list of strings — remove it, or start "
                    f"over: {RESTART}")
    return None


class InitFlow:
    def __init__(self, root: Path, config_dir: Path, config: dict):
        self.root, self.config_dir, self.config = root, config_dir, config
        self.work = config_dir / "init"
        self.state_path = self.work / "state.json"

    def rel(self, path: Path) -> str:
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return str(path)

    def output(self, phase: str) -> Path:
        return self.work / OUTPUTS[phase]

    def files(self) -> list[str]:
        """The file set (`preflight.list_files`) without the init work directory itself."""
        inside = self.rel(self.work) + "/"
        return [f for f in preflight.list_files(self.root, self.config)
                if not f.startswith(inside)]

    # --- files --------------------------------------------------------------------------

    def check_work_dir(self) -> None:
        if self.work.is_symlink():
            raise UsageError(f"{self.rel(self.work)} is a symlink — the init work directory must "
                             f"be a real directory (nothing written, its target left alone)")

    def read_json(self, path: Path, schema: str | None = None) -> dict | None:
        """The document at `path` (None when missing); unreadable, not JSON, not an object or
        of another schema is exit 2 naming the file and the restart."""
        if not os.path.lexists(path):
            return None
        try:
            doc = json.loads(path.read_bytes().decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            raise UsageError(f"{self.rel(path)}: cannot read it as JSON ({e}) — fix it, or start "
                             f"over: {RESTART}") from None
        if not isinstance(doc, dict) or (schema and doc.get("schema") != schema):
            raise UsageError(f"{self.rel(path)}: not a {schema or 'JSON object'} document — "
                             f"start over: {RESTART}")
        return doc

    def write(self, path: Path, text: str, seam: str | None = None) -> None:
        """Temp file + atomic rename in the file's own directory (the work directory or one
        below it — never through a symlinked directory); stale temp files of `path` (a crash's:
        older than `STALE_TEMP_S`, so a concurrent run's live one stays) are removed first. A
        failed write is exit 2 `cannot write <path>: <reason>`. `seam`: the phase the test
        seam may stop."""
        self.check_work_dir()
        here = path.parent
        for d in [here, *here.parents]:
            if d == self.work:
                break
            if d.is_symlink():
                raise UsageError(f"{self.rel(d)} is a symlink — the init work directory must be "
                                 f"real directories (nothing written, its target left alone)")
        try:
            here.mkdir(parents=True, exist_ok=True)
            for stale in here.glob(f".{path.name}.*.tmp"):
                with contextlib.suppress(FileNotFoundError):
                    if time.time() - stale.lstat().st_mtime > STALE_TEMP_S:
                        stale.unlink()
            fd, tmp = tempfile.mkstemp(dir=here, prefix=f".{path.name}.", suffix=".tmp")
        except OSError as e:
            raise UsageError(f"cannot write {self.rel(path)}: {e.strerror or e}") from None
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                half = len(text) // 2
                fh.write(text[:half])
                fh.flush()
                if seam and os.environ.get(TEST_STOP) == seam:
                    raise KeyboardInterrupt  # the test seam: stopped after a partial write
                fh.write(text[half:])
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(tmp, 0o644)
            os.replace(tmp, path)
        except FileNotFoundError:  # the temp file vanished: another run swept or cleared it
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp)
            raise UsageError(f"cannot write {self.rel(path)}: another init run is working in "
                             f"{self.rel(self.work)}/ — try again") from None
        except OSError as e:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp)
            raise UsageError(f"cannot write {self.rel(path)}: {e.strerror or e}") from None
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp)
            raise
        if seam and os.environ.get(TEST_STOP) == f"{seam}:renamed":
            raise KeyboardInterrupt  # the test seam: renamed into place, state not marked yet

    # --- state --------------------------------------------------------------------------

    sha = staticmethod(sha256_text)

    def locked(self):
        """The advisory lock of every read-modify-write of the state (`state.json.lock`); a
        writer that waits past `LOCK_TIMEOUT_S` is exit 2 naming the lock."""
        self.check_work_dir()
        return file_lock(self.state_path, LOCK_TIMEOUT_S)

    def load_state(self) -> dict | None:
        """The state (None when there is none), the phases it lacks at the end of `PHASES`
        filled in as pending (in memory); a corrupt state (`state_problem`), or a proposal that
        is no longer JSON, is exit 2 naming the file and the restart."""
        self.check_work_dir()
        state = self.read_json(self.state_path, STATE_SCHEMA)
        if state is not None:
            problem = state_problem(state)
            if problem:
                way = "" if RESTART in problem else f" — start over: {RESTART}"
                raise UsageError(f"{self.rel(self.state_path)}: not a valid init state "
                                 f"({problem}){way}")
            for p in PHASES:
                state["phases"].setdefault(p, pending())
        self.read_json(self.output("map"))
        return state

    def new_state(self) -> dict:
        return {"schema": STATE_SCHEMA, "engine": __version__, "started_at": utc_now(),
                "phase": None, "phases": {p: pending() for p in PHASES}, "modules": {}}

    @staticmethod
    def statuses(state: dict | None) -> dict:
        """{phase: status} of the phases this engine knows ({} without a state)."""
        return {p: state["phases"][p]["status"] for p in PHASES} if state else {}

    def save_state(self, state: dict) -> None:
        self.write(self.state_path, serialize(state))

    def mark(self, state: dict, phase: str, status: str, sha: str | None = None) -> None:
        entry = state["phases"][phase]
        if status == "running":
            entry.update(status="running", started_at=utc_now(), finished_at=None, sha256=None)
            state["phase"] = phase
        else:
            entry.update(status="done", finished_at=utc_now(), sha256=sha)
        self.save_state(state)

    def next_step(self, state: dict | None, work_rel: str) -> str:
        if state is None:
            return "run segmently-modules init map"
        phases = state["phases"]
        if phases["finish"]["status"] == "done":
            if state.get("pr") == "pending":
                return "the pull request is pending: segmently-modules init resume --open-pr"
            pr = f" ({state['pr']})" if state.get("pr") else ""
            return f"init is finished{pr} — review, then commit (init never commits)"
        if phases["finish"]["status"] == "running":
            return ("init finish was interrupted: run segmently-modules init finish again (a failed or "
                    "interrupted finish puts back every file it wrote; after a kill, move away "
                    "what it left — its refusal names each file)")
        for phase in ("preflight", "map"):
            if phases[phase]["status"] == "running":
                return (f"phase {phase} was interrupted: segmently-modules init resume re-runs it from its "
                        f"start")
            if phases[phase]["status"] != "done":
                return f"phase {phase} has not run: segmently-modules init resume"
        if phases["gate-map"]["status"] != "done":
            return (f"gate 3: edit {work_rel}/proposal.json (each candidate's include, name and "
                    f"paths), then run segmently-modules init confirm")
        if phases["fanout"]["status"] == "running":
            return "the fan-out was interrupted: segmently-modules init fanout writes the work items again"
        if phases["fanout"]["status"] != "done":
            return (f"gate 3 passed ({work_rel}/confirmed.json): segmently-modules init fanout writes one "
                    f"work item per module")
        modules = state["modules"]
        done = sum(e["status"] == "done" for e in modules.values())
        stuck = sorted(m for m, e in modules.items() if e["status"] in ("running", "failed"))
        if stuck:
            return (f"segmently-modules init resume (puts {len(stuck)} interrupted or failed module(s) back "
                    f"to pending: {', '.join(stuck)}); then segmently-modules init run --executor "
                    f"\"<command>\", or segmently-modules init next")
        if done < len(modules):
            return (f"{done} of {len(modules)} module(s) done: segmently-modules init run --executor "
                    f"\"<command>\" (every pending module), or claim one with segmently-modules init next, "
                    f"write its files, then segmently-modules init done <module>")
        if phases["reconcile"]["status"] != "done":
            return ("every module is done: segmently-modules init reconcile builds the staging registry "
                    "(edges, keyword collisions, duplicates)")
        if phases["eval-tasks"]["status"] == "running":
            return (f"the routing tasks were refused or interrupted (the file, if any: "
                    f"{work_rel}/routing-tasks.rejected.json): segmently-modules init eval-tasks --executor "
                    f"\"<command>\" writes them again")
        if phases["verify"]["status"] != "done":
            if not (self.work / "routing-tasks.json").is_file():
                return (f"routing tasks: segmently-modules init eval-tasks --executor \"<command>\", or "
                        f"write {work_rel}/routing-tasks.json from segmently-modules eval routing --prompt "
                        f"(the judgement items: {work_rel}/reconcile.json); then segmently-modules init "
                        f"verify — without tasks it reports routing: not measured")
            return ("segmently-modules init verify: lint, the invented-component check and the routing "
                    "hit rate over the staging tree")
        try:
            passed = json.loads((self.work / "verify.json").read_text(encoding="utf-8"))["passed"]
        except (OSError, ValueError, KeyError, TypeError):
            passed = False
        if passed:
            return (f"gate 7: a person reads {work_rel}/verify.json, then segmently-modules init finish "
                    f"(never commits), or segmently-modules init finish --open-pr")
        return (f"verify failed ({work_rel}/verify.json): fix the staging docs or keywords (never "
                f"the tasks), then segmently-modules init verify")

    # --- phases -------------------------------------------------------------------------

    def compute(self, files: list[str]) -> tuple[dict, list[dict], dict]:
        """(preflight.json's document, the manifests, the texts the import scan reuses)."""
        counts = preflight.scan(self.root, files, keep=mapper.scanned)
        found = preflight.manifests(self.root, files, counts["texts"])
        return preflight.build(self.root, files, found, counts), found, counts["texts"]

    def run_phases(self, state: dict, todo: list[str]) -> None:
        """Run `todo` (a suffix of preflight, map) in order; each marks running, writes its
        output atomically, then marks done with the output's sha256."""
        files = found = texts = None
        if "preflight" in todo:
            self.mark(state, "preflight", "running")
            files = self.files()
            doc, found, texts = self.compute(files)
            text = serialize(doc)
            self.write(self.output("preflight"), text, seam="preflight")
            self.mark(state, "preflight", "done", sha256_text(text))
        if "map" in todo:
            self.mark(state, "map", "running")
            if files is None:
                files = self.files()
                found = preflight.manifests(self.root, files)
            text = serialize(mapper.build(self.root, self.config, files, found, texts))
            self.write(self.output("map"), text, seam="map")
            self.mark(state, "map", "done", sha256_text(text))

    # --- actions ------------------------------------------------------------------------

    def finished(self) -> bool:
        """The state on disk says `init finish` is done (a state that cannot be read: no)."""
        try:
            state = json.loads(self.state_path.read_bytes().decode("utf-8"))
            return state["phases"]["finish"]["status"] == "done"
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def refuse_modules(self) -> None:
        registry = self.root / self.config["paths"]["registry"]
        if registry.is_file():
            count = len(load_registry(registry).modules)
            if count and self.finished():  # init wrote them
                raise UsageError("init is finished — see segmently-modules init status")
            if count and self.state_path.is_file():  # created by hand while init was running
                raise UsageError(f"{self.rel(registry)} already has {count} module(s), created "
                                 f"by hand during init — init map (and --restart) starts only "
                                 f"from code without modules: continue with segmently-modules init resume "
                                 f"(a module in the registry is kept as it is), or take them "
                                 f"out of the registry and the modules dir, then run {RESTART}")
            if count:
                raise UsageError(f"{self.rel(registry)} already has {count} module(s) — init map "
                                 f"starts from code without modules. To make the engine read "
                                 f"that registry run segmently-modules adopt; to see how much code the "
                                 f"modules cover run segmently-modules coverage")

    def check_map(self, restart: bool) -> None:
        """The refusals of `init map` before anything is written."""
        self.refuse_modules()
        self.check_work_dir()
        if restart:
            return
        state = self.load_state()
        if state is None:
            return
        if state["phases"]["gate-map"]["status"] == "done":
            raise UsageError(f"gate 3 passed ({self.rel(self.output('gate-map'))}); init map "
                             f"would start over — run {RESTART} to do that")
        recorded = state["phases"]["map"]
        if self.output("map").is_file() and recorded["status"] == "done" and \
                sha256_text(self.output("map").read_text(encoding="utf-8")) != recorded["sha256"]:
            raise UsageError(f"{self.rel(self.output('map'))} was edited: init map would lose "
                             f"the edits — run segmently-modules init confirm, or {RESTART} to discard "
                             f"them")

    def map(self, restart: bool, dry_run: bool) -> dict:
        """Phases 1 and 2 from their start (the starter files are the caller's); stops at
        gate 3. `dry_run` computes both in memory and writes nothing."""
        if dry_run:
            files = self.files()
            doc, found, texts = self.compute(files)
            return {"proposal": mapper.build(self.root, self.config, files, found, texts),
                    "preflight": doc, "state": None}
        if restart and self.work.exists():
            try:
                shutil.rmtree(self.work)
            except OSError as e:
                raise UsageError(f"cannot write {self.rel(self.work)}/: {e.strerror or e}") \
                    from None
        state = self.new_state()
        self.save_state(state)
        try:  # a fresh state has not passed gate 3: an older confirmed.json no longer counts
            self.output("gate-map").unlink(missing_ok=True)
        except OSError as e:
            raise UsageError(f"cannot write {self.rel(self.output('gate-map'))}: "
                             f"{e.strerror or e}") from None
        self.run_phases(state, ["preflight", "map"])
        return {"proposal": self.read_json(self.output("map")), "state": state}

    def resume(self) -> tuple[dict, list[str]]:
        """(state, the phases run): re-runs every phase before gate 3 that is not done."""
        state = self.load_state()
        if state is None:
            raise UsageError("no init state to resume — run segmently-modules init map")
        todo = [p for p in ("preflight", "map") if state["phases"][p]["status"] != "done"]
        if "preflight" in todo:
            todo = ["preflight", "map"]
        if todo:
            self.run_phases(state, todo)
        return state, todo

    def validate(self, proposal: dict) -> list[str]:
        """Every problem of an (edited) proposal, at once; [] when it can be confirmed."""
        problems = []
        candidates = proposal.get("candidates")
        if not isinstance(candidates, list) or not all(isinstance(c, dict) for c in candidates):
            return ["candidates must be a list of objects"]
        included = []
        for i, c in enumerate(candidates):
            label = c.get("name") if isinstance(c.get("name"), str) else f"#{i + 1}"
            if not isinstance(c.get("name"), str):
                problems.append(f"candidate #{i + 1} has no name")
            if not isinstance(c.get("include"), bool):
                problems.append(f"candidate '{label}': include must be true or false")
                continue
            if not c["include"]:
                continue
            included.append(c)
            if isinstance(c.get("name"), str) and (not NAME.fullmatch(c["name"])
                                                   or len(c["name"]) > 48):
                problems.append(f"candidate '{label}': the name breaks the create rule "
                                f"(lowercase words joined by '-', max 48)")
            paths = c.get("paths")
            if not isinstance(paths, list) or not paths or \
                    not all(isinstance(p, str) and p for p in paths):
                problems.append(f"candidate '{label}' has no paths (a list of globs)")
        if not included and not problems:
            return ["no candidate is included"]
        names = [c["name"] for c in included if isinstance(c.get("name"), str)]
        for name in sorted({n for n in names if names.count(n) > 1}):
            problems.append(f"duplicate name '{name}': {names.count(name)} included candidates")
        globbed = [c for c in included if isinstance(c.get("paths"), list) and c["paths"]
                   and all(isinstance(p, str) and p for p in c["paths"])]
        if globbed:
            files = self.files()
            claims: dict[str, list[str]] = {}
            for c in globbed:
                for glob in c["paths"]:
                    rx = glob_to_regex(glob)
                    hits = [f for f in files if rx.match(f)]
                    if not hits:
                        problems.append(f"candidate '{c.get('name')}': glob '{glob}' matches no "
                                        f"file")
                    for f in hits:
                        owners = claims.setdefault(f, [])
                        if c.get("name") not in owners:
                            owners.append(c.get("name"))
            pairs: dict[tuple, list[str]] = {}
            for f, owners in claims.items():
                for a in owners:
                    for b in owners:
                        if str(a) < str(b):
                            pairs.setdefault((a, b), []).append(f)
            for (a, b), shared in sorted(pairs.items(), key=lambda kv: (str(kv[0][0]),
                                                                         str(kv[0][1]))):
                problems.append(f"candidates '{a}' and '{b}' both claim {len(shared)} file(s), "
                                f"e.g. {shared[0]}")
        return problems

    def confirm(self, dry_run: bool) -> dict:
        """Gate 3: validate proposal.json and freeze it as confirmed.json — refused once the
        fan-out has started (a work item exists): the module set is fixed from then on."""
        state = self.load_state()
        if state is None or not os.path.lexists(self.output("map")):
            raise UsageError("nothing to confirm — run segmently-modules init map first")
        if state["phases"]["fanout"]["status"] != "pending" or state["modules"] \
                or any((self.work / "work").glob("*.json")):
            raise UsageError(f"the fan-out has started — to change the module set: {RESTART}")
        if state["phases"]["map"]["status"] != "done":
            raise UsageError(f"phase map has not finished ({state['phases']['map']['status']}) "
                             f"— run segmently-modules init resume")
        proposal = self.read_json(self.output("map"), mapper.SCHEMA)
        problems = self.validate(proposal)
        if problems:
            raise UsageError(f"{self.rel(self.output('map'))} cannot be confirmed: "
                             + "; ".join(problems))
        text = serialize(proposal)
        target = self.output("gate-map")
        old = target.read_text(encoding="utf-8") if target.is_file() else None
        if state["phases"]["gate-map"]["status"] != "done" or old is None:
            status = "confirmed"  # gate 3 passes now (also after an interrupted confirm)
        else:
            status = "unchanged" if old == text else "updated"
        if not dry_run and status != "unchanged":
            self.mark(state, "gate-map", "running")
            self.write(target, text)
            self.mark(state, "gate-map", "done", sha256_text(text))
        names = [c["name"] for c in proposal["candidates"]]
        return {"included": [n for n, c in zip(names, proposal["candidates"]) if c["include"]],
                "excluded": [n for n, c in zip(names, proposal["candidates"])
                             if not c["include"]],
                "status": status}
