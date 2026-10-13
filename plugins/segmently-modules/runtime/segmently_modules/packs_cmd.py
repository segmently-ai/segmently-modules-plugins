"""`segmently-modules packs`: create, list and sync packs — a team's roles, role templates and agent
skills.

  new ID [--role NAME]… [--skill NAME]… [--description TEXT] [--priority N]
        scaffold `<config_dir>/packs/ID/`: `pack.toml`, a role template per `--role` and a
        `SKILL.md` per `--skill` (reading every `--role`); every refusal writes nothing
  list  the active packs in precedence order (repository packs, then the enabled built-in
        packs), with their roles and skills
  sync [--agent claude|codex|cursor|gemini|copilot]… [--check] [--remove]
        copy every pack skill into the agents' skill directories (`skill_sync`) and, for codex,
        write the agents of the agent table into `.codex/agents/`; agents = the flags, else
        `[packs] agents`, else the agents whose directories already hold managed skills (an
        earlier sync; under `builtin_delivery = "plugin"` also codex when `.codex/agents/` holds
        a marked agent file); `--remove` (with `--agent`) deletes the copies instead"""
import functools
import os
import re
import shutil
import string
import subprocess
from importlib import resources
from pathlib import Path

from segmently_modules.changes import git_env
from segmently_modules.code_map_cmd import _toml_string
from segmently_modules.config import (BUILTIN_PACKS, BUILTIN_PLUGINS, DEFAULT_PACK_PRIORITY,
                           core_defaults, delivery_for, discover_packs,
                           plugin_agents)
from segmently_modules.create import NAME, article
from segmently_modules.output import EXIT_FINDINGS, EXIT_OK, UsageError, emit
from segmently_modules.skill_sync import (AGENT_BAD_MARKER, AGENT_NOT_MANAGED, AGENT_STATUSES, NO_RECORD,
                               STATUSES, agent_row, apply_agent_file, apply_plan, conflict_kind,
                               managed_agents, plan_agent_files, plan_remove, plan_sync, row,
                               skill_sources, sync_command)
from segmently_modules.skills import (AGENT_DIRS, CODEX_AGENTS, NAME_RULE, declared_skills,
                           ejected_dir, is_ejected, pack_skills, read_front_matter, skill_id_ok)
from segmently_modules.workspace import Workspace

ACTIONS = ("new", "list", "sync")
NEW_FLAGS = ("--role", "--skill", "--description", "--priority")
SYNC_FLAGS = ("--agent", "--check", "--remove")
NO_PLUGIN = ("cursor", "gemini", "copilot")  # agents no segmently-modules plugin exists for (P6 D5)
ROLE_NAME = re.compile(r"^[a-z][a-z0-9_]*(-[a-z0-9]+)*$")
FIRST_ROLE_ORDER, ROLE_ORDER_STEP = 100, 10
PACK_DESCRIPTION = "Describe what this pack adds: its roles and skills."


def register(sub, common) -> None:
    p = sub.add_parser("packs", parents=[common],
                       help="create, list or sync packs: a team's roles, templates and "
                            "agent skills",
                       description="new ID: scaffold <config_dir>/packs/ID/ — pack.toml, "
                                   "roles/<role>.md per --role, skills/<skill>/SKILL.md per "
                                   "--skill (each skill reads every --role). list: the "
                                   "installed packs in precedence order with their roles and "
                                   "skills. sync: copy every pack skill into the agents' skill "
                                   "directories (claude: .claude/skills/; codex, cursor, "
                                   "gemini and copilot: .agents/skills/) and, for codex, the "
                                   "agents of module-discover, module-scout and module-research "
                                   "into .codex/agents/; a locally edited or "
                                   "foreign copy is a conflict and is never overwritten; "
                                   "--remove deletes the copies instead.")
    p.add_argument("action", choices=ACTIONS)
    p.add_argument("name", nargs="?", metavar="ID",
                   help="new: the pack id (lowercase words joined by '-', max 48)")
    p.add_argument("--role", action="append", dest="roles", metavar="NAME",
                   help="new: a role the pack adds, with its template roles/NAME.md "
                        "(repeatable)")
    p.add_argument("--skill", action="append", dest="skills", metavar="NAME",
                   help="new: an agent skill the pack adds, skills/NAME/SKILL.md "
                        "(repeatable)")
    p.add_argument("--description", help="new: one line — what the pack adds")
    p.add_argument("--priority", type=int,
                   help=f"new: precedence among packs (default {DEFAULT_PACK_PRIORITY}; a "
                        f"lower number wins)")
    p.add_argument("--agent", action="append", dest="agents",
                   metavar="claude|codex|cursor|gemini|copilot",
                   help="sync: an agent to write skills for (repeatable; default: [packs] "
                        "agents)")
    p.add_argument("--check", action="store_true",
                   help="sync: write nothing; exit 1 unless every skill is unchanged (CI)")
    p.add_argument("--remove", action="store_true",
                   help="sync: delete every copy packs sync made in the --agent directories "
                        "(an edited copy stays; other files are never touched)")
    p.add_argument("--dry-run", action="store_true",
                   help="new, sync: report what would be written, write nothing")
    p.set_defaults(func=run)


def _scaffold(name: str) -> str:
    return resources.files("segmently_modules").joinpath(f"defaults/scaffold/{name}").read_text(
        encoding="utf-8")


def _and(words: list[str]) -> str:
    return words[0] if len(words) == 1 else f"{', '.join(words[:-1])} and {words[-1]}"


def _check_names(pack_id: str, roles: list[str], skills: list[str]) -> None:
    if not NAME.fullmatch(pack_id) or len(pack_id) > 48:
        raise UsageError(f"pack id {pack_id!r}: use lowercase words joined by '-' (max 48)")
    for flag, values in (("--role", roles), ("--skill", skills)):
        repeated = sorted({v for v in values if values.count(v) > 1})
        if repeated:
            raise UsageError(f"{flag} {repeated[0]!r} is repeated")
    for role in roles:
        if not ROLE_NAME.fullmatch(role) or len(role) > 48:
            raise UsageError(f"role {role!r}: use lowercase letters, digits and '_', words "
                             f"joined by '-', starting with a letter (max 48)")
    for skill in skills:
        if not skill_id_ok(skill):
            raise UsageError(f"skill {skill!r}: {NAME_RULE} (the Agent Skills name rule)")


def _check_free(ws, pack_id: str, pack_dir: Path, roles: list[str], skills: list[str]) -> None:
    if pack_id in BUILTIN_PACKS:
        raise UsageError(f"pack id '{pack_id}' is reserved for the engine's built-in pack — "
                         f"enable it: [packs] builtin = [\"{pack_id}\"]")
    if os.path.lexists(pack_dir):
        raise UsageError(f"{ws.rel(pack_dir)}/ already exists")
    for pack in discover_packs(ws.config_dir):
        if pack["id"] == pack_id:
            raise UsageError(f"pack id '{pack_id}' is already installed "
                             f"({ws.rel(pack['path'])})")
    configured, engine = ws.config.get("roles") or {}, core_defaults().get("roles") or {}
    for role in roles:
        if role in configured:
            owner = configured[role].get("owner")
            where = ("engine defaults" if role in engine else f"pack '{owner}'" if owner
                     else "the team config")
            raise UsageError(f"role '{role}' is already configured ({where}) — to change its "
                             f"doc template: segmently-modules templates override roles/{role}.md")
    declared = {}
    for skill in declared_skills(ws.config_dir):
        declared.setdefault(skill.id, skill)
    for skill in skills:
        if skill in declared:
            raise UsageError(f"skill '{skill}' is already declared by pack "
                             f"'{declared[skill].pack}' ({ws.rel(declared[skill].pack_toml)})")


def scaffold_files(pack_id: str, roles: list[str], skills: list[str], description: str | None,
                   priority: int | None) -> dict[str, str]:
    """{path inside the pack: text} of a new pack, in writing order."""
    tables = ""
    for n, role in enumerate(roles):
        tables += (f"\n[roles.{role}]\norder = {FIRST_ROLE_ORDER + n * ROLE_ORDER_STEP}\n"
                   f"standard = false\n"
                   f"description = "
                   f"{_toml_string(f'What {article(role)} {role} needs to know about a module')}"
                   f"\ntemplate = {_toml_string(f'roles/{role}.md')}\n")
    for skill in skills:
        reads = ", ".join(_toml_string(r) for r in roles)
        tables += (f"\n[skills.{skill}]\npath = {_toml_string(f'skills/{skill}')}\n"
                   f"reads_roles = [{reads}]\n")
    files = {"pack.toml": string.Template(_scaffold("pack.toml")).substitute(
        id=pack_id, id_toml=_toml_string(pack_id),
        priority=DEFAULT_PACK_PRIORITY if priority is None else priority,
        description_toml=_toml_string(description or PACK_DESCRIPTION), tables=tables)}
    for role in roles:  # `${article}` is resolved now; the other placeholders by `create`
        files[f"roles/{role}.md"] = _scaffold("role.md").replace("${article}", article(role))
    # the task goes through a file (a quoted argument would expand `$` and backticks) and the
    # keyword routing is pinned: a team's `[match] mode` never makes the step refuse (P8.1)
    task = "--task-file <the task in one sentence, in a temporary file outside the repository>"
    if roles:
        context = "\n".join(f"   `segmently-modules context {task} --role {r} --match lexical --json`"
                             for r in roles)
        show = "\n".join(f"   `segmently-modules show <module> --role {r}`" for r in roles)
        docs = f"{_and(roles)} docs"
    else:
        context, show, docs = f"   `segmently-modules context {task} --match lexical --json`", \
            "   `segmently-modules show <module>`", "docs"
    for skill in skills:
        what = (f"Works through a task with the {docs} of the modules it touches. Rewrite this "
                f"line to say what the skill does and when an agent should use it.")
        files[f"skills/{skill}/SKILL.md"] = string.Template(_scaffold("SKILL.md")).substitute(
            skill=skill, description=what, context_lines=context, read_what=docs,
            show_lines=show)
    return files


def new_pack(ws, pack_id: str, roles: list[str], skills: list[str], description: str | None,
             priority: int | None, dry_run: bool) -> dict:
    """Scaffold a pack; every refusal writes nothing, an interrupted write removes its files."""
    _check_names(pack_id, roles, skills)
    pack_dir = ws.config_dir / "packs" / pack_id
    _check_free(ws, pack_id, pack_dir, roles, skills)
    files = scaffold_files(pack_id, roles, skills, description, priority)
    if not dry_run:
        try:
            pack_dir.mkdir(parents=True)  # never an existing directory: the pack is ours alone
        except OSError as e:
            raise UsageError(f"cannot create {ws.rel(pack_dir)}/: {e.strerror}; nothing "
                             f"written") from None
        try:
            for rel, text in files.items():
                path = pack_dir / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "x", encoding="utf-8", newline="\n") as fh:
                    fh.write(text)
        except BaseException as e:  # Ctrl-C or a failed write: remove the half-made pack
            shutil.rmtree(pack_dir, ignore_errors=True)
            if isinstance(e, OSError):
                raise UsageError(f"cannot write {ws.rel(pack_dir)}/: {e.strerror}; nothing "
                                 f"written") from None
            raise
    return {"pack": pack_id, "dir": ws.rel(pack_dir),
            "files": [ws.rel(pack_dir / rel) for rel in files], "dry_run": dry_run}


def pack_rows(ws) -> list[dict]:
    """`packs list` data: active packs in precedence order (`builtin`: an engine pack, whose
    `priority` is null — it ranks below every repository pack)."""
    rows = []
    for pack in discover_packs(ws.config_dir):
        data, pack_dir = pack["data"], pack["path"].parent
        skills = []
        for sid, spec in (data.get("skills") or {}).items():
            meta = read_front_matter(pack_dir / spec["path"] / "SKILL.md") or {}
            skills.append({"id": sid, "path": spec["path"],
                           "reads_roles": list(spec.get("reads_roles", [])),
                           "description": meta.get("description") or None,
                           "ejected": is_ejected(ws.config_dir, sid)})
        version, description = data.get("version"), data.get("description")
        rows.append({"id": pack["id"], "version": version if isinstance(version, str) else None,
                     "priority": pack["priority"], "builtin": pack["builtin"],
                     "dir": ws.rel(pack_dir),
                     "description": description if isinstance(description, str) else None,
                     "roles": list(data.get("roles") or {}), "skills": skills})
    return rows


def _names(words: list[str]) -> str:
    return ", ".join(words)


def sync_notes(ws, chosen: list[str], plugin: set[str], rows: list[dict],
               agent_rows: list[dict] = ()) -> list[str]:
    """The `note:` lines of a `packs sync` run (`data.notes`): for the chosen agents whose
    built-in skills a plugin provides (`plugin`), the plugins that provide the enabled built-in
    packs' skills — naming those agents when the others get copies — and the agents among them
    no plugin exists for; Copilot's duplicates (it reads both directories) when `claude`
    syncs together with an agent of `.agents/skills` — under `"plugin"` only when a copy stays
    in both (a row that is not `removed`): the built-in skills are in neither there; the copies
    and the Codex agent files (`agent_rows`) git ignores."""
    notes = []
    provided = [p["id"] for p in discover_packs(ws.config_dir) if p["builtin"]] if plugin else []
    if provided:
        some = [a for a in chosen if a in plugin] if set(chosen) - plugin else []
        lead = f'builtin_delivery = "plugin" for {_names(some)}' if some else \
            'builtin_delivery = "plugin"'
        notes.append(f"{lead}: the built-in skills come from the plugins "
                     + ", ".join(f"{BUILTIN_PLUGINS[p]} ({p})" for p in provided)
                     + " — packs sync copies none of them" + (" there" if some else ""))
        bare = [a for a in chosen if a in NO_PLUGIN and a in plugin]
        if bare:
            verb, pronoun = ("gets", "it") if len(bare) == 1 else ("get", "them")
            notes.append(f"{_names(bare)} {verb} no built-in skills: no segmently-modules plugin exists "
                         f'for {pronoun} — set [packs] builtin_delivery = "repo" to sync the '
                         f"built-in skills for {pronoun}")
    dirs = ({AGENT_DIRS[r["agent"]] for r in rows if r["status"] != "removed"} if plugin
            else {AGENT_DIRS[a] for a in chosen})
    if AGENT_DIRS["claude"] in dirs and len(dirs) > 1:
        notes.append("GitHub Copilot reads both .claude/skills and .agents/skills, so it sees "
                     "each skill twice — where Copilot works, sync only one of the two "
                     "directories (Copilot reads either)")
    notes.extend(_ignored_copies_notes(ws.root, rows))
    notes.extend(_ignored_agent_files_note(ws.root, agent_rows))
    return notes


COPY_STATUSES = ("created", "updated", "unchanged")


def _ignored_copies_notes(root: Path, rows: list[dict]) -> list[str]:
    """One note per skills directory in which git ignores some of the copies the run wrote or
    would write (rows `created`, `updated`, `unchanged`; a copy shared by `same_as` rows counts
    once). Each copy is probed through its own `SKILL.md` — a path git judges the same before
    and after the directory exists — with one `git check-ignore` per skills directory, and only
    the ignored ones are named, in row order."""
    copies: dict[str, dict[str, str]] = {}  # directory -> copy dir -> skill id
    for r in rows:
        if r["status"] in COPY_STATUSES and not r.get("same_as"):
            copies.setdefault(os.path.dirname(r["dir"]), {}).setdefault(r["dir"], r["skill"])
    notes = []
    for d in sorted(copies):
        ignored = _git_ignored(root, [f"{c}/SKILL.md" for c in copies[d]])
        names = [skill for c, skill in copies[d].items() if f"{c}/SKILL.md" in ignored]
        if names:
            notes.append(f"git ignores {len(names)} of the {len(copies[d])} skill copies in {d} "
                         f"({_names(names)}) — they are written but will not be committed; "
                         f"take them out of .gitignore to share them with the team")
    return notes


def _ignored_agent_files_note(root: Path, agent_rows: list[dict]) -> list[str]:
    """One note when git ignores some of the Codex agent files the run wrote or would write
    (rows `created`, `updated`, `unchanged`), probed by their paths in one `git check-ignore`;
    only the ignored ones are named, in row order."""
    files = {r["path"]: r["name"] for r in agent_rows if r["status"] in COPY_STATUSES}
    if not files:
        return []
    ignored = _git_ignored(root, list(files))
    names = [name for path, name in files.items() if path in ignored]
    if not names:
        return []
    return [f"git ignores {len(names)} of the {len(files)} agent files in {CODEX_AGENTS} "
            f"({_names(names)}) — they are written but will not be committed; take them out "
            f"of .gitignore to share them with the team"]


def _git_ignored(root: Path, rels: list[str]) -> set[str]:
    """The paths among `rels` that git ignores, from one `git check-ignore -z --stdin` (none
    outside a repository, or when git cannot run)."""
    try:
        proc = subprocess.run(["git", "-C", str(root), "check-ignore", "-z", "--stdin"],
                              input="".join(f"{r}\0" for r in rels).encode(),
                              capture_output=True, env=git_env())
    except OSError:
        return set()
    if proc.returncode != 0:  # 1: none ignored; 128: not a repository or a path git refuses
        return set()
    return {p for p in proc.stdout.decode("utf-8", "replace").split("\0") if p}


def remove_scope(ws, agents: list[str] | None, check: bool) -> list[str]:
    """The agents `packs sync --remove` removes the copies of (P6 D5): the `--agent` flags
    only. Refused (exit 2, nothing written) without `--agent`, with `--check`, and while an
    agent of `[packs] agents` that reads the same directory is not among the flags."""
    if check:
        raise UsageError("--check and --remove cannot be combined (--check never writes)")
    if not agents:
        raise UsageError("--remove needs --agent: the agents whose copies to remove "
                         "(--agent claude|codex|cursor|gemini|copilot, repeatable)")
    chosen = list(dict.fromkeys(agents))
    real = {os.path.realpath(ws.root / AGENT_DIRS[a]) for a in chosen}
    configured = (ws.config.get("packs") or {}).get("agents") or []
    kept = [a for a in dict.fromkeys(configured) if a not in chosen
            and os.path.realpath(ws.root / AGENT_DIRS[a]) in real]
    if kept:
        where, verb = AGENT_DIRS[kept[0]], "reads" if len(kept) == 1 else "read"
        raise UsageError(f"--remove would delete the copies {_names(kept)} still {verb} in "
                         f"{where} ([packs] agents lists {_names(kept)}) — add "
                         + " ".join(f"--agent {a}" for a in kept)
                         + ", or take it out of [packs] agents first; nothing written")
    return chosen


def remove_notes(ws, chosen: list[str], dry_run: bool) -> list[str]:
    """`--remove`: the agents that read a directory it empties without being among the flags;
    the agents among the flags that `[packs] agents` still lists (a bare sync copies again)."""
    real = {os.path.realpath(ws.root / AGENT_DIRS[a]) for a in chosen}
    others = [a for a in AGENT_DIRS if a not in chosen
              and os.path.realpath(ws.root / AGENT_DIRS[a]) in real]
    notes = []
    if others:
        dirs = sorted({AGENT_DIRS[a] for a in others})
        notes.append(f"{', '.join(dirs)} is also where {_names(others)} read skills — the "
                     f"copies {'would be' if dry_run else 'are'} gone for them too")
    listed = [a for a in (ws.config.get("packs") or {}).get("agents") or [] if a in chosen]
    if listed:
        verb, pronoun = ("is", "its") if len(listed) == 1 else ("are", "their")
        notes.append(f"{_names(listed)} {verb} still in [packs] agents: the next packs sync "
                     f"copies {pronoun} skills again and packs sync --check is stale — take "
                     f"{'it' if len(listed) == 1 else 'them'} out of [packs] agents to keep "
                     f"the copies gone")
    return notes


def sync(ws, agents: list[str] | None, check: bool, dry_run: bool,
         remove: bool = False) -> dict:
    """`packs sync`: plan every (agent, skill), then apply the plans unless `check` /
    `dry_run`; a conflicting or invalid skill is never written, the others are. `remove`:
    plan the removal of every managed copy in the `--agent` directories instead."""
    if check and dry_run:
        raise UsageError("--check and --dry-run cannot be combined (--check never writes)")
    for agent in agents or []:
        if agent not in AGENT_DIRS:
            raise UsageError(f"unknown agent {agent!r} (agents: {', '.join(AGENT_DIRS)})")
    if remove:
        chosen = remove_scope(ws, agents, check)
    else:
        chosen = list(dict.fromkeys(
            agents or (ws.config.get("packs") or {}).get("agents")
            or managed_agents(ws.root, delivery_for(ws.config, "codex") == "plugin")))
    if not chosen:
        *first, last = AGENT_DIRS
        raise UsageError(f"choose --agent {', '.join(first)} or {last} (repeatable), or set "
                         f"[packs] agents")
    plugin = plugin_agents(ws.config, chosen)
    try:
        sources = None if remove else skill_sources(ws)
        plans = plan_remove(ws, chosen) if remove else plan_sync(ws, chosen, plugin, sources)
        # codex only (P8.4 D3): a run that names its agents without codex never opens `.codex/`;
        # a bare run under `builtin_delivery = "plugin"` reads `.codex/agents/` only to infer
        # codex (`managed_agents`, above)
        agent_plans = plan_agent_files(ws, sources, remove) if "codex" in chosen else None
    except OSError as e:  # planning only reads: an unreadable agent copy stops the run
        raise UsageError(f"cannot read {ws.rel(e.filename or ws.root)}: "
                         f"{e.strerror or e}") from None
    if not check and not dry_run:
        for plan in plans:
            if plan.same_as is None:
                try:
                    apply_plan(plan)
                except OSError as e:
                    raise UsageError(f"cannot write {ws.rel(plan.dest)}: {e.strerror or e} — "
                                     f"fix it and run packs sync again (a skill written in "
                                     f"part resumes)") from None
        for plan in agent_plans or []:
            if plan.status in ("created", "updated", "removed"):
                try:
                    apply_agent_file(plan)
                except OSError as e:
                    raise UsageError(f"cannot write {ws.rel(plan.path)}: {e.strerror or e} — "
                                     f"fix it and run packs sync again (an agent file is "
                                     f"written whole or not at all)") from None
    rows = [row(ws, plan) for plan in plans]
    agent_rows = None if agent_plans is None else [agent_row(ws, p) for p in agent_plans]
    summary = {s: sum(r["status"] == s for r in rows) for s in STATUSES}
    every = [r["status"] for r in rows + (agent_rows or [])]
    failed = (any(s != "unchanged" for s in every) if check
              else any(s in ("conflict", "invalid") for s in every))
    if not remove:
        notes = sync_notes(ws, chosen, plugin, rows, agent_rows or [])
    else:  # only when a copy went (or would go): the other readers lose it too
        notes = remove_notes(ws, chosen, dry_run) if summary["removed"] else []
    return {"agents": chosen, "check": check, "dry_run": dry_run, "skills": rows,
            **({} if agent_rows is None else {"agent_files": agent_rows}),
            "summary": summary, "failed": failed, "notes": notes}


def _refuse_flags(args, action: str, allowed: tuple[str, ...]) -> None:
    given = {"ID": args.name, "--role": args.roles, "--skill": args.skills,
             "--description": args.description, "--priority": args.priority,
             "--agent": args.agents, "--check": args.check or None,
             "--dry-run": args.dry_run or None, "--remove": args.remove or None}
    used = [flag for flag, value in given.items() if value is not None and flag not in allowed]
    if used:
        raise UsageError(f"packs {action} takes no {used[0]}")


def run(args) -> int:
    ws = Workspace.from_args(args)
    if args.action == "list":
        _refuse_flags(args, "list", ())
        emit("packs", pack_rows(ws), args.json, _render_list)
        return EXIT_OK
    if args.action == "sync":
        _refuse_flags(args, "sync", SYNC_FLAGS + ("--dry-run",))
        data = sync(ws, args.agents, args.check, args.dry_run, args.remove)
        emit("packs", data, args.json, functools.partial(_render_sync, ws=ws,
                                                          remove=args.remove))
        return EXIT_FINDINGS if data["failed"] else EXIT_OK
    _refuse_flags(args, "new", ("ID",) + NEW_FLAGS + ("--dry-run",))
    if args.name is None:
        raise UsageError("packs new needs an ID (the new pack's id, e.g. team)")
    data = new_pack(ws, args.name, args.roles or [], args.skills or [], args.description,
                    args.priority, args.dry_run)
    agents = (ws.config.get("packs") or {}).get("agents")
    emit("packs", data, args.json, functools.partial(_render_new, agents=agents))
    return EXIT_OK


def _render_new(d, agents: list[str] | None = None) -> None:
    """`agents`: the config's `[packs] agents` — set, a bare `segmently-modules packs sync` works."""
    verb = "would create" if d["dry_run"] else "created"
    for f in d["files"]:
        print(f"{verb}  {f}")
    role_dir = Path(d["dir"]) / "roles"  # only <pack dir>/roles/<role>.md is a role template
    roles = [Path(f).stem for f in d["files"] if Path(f).parent == role_dir]
    skills = any(Path(f).name == "SKILL.md" for f in d["files"])
    steps = [f"segmently-modules create NAME … --role {roles[0]} (a module with the {roles[0]} doc)"
             if roles else "edit pack.toml (roles, fields, [[code_map]] rules, skills)"]
    if skills:
        steps.append(f"{sync_command(None, agents)} (the skills into the agents' skill "
                     f"directories)")
    print(f"next: {'; then '.join(steps)}")


def _hint(ws, r) -> str:
    """How to resolve a `conflict` or `invalid` row (text output only): by the reason."""
    here, copy = r["dir"], ws.rel(ejected_dir(ws.config_dir, r["skill"]))
    if r["status"] == "invalid":
        if r["source"] != "ejected":
            return "fix the skill in its pack (plain segmently-modules lint reports it as MS062)"
        code = "MS063" if r["reason"].endswith(NO_RECORD) else "MS062"
        return f"fix the ejected copy {copy} (plain segmently-modules lint reports it as {code})"
    if r["status"] != "conflict":
        return ""
    kind, other = conflict_kind(r["reason"])
    if kind == "edit":
        keep = (f"copy it into {copy}" if r["source"] == "ejected"
                else f"segmently-modules eject {r['skill']}, copy the change into {copy}")
        return (f"revert it (git checkout -- {here}) and sync again, or keep the change: {keep}, "
                f"then packs sync")
    return {"hand-written": "a skill written by hand: move or rename it, then sync again",
            "other-pack": f"it belongs to pack '{other}': remove it if that pack is gone, or "
                          f"rename one of the skills",
            "bad-marker": f"restore the marker (git checkout -- {here}) or move the directory "
                          f"away, then sync again",
            "orphan-edit": "revert the edit, or delete the directory if the skill is no longer "
                           "wanted",
            "orphan-bad-marker": f"restore the marker (git checkout -- {here}) or delete the "
                                 f"directory",
            "plugin": ""}.get(kind, "move it away, then sync again")  # its reason names the fixes


def agent_hint(ws, r) -> str:
    """How to resolve a `conflict` row of an agent file (text output only): by the reason."""
    reason, here = r["reason"] or "", r["path"]
    if r["status"] != "conflict":
        return ""
    if reason.endswith("(locally edited)"):
        copy = f"{ws.rel(ejected_dir(ws.config_dir, r['skill']))}/SKILL.md"  # the agent runs it
        keep = (f"edit {copy}" if is_ejected(ws.config_dir, r["skill"])
                else f"segmently-modules eject {r['skill']}, edit {copy}")
        skill = pack_skills(ws.config_dir).get(r["skill"])
        if skill and skill.builtin and delivery_for(ws.config, "codex") == "plugin":  # codex's file
            keep = f'set [packs] builtin_delivery = "repo", {keep}'  # eject needs "repo"
        return (f"revert it (git checkout -- {here}) and sync again, or keep the change: {keep}, "
                f"then packs sync")
    if reason.endswith("(locally edited; not removed)"):
        return "revert the edit, or delete the file if the agent is no longer wanted"
    if reason == AGENT_NOT_MANAGED:
        return "an agent written by hand: move or rename it, then sync again"
    if reason.startswith(AGENT_BAD_MARKER):
        return (f"restore its first line (git checkout -- {here}) or "
                + ("delete the file" if reason != AGENT_BAD_MARKER
                   else "move the file away, then sync again"))
    if reason.startswith(".codex") and " cannot remove " in reason:  # a file behind a symlink
        return ("delete that file where the symlink points, or make .codex/agents a plain "
                "directory, then sync again")
    if reason.startswith(".codex"):
        return "make .codex/agents a plain directory, then sync again"
    other = re.fullmatch(r"managed for pack '(.*)', skill '(.*)'", reason)
    if other:
        return (f"it is the agent file of skill '{other.group(2)}' (pack '{other.group(1)}'): "
                f"move it away, then sync again")
    return "move it away, then sync again"


def _render_sync(d, ws, remove: bool = False) -> None:
    agent_rows = d.get("agent_files") or []  # codex only (P8.4 D3)
    if not d["skills"] and not agent_rows:
        if remove:
            print("nothing to remove: no copy made by packs sync in " + ", ".join(
                dict.fromkeys(AGENT_DIRS[a] for a in d["agents"])))
        elif plugin_agents(ws.config, d["agents"]):
            print('nothing to copy: the built-in skills come from the segmently-modules plugins '
                  '(builtin_delivery = "plugin"); a repository pack\'s skills are copied (add '
                  'one: segmently-modules packs new ID --skill NAME)')
        else:
            print("no pack skills (add one: segmently-modules packs new ID --skill NAME)")
    upstream = pack_skills(ws.config_dir)
    for r in d["skills"]:
        where = f"({r['pack']} {r['version']}" if r["version"] else f"({r['pack']}"
        now = upstream.get(r["skill"]) if r["source"] == "ejected" else None
        if now is not None and (now.pack, now.version) != (r["pack"], r["version"]):
            where += (f", ejected copy; the pack is now {now.version})" if now.pack == r["pack"]
                      else f", ejected copy; now pack {now.pack} {now.version})")
        else:
            where += ", ejected copy)" if r["source"] == "ejected" else ")"
        if r["pack"] is None and r["source"] is None:  # an orphan whose marker is unreadable
            where = "(no valid marker)"
        elif r["pack"] is None:  # an ejected copy without a record of a skill no pack declares
            where = "(no valid record)"
        same = f"  same directory as {r['same_as']}" if r.get("same_as") else ""
        print(f"{r['status']:<10} {r['agent']:<7} {r['dir']}  {where}{same}")
        if r["reason"]:
            hint = _hint(ws, r)
            print(f"  {r['reason']}" + (f" — {hint}" if hint else ""))
    for r in agent_rows:  # after the skill rows: one row per agent file
        where = (f"  ({r['pack']} {r['version']})" if r["pack"] and r["version"]
                 else f"  ({r['pack']})" if r["pack"] else "")
        print(f"{r['status']:<10} {r['agent']:<7} {r['path']}{where}")
        if r["reason"]:
            hint = agent_hint(ws, r)
            print(f"  {r['reason']}" + (f" — {hint}" if hint else ""))
    for note in d["notes"]:
        print(f"note: {note}")
    s = d["summary"]
    counts = ", ".join(f"{s[k]} {k}" for k in STATUSES)
    a = {k: sum(r["status"] == k for r in agent_rows) for k in AGENT_STATUSES}
    if agent_rows:
        counts += "; agent files: " + ", ".join(f"{a[k]} {k}" for k in AGENT_STATUSES)
    if d["check"]:
        configured = (ws.config.get("packs") or {}).get("agents")
        state = "; ".join(
            ([f"stale — run {sync_command(d['agents'], configured)}"]
             if s["created"] or s["updated"] or s["removed"]
             or a["created"] or a["updated"] or a["removed"] else [])
            + (["blocked — resolve the conflict / invalid rows above"]
               if s["conflict"] or s["invalid"] or a["conflict"] else [])) or "in sync"
        print(f"packs sync --check: {counts}: {state}")
    else:
        print(f"packs sync{' --remove' if remove else ''}: {counts}"
              + ("  (dry run: nothing written)" if d["dry_run"] else ""))


def _render_list(rows) -> None:
    if not rows:
        print("no packs (create one: segmently-modules packs new ID)")
    for r in rows:
        rank = "built-in" if r["builtin"] else f"priority {r['priority']}"
        print(f"{r['id']} {r['version'] or '(no version)'} {rank}  {r['dir']}")
        if r["description"] and r["description"].strip():
            print(f"  {r['description'].strip().splitlines()[0]}")
        for role in r["roles"]:
            print(f"  role   {role}")
        for s in r["skills"]:
            reads = f"  reads {', '.join(s['reads_roles'])}" if s["reads_roles"] else ""
            print(f"  skill  {s['id']}{reads}{'  (ejected)' if s['ejected'] else ''}")
