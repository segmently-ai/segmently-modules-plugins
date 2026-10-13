"""`init resume` — continue from the recorded phase (D5, SI-21): every scripted step that can run
runs; the first step that needs an agent or a person stops the run, named in `next` (exit 0).

  plain                 re-runs an interrupted phase before gate 3, stops at gate 3; after it:
                        the fan-out (when it has not run), running / failed modules back to
                        pending, then reconcile and verify when their inputs exist
  --executor CMD        also runs the pending modules (`init run`) and writes the routing tasks
                        (`init eval-tasks`) when they are missing
  --non-interactive     never waits for a person: gate 3 passes as the proposal stands (`init
                        confirm`), a verify that does not pass is exit 1; it stops before gate 7
                        unless `--open-pr`. Without `--executor` it is exit 2 before anything
                        runs when a writer will be needed (a module not done, or no routing
                        tasks)
  --open-pr             gate 7 as a pull request: `init finish --open-pr` (or, after a failed
                        push or `gh`, the steps that are left)"""
import json

from segmently_modules.output import EXIT_FINDINGS, EXIT_OK, UsageError


class Chain:
    def __init__(self, flow, work, argv: list[str] | None, non_interactive: bool,
                 open_pr: bool, base: str | None, branch: str):
        self.flow, self.work, self.argv = flow, work, argv
        self.non_interactive, self.open_pr = non_interactive, open_pr
        self.base, self.branch = base, branch
        self.ran: list[str] = []
        self.messages: list[str] = []

    def refuse(self, what: str) -> None:
        raise UsageError(f"{what}: init resume --non-interactive needs --executor "
                         f"\"<command>\" (nothing ran)")

    def blocked(self, what: str) -> bool:
        """True when this step needs a writer and none was given (the plain resume stops)."""
        if self.argv is None and self.non_interactive:
            self.refuse(what)  # the up-front check makes this unreachable; never a silent stop
        return self.argv is None

    def writer_needed(self, state: dict) -> str | None:
        """What a writer would have to do in this run (checked before anything runs), else
        None: a module that is not done, or routing tasks that are missing or were refused."""
        flow, work = self.flow, self.work
        if state["phases"]["fanout"]["status"] != "done":
            gate = "gate-map" if state["phases"]["gate-map"]["status"] == "done" else "map"
            doc = flow.read_json(flow.output(gate))  # None: map has not run yet
            names = {c.get("name") for c in (doc or {}).get("candidates") or []
                     if isinstance(c, dict) and c.get("include") is True}
            if doc is None or names - set(work.registry_modules()):
                return "modules are pending"
        elif any(e["status"] != "done" for e in state["modules"].values()):
            return "modules are pending"
        tasks = state["phases"]["eval-tasks"]["status"]
        if not flow.output("eval-tasks").is_file() or tasks == "running":
            return "the routing tasks are missing"
        return None

    def verified(self) -> bool:
        """verify ran, passed, and the staging tree is the one it verified."""
        from segmently_modules.init_verify import tree_sha
        try:
            doc = json.loads((self.flow.work / "verify.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return doc.get("passed") is True and doc.get("staging_sha256") == \
            tree_sha(self.work.staging)

    def run(self) -> int:
        """The steps that are left; the exit code."""
        from segmently_modules.init_finish import Finish
        from segmently_modules.init_reconcile import Reconcile
        from segmently_modules.init_run import Runner
        from segmently_modules.init_verify import Verify
        flow, work = self.flow, self.work
        state = flow.load_state()
        if state is None:
            raise UsageError("no init state to resume — run segmently-modules init map")
        if state["phases"]["finish"]["status"] == "done":
            if state.get("pr") == "pending" and self.open_pr:
                self.ran.append("pr")
                url, error = Finish(work).publish(state)
                if error:
                    self.messages.append(f"the pull request is still pending: {error}")
                    return EXIT_FINDINGS
                return EXIT_OK
            self.messages.append("init is finished")
            return EXIT_OK
        if self.non_interactive and self.argv is None:
            what = self.writer_needed(state)
            if what:
                self.refuse(what)
        state, ran = flow.resume()
        self.ran += ran
        if state["phases"]["gate-map"]["status"] != "done":
            if not self.non_interactive:
                return EXIT_OK  # gate 3 is a person's
            flow.confirm(False)
            self.ran.append("gate-map")
        state = flow.load_state()
        if state["phases"]["fanout"]["status"] != "done":
            work.fanout()
            self.ran.append("fanout")
        reset = work.reset()
        if reset:
            self.messages.append(f"back to pending (their staging cleared): {', '.join(reset)}")
        state = flow.load_state()
        if any(e["status"] != "done" for e in state["modules"].values()):
            if self.blocked("modules are pending"):
                return EXIT_OK  # an agent writes them: init next / done, or init run
            result = Runner(work, self.argv).run()
            self.ran.append("run")
            failed = [r["module"] for r in result["modules"] if r["status"] == "failed"]
            if failed or result["outside"]:
                self.messages += [f"{m} failed (see segmently-modules init status)" for m in failed]
                self.messages += [f"wrote outside the staging dir: {p}"
                                  for p in result["outside"]]
                return EXIT_FINDINGS
        state = flow.load_state()
        if state["phases"]["reconcile"]["status"] != "done":
            Reconcile(work).run(False)
            self.ran.append("reconcile")
        check = Verify(work)
        state = flow.load_state()  # a refused or interrupted eval-tasks runs again, file or not
        if not check.tasks_path.is_file() or state["phases"]["eval-tasks"]["status"] == "running":
            if self.blocked("the routing tasks are missing"):
                return EXIT_OK  # an agent (or a person) writes them
            result = check.eval_tasks(self.argv, False)
            self.ran.append("eval-tasks")
            if result["problems"]:
                self.messages += [f"eval-tasks: {p}" for p in result["problems"]]
                return EXIT_FINDINGS
        if "eval-tasks" in self.ran or not self.verified():  # new tasks: measure them
            result = check.run()
            self.ran.append("verify")
            if not result["passed"]:
                self.messages.append("verify did not pass — see verify.json")
                return EXIT_FINDINGS
        if not self.open_pr:
            return EXIT_OK  # gate 7 is a person's: init finish
        result = Finish(work).run(False, [], True, self.base, self.branch)
        self.ran.append("finish")
        if result["error"]:
            self.messages.append(f"the pull request is pending: {result['error']}")
            return EXIT_FINDINGS
        return EXIT_OK
