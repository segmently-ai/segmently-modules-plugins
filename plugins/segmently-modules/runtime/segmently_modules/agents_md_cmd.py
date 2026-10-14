"""`segmently-modules agents-md --target FILE…`: keep one managed block in agent instruction files
(`CLAUDE.md`, `AGENTS.md`, …). The block is the line `<!-- segmently-modules:begin v1 -->`, the rendered
template `agents-md.md` (resolved like every template, so a team or a pack can override it) and
the line `<!-- segmently-modules:end -->`. Only the lines from the begin marker through the end marker are
ever rewritten; every other byte of the file is kept, the block takes the file's newline style,
and the file is replaced atomically — through a symlink, keeping its mode."""
from __future__ import annotations

import os
import re
import string
from pathlib import Path

from segmently_modules import __version__
from segmently_modules.config import builtin_delivery, enabled_roles, plugin_agents
from segmently_modules.create import resolve_template
from segmently_modules.output import EXIT_FINDINGS, EXIT_OK, UsageError, emit
from segmently_modules.skill_sync import skill_sources
from segmently_modules.skills import pack_skills, read_front_matter
from segmently_modules.store import atomic_write
from segmently_modules.workspace import Workspace

BEGIN, END = "<!-- segmently-modules:begin v1 -->", "<!-- segmently-modules:end -->"
_BEGIN = re.compile(r"<!-- segmently-modules:begin v\d+ -->")
SKILLS_DELIVERY = {"repo": "`segmently-modules packs sync` copies them into the agents' skill directories",
                   "plugin": "the segmently-modules plugins provide these skills"}
NO_SKILLS = "- none yet (add one: segmently-modules packs new ID --skill NAME)"


def register(sub, common) -> None:
    p = sub.add_parser("agents-md", parents=[common],
                       help="keep the segmently-modules block in agent instruction files (CLAUDE.md, "
                            "AGENTS.md)",
                       description="Write or refresh one managed block — <!-- segmently-modules:begin v1 "
                                   "--> … <!-- segmently-modules:end --> — in each target file: how agents "
                                   "use segmently-modules here, the roles and the pack skills (the "
                                   "agents-md.md template). Text outside the markers is never "
                                   "changed.")
    p.add_argument("--target", action="append", dest="targets", required=True, metavar="FILE",
                   help="a root-relative instruction file, e.g. CLAUDE.md or AGENTS.md "
                        "(repeatable)")
    p.add_argument("--check", action="store_true",
                   help="write nothing; exit 1 unless every target is unchanged (CI)")
    p.add_argument("--dry-run", action="store_true", help="report the statuses, write nothing")
    p.set_defaults(func=run)


def _skill_line(sid, src) -> str:
    meta = read_front_matter(src.dir / "SKILL.md") or {}
    full = " ".join((meta.get("description") or "").split())
    description = full.split(". ")[0]
    if description != full:  # a sentence cut off its text keeps its full stop
        description += "."
    return f"- `{sid}` — {description}" if description else f"- `{sid}`"


def skill_groups(ws) -> list[tuple[str, str]]:
    """[(delivery key, lines)] — one line per pack skill, `` - `<skill>` — <first sentence of
    the description> ``, from the source `packs sync` uses (an ejected copy first). Under
    `builtin_delivery = "plugin"` (or a table that gives "plugin" to some agents) the skills of
    an enabled built-in pack (not ejected, not shadowed by a repository pack) are the `plugin`
    group, listed first; every other skill is the `repo` group (`packs sync` still copies it).
    An empty group is left out."""
    plugin = builtin_delivery(ws.config) != "repo"
    builtin = ({sid for sid, s in pack_skills(ws.config_dir).items() if s.builtin}
               if plugin else set())
    groups = {"plugin": [], "repo": []}
    for sid, src in skill_sources(ws).items():
        key = "plugin" if sid in builtin and src.kind == "pack" else "repo"
        groups[key].append(_skill_line(sid, src))
    return [(k, "\n".join(v)) for k, v in groups.items() if v] or [("repo", NO_SKILLS)]


def render_block(ws) -> list[str]:
    """The block's lines, markers included, without line ends."""
    groups = skill_groups(ws)
    words = dict(SKILLS_DELIVERY)
    if builtin_delivery(ws.config) == "mixed":  # a table: name the agents the plugins serve
        from segmently_modules.skills import AGENT_DIRS
        words["plugin"] = (f"the segmently-modules plugins provide these skills for "
                           f"{', '.join(sorted(plugin_agents(ws.config, AGENT_DIRS)))}; "
                           f"`segmently-modules packs sync` copies them for the other agents")
    skills = groups[0][1]
    for key, lines in groups[1:]:
        skills += f"\nSkills from packs ({words[key]}):\n{lines}"
    values = {"modules_dir": ws.config["paths"]["modules_dir"],
              "registry": ws.config["paths"]["registry"],
              "roles": ", ".join(enabled_roles(ws.config)), "skills": skills,
              "skills_delivery": words[groups[0][0]], "version": __version__}
    body = string.Template(resolve_template(ws, "agents-md.md")).safe_substitute(values)
    return [BEGIN, *body.replace("\r\n", "\n").rstrip("\n").split("\n"), END]


def _target(ws, target: str) -> tuple[str, Path]:
    """(root-relative posix path, path) of a `--target`; outside the root or a directory is
    refused."""
    path = Path(os.path.normpath(Path(target) if Path(target).is_absolute()
                                 else ws.root / target))
    try:
        rel = path.relative_to(ws.root).as_posix()
    except ValueError:
        raise UsageError(f"--target {target}: outside the repository root {ws.root}") from None
    if rel == "." or path.is_dir():
        raise UsageError(f"--target {target} is a directory, not an instruction file")
    return rel, path


def _lines(text: str) -> list[str]:
    """The file's lines with their `\\n` ends (a last line without one kept as is)."""
    parts = text.split("\n")
    return [p + "\n" for p in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def _bare(line: str) -> str:
    line = line[:-1] if line.endswith("\n") else line
    return line[:-1] if line.endswith("\r") else line


def updated_text(rel: str, text: str | None, block: list[str]) -> tuple[str, str]:
    """(status, new text): `created` (no file), `added` (no markers: appended after one blank
    line), `updated` / `unchanged` (the lines from begin through end replaced). Malformed
    markers are exit 2 naming the file and line."""
    if text is None:
        return "created", "\n".join(block) + "\n"
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = _lines(text)
    begins = [i for i, line in enumerate(lines) if _BEGIN.fullmatch(_bare(line))]
    ends = [i for i, line in enumerate(lines) if _bare(line) == END]
    if not begins and not ends:
        if not text:
            return "added", nl.join(block) + nl
        body = text if text.endswith("\n") else text + nl
        blank = "" if body.endswith(nl + nl) or body == nl else nl
        return "added", body + blank + nl.join(block) + nl
    if len(begins) == 1 and len(ends) == 1 and begins[0] < ends[0]:
        b, e = begins[0], ends[0]
        tail = lines[e][len(_bare(lines[e])):]  # the end line keeps its own line end
        new = "".join(lines[:b] + [line + nl for line in block[:-1]] + [block[-1] + tail]
                      + lines[e + 1:])
        return ("unchanged" if new == text else "updated"), new
    if len(begins) > 1:
        line, what = begins[1], f"a second begin marker (the first is on line {begins[0] + 1})"
    elif len(ends) > 1:
        line, what = ends[1], f"a second end marker (the first is on line {ends[0] + 1})"
    elif not ends:
        line, what = begins[0], f"a begin marker without an end marker ({END})"
    else:
        line, what = ends[0], "an end marker before any begin marker"
    raise UsageError(f"{rel}:{line + 1}: {what} — fix the markers by hand; nothing written")


def agents_md(ws, targets: list[str], check: bool, dry_run: bool) -> dict:
    """Plan every target first (a malformed or unreadable one stops the run before any
    write), then write what changed unless `check` / `dry_run`."""
    if check and dry_run:
        raise UsageError("--check and --dry-run cannot be combined (--check never writes)")
    block = render_block(ws)
    rows, writes, seen = [], [], {}
    for target in targets:
        rel, path = _target(ws, target)
        real = Path(os.path.realpath(path))
        if real in seen:
            first = seen[real]
            rows.append({"path": rel, "status": first["status"], "same_as": first["path"]})
            continue
        text = None
        if real.exists():
            try:
                text = real.read_bytes().decode("utf-8")
            except UnicodeDecodeError:
                raise UsageError(f"{rel} is not valid UTF-8 text; nothing written") from None
            except OSError as e:
                raise UsageError(f"cannot read {rel}: {e.strerror or e}") from None
        status, new = updated_text(rel, text, block)
        row = {"path": rel, "status": status}
        rows.append(row)
        seen[real] = row
        if status != "unchanged":
            writes.append((rel, real, new))
    if not check and not dry_run:
        for rel, real, new in writes:
            try:
                atomic_write(real, new)  # the link's target: a symlink stays a symlink
            except OSError as e:
                raise UsageError(f"cannot write {rel}: {e.strerror or e}") from None
    return {"targets": rows, "check": check, "dry_run": dry_run}


def run(args) -> int:
    ws = Workspace.from_args(args)
    data = agents_md(ws, args.targets, args.check, args.dry_run)
    emit("agents-md", data, args.json, _render)
    stale = any(r["status"] != "unchanged" for r in data["targets"])
    return EXIT_FINDINGS if args.check and stale else EXIT_OK


def _render(d) -> None:
    for r in d["targets"]:
        same = f"  (same file as {r['same_as']})" if r.get("same_as") else ""
        print(f"{r['status']:<10} {r['path']}{same}")
    if d["check"] and any(r["status"] != "unchanged" for r in d["targets"]):
        print("agents-md --check: stale — run segmently-modules agents-md with the same --target flags")
