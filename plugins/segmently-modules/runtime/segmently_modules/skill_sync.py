"""`segmently-modules packs sync`: copy pack skills into the agents' skill directories — claude
`<root>/.claude/skills/<skill>/`; codex, cursor, gemini and copilot
`<root>/.agents/skills/<skill>/` (one directory, written once) — and keep them there;
`--remove` takes every managed copy of an agent's directory out again (`plan_remove`).

Every (agent, skill) gets its status BEFORE anything is written:
  created    the destination directory does not exist
  unchanged  every managed file on disk equals the source (bytes and mode), marker current
  updated    the source or the marker differs and nothing was edited locally: changed and new
             files are written, files the source dropped are deleted, the marker is rewritten
  removed    a managed skill (it has a marker) that no installed pack declares any more: its
             managed files and marker are deleted, directories left empty removed; unmanaged
             files stay and are named in `reason`
  conflict   the destination is not ours (no marker, a marker of another pack or skill, not a
             directory), a managed file was edited or deleted locally, or a new source file
             would replace an unmanaged one — the skill is left untouched
  invalid    the source is not loadable by agents (lint MS062) — nothing written for it
The marker `<dest>/.segmently-modules-managed` = {schema, pack, skill, version, source, files: {path:
sha256}} is written LAST: after an interrupted update, a file that already equals the source is
not a local edit, so the next run resumes; a first write (`created`) that fails or is interrupted
removes the directory it made, so the next run creates the skill again. Directories without a
marker are never read beyond the existence check; a symlink inside a destination is never
written through.

For `codex` (P8.4 D3) it also writes the agents of the agent table (`SKILL_AGENTS`) as
`<root>/.codex/agents/<name>.toml` — `name`, `description` and `developer_instructions` = a short
body that runs the skill and returns its output (`AGENT_BODY` + `CODEX_FALLBACK`, P8.6 D1; no skill
text is copied), for every agent whose skill the sources hold, under either delivery — each a
managed file whose first line is the marker
`# segmently-modules-managed: {schema, pack, skill, version, sha256 of the bytes after that line}`, written
whole (temp file + rename). Their statuses (`plan_agent_files`): `created`, `unchanged` (the
bytes equal what would be written), `updated` (marker intact, content or marker stale),
`removed` (a managed file whose skill no enabled pack declares any more: deleted), `conflict` (no
marker, a damaged one, another skill's, a local edit, a symlink or directory at the path). A
symlinked or non-directory `.codex/agents` (or `.codex`) is never written or removed through:
while the repository wants the agents, all three are a `conflict`; when it wants none, a
read-only look behind a symlink makes each agent file there with a marker line a `conflict` (it
cannot be removed through the symlink), and nothing else gives a row. A skill whose source is
not loadable keeps its agent file as it is (the skill's own row reports it); a file without a
marker is never removed; nothing else under `.codex/` is read or written. A run that names its
agents without codex never opens `.codex/`; a bare run under `builtin_delivery = "plugin"`
reads `.codex/agents/` only to infer codex (`managed_agents`)."""
import contextlib
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path

from segmently_modules.output import UsageError
from segmently_modules.skills import (AGENT_BODY, AGENT_DIRS, CODEX_AGENTS, CODEX_FALLBACK, DEFAULT_AGENTS,
                           EJECTED, MANAGED, SKILL_AGENTS, ejected_copies, ejected_symlinks, pack_skills,
                           read_ejected, sha256_file, source_hashes, source_problem)

MANAGED_SCHEMA = "segmently-modules.managed/1"
STATUSES = ("created", "updated", "unchanged", "removed", "conflict", "invalid")
# fixed reasons that `conflict_kind` and the `packs sync` hints read back
NOT_MANAGED = f"not managed by segmently-modules (no {MANAGED})"
BAD_MARKER = f"{MANAGED} is not a valid marker"
NO_RECORD = f"has no valid {EJECTED} record"  # an `invalid` ejected copy: lint MS063, not MS062
ORPHAN_BAD_MARKER = f"{BAD_MARKER} (not removed)"
PLUGIN_PROVIDES = 'builtin_delivery = "plugin" (the plugin provides this skill)'
_OTHER_PACK = re.compile(r"managed for pack '(.*)', skill '.*'")
_EDIT = re.compile(r" \(locally (?:edited|deleted)\)(?:; |$)")


def sync_command(agents: list[str] | None, configured: list[str] | None) -> str:
    """The `packs sync` command every hint names: bare when `[packs] agents` (`configured`)
    already names `agents` (None: whatever the config names), else with the `--agent` flags
    — claude and codex when no agent was chosen."""
    if configured and (agents is None or list(agents) == list(configured)):
        return "segmently-modules packs sync"
    return "segmently-modules packs sync " + " ".join(f"--agent {a}" for a in agents or DEFAULT_AGENTS)


@dataclass
class Source:
    """Where a skill is materialized from."""
    skill: str
    pack: str | None
    version: str | None
    kind: str  # "pack" | "ejected"
    dir: Path
    problem: str | None
    files: dict[str, str] = field(default_factory=dict)  # path -> sha256
    blocked: str | None = None  # a symlink at the ejected path: a conflict, nothing is read


@dataclass
class Plan:
    """The decided status of one (agent, skill) and what applying it writes or deletes."""
    agent: str
    skill: str
    dest: Path
    status: str
    source: Source | None = None
    marker: dict | None = None  # the marker on disk (removed rows: what they came from)
    write: list[str] = field(default_factory=list)
    delete: list[str] = field(default_factory=list)
    reason: str | None = None
    same_as: str | None = None


def skill_sources(ws) -> dict[str, Source]:
    """The source of every skill to materialize, by id: its ejected copy when one exists
    (`<config_dir>/overrides/skills/<id>/`, synced even when no pack declares the skill any
    more; pack and version from its record), else the declaring pack's directory."""
    out = {}
    skills, ejected = pack_skills(ws.config_dir), ejected_copies(ws.config_dir)
    links = ejected_symlinks(ws.config_dir)
    for sid in sorted(set(skills) | set(ejected)):
        if sid in links and sid in skills:  # never materialized from the pack behind its back
            out[sid] = Source(sid, skills[sid].pack, skills[sid].version, "ejected", links[sid],
                              None, blocked=f"{ws.rel(links[sid])} is a symlink, not an "
                                           f"ejected copy")
            continue
        if sid in ejected:
            record = read_ejected(ejected[sid])
            if record is None:
                out[sid] = Source(sid, skills[sid].pack if sid in skills else None, None,
                                  "ejected", ejected[sid],
                                  f"the ejected copy {ws.rel(ejected[sid])} {NO_RECORD}")
                continue
            version = record.get("version")
            src = Source(sid, record["pack"], version if isinstance(version, str) else None,
                         "ejected", ejected[sid], source_problem(ejected[sid], sid))
        else:
            skill = skills[sid]
            src = Source(sid, skill.pack, skill.version, "pack", skill.source,
                         source_problem(skill.source, sid, skill.pack_dir))
        src.files = {} if src.problem else source_hashes(src.dir, ws.rel)
        out[sid] = src
    return out


def plugin_sources(ws, sources: dict[str, Source]) -> dict[str, Source]:
    """`[packs] builtin_delivery = "plugin"` (P6 D2): the built-in packs' skills are not
    materialized — the copies an earlier sync made become orphans that `packs sync` removes —
    and an ejected copy of one is a conflict: syncing it would put the skill next to the
    plugin's. A repository pack's skill (any id) is synced as always."""
    builtin = {sid for sid, s in pack_skills(ws.config_dir).items() if s.builtin}
    out = {}
    for sid, src in sources.items():
        if sid in builtin and src.kind == "ejected" and not src.blocked:
            # a copy, not the shared source: an agent with "repo" delivery still syncs it
            src = replace(src, blocked=(f"ejected to {ws.rel(src.dir)} while {PLUGIN_PROVIDES} "
                                        f"— delete the ejected copy, or set [packs] "
                                        f"builtin_delivery = \"repo\""))
        if sid not in builtin or src.kind == "ejected":
            out[sid] = src
    return out


def marker_text(src: Source) -> str:
    return json.dumps({"schema": MANAGED_SCHEMA, "pack": src.pack, "skill": src.skill,
                       "version": src.version, "source": src.kind, "files": src.files},
                      indent=2, sort_keys=True) + "\n"


def _safe(rel) -> bool:
    """A marker path the engine may touch: relative, normalized, never leaving the skill."""
    return (isinstance(rel, str) and bool(rel) and not rel.startswith("/") and "\\" not in rel
            and all(part not in ("", ".", "..") for part in rel.split("/")))


def read_marker(dest: Path) -> dict | None:
    """The marker of `dest`, or None when it is missing or not a well-formed marker."""
    try:
        data = json.loads((dest / MANAGED).read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if (not isinstance(data, dict) or data.get("schema") != MANAGED_SCHEMA
            or not isinstance(data.get("pack"), str) or not isinstance(data.get("skill"), str)
            or not isinstance(data.get("files"), dict)
            or not all(_safe(k) and isinstance(v, str) for k, v in data["files"].items())):
        return None
    return data


def _in_the_way(dest: Path, rel: str, dropped: frozenset = frozenset()) -> bool:
    """A symlink or a non-directory on the way to `dest/rel`, or `dest/rel` itself a symlink or
    a directory: writing or deleting there could leave the skill directory. `dropped`: managed
    files the sync deletes BEFORE it writes — a file among them on the way, or a directory that
    holds only them, is gone by then (the source turned a file into a directory or back)."""
    path = dest
    for part in rel.split("/")[:-1]:
        path = path / part
        if path.is_symlink():
            return True
        if os.path.lexists(path) and not path.is_dir():
            return path.relative_to(dest).as_posix() not in dropped
    target = dest / rel
    if target.is_symlink():
        return True
    return target.is_dir() and not _only_dropped(dest, target, dropped)


def _only_dropped(dest: Path, directory: Path, dropped: frozenset) -> bool:
    """Every entry below `directory` is a plain directory or a file in `dropped`."""
    for dirpath, dirnames, filenames in os.walk(directory):
        for name in dirnames + filenames:
            path = Path(dirpath) / name
            if path.is_symlink() or (name in filenames
                                     and path.relative_to(dest).as_posix() not in dropped):
                return False
    return True


def _same_file(path: Path, src: Path) -> bool:
    return (sha256_file(path) == sha256_file(src)
            and stat.S_IMODE(path.stat().st_mode) == stat.S_IMODE(src.stat().st_mode))


def plan_skill(agent: str, dest: Path, src: Source) -> Plan:
    plan = Plan(agent, src.skill, dest, "invalid", src)
    if src.blocked:
        plan.status, plan.reason = "conflict", src.blocked
        return plan
    if src.problem:
        plan.reason = src.problem
        return plan
    if not os.path.lexists(dest):
        plan.status, plan.write = "created", sorted(src.files)
        return plan
    plan.status = "conflict"
    if dest.is_symlink() or not dest.is_dir():
        plan.reason = ("the destination is a symlink" if dest.is_symlink()
                       else "the destination is not a directory")
        return plan
    if not os.path.lexists(dest / MANAGED):
        plan.reason = NOT_MANAGED
        return plan
    marker = plan.marker = read_marker(dest)
    if marker is None:
        plan.reason = BAD_MARKER
        return plan
    if (marker["pack"], marker["skill"]) != (src.pack, src.skill):
        plan.reason = f"managed for pack '{marker['pack']}', skill '{marker['skill']}'"
        return plan
    problems = []
    for rel, recorded in sorted(marker["files"].items()):
        path = dest / rel
        if _in_the_way(dest, rel):
            problems.append(f"{rel} (a symlink or directory in the way)")
        elif not os.path.lexists(path):
            if rel in src.files:
                problems.append(f"{rel} (locally deleted)")
        elif sha256_file(path) not in (recorded, src.files.get(rel)):
            problems.append(f"{rel} (locally edited)")
    dropped = frozenset(set(marker["files"]) - set(src.files))
    for rel in sorted(set(src.files) - set(marker["files"])):
        path = dest / rel
        if _in_the_way(dest, rel, dropped):
            problems.append(f"{rel} (a symlink or directory in the way)")
        elif (os.path.lexists(path) and not path.is_dir()
              and sha256_file(path) != src.files[rel]):
            problems.append(f"{rel} (exists and is not managed by segmently-modules)")
    if problems:
        plan.reason = "; ".join(problems)
        return plan
    plan.write = [rel for rel in sorted(src.files)
                  if not (dest / rel).is_file() or not _same_file(dest / rel, src.dir / rel)]
    plan.delete = [rel for rel in sorted(marker["files"])
                   if rel not in src.files and os.path.lexists(dest / rel)]
    current = (dest / MANAGED).read_bytes() == marker_text(src).encode("utf-8")
    plan.status = "unchanged" if not plan.write and not plan.delete and current else "updated"
    return plan


def plan_orphans(agent: str, agent_dir: Path, wanted: set[str]) -> list[Plan]:
    """`removed` (or `conflict`) plans for managed skill directories nobody declares."""
    plans = []
    if not agent_dir.is_dir():
        return plans
    for dest in sorted(agent_dir.iterdir()):
        if (dest.name in wanted or dest.is_symlink() or not dest.is_dir()
                or not os.path.lexists(dest / MANAGED)):
            continue
        marker = read_marker(dest)
        if marker is not None and marker["skill"] != dest.name:
            continue  # a marker copied from elsewhere: not this directory's own
        plan = Plan(agent, dest.name, dest, "conflict", marker=marker)
        if marker is None:
            plan.reason = ORPHAN_BAD_MARKER
        else:
            edited = [rel for rel, recorded in sorted(marker["files"].items())
                      if os.path.lexists(dest / rel) and (_in_the_way(dest, rel)
                                                          or sha256_file(dest / rel) != recorded)]
            if edited:
                plan.reason = f"{', '.join(edited)} (locally edited; not removed)"
            else:
                plan.status = "removed"
                plan.delete = [rel for rel in sorted(marker["files"])
                               if os.path.lexists(dest / rel)]
                left = sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*")
                              if not p.is_dir() and p.name != MANAGED
                              and p.relative_to(dest).as_posix() not in marker["files"])
                plan.reason = f"left unmanaged files: {', '.join(left)}" if left else None
        plans.append(plan)
    return plans


def conflict_kind(reason: str) -> tuple[str, str | None]:
    """What a `conflict` reason is about, for the hint `packs sync` prints, and the other pack
    for `other-pack`: `orphan-bad-marker` / `orphan-edit` (a skill no pack declares any more,
    not removed), `hand-written` (no marker), `bad-marker`, `other-pack`, `edit` (a managed
    file edited or deleted locally — it wins when a reason joins several problems), else
    `in-the-way` (something the sync must not write over)."""
    if reason == ORPHAN_BAD_MARKER:
        return "orphan-bad-marker", None
    if PLUGIN_PROVIDES in reason:
        return "plugin", None
    if reason.endswith("(locally edited; not removed)"):
        return "orphan-edit", None
    if reason == NOT_MANAGED:
        return "hand-written", None
    if reason == BAD_MARKER:
        return "bad-marker", None
    other = _OTHER_PACK.fullmatch(reason)
    if other:
        return "other-pack", other.group(1)
    return ("edit" if _EDIT.search(reason) else "in-the-way"), None


def copy_file(src: Path, path: Path) -> None:
    """Write `src`'s bytes and permission bits to `path` atomically (temp file + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(src.read_bytes())
        os.chmod(tmp, stat.S_IMODE(src.stat().st_mode))
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def _prune(dest: Path, rels: list[str], including_dest: bool) -> None:
    """Remove the directories the deleted files leave empty (deepest first)."""
    dirs = {p for rel in rels for p in (dest / rel).parents if dest in p.parents}
    if including_dest:
        dirs.add(dest)
    for d in sorted(dirs, key=lambda p: -len(p.parts)):
        with contextlib.suppress(OSError):
            d.rmdir()


def _write(plan: Plan) -> None:
    for rel in plan.delete:  # first: a dropped file may stand where a new directory goes
        (plan.dest / rel).unlink()
    _prune(plan.dest, plan.delete, False)
    for rel in plan.write:
        copy_file(plan.source.dir / rel, plan.dest / rel)
    text = marker_text(plan.source)
    path = plan.dest / MANAGED
    fd, tmp = tempfile.mkstemp(dir=plan.dest, prefix=f".{MANAGED}.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)  # last: the marker only ever describes files already written


def apply_plan(plan: Plan) -> None:
    """Write, update or remove one skill. A `created` skill's directory is made here (never an
    existing one) and removed again when the write fails or is interrupted, so a rerun creates
    it instead of finding a directory without a marker; an `updated` one resumes by hash."""
    if plan.status == "created":
        plan.dest.parent.mkdir(parents=True, exist_ok=True)
        os.mkdir(plan.dest)  # exclusive: the directory is this run's alone to remove
        try:
            _write(plan)
        except BaseException:  # a failed write or Ctrl-C: no marker-less directory stays
            shutil.rmtree(plan.dest, ignore_errors=True)
            raise
    elif plan.status == "updated":
        _write(plan)
    elif plan.status == "removed":
        for rel in plan.delete:
            (plan.dest / rel).unlink()
        (plan.dest / MANAGED).unlink()
        _prune(plan.dest, plan.delete, True)


def _marked_agent_file(root: Path) -> bool:
    """Does `.codex/agents` (a plain directory, or a symlink to one) hold a regular, non-symlink
    file directly in it whose first line `read_agent_marker` reads as `ok`? Reads only."""
    base = root / CODEX_AGENTS
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return False
    for name in names:
        path = base / name
        try:
            if path.is_symlink() or not path.is_file():
                continue
            with path.open("rb") as fh:
                first = fh.readline()
        except OSError:
            continue
        if read_agent_marker(first)[0] == "ok":
            return True
    return False


def managed_agents(root: Path, agent_files: bool = False) -> list[str]:
    """The agents whose skill directory already holds a skill `packs sync` manages (a valid
    marker proves an earlier sync), in the engine's order — `packs sync` uses them when neither
    `--agent` nor `[packs] agents` names any. A directory several agents read counts once, for
    the first of them: a marker in `.agents/skills` means `codex`. `agent_files` (the caller's
    `builtin_delivery = "plugin"`: the plugin delivers the skills, so no skill copy may carry a
    marker): a `.codex/agents/` holding a marked agent file (`read_agent_marker` reads `ok`)
    also means `codex`, once. Bare `packs sync` and `next` pass it; `setup` never does."""
    out, seen = [], set()
    for agent, rel in AGENT_DIRS.items():
        if rel in seen:
            continue
        seen.add(rel)
        base = root / rel
        if base.is_dir() and any(d.is_dir() and not d.is_symlink() and read_marker(d)
                                 for d in sorted(base.iterdir())):
            out.append(agent)
        elif agent_files and agent == "codex" and _marked_agent_file(root):
            out.append(agent)
    return out


def plan_sync(ws, agents: list[str], plugin: bool | set[str] = False,
              sources: dict[str, Source] | None = None) -> list[Plan]:
    """Every (agent, skill) plan, agents in the given order, skills by id; an agent whose
    directory is the same real directory as an earlier agent's repeats that agent's plans
    with `same_as` (applied once). `plugin`: the agents whose built-in skills a plugin provides
    (`plugin_sources`; True: every agent). `sources`: `skill_sources(ws)` when the caller
    already has them."""
    sources = skill_sources(ws) if sources is None else sources
    plugged = set(agents) if plugin is True else set(plugin or ())
    by_plugin = plugin_sources(ws, sources) if plugged else sources
    plans, seen = [], {}
    for agent in agents:
        agent_dir = ws.root / AGENT_DIRS[agent]
        real = os.path.realpath(agent_dir)
        if real in seen:
            first = seen[real]
            plans += [Plan(agent, p.skill, agent_dir / p.skill, p.status, p.source, p.marker,
                           p.write, p.delete, p.reason, same_as=first)
                      for p in plans if p.agent == first]
            continue
        seen[real] = agent
        own = by_plugin if agent in plugged else sources
        mine = [plan_skill(agent, agent_dir / sid, src) for sid, src in own.items()]
        mine += plan_orphans(agent, agent_dir, set(own))
        plans += sorted(mine, key=lambda p: p.skill)
    return plans


def plan_remove(ws, agents: list[str]) -> list[Plan]:
    """`packs sync --remove` (P6 D5): every managed copy in the agents' directories becomes a
    `removed` plan — an edited one, or one whose marker is damaged, a `conflict` — as for a
    skill no pack declares any more; a directory without a marker (or with another skill's)
    gets no plan. An agent whose directory is an earlier agent's repeats its plans (`same_as`)."""
    plans, seen = [], {}
    for agent in agents:
        agent_dir = ws.root / AGENT_DIRS[agent]
        real = os.path.realpath(agent_dir)
        if real in seen:
            plans += [Plan(agent, p.skill, agent_dir / p.skill, p.status, p.source, p.marker,
                           p.write, p.delete, p.reason, same_as=seen[real])
                      for p in plans if p.agent == seen[real]]
            continue
        seen[real] = agent
        plans += plan_orphans(agent, agent_dir, set())
    return plans


def row(ws, plan: Plan) -> dict:
    src, marker = plan.source, plan.marker or {}
    files = plan.write + plan.delete if plan.status in ("created", "updated", "removed") else []
    out = {"agent": plan.agent, "skill": plan.skill,
           "pack": src.pack if src else marker.get("pack"),
           "version": src.version if src else marker.get("version"),
           "source": src.kind if src else marker.get("source"),
           "dir": ws.rel(plan.dest), "status": plan.status, "files": sorted(files),
           "reason": plan.reason}
    if plan.same_as:
        out["same_as"] = plan.same_as
    return out


# --- the Codex agent files (P8.4 D3) -------------------------------------------------------------

AGENT_STATUSES = ("created", "updated", "unchanged", "removed", "conflict")
AGENT_MARKER = "# segmently-modules-managed: "  # the first line of every agent file packs sync manages
AGENT_NOT_MANAGED = "not managed by segmently-modules (its first line is no segmently-modules-managed marker)"
AGENT_BAD_MARKER = "its segmently-modules-managed first line is not a valid marker"
_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass
class AgentPlan:
    """The decided status of one Codex agent file and the bytes a write puts there."""
    name: str
    path: Path
    status: str
    pack: str | None = None
    skill: str | None = None
    version: str | None = None
    reason: str | None = None
    data: bytes | None = None  # created / updated: the whole file


def toml_string(text: str, multiline: bool = False) -> str:
    """`text` as a TOML basic string that `tomllib` reads back exactly: a backslash, a control
    character (tab and, multi-line, newline aside) and a quote are escaped — in a multi-line
    string only a quote that another quote follows, or the last character, so three never
    meet. A multi-line string opens with three double quotes and a newline (TOML drops a
    newline right after them)."""
    out = []
    for i, ch in enumerate(text):
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            escape = not multiline or i + 1 == len(text) or text[i + 1] == '"'
            out.append('\\"' if escape else '"')
        elif ch == "\t" or (ch == "\n" and multiline):
            out.append(ch)
        elif ch in "\n\r":
            out.append("\\n" if ch == "\n" else "\\r")
        elif ord(ch) < 0x20 or ch == "\x7f":
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    body = "".join(out)
    return f'"""\n{body}"""' if multiline else f'"{body}"'


def codex_instructions(name: str) -> str:
    """The `developer_instructions` of agent `name`: run its skill, return its output; read the
    skill's copy by its path only when the skill is not available (P8.6 D1)."""
    return (AGENT_BODY + CODEX_FALLBACK).format(skill=SKILL_AGENTS[name]["skill"]) + "\n"


def codex_agent(name: str, pack: str | None, skill: str, version: str | None) -> bytes:
    """The bytes of `.codex/agents/<name>.toml`: the marker line, then `name`, `description`
    (the agent table's) and `developer_instructions` (`codex_instructions`)."""
    body = (f"name = {toml_string(name)}\n"
            f"description = {toml_string(SKILL_AGENTS[name]['description'])}\n"
            f"developer_instructions = {toml_string(codex_instructions(name), multiline=True)}\n"
            ).encode("utf-8")
    marker = {"schema": MANAGED_SCHEMA, "pack": pack, "skill": skill, "version": version,
              "sha256": hashlib.sha256(body).hexdigest()}
    return (AGENT_MARKER + json.dumps(marker) + "\n").encode("utf-8") + body


def read_agent_marker(data: bytes) -> tuple[str, dict | None, bytes]:
    """(`none` | `bad` | `ok`, the marker, the bytes after its line) of an agent file's bytes:
    `none` when the first line is not a segmently-modules-managed marker line at all."""
    line, _, rest = data.partition(b"\n")
    if not line.startswith(AGENT_MARKER.rstrip().encode()):
        return "none", None, rest
    try:
        marker = json.loads(line[len(AGENT_MARKER.rstrip()):].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "bad", None, rest
    if (not isinstance(marker, dict) or marker.get("schema") != MANAGED_SCHEMA
            or not isinstance(marker.get("pack"), str) or not isinstance(marker.get("skill"), str)
            or not isinstance(marker.get("version"), (str, type(None)))
            or not isinstance(marker.get("sha256"), str)
            or not _SHA256.fullmatch(marker["sha256"])):
        return "bad", None, rest
    return "ok", marker, rest


def codex_dir_problem(root: Path) -> tuple[str, bool] | None:
    """(the path, is it a symlink) when `.codex/agents`, or `.codex`, cannot hold the agent
    files: it is a symlink or not a directory — nothing is written or removed through it."""
    path = root
    for part in CODEX_AGENTS.split("/"):
        path = path / part
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            return rel, True
        if os.path.lexists(path) and not path.is_dir():
            return rel, False
    return None


def _behind_symlink(base: Path, rel: str) -> list[AgentPlan]:
    """No agent wanted and `rel` (`.codex/agents` or `.codex`) a symlink: a read-only look
    behind it. Each agent file there whose first line is a segmently-modules marker line (a damaged one
    too) is a `conflict` — packs sync would remove it, but never through a symlink; a file
    without one is not ours and gives no row."""
    plans = []
    for name in sorted(SKILL_AGENTS):
        path = base / f"{name}.toml"
        if not os.path.lexists(path) or path.is_symlink() or not path.is_file():
            continue
        kind, marker, _ = read_agent_marker(path.read_bytes())
        if kind == "none":
            continue
        who = ((marker["pack"], marker["skill"], marker.get("version")) if kind == "ok"
               else (None, SKILL_AGENTS[name]["skill"], None))
        plans.append(AgentPlan(name, path, "conflict", *who,
                               reason=f"{rel} is a symlink — packs sync cannot remove "
                                      f"{path.name} through it"))
    return plans


def agent_sources(sources: dict[str, Source]) -> tuple[dict[str, Source], set[str]]:
    """({agent: its skill's source} of the agents to write, the agents whose skill's source is
    not loadable — their files stay as they are). A skill no pack declares has no agent."""
    wanted, held = {}, set()
    for name, spec in sorted(SKILL_AGENTS.items()):
        src = sources.get(spec["skill"])
        if src is None:
            continue
        if src.problem or src.blocked:
            held.add(name)
            continue
        wanted[name] = src
    return wanted, held


def _plan_agent(path: Path, name: str, src: Source) -> AgentPlan:
    data = codex_agent(name, src.pack, src.skill, src.version)
    plan = AgentPlan(name, path, "created", src.pack, src.skill, src.version, data=data)
    if not os.path.lexists(path):
        return plan
    plan.status, plan.data = "conflict", None
    if path.is_symlink() or not path.is_file():
        plan.reason = ("the destination is a symlink" if path.is_symlink()
                       else "the destination is not a file")
        return plan
    old = path.read_bytes()
    if old == data:
        plan.status = "unchanged"
        return plan
    kind, marker, rest = read_agent_marker(old)
    if kind == "none":
        plan.reason = AGENT_NOT_MANAGED
    elif kind == "bad":
        plan.reason = AGENT_BAD_MARKER
    elif (marker["pack"], marker["skill"]) != (src.pack, src.skill):
        plan.reason = f"managed for pack '{marker['pack']}', skill '{marker['skill']}'"
    elif (hashlib.sha256(rest).hexdigest() != marker["sha256"]
          and rest != data.partition(b"\n")[2]):
        plan.reason = f"{path.name} (locally edited)"
    else:
        plan.status, plan.data = "updated", data
    return plan


def _plan_agent_orphan(path: Path, name: str) -> AgentPlan | None:
    """`removed` (or `conflict`) for a managed agent file nobody wants; None for no file, or one
    without a marker line (never ours to remove)."""
    if not os.path.lexists(path) or path.is_symlink() or not path.is_file():
        return None
    kind, marker, rest = read_agent_marker(path.read_bytes())
    if kind == "none":
        return None
    if kind == "bad":
        return AgentPlan(name, path, "conflict", skill=SKILL_AGENTS[name]["skill"],
                         reason=f"{AGENT_BAD_MARKER} (not removed)")
    plan = AgentPlan(name, path, "removed", marker["pack"], marker["skill"], marker.get("version"))
    if hashlib.sha256(rest).hexdigest() != marker["sha256"]:
        plan.status, plan.reason = "conflict", f"{path.name} (locally edited; not removed)"
    return plan


def plan_agent_files(ws, sources: dict[str, Source] | None, remove: bool = False
                     ) -> list[AgentPlan]:
    """Every Codex agent file's plan, by name: the agents to write (`agent_sources` of the
    `sources` the skill copies come from) and the managed files nobody wants any more —
    `remove` (`packs sync --remove --agent codex`): every managed file. When `.codex/agents`
    (or `.codex`) is a symlink or not a directory, nothing is written or removed through it
    (P84-AC-007, amended): while the repository wants the agents (one to write, or one held by
    its skill's problem) all three files are a `conflict`; when it wants none (core disabled, a
    repository `core` without the wrapped skills, `remove`) only a marked file behind a
    symlink is one (`_behind_symlink`) — a regular file has nothing behind it."""
    base = ws.root / CODEX_AGENTS
    wanted, held = ({}, set()) if remove else agent_sources(sources or {})
    problem = codex_dir_problem(ws.root)
    if problem and not (wanted or held):
        rel, link = problem
        return _behind_symlink(base, rel) if link else []
    if problem:
        rel, link = problem
        reason = (f"{rel} is a symlink — packs sync writes nothing through it" if link
                  else f"{rel} is not a directory")
        return [AgentPlan(name, base / f"{name}.toml", "conflict",
                          *((wanted[name].pack, wanted[name].skill,
                             wanted[name].version) if name in wanted
                            else (None, SKILL_AGENTS[name]["skill"], None)), reason=reason)
                for name in sorted(SKILL_AGENTS)]
    plans = []
    for name in sorted(SKILL_AGENTS):
        path = base / f"{name}.toml"
        if name in wanted:
            plans.append(_plan_agent(path, name, wanted[name]))
        elif name not in held and (orphan := _plan_agent_orphan(path, name)):
            plans.append(orphan)
    return plans


def apply_agent_file(plan: AgentPlan) -> None:
    """Write (whole: a temp file renamed over it, mode 0644) or delete one agent file; the
    parent directories are made as needed."""
    if plan.status == "removed":
        plan.path.unlink()
        return
    if plan.status not in ("created", "updated"):
        return
    plan.path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=plan.path.parent, prefix=f".{plan.path.name}.",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(plan.data)
        os.chmod(tmp, 0o644)
        os.replace(tmp, plan.path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def agent_row(ws, plan: AgentPlan) -> dict:
    return {"agent": "codex", "name": plan.name, "path": ws.rel(plan.path),
            "status": plan.status, "pack": plan.pack, "skill": plan.skill,
            "version": plan.version, "reason": plan.reason}
