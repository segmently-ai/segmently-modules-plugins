"""Pack skills (the Agent Skills format): the `[skills.<id>]` model of a pack, the `SKILL.md`
front-matter reader and the checks that decide whether agents can load a skill.

A pack declares a skill as a `[skills.<id>]` table in its `pack.toml` — a pack meta key, never
merged into the config: `path` (required: the skill directory, relative to the pack) and
`reads_roles` (optional: the roles whose module docs the skill reads). The id follows the
Agent Skills name rule and must equal the `name` in the skill's `SKILL.md` front matter. When
two packs declare one id, the higher-precedence pack's declaration wins everywhere (plain
`lint` reports the other as MS065)."""
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from segmently_modules.config import discover_packs
from segmently_modules.output import UsageError

SKILL_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SKILL_ID_MAX = 64
SKILL_KEYS = ("path", "reads_roles")
NAME_RULE = "1–64 characters: lowercase letters and digits, words joined by single hyphens"
DESCRIPTION_MAX = 1024
# where each agent reads skills, in the engine's agent order (P6 D5: cursor, gemini and copilot
# share codex's `.agents/skills` — one write per directory, however many agents read it)
AGENT_DIRS = {"claude": ".claude/skills", "codex": ".agents/skills", "cursor": ".agents/skills",
              "gemini": ".agents/skills", "copilot": ".agents/skills"}
DEFAULT_AGENTS = ("claude", "codex")  # the agents a hint names when none was chosen
MANAGED = ".segmently-modules-managed"  # the marker `packs sync` writes into every skill it manages
EJECTED = ".segmently-modules-ejected"  # the record `segmently-modules eject` writes into an ejected copy
EJECTED_SCHEMA = "segmently-modules.ejected/1"
NOT_COPIED = {MANAGED, EJECTED, ".DS_Store"}  # never part of a skill's files
# The agents that run a skill in their own context (P8.4 D3, P8.6 D1): the one table that the
# plugin build (`tools/build_plugins.py`: the `segmently-modules` plugin's `agents/<name>.md`, Claude Code)
# and `packs sync` (`.codex/agents/<name>.toml`, Codex) read — agent name -> the skill it runs,
# and the agent's one-sentence description. An agent's body only runs its skill (`AGENT_BODY`
# and the platform's fallback line); no skill text is copied into it — the skill is the one
# source. Plain literals: the build reads them from this file without importing the engine.
SKILL_AGENTS = {
    "module-discover-agent": {
        "skill": "module-discover",
        "description": "Maps a confirmed task, a branch or changed files to the modules, docs and "
                       "code files they touch through the segmently-modules CLI, read-only, and reports the "
                       "touch-set with file:line evidence."},
    "module-research-agent": {
        "skill": "module-research",
        "description": "Answers one question about one or more modules in depth from their docs "
                       "and code through the segmently-modules CLI, read-only, with file:line evidence and "
                       "every place where the two disagree."},
    "module-scout-agent": {
        "skill": "module-scout",
        "description": "Reads the modules a task under discussion names or implies through the "
                       "segmently-modules CLI, read-only, and reports a short brief of what each owns, its "
                       "rules and its linked modules."},
}
AGENT_BODY = ("Run the `{skill}` skill on the task you are handed, verbatim, with what the "
              "caller settled (files, constraints, the depth), and return its output "
              "unchanged: its report, or the question it asks the user.")
# Claude Code: the front matter preloads the skill (`skills:`); the Skill tool is the fallback
CLAUDE_FALLBACK = (" If the skill's text is not in your context, load it with the Skill tool "
                   "(`segmently-modules:{skill}`) first.")
# Codex: a custom agent inherits the session's skills; reading the copy by its path is the fallback
CODEX_FALLBACK = (" Only when that skill is not available to you, read "
                  "`.agents/skills/{skill}/SKILL.md` and follow it.")
CODEX_AGENTS = ".codex/agents"  # where `packs sync` writes the agents for Codex
_KEY = re.compile(r"^([A-Za-z_][\w.-]*)[ \t]*:(?:[ \t]+(.*))?$")
_BLOCK = re.compile(r"^([|>])(?:[1-9]?[+-]?|[+-][1-9])$")  # block scalar indicator
_COMMENT = re.compile(r"[ \t]+#.*$")
_PLAIN_STARTS = "`@%*&![{"  # characters a plain YAML scalar cannot start with
_PLAIN_COLON = re.compile(r":(?:\s|$)")  # `: ` inside, or `:` at the end, of a plain scalar


def skill_id_ok(value: str) -> bool:
    return len(value) <= SKILL_ID_MAX and bool(SKILL_ID.fullmatch(value))


def validate_skills(data: dict, source) -> None:
    """Config errors (exit 2, naming `source`) in the `[skills.<id>]` tables of one pack.
    Missing files and unknown keys are lint findings instead (MS062, MS060)."""
    skills = data.get("skills")
    if skills is None:
        return
    if not isinstance(skills, dict):
        raise UsageError(f"{source}: skills must be a table of [skills.<id>] tables, "
                         f"got {skills!r}")
    for sid, spec in skills.items():
        if not isinstance(spec, dict):
            raise UsageError(f"{source}: skills.{sid} must be a table ([skills.{sid}]), "
                             f"got {spec!r}")
        if not skill_id_ok(sid):
            raise UsageError(f"{source}: skill id {sid!r}: {NAME_RULE} (the Agent Skills "
                             f"name rule)")
        if "path" not in spec:
            raise UsageError(f"{source}: [skills.{sid}] path is missing (the skill directory, "
                             f"relative to the pack)")
        if not isinstance(spec["path"], str):
            raise UsageError(f"{source}: [skills.{sid}] path: expected a string, "
                             f"got {spec['path']!r}")
        roles = spec.get("reads_roles", [])
        if not (isinstance(roles, list) and all(isinstance(r, str) for r in roles)):
            raise UsageError(f"{source}: [skills.{sid}] reads_roles: expected a list of "
                             f"strings, got {roles!r}")


def _unquote(value: str) -> str | None:
    """A quoted scalar's text (None when `value` is not one complete quoted scalar, optionally
    followed by a comment)."""
    quote = value[:1]
    if quote not in ("'", '"'):
        return None
    i = 1
    while i < len(value):
        if quote == '"' and value[i] == "\\":
            i += 2
            continue
        if value[i] == quote:
            if quote == "'" and value[i + 1:i + 2] == "'":
                i += 2
                continue
            rest = value[i + 1:].strip()
            if rest and not rest.startswith("#"):
                return None
            inner = value[1:i]
            if quote == "'":
                return inner.replace("''", "'")
            try:
                return json.loads(f'"{inner}"')
            except json.JSONDecodeError:
                return inner
        i += 1
    return None


def _fold(lines: list[str]) -> str:
    """`>` block: lines joined with spaces; a blank line starts a new line."""
    paragraphs, current = [], []
    for line in lines:
        if line:
            current.append(line)
        elif current:
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    return "\n".join(paragraphs)


def front_matter(text: str) -> dict[str, str] | None:
    """The top-level `key: value` pairs of a `SKILL.md` front matter, or None when there is
    none (the first line is not `---`, or no later line is). A stdlib-only reader for what
    skills use: quoted scalars are unquoted; block scalars (`|`, `>`, with `-` / `+`) are
    joined from their indented lines (`>` folded with spaces) and never end in a newline; a
    plain scalar's indented continuation lines are folded with spaces (a quoted scalar over
    several lines is folded the same way, then unquoted); the indented lines
    under a key without a value (e.g. `metadata:`) are skipped (the key reads as ""); comment
    lines are skipped. A UTF-8 BOM and `\\r\\n` line ends are accepted."""
    parsed = _front_matter(text)
    return None if parsed is None else parsed[0]


def _front_matter(text: str) -> tuple[dict[str, str], set[str]] | None:
    """`front_matter` plus the keys whose value is a plain (unquoted, non-block) scalar."""
    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].rstrip() != "---":
        return None
    end = next((i for i in range(1, len(lines)) if lines[i].rstrip() == "---"), None)
    if end is None:
        return None
    out: dict[str, str] = {}
    plain: set[str] = set()
    key, style, value, extra = None, "skip", "", []

    def flush() -> None:
        if key is None:
            return
        plain.discard(key)
        if style in ("|", ">"):
            indent = min((len(l) - len(l.lstrip()) for l in extra if l.strip()), default=0)
            body = [l[indent:].rstrip() if l.strip() else "" for l in extra]
            out[key] = ("\n".join(body) if style == "|" else _fold(body)).strip("\n")
        elif style == "plain":
            joined = " ".join([value] + [l.strip() for l in extra if l.strip()])
            quoted = _unquote(joined) if extra else None  # a quoted scalar over several lines
            out[key] = joined if quoted is None else quoted
            if quoted is None:
                plain.add(key)
        else:
            out[key] = value

    for line in lines[1:end]:
        if line[:1] in (" ", "\t") or not line.strip():
            if key is not None and style != "skip":
                extra.append(line if line.strip() else "")
            continue
        if line.startswith("#"):
            continue
        flush()
        m = _KEY.match(line.rstrip())
        if not m:
            key = None
            continue
        key, raw, extra = m.group(1), (m.group(2) or "").strip(), []
        if not raw:
            style, value = "skip", ""
        elif _BLOCK.match(_COMMENT.sub("", raw)):
            style, value = raw[0], ""
        elif (quoted := _unquote(raw)) is not None:
            style, value = "quoted", quoted
        else:
            style, value = "plain", _COMMENT.sub("", raw).strip()
    flush()
    return out, plain


def _read_front_matter(path: Path) -> tuple[dict[str, str], set[str]] | None:
    try:
        return _front_matter(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError):
        return None


def read_front_matter(path: Path) -> dict[str, str] | None:
    """`front_matter` of a file; None when it is unreadable or not UTF-8."""
    parsed = _read_front_matter(path)
    return None if parsed is None else parsed[0]


def strict_yaml_problem(key: str, value: str) -> str | None:
    """Why agents' strict YAML loaders would reject `key`'s plain (unquoted) value although the
    lenient reader above takes it: a `: ` inside or a `:` at the end, or a first character
    that starts another YAML construct. Quoting the value fixes it."""
    if value[:1] in ('"', "'", "|", ">"):
        return None
    what = (f"start with '{value[0]}'" if value[:1] and value[0] in _PLAIN_STARTS
            else "end with ':'" if value.endswith(":")
            else "contain ': '" if _PLAIN_COLON.search(value) else None)
    return (f"SKILL.md {key}: quote the value — a plain YAML value cannot {what} (agents' YAML "
            f"loaders reject it)") if what else None


def first_symlink(directory: Path) -> str | None:
    """The first symlink below `directory` (posix, relative to it), never following one."""
    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames.sort()
        for name in sorted(dirnames + filenames):
            path = Path(dirpath) / name
            if path.is_symlink():
                return path.relative_to(directory).as_posix()
    return None


def _inside(path: Path, base: Path) -> bool:
    return path == base or base in path.parents


def inside(path: Path, base: Path) -> bool:
    """`path` is `base` or lies below it, both as written (normalized) and with every symlink
    resolved — the one containment check of pack skills (MS062) and role templates (MS061)."""
    return _inside(Path(os.path.normpath(path.absolute())),
                   Path(os.path.normpath(base.absolute()))) and _inside(
        Path(os.path.realpath(path)), Path(os.path.realpath(base)))


def source_problem(src: Path, skill_id: str, pack_dir: Path | None = None) -> str | None:
    """Why agents could not load the skill in directory `src` — lint MS062, `packs sync`
    status `invalid`, `eject` refusals — or None. `pack_dir`: the pack the source must stay
    inside (a pack skill); None for an ejected copy."""
    if pack_dir is not None and not inside(src, pack_dir):
        return "the path is outside the pack directory"
    if not os.path.lexists(src):
        return "the path does not exist"
    if src.is_symlink():
        return "symlink in source: ."
    if not src.is_dir():
        return "the path is not a directory"
    link = first_symlink(src)
    if link:
        return f"symlink in source: {link}"
    md = src / "SKILL.md"
    if not md.is_file():
        return "no SKILL.md"
    parsed = _read_front_matter(md)
    if parsed is None:
        return "SKILL.md has no front matter (a --- block at the top, closed by a --- line)"
    meta, plain = parsed
    name = meta.get("name")
    if not name:
        return "SKILL.md front matter has no name"
    if name != skill_id:
        return f"SKILL.md name '{name}' is not the skill id '{skill_id}'"
    for key in ("name", "description"):
        problem = strict_yaml_problem(key, meta[key]) if key in plain else None
        if problem:
            return problem
    description = meta.get("description", "")
    if not description.strip():
        return "SKILL.md front matter has no description"
    if len(description) > DESCRIPTION_MAX:
        return (f"SKILL.md description has {len(description)} characters "
                f"(max {DESCRIPTION_MAX})")
    return None


def skill_files(directory: Path) -> list[str]:
    """The files a skill is made of (posix, relative to `directory`, sorted): every regular
    file below it, recursively, except `__pycache__/`, `*.pyc`, `.DS_Store` and the engine's
    own markers. Symlinks are never followed (a source holding one is not loadable)."""
    out = []
    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        for name in filenames:
            path = Path(dirpath) / name
            if (name in NOT_COPIED or name.endswith(".pyc") or path.is_symlink()
                    or not path.is_file()):
                continue
            out.append(path.relative_to(directory).as_posix())
    return sorted(out)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_hashes(directory: Path) -> dict[str, str]:
    """{relative path: sha256} of a skill's files (`skill_files`)."""
    return {rel: sha256_file(directory / rel) for rel in skill_files(directory)}


def source_hashes(directory: Path, show) -> dict[str, str]:
    """`file_hashes` for a verb that copies or renders the skill: an unreadable file is exit 2
    `cannot read <path>: <reason>` (`show` prints the path), never an internal error."""
    try:
        return file_hashes(directory)
    except OSError as e:
        raise UsageError(f"cannot read {show(e.filename or directory)}: "
                         f"{e.strerror or e}") from None


@dataclass
class PackSkill:
    """One `[skills.<id>]` declaration of an installed pack."""
    id: str
    pack: str
    version: str | None
    pack_dir: Path
    pack_toml: Path
    path: str
    reads_roles: list[str]
    shadowed_by: str | None = None  # the higher-precedence pack that declares the same id
    builtin: bool = False  # a pack the engine ships: its version is the engine version

    @property
    def source(self) -> Path:
        return self.pack_dir / self.path


def declared_skills(config_dir: Path) -> list[PackSkill]:
    """Every skill declaration of every installed pack: packs in precedence order (highest
    first), each pack's skills in declaration order."""
    out, first = [], {}
    for pack in discover_packs(config_dir):
        version = pack["data"].get("version")
        for sid, spec in (pack["data"].get("skills") or {}).items():
            out.append(PackSkill(sid, pack["id"], version if isinstance(version, str) else None,
                                 pack["path"].parent, pack["path"], spec["path"],
                                 list(spec.get("reads_roles", [])), first.get(sid),
                                 bool(pack.get("builtin"))))
            first.setdefault(sid, pack["id"])
    return out


def pack_skills(config_dir: Path) -> dict[str, PackSkill]:
    """The declaration each skill id resolves to (the highest-precedence pack's), by id."""
    return {s.id: s for s in sorted(declared_skills(config_dir), key=lambda s: s.id)
            if s.shadowed_by is None}


def ejected_dir(config_dir: Path, skill_id: str) -> Path:
    """Where `segmently-modules eject` puts a skill's repo-owned copy."""
    return config_dir / "overrides" / "skills" / skill_id


def ejected_copies(config_dir: Path) -> dict[str, Path]:
    """Every ejected copy by skill id: the directories under `<config_dir>/overrides/skills/`."""
    root = config_dir / "overrides" / "skills"
    if not root.is_dir():
        return {}
    return {d.name: d for d in sorted(root.iterdir()) if d.is_dir() and not d.is_symlink()}


def ejected_symlinks(config_dir: Path) -> dict[str, Path]:
    """The symlinks under `<config_dir>/overrides/skills/`, by name: never an ejected copy —
    `eject` refuses them as in the way, `packs sync` reports a conflict, lint MS063; their
    target is never read."""
    root = config_dir / "overrides" / "skills"
    if not root.is_dir():
        return {}
    return {d.name: d for d in sorted(root.iterdir()) if d.is_symlink()}


def is_ejected(config_dir: Path, skill_id: str) -> bool:
    """An ejected copy exists: a real directory (a symlink there is not one)."""
    path = ejected_dir(config_dir, skill_id)
    return path.is_dir() and not path.is_symlink()


def read_ejected(directory: Path) -> dict | None:
    """The `.segmently-modules-ejected` record of an ejected copy — {schema, skill, pack, version, files:
    {path: sha256}}, the upstream snapshot at eject time — or None when missing or malformed."""
    try:
        data = json.loads((directory / EJECTED).read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if (not isinstance(data, dict) or data.get("schema") != EJECTED_SCHEMA
            or not isinstance(data.get("skill"), str) or not isinstance(data.get("pack"), str)
            or not isinstance(data.get("files"), dict)):
        return None
    return data


def behind_reason(skill: PackSkill, record: dict,
                  upstream: dict[str, str] | None = None) -> str | None:
    """Why the pack moved on since the eject, or None — the one rule of lint MS063 and `eject
    --diff`: another pack, another version, or other files. The version counts for a
    repository pack only: a built-in pack's version is the engine's, so an engine upgrade that
    leaves the skill's files alone is no move. `upstream`: the pack source's `file_hashes` when
    the caller already has them (hashed here otherwise; an unreadable file raises OSError)."""
    if upstream is None:
        upstream = file_hashes(skill.source) if skill.source.is_dir() else {}
    if skill.pack != record["pack"]:
        return f"ejected from pack '{record['pack']}', now declared by pack '{skill.pack}'"
    if not skill.builtin and skill.version != record.get("version"):
        return f"ejected from {record.get('version')}, pack is now {skill.version}"
    if upstream != record["files"]:
        return "the pack's files changed since the eject"
    return None


def is_behind(skill: PackSkill, record: dict, upstream: dict[str, str] | None = None) -> bool:
    """`behind_reason` is not None."""
    return behind_reason(skill, record, upstream) is not None
