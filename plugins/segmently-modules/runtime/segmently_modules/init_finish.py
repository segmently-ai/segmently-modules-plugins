"""`init finish` — gate 7 (D4): the staging tree becomes the registry and the module docs.

Interactive: a person has read `init status` and `verify.json`; `init finish` moves every new
module's staging docs to `<modules_dir>/<module>/` (the configured layout), adds its entry to
the registry through the registry writer (lock, the house serializer; in the per-module layout
its `module.json` and the rebuilt index), appends one `[[code_map]]` rule `init-<module>` (its
confirmed paths) per new module to `<config_dir>/config.toml` through the `code-map add` writer
(when that file exists), writes the managed block into `CLAUDE.md` / `AGENTS.md` (those that
exist; `--agents-md FILE` names others) and marks the state finished — all or nothing: a failed
or interrupted write puts back every file it touched. It never commits: it prints the `git add`
line. A module already in the registry is never moved or rewritten.

The state is saved as finished only as the last step of the writes (the commit point): a failure
or Ctrl-C before it puts every file back — its saved bytes at its real path, so a symlinked
`CLAUDE.md` stays a symlink; each file is tried even when another one fails, and one that could
not be put back is named. Once the state on disk says finished, nothing is put back.

Refusals (exit 2, nothing written): already finished; reconcile never ran; the last `init
eval-tasks` run refused, verify not passed or the staging tree changed since it (overridden by
`--force`, recorded in the state); a symlinked staging dir, a module directory or registry entry
that appeared since, a registry changed since reconcile (or a staging registry that changes a
module already in the registry: finish never rewrites one), a `[[code_map]]` id already taken
(never overridden); an instruction file the agents' block cannot go into (its markers, not
UTF-8, unreadable) — all checked before the first write. The staging registry is read once.

`--open-pr [--base B] [--branch segmently-modules/init]`: needs `gh` on PATH, a git remote `origin` and a
tree with no change outside what the commit takes (the files above plus the starter files `init`
created); creates the branch from the current commit, commits every written file in ONE commit
(subject = the pull request's title, `docs: module docs for <n> module(s) (segmently-modules init)`, n =
the new modules), pushes it and runs `gh pr create` with the verify summary, the routing table
and the judgement items as the body. Each step is recorded in `open_pr` (`branch_created`,
`committed`, `pushed`; `start` = the commit the branch starts from): a failed commit (a hook,
the git identity, signing), push or `gh` records `pr: "pending"` and exits 1; `init resume
--open-pr` retries only what is left — back on the branch, never a second branch, commit or
push. A step done but not recorded (a kill) is recognised: a commit on the branch with the
title and nothing of its paths left to commit, a pull request `gh` says already exists."""
import contextlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from segmently_modules.agents_md_cmd import _target, agents_md
from segmently_modules.changes import git_env, work_tree_error
from segmently_modules.code_map_cmd import _defined_in, add_rule
from segmently_modules.config import load_config
from segmently_modules.fields import load_field_defs
from segmently_modules.init_overlay import code_map_rules, staged_registry
from segmently_modules.init_run import changed_paths
from segmently_modules.init_verify import REFUSED_TASKS, tree_sha
from segmently_modules.layout import build_index
from segmently_modules.output import UsageError
from segmently_modules.store import atomic_write, open_store, serialize, sha256_bytes, utc_now
from segmently_modules.workspace import Workspace

INSTRUCTION_FILES = ("CLAUDE.md", "AGENTS.md")
REFUSALS = {  # a forced finish's reasons, the refusal of each without --force
    "routing tasks refused": REFUSED_TASKS,
    "verify not passed": "verify has not passed — run segmently-modules init verify",
    "staging changed since verify": "staging changed since verify — run segmently-modules init verify"}


def run_git(root: Path, *args: str) -> subprocess.CompletedProcess:
    """One git command in the root, its result as it is (the caller words the failure;
    `segmently_modules.changes.git` raises instead)."""
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=git_env())


def pr_title(modules: int) -> str:
    """The pull request's title and its commit's subject (Conventional Commits)."""
    return f"docs: module docs for {modules} module(s) (segmently-modules init)"


def restore(path: Path, data: bytes | None) -> None:
    """Put a file back as it was before `init finish`: its saved bytes at its real path (temp
    file + rename: a symlink stays a symlink, the mode is kept), or gone when it did not
    exist."""
    real = Path(os.path.realpath(path))
    if data is None:
        real.unlink(missing_ok=True)
        return
    if real.is_file() and real.read_bytes() == data:
        return  # never touched
    mode = stat.S_IMODE(real.stat().st_mode) if real.exists() else 0o644
    fd, tmp = tempfile.mkstemp(dir=real.parent, prefix=f".{real.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, real)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


class Finish:
    def __init__(self, work):
        self.work, self.flow, self.root = work, work.flow, work.flow.root

    def workspace(self) -> Workspace:
        config = load_config(self.flow.config_dir, self.root)
        return Workspace(self.root, self.flow.config_dir, config, load_field_defs(config))

    # --- checks ---------------------------------------------------------------------------

    def check(self, state: dict | None, force: bool) -> tuple[dict, dict, bytes, list[str]]:
        """(state, the staging registry, its bytes as read — the only read —, the reasons a
        forced finish overrides)."""
        if state is None:
            raise UsageError("no init state — run segmently-modules init map")
        if state["phases"]["finish"]["status"] == "done":
            raise UsageError("already finished — see segmently-modules init status")
        if state["phases"]["reconcile"]["status"] != "done" or \
                not (self.work.staging / "registry.json").is_file():
            raise UsageError("reconcile has not run — run segmently-modules init reconcile, then segmently-modules init "
                             "verify")
        linked = self.work.linked_staging(state)
        if linked:  # never copied through a link (verify hashed the link text only)
            raise UsageError("; ".join(linked) + " — nothing written")
        forced = []
        if state["phases"]["eval-tasks"]["status"] == "running":
            forced.append("routing tasks refused")
        verify = None
        with contextlib.suppress(OSError, ValueError):
            verify = json.loads((self.flow.work / "verify.json").read_text(encoding="utf-8"))
        if state["phases"]["verify"]["status"] != "done" or not isinstance(verify, dict) \
                or verify.get("passed") is not True:
            forced.append("verify not passed")
        elif verify.get("staging_sha256") != tree_sha(self.work.staging):
            forced.append("staging changed since verify")
        if forced and not force:
            raise UsageError(REFUSALS[forced[0]])
        staged, data = staged_registry(self.flow, self.work)
        return state, staged, data, forced

    @staticmethod
    def new_modules(state: dict) -> list[str]:
        """The modules `init` wrote, in name order (not those created by hand)."""
        return [m for m, e in sorted(state["modules"].items()) if not e.get("existing")]

    def starters(self, ws) -> set[str]:
        """The starter files `init` created: the commit takes them when git reports them."""
        return {".gitignore", self.flow.rel(self.flow.config_dir / "config.toml"),
                ws.config["paths"]["registry"]}

    def conflicts(self, ws, staged: dict, data: bytes, state: dict) -> list[str]:
        """Everything `finish` would overwrite: it never does (`data`: the staging registry's
        bytes `staged` was parsed from)."""
        mdir = ws.config["paths"]["modules_dir"]
        real = self.work.registry_modules()
        new = self.new_modules(state)
        out = [f"{mdir}/{m}/ exists" for m in new if (self.root / mdir / m).exists()]
        out += [f"the registry already has '{m}'" for m in new if m in real]
        kept = {m: e for m, e in staged["modules"].items() if m not in new}
        changed = sorted(m for m in set(kept) | set(real)
                         if m not in new and serialize(kept.get(m, {})) != serialize(
                             real.get(m, {})))
        edited = sha256_bytes(data) != state["phases"]["reconcile"]["sha256"]
        mine = [m for m in changed if edited and m in kept and m in real]  # the staging edit
        theirs = [m for m in changed if m not in mine]  # the registry changed since reconcile
        if theirs:
            out.append(f"the registry changed since init reconcile ({', '.join(theirs)}) — "
                       f"rerun segmently-modules init reconcile")
        if mine:
            out.append(f"the staging registry changes {', '.join(mine)}, already in the "
                       f"registry — finish never rewrites a registry module: make that change "
                       f"in {ws.config['paths']['registry']} itself, then run segmently-modules init "
                       f"reconcile --force")
        if (self.flow.config_dir / "config.toml").is_file():
            for rule in code_map_rules(self.work, state):
                owner = _defined_in(ws, rule["id"])  # root-relative
                if owner:
                    out.append(f"[[code_map]] '{rule['id']}' is already defined in {owner}")
        return out

    def targets(self, ws, agents_md_args: list[str]) -> list[str]:
        if agents_md_args:
            for target in agents_md_args:
                _target(ws, target)  # outside the root or a directory: exit 2
            return list(agents_md_args)
        return [t for t in INSTRUCTION_FILES if (self.root / t).is_file()]

    # --- the writes -----------------------------------------------------------------------

    def apply(self, state: dict, staged: dict, targets: list[str], forced: list[str],
              pr: dict | None) -> dict:
        """Move, register, map and tell the agents, then save the state as finished (the
        commit point: `git_add`, the pull request's body and the state are part of it) — or,
        on any failure or Ctrl-C before that, put everything back."""
        ws = self.workspace()
        paths = ws.config["paths"]
        new = self.new_modules(state)
        registry = self.root / paths["registry"]
        touched = [registry, self.flow.config_dir / "config.toml",
                   *(self.root / t for t in targets)]
        if paths["registry_layout"] == "per-module":
            touched += [self.root / paths["modules_dir"] / m / paths["module_entry"] for m in new]
        saved = {}
        for p in touched:
            try:
                saved[p] = p.read_bytes() if p.is_file() else None
            except OSError as e:
                raise UsageError(f"cannot read {self.flow.rel(p)}: {e.strerror or e} — nothing "
                                 f"written") from None
        moved, created = [], []
        try:
            for m in new:
                base, final = self.work.staging_dir(m), f"{paths['modules_dir']}/{m}"
                docs = [(base / "MODULE.md", f"{final}/{paths['module_doc']}")]
                docs += [(d, f"{final}/roles/{d.name}") for d in sorted((base / "roles")
                                                                         .glob("*.md"))]
                for source, rel in docs:
                    created.append(self.root / rel)
                    try:
                        atomic_write(self.root / rel, source.read_text(encoding="utf-8"))
                    except OSError as e:
                        raise UsageError(f"cannot write {rel}: {e.strerror or e}") from None
                    moved.append(rel)
            try:
                with open_store(ws).edit() as reg:
                    for m in new:
                        if m in reg.raw["modules"]:
                            raise UsageError(f"the registry already has '{m}' — nothing written")
                        reg.raw["modules"][m] = staged["modules"][m]
                if paths["registry_layout"] == "per-module":
                    text, stale = build_index(self.root, ws.config)
                    if stale:
                        atomic_write(registry, text)
            except OSError as e:
                raise UsageError(f"cannot write {paths['registry']}: {e.strerror or e}") from None
            ws = self.workspace()
            ids = []
            if (self.flow.config_dir / "config.toml").is_file():
                for rule in code_map_rules(self.work, state):
                    add_rule(ws, rule["id"], None, rule["globs"], rule["module"], False, False)
                    ids.append(rule["id"])
                ws = self.workspace()
            rows = agents_md(ws, targets, False, False)["targets"] if targets else []
            written = moved + [self.flow.rel(p) for p, data in saved.items()
                               if p.is_file() and p.read_bytes() != data]
            add = self.git_add(ws, sorted(set(written)))
            state["phases"]["finish"].update(status="done", finished_at=utc_now())
            state["phase"] = "finished"
            if forced:
                state["forced"] = {"at": utc_now(), "reason": "; ".join(forced)}
            if pr is not None:
                state["pr"] = "pending"
                state["open_pr"] = {"branch": pr["branch"], "base": pr["base"],
                                    "start": pr.get("start"), "paths": add,
                                    "committed": False, "pushed": False,
                                    "title": pr_title(len(new))}
                self.flow.write(self.flow.work / "pr-body.md", self.pr_body(state, forced))
            self.flow.save_state(state)  # the commit point: from here on, finish is done
        except BaseException as e:
            if self.flow.finished():  # stopped after the state was saved: the writes stand
                raise
            failed = self.rollback(saved, created, paths)
            if failed:
                note = f"could not put back: {', '.join(failed)} (restore them by hand)"
                if isinstance(e, UsageError):
                    raise UsageError(f"{e} — {note}") from None
                print(f"segmently-modules: init finish {note}", file=sys.stderr)
            raise
        return {"moved": moved, "agents_md": [{"path": r["path"], "status": r["status"]}
                                              for r in rows], "code_map": ids, "git_add": add}

    def rollback(self, saved: dict, created: list, paths: dict) -> list[str]:
        """Put back every file `apply` touched; each step is tried even when one fails (the
        caller re-raises the error that stopped `apply`). What could not be put back,
        root-relative."""
        failed = []
        for path, data in saved.items():
            try:
                restore(path, data)
            except Exception:
                failed.append(self.flow.rel(path))
        for path in created:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                failed.append(self.flow.rel(path))
        stop = self.root / paths["modules_dir"]
        for d in sorted({d for p in created for d in p.parents if stop in d.parents},
                        key=lambda d: -len(d.parts)):
            try:
                d.rmdir()
            except FileNotFoundError:
                pass
            except Exception:
                failed.append(self.flow.rel(d) + "/")
        return sorted(set(failed))

    def git_add(self, ws, written: list[str]) -> list[str]:
        """What the commit takes: every file finish wrote, and the starter files `init` created
        that git still reports as changed or new."""
        paths = set(written)
        if work_tree_error(self.root) is None:
            starters = self.starters(ws)
            paths |= {p for _, p in changed_paths(self.root) if p in starters}
        return sorted(paths)

    # --- the pull request -----------------------------------------------------------------

    def pr_checks(self, base: str | None, branch: str, expected: set[str]) -> str:
        """Everything `--open-pr` needs, before anything is written; the base branch."""
        for flag, value in (("--base", base), ("--branch", branch)):
            if value is not None and value.startswith("-"):
                raise UsageError(f"{flag} {value!r} may not start with '-'")
        if shutil.which("gh") is None:
            raise UsageError("gh is not installed (needed for --open-pr)")
        error = work_tree_error(self.root)
        if error:
            raise UsageError(f"--open-pr needs a git repository ({error})")
        dirty = list(dict.fromkeys(p for _, p in changed_paths(self.root) if p not in expected))
        if dirty:
            raise UsageError(f"working tree not clean ({', '.join(dirty[:5])}) — commit or stash "
                             f"it first")
        if run_git(self.root, "remote", "get-url", "origin").returncode != 0:
            raise UsageError("no git remote 'origin' (needed for --open-pr)")
        if run_git(self.root, "check-ref-format", "--branch", branch).returncode != 0:
            raise UsageError(f"--branch {branch!r} is not a valid branch name")
        if run_git(self.root, "rev-parse", "--verify", "--quiet",
                   f"refs/heads/{branch}").returncode == 0:
            raise UsageError(f"branch {branch} exists — name another with --branch")
        if base is None:
            current = run_git(self.root, "symbolic-ref", "--short", "HEAD")
            if current.returncode != 0:
                raise UsageError("HEAD is detached — name the base with --base")
            base = current.stdout.strip()
        return base

    def pr_body(self, state: dict, forced: list[str]) -> str:
        verify, report = {}, {}
        with contextlib.suppress(OSError, ValueError):
            verify = json.loads((self.flow.work / "verify.json").read_text(encoding="utf-8"))
        with contextlib.suppress(OSError, ValueError):
            report = json.loads((self.flow.work / "reconcile.json").read_text(encoding="utf-8"))
        new = self.new_modules(state)
        lines = [f"Module docs for {len(new)} module(s), written by `segmently-modules init`: "
                 f"{', '.join(new)}.", "", "## Verify", ""]
        s = (verify.get("lint") or {}).get("summary") or {}
        lines.append(f"- lint: {s.get('error', '?')} error(s), {s.get('warning', '?')} "
                     f"warning(s), {s.get('info', '?')} info")
        lines.append(f"- invented components: {len(verify.get('invented') or [])}")
        routing = verify.get("routing")
        if not routing:
            lines.append("- routing: not measured")
        else:
            lines += [f"- routing: hit rate {routing['hit_rate']} ({routing['hits']}/"
                      f"{routing['tasks']}, top {routing['top']}; threshold "
                      f"{routing['min_hit_rate']})", "", "| Module | Hits | Tasks |",
                      "|---|---|---|"]
            lines += [f"| {r['module']} | {r['hits']} | {r['tasks']} |"
                      for r in routing["per_module"]]
            misses = [f"- {r['module']}: \"{m['task']}\" → {', '.join(m['got']) or 'none'}"
                      for r in routing["per_module"] for m in r["misses"]]
            if misses:
                lines += ["", "Misses:", *misses]
        lines += ["", "## Judgement items (init reconcile)", ""]
        items = report.get("judgement") or []
        for j in items:
            if j["kind"] == "duplicate":
                where = ", ".join(f"{d['file']}:{d['line']}" for d in j["definitions"])
                lines.append(f"- duplicate `{j['name']}`: {where}")
            elif j["kind"] == "keyword-tie":
                lines.append(f"- keyword `{j['keyword']}` ties: {', '.join(j['modules'])}")
            else:
                lines.append(f"- keyword `{j['keyword']}` stays in {j['module']} (it would drop "
                             f"below the keyword minimum)")
        if not items:
            lines.append("- none")
        if forced:
            lines += ["", f"Finished with --force: {'; '.join(forced)}."]
        return "\n".join(lines) + "\n"

    def on_branch(self, state: dict) -> str | None:
        """HEAD on the pull request's branch: created from the current commit when it does not
        exist yet (`pr_checks` made sure it did not before `finish`), else switched to — or left
        as it is when HEAD is on it; `branch_created` is saved at once. The error, else None."""
        pr = state["open_pr"]
        head = run_git(self.root, "symbolic-ref", "--short", "-q", "HEAD")
        if head.returncode != 0 or head.stdout.strip() != pr["branch"]:
            exists = run_git(self.root, "rev-parse", "--verify", "--quiet",
                             f"refs/heads/{pr['branch']}").returncode == 0
            proc = run_git(self.root, "checkout", "-q", *(() if exists else ("-b",)),
                           pr["branch"])
            if proc.returncode != 0:
                return f"git checkout failed: {proc.stderr.strip()[:300]}"
        if not pr.get("branch_created"):
            pr["branch_created"] = True
            self.flow.save_state(state)
        return None

    def commit_made(self, pr: dict) -> bool:
        """The commit a kill kept from being recorded: HEAD carries the pull request's title, is
        ahead of the commit the branch started from (a state without `start`: the base), and
        none of the paths it takes is staged or changed any more."""
        subject = run_git(self.root, "log", "-1", "--format=%s", "HEAD")
        if subject.returncode != 0 or subject.stdout.rstrip("\n") != pr["title"]:
            return False
        ahead = run_git(self.root, "rev-list", "--count",
                        f"{pr.get('start') or pr['base']}..HEAD")
        if ahead.returncode != 0 or not ahead.stdout.strip().isdigit() \
                or int(ahead.stdout) < 1:
            return False
        left = run_git(self.root, "--literal-pathspecs", "status", "--porcelain=v1", "-z",
                       "--untracked-files=all", "--", *pr["paths"])
        return left.returncode == 0 and not left.stdout

    def publish(self, state: dict) -> tuple[str, str | None]:
        """The steps of the pull request not done yet (the branch, add + commit, push, `gh pr
        create`); (pr, the error that left it pending)."""
        pr = state["open_pr"]
        body = self.flow.work / "pr-body.md"
        if not pr["committed"]:
            error = self.on_branch(state)
            if error:
                return "pending", error
            if not self.commit_made(pr):
                proc = run_git(self.root, "add", "--", *pr["paths"])
                if proc.returncode != 0:
                    return "pending", (f"git add failed on branch {pr['branch']}: "
                                       f"{proc.stderr.strip()[:300]} (the retry picks up from "
                                       f"the branch)")
                proc = run_git(self.root, "commit", "-q", "-m", pr["title"])
                if proc.returncode != 0:
                    why = (proc.stderr.strip() or proc.stdout.strip())[:300]
                    return "pending", (f"git commit failed on branch {pr['branch']}: {why} (a "
                                       f"hook, the git identity or commit signing refused it; "
                                       f"the files stay on the branch: fix that, and the retry "
                                       f"picks up from the branch)")
            pr["committed"] = True
            self.flow.save_state(state)
        if not pr["pushed"]:
            proc = run_git(self.root, "push", "-q", "origin", pr["branch"])
            if proc.returncode != 0:
                return "pending", f"git push failed: {proc.stderr.strip()[:300]}"
            pr["pushed"] = True
            self.flow.save_state(state)
        try:
            proc = subprocess.run(["gh", "pr", "create", "--base", pr["base"], "--head",
                                   pr["branch"], "--title", pr["title"], "--body-file", str(body)],
                                  cwd=self.root, capture_output=True, text=True, errors="replace")
        except OSError as e:
            return "pending", f"gh cannot run: {e.strerror or e}"
        if proc.returncode == 0:
            url = next((l.strip() for l in reversed(proc.stdout.splitlines()) if l.strip()),
                       "created")
        else:  # created before but not recorded (a kill): gh names that pull request
            said = f"{proc.stderr}\n{proc.stdout}"
            urls = re.findall(r"https?://\S+", said) if "already exists" in said else []
            if not urls:
                return "pending", (f"gh pr create failed: "
                                   f"{(proc.stderr or proc.stdout).strip()[:300]}")
            url = urls[-1]
        state["pr"] = url
        self.flow.save_state(state)
        return url, None

    # --- the action -----------------------------------------------------------------------

    def run(self, force: bool, agents_md_args: list[str], open_pr: bool, base: str | None,
            branch: str) -> dict:
        state, staged, data, forced = self.check(self.flow.load_state(), force)
        ws = self.workspace()
        problems = self.conflicts(ws, staged, data, state)
        if problems:
            raise UsageError("init finish would overwrite: " + "; ".join(problems) +
                             " — nothing written")
        targets = self.targets(ws, agents_md_args)
        if targets:  # the block's markers, UTF-8, readable — refused before the first write
            agents_md(ws, targets, False, True)
        pr = None
        if open_pr:  # the starter files init created may still be uncommitted: the PR takes them
            pr = {"branch": branch, "base": self.pr_checks(base, branch, self.starters(ws))}
            head = run_git(self.root, "rev-parse", "--verify", "--quiet", "HEAD")
            pr["start"] = head.stdout.strip() if head.returncode == 0 else None
        self.flow.mark(state, "finish", "running")
        result = self.apply(state, staged, targets, forced, pr)
        error = None
        if open_pr:
            _, error = self.publish(state)
        return {**result, "registry": ws.config["paths"]["registry"], "forced": bool(forced),
                "pr": state.get("pr"), "error": error, "state": state}
