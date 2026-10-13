"""`segmently-modules setup [--agent A]… [--target FILE]… [--dry-run]`: the one-command start (P6.1 D5).
Three existing steps run in-process, in order — each writes exactly what its own verb writes:

  init        bare `segmently-modules init`, always: it creates only what is missing of the starter
              config, the empty registry and the .gitignore lines
  packs sync  `segmently-modules packs sync` for the agents: `--agent`, else `[packs] agents`, else the
              agents whose skill directories hold copies an earlier sync made (a marker in
              `.agents/skills` means codex), else claude and codex — for codex also the agent
              files in `.codex/agents/`
  agents-md   `segmently-modules agents-md` for the targets: `--target`, else the instruction files at
              the root that already hold a segmently-modules block (CLAUDE.md, AGENTS.md, GEMINI.md,
              .github/copilot-instructions.md — the files `next` checks), else CLAUDE.md when
              claude is chosen and AGENTS.md when any other agent is (Gemini CLI reads
              GEMINI.md: `--target GEMINI.md`)

Each step reports one status — `created` (a new file or copy), `updated` (only existing ones
changed: init appended `.gitignore` lines), `unchanged`, `exists` (init: nothing was missing),
`skipped` (packs sync: no skill to copy), `conflict` / `invalid` (packs sync left a copy
unwritten; its skill copies and agent files fold into one status) — and its own `--json` data
as `detail`. A second run writes nothing. `--dry-run`
writes nothing; when init would create the config, it plans the later steps against that config:
a scratch config dir outside the repository holding that config.toml beside the real config
dir's packs, overrides and config.user.toml. A step that refuses (exit 2) stops setup at once,
naming the step and what ran before it; a packs sync conflict (exit 1) lets agents-md run, and
setup exits 1. Root: `--root`, else the nearest directory with a segmently-modules marker or `.git` above
the current directory (as every other verb finds it), else the current directory."""
import contextlib
import functools
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from segmently_modules.agents_md_cmd import _target, agents_md
from segmently_modules.config import builtin_delivery
from segmently_modules.init_cmd import init_root, plan_init, starter
from segmently_modules.next_cmd import block_files
from segmently_modules.output import EXIT_FINDINGS, EXIT_OK, UsageError, emit
from segmently_modules.packs_cmd import _hint, agent_hint, sync as packs_sync
from segmently_modules.skill_sync import AGENT_STATUSES, STATUSES, managed_agents
from segmently_modules.skills import AGENT_DIRS, DEFAULT_AGENTS
from segmently_modules.workspace import CONFIG_DIR, Workspace, find_root, refuse_legacy_config

FINDINGS = ("conflict", "invalid")  # packs sync rows it did not write: exit 1, the run goes on
CHANGED = ("updated", "added", "removed")  # an existing file or copy changed
PLANNING_READS = ("packs", "overrides", "config.user.toml")  # besides config.toml
_WORDS = {"created": ("created", "would create"), "updated": ("updated", "would update")}


def register(sub, common) -> None:
    p = sub.add_parser("setup", parents=[common],
                       help="the one-command start: starter config and registry, the skill "
                            "copies, the agents-md block (idempotent)",
                       description="Runs three steps in order: init (whatever is missing of "
                                   "the starter config, the empty registry and the .gitignore "
                                   "lines), packs sync for the agents (for codex also the "
                                   "agent files in .codex/agents/) "
                                   "and agents-md for the instruction files. Agents: --agent, "
                                   "else [packs] agents, else the agents whose skill "
                                   "directories already hold copies packs sync made, else "
                                   "claude and codex. Targets: --target, else the instruction "
                                   "files that already hold a segmently-modules block (CLAUDE.md, "
                                   "AGENTS.md, GEMINI.md, .github/copilot-instructions.md), "
                                   "else CLAUDE.md when claude is chosen and AGENTS.md when "
                                   "any other agent is; Gemini CLI reads GEMINI.md: add "
                                   "--target GEMINI.md. A "
                                   "second run writes nothing. A refused step stops setup "
                                   "(exit 2, naming the step); a skill copy in conflict lets "
                                   "the later steps run and setup exits 1.")
    p.add_argument("--agent", action="append", dest="agents",
                   metavar="claude|codex|cursor|gemini|copilot",
                   help="an agent to copy the pack skills for (repeatable; default: [packs] "
                        "agents, else the agents an earlier packs sync wrote for, else claude "
                        "and codex)")
    p.add_argument("--target", action="append", dest="targets", metavar="FILE",
                   help="a root-relative instruction file for the segmently-modules block (repeatable; "
                        "default: the instruction files that already hold one, else CLAUDE.md "
                        "for claude and AGENTS.md for the other agents; for Gemini CLI: "
                        "--target GEMINI.md)")
    p.add_argument("--dry-run", action="store_true",
                   help="report what each step would do, write nothing")
    p.set_defaults(func=run)


@dataclass
class _Planned(Workspace):
    """A dry run's workspace before init wrote the config: it reads a scratch config dir, and
    shows the paths inside it as the real config dir's (`rel`)."""
    shown_as: Path | None = None

    def rel(self, path) -> str:
        path = Path(os.path.normpath(Path(path).absolute()))
        with contextlib.suppress(ValueError):
            path = self.shown_as / path.relative_to(self.config_dir)
        return super().rel(path)


def _mirror(src: Path, dst: Path) -> None:
    try:
        dst.symlink_to(src, target_is_directory=src.is_dir())
    except OSError:  # no symlinks here (Windows without the privilege): a copy reads the same
        if src.is_dir():
            shutil.copytree(src, dst, symlinks=True)
        else:
            shutil.copy2(src, dst)


@contextlib.contextmanager
def _workspace(root: Path, config_dir: Path, pending: str | None):
    """The workspace the later steps read: the real one, or — a dry run whose init would
    create the config (`pending`: its text) — one that reads that config without writing it."""
    if pending is None:
        yield Workspace.load(root, config_dir)
        return
    with tempfile.TemporaryDirectory(prefix="segmently-modules-setup-") as tmp:
        scratch = Path(tmp).resolve() / "config"
        scratch.mkdir()
        with open(scratch / "config.toml", "w", encoding="utf-8", newline="\n") as fh:
            fh.write(pending)
        for name in PLANNING_READS:
            if os.path.lexists(config_dir / name):
                _mirror(config_dir / name, scratch / name)
        ws = _Planned.load(root, scratch)
        ws.shown_as = config_dir
        yield ws


def choose_agents(ws, flags: list[str] | None) -> list[str]:
    """`--agent`, else `[packs] agents`, else the agents a bare `packs sync` infers from the
    skill directories, else claude and codex — in order, each once."""
    configured = (ws.config.get("packs") or {}).get("agents")
    return list(dict.fromkeys(flags or configured or managed_agents(ws.root)
                              or DEFAULT_AGENTS))


def default_targets(root: Path, agents: list[str]) -> list[str]:
    """The instruction files at `root` that already hold a segmently-modules block (`next`'s set and
    order, `block_files`); when none does, CLAUDE.md for claude and AGENTS.md for any other
    agent (D5)."""
    held = list(block_files(root))
    if held:
        return held
    return (["CLAUDE.md"] if "claude" in agents else []) + \
        (["AGENTS.md"] if any(a != "claude" for a in agents) else [])


def setup_root(arg) -> Path:
    """`--root` (an existing directory), else the root every other verb finds — the nearest
    directory with a segmently-modules marker or `.git` above the current directory —, else the current
    directory (no marker, no git: a place where segmently-modules is not set up yet)."""
    if arg is not None:
        return init_root(arg)  # resolved; refused unless it is a directory
    try:
        return find_root(Path.cwd())
    except UsageError:
        return Path.cwd().resolve()


def init_status(files: list[dict]) -> str:
    """`exists` when bare init found everything, `created` when it created a file, else
    `updated` (it only appended lines to an existing `.gitignore`)."""
    found = {f["status"] for f in files}
    if found == {"exists"}:
        return "exists"
    return "created" if "created" in found else "updated"


def _fold(statuses: list[str]) -> str:
    if any(s in CHANGED for s in statuses):
        return "updated"
    return "created" if "created" in statuses else "unchanged"


def sync_status(data: dict) -> str:
    """packs sync's status: its skill copies and its agent files (codex) together."""
    rows = [r["status"] for r in data["skills"] + data.get("agent_files", [])]
    for finding in FINDINGS:
        if finding in rows:
            return finding
    return _fold(rows) if rows else "skipped"


def _stopped(step: str, error: UsageError, steps: list[dict], dry_run: bool) -> UsageError:
    """A step's refusal: its own message, then what the steps before it did."""
    notes = ["dry run: nothing written"] if dry_run else []
    if steps:
        notes.append("before it: " + ", ".join(f"{s['step']} {s['status']}" for s in steps))
    return UsageError(f"setup stopped at {step}: {error}"
                      + (f" ({'; '.join(notes)})" if notes else ""))


def setup(root: Path, config_dir: Path, agents: list[str] | None, targets: list[str] | None,
          dry_run: bool) -> tuple[dict, Workspace]:
    """Run (or plan) the three steps; (data, the workspace the later steps read). Flags are
    checked before any step; a step's refusal stops the run (exit 2, naming the step)."""
    for agent in agents or []:
        if agent not in AGENT_DIRS:
            raise UsageError(f"unknown agent {agent!r} (agents: {', '.join(AGENT_DIRS)})")
    targets = [_target(SimpleNamespace(root=root), t)[0] for t in targets or []]
    steps, pending = [], None
    config = config_dir / "config.toml"
    try:  # bare init creates only what is missing: run every time
        layout, files = starter(root, config_dir, None, dry_run)
        if dry_run:  # the config it would create (None when config.toml is there)
            pending = next((t for p, s, t in plan_init(root, config_dir, None)[1]
                            if p == config and s == "created"), None)
    except UsageError as e:
        raise _stopped("init", e, steps, dry_run) from None
    steps.append({"step": "init", "status": init_status(files),
                  "detail": {"root": str(root), "layout": layout, "files": files,
                             "dry_run": dry_run}})
    step = "packs sync"
    try:
        with _workspace(root, config_dir, pending) as ws:
            chosen = choose_agents(ws, agents)
            targets = targets or default_targets(root, chosen)
            synced = packs_sync(ws, chosen, check=False, dry_run=dry_run)
            steps.append({"step": step, "status": sync_status(synced), "detail": synced})
            step = "agents-md"
            written = agents_md(ws, targets, check=False, dry_run=dry_run)
            steps.append({"step": step, "status": _fold([t["status"]
                                                         for t in written["targets"]]),
                          "detail": written})
    except UsageError as e:
        raise _stopped(step, e, steps, dry_run) from None
    return {"dry_run": dry_run, "agents": chosen, "targets": targets, "steps": steps}, ws


def run(args) -> int:
    root = setup_root(args.root)
    refuse_legacy_config(root, args.config_dir)
    config_dir = Path(args.config_dir or root / CONFIG_DIR).resolve()
    data, ws = setup(root, config_dir, args.agents, args.targets, args.dry_run)
    emit("setup", data, args.json, functools.partial(_render, ws=ws))
    failed = any(s["status"] in FINDINGS for s in data["steps"])
    return EXIT_FINDINGS if failed else EXIT_OK


def _copies(n: int) -> str:
    return f"{n} skill cop{'y' if n == 1 else 'ies'}"


def _agent_files(n: int) -> str:
    return f"{n} agent file{'' if n == 1 else 's'}"


def _items(rows: list[dict], status: str) -> str:
    """Paths, each with its own status when it is not the step's."""
    out = []
    for r in rows:
        own = f"same file as {r['same_as']}" if r.get("same_as") else r["status"]
        out.append(r["path"] + (f" ({own})" if own != status else ""))
    return ", ".join(out)


def _summary(s: dict, ws) -> str:
    d = s["detail"]
    if s["step"] == "init":
        return _items(d["files"], s["status"])
    if s["step"] == "agents-md":
        return _items(d["targets"], s["status"])
    agents = d.get("agent_files") or []  # codex only
    if not d["skills"] and not agents:  # under builtin_delivery = "plugin" a note names them
        return ("nothing to copy" if builtin_delivery(ws.config) != "repo"
                else "no pack skills (add one: segmently-modules packs new ID --skill NAME)")
    parts = []
    if d["skills"]:
        counts = [f"{d['summary'][k]} {k}" for k in STATUSES if d["summary"][k]]
        parts.append(_copies(len(d["skills"]))
                     + (f" ({', '.join(counts)})" if len(counts) > 1 else ""))
    if agents:
        counts = [f"{n} {k}" for k in AGENT_STATUSES
                  if (n := sum(r["status"] == k for r in agents))]
        parts.append(_agent_files(len(agents))
                     + (f" ({', '.join(counts)})" if len(counts) > 1 else ""))
    return ", ".join(parts)


def _render(d, ws) -> None:
    for s in d["steps"]:
        word = _WORDS.get(s["status"], (s["status"],) * 2)[d["dry_run"]]
        print(f"{s['step']:<11} {word:<12} {_summary(s, ws)}")
        if s["step"] != "packs sync":
            continue
        for r in s["detail"]["skills"]:
            if r["status"] in FINDINGS:
                print(f"  {r['status']:<9} {r['agent']:<7} {r['dir']}")
                hint = _hint(ws, r)
                print(f"    {r['reason']}" + (f" — {hint}" if hint else ""))
        for r in s["detail"].get("agent_files", []):
            if r["status"] in FINDINGS:
                print(f"  {r['status']:<9} {r['agent']:<7} {r['path']}")
                hint = agent_hint(ws, r)
                print(f"    {r['reason']}" + (f" — {hint}" if hint else ""))
        for note in s["detail"]["notes"]:
            print(f"  note: {note}")
    print(f"{'agents':<11} {', '.join(d['agents'])}")
    print(f"{'targets':<11} {', '.join(d['targets'])}")
    if d["dry_run"]:
        print("dry run: nothing written")
    for s in d["steps"]:
        if s["status"] in FINDINGS:
            n = sum(s["detail"]["summary"][k] for k in FINDINGS)
            m = sum(r["status"] in FINDINGS for r in s["detail"].get("agent_files", []))
            left = " and ".join(([_copies(n)] if n else []) + ([_agent_files(m)] if m else []))
            print(f"setup: {s['step']} left {left} unwritten — resolve "
                  f"{'it' if n + m == 1 else 'them'} as shown above, then run segmently-modules setup again")
