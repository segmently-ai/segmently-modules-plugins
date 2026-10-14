"""`segmently-modules next [--base REF]`: what the repository needs now — one ranked list, each item with
the segmently-modules command that fixes it. Read-only: it composes in-process what plain `lint`, `packs
sync --check`, `agents-md --check`, `roles list`, `proposals list`, `coverage` and the drift of
`ci` report; it writes nothing, takes no lock and keeps no state. What an engine upgrade brought
shows up the same way (D2): a standard role without docs, stale skill copies, a stale block, an
ejected skill behind its pack — derived from the repository, never from a "last seen version".

The kinds, in rank order (D4):
  lint-error    one per plain-lint error: `segmently-modules lint`; a registered role doc missing on disk
                (MS004) `segmently-modules roles add ROLE TARGET --recreate` (SI-P61-7)
  skills        one for the copies `packs sync --check` finds stale, missing, to remove or in
                conflict — agents resolved as a bare `packs sync` resolves them (SI-P61-5) —
                and the Codex agent files in `.codex/agents` it finds so (P8.4)
  agents-md     one per instruction file at the root (CLAUDE.md, AGENTS.md, GEMINI.md,
                .github/copilot-instructions.md) that holds a segmently-modules block differing from its
                render (SI-P61-4)
  role          one per enabled standard role that some module or child has no doc for (all
                of them in `modules`)
  ejected       one per ejected skill lint MS063 warns about (`eject --diff SKILL` when it is
                behind its pack)
  proposals     the pending proposal files
  lint-warning  the other lint warnings, counted, with their codes (MS063 never twice, SI-P61-6)
  unmapped      the files no module maps — only with a `[[code_map]]` rule, inside git
  no-code       the active modules that map no code file (lint MS054), in `modules`
  drift         with --base: MS050 / MS051 since REF (`sync-instructions --from-diff REF..HEAD`;
                drift that includes an uncommitted or untracked file: `sync-instructions
                --module M` per drifted module, in registry order)
A kind that cannot run is named in `skipped` (JSON only) with the reason. No config and no
registry: one item, `segmently-modules setup` (SI-P61-8). Exit 0 with or without items."""
from __future__ import annotations

import contextlib
import os
import re
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path
from shlex import quote

from segmently_modules import __version__
from segmently_modules.agents_md_cmd import _BEGIN, END, _bare, _lines, agents_md
from segmently_modules.changes import (changed_files, commit_ref, commit_sha, git, map_files, repo_files,
                            work_tree_error)
from segmently_modules.ci_cmd import SHORT, base_notes
from segmently_modules.config import delivery_for, enabled_roles
from segmently_modules.coverage_cmd import coverage_report
from segmently_modules.init_cmd import init_root
from segmently_modules.lint import drift_report, lint_registry
from segmently_modules.output import EXIT_OK, UsageError, emit
from segmently_modules.packs_cmd import sync as packs_sync
from segmently_modules.proposals import pending
from segmently_modules.registry import as_list
from segmently_modules.roles_cmd import all_targets, role_rows
from segmently_modules.skill_sync import managed_agents
from segmently_modules.skills import CODEX_AGENTS
from segmently_modules.workspace import Workspace, find_root

INSTRUCTION_FILES = ("CLAUDE.md", "AGENTS.md", "GEMINI.md", ".github/copilot-instructions.md")
COPY_STATES = (("updated", "stale"), ("created", "missing"), ("removed", "to remove"),
               ("conflict", "in conflict"))  # `packs sync` statuses -> how the item names them
NOT_SET_UP = "segmently-modules is not set up here: no config, no registry"
NO_AGENT = ("no agent to check: [packs] agents is not set and no agent's skill directory holds "
            "a copy packs sync made")
_ROLE_DOC = re.compile(r"(?:^|\.)context_files\.roles\.([^.\[\]\s]+)(?:\[\])? path missing on "
                       r"disk$")  # lint MS004 on a registered role doc
_SKILL = re.compile(r"skill '([^']+)'")
_BEHIND, _REVIEW = " is behind pack ", " — review: "  # lint MS063: behind, and its hint


class Skip(Exception):
    """A kind that cannot run here; the message is the reason `skipped` gives."""


def register(sub, common) -> None:
    p = sub.add_parser("next", parents=[common],
                       help="what the repository needs now: one ranked list, each item with "
                            "the command that fixes it (read-only)",
                       description="One ranked list: lint errors, stale or missing skill "
                                   "copies and stale agents-md blocks, standard roles without "
                                   "docs, ejected skills behind their pack, pending proposals, "
                                   "lint warnings, unmapped files (with a [[code_map]] rule), "
                                   "active modules that map no code, "
                                   "drift since --base — each with the segmently-modules command that "
                                   "fixes it. Also what an engine upgrade brought. Writes "
                                   "nothing; exit 0 with or without items.")
    p.add_argument("--base", metavar="REF",
                   help="also report the drift since REF (code changed without a doc update), "
                        "e.g. the target branch")
    p.set_defaults(func=run)


def _root(args) -> Path:
    """`--root` (resolved; refused unless it is an existing directory, as `setup` and `init`
    refuse it), else the root `find_root` finds, else the current directory: a directory with
    no root marker and no git above it is a place where segmently-modules is not set up yet."""
    if args.root is not None:
        return init_root(args.root)
    try:
        return find_root(Path.cwd())
    except UsageError:
        return Path.cwd()


def _set_up(ws) -> bool:
    return ((ws.config_dir / "config.toml").exists()
            or (ws.root / ws.config["paths"]["registry"]).exists())


def lint_errors(ws, findings: list) -> list[tuple]:
    """One item per plain-lint error; MS004 on a role doc of an enabled role points at `roles
    add ROLE TARGET --recreate`, which writes it (SI-P61-7)."""
    enabled, out = set(enabled_roles(ws.config)), []
    for f in findings:
        if f.severity != "error":
            continue
        role = _ROLE_DOC.search(f.message) if f.code == "MS004" and f.path else None
        command = (f"segmently-modules roles add {quote(role.group(1))} {quote(f.module)} --recreate"
                   if role and role.group(1) in enabled else "segmently-modules lint")
        where = f" ({f.path})" if f.path else ""
        out.append(("lint-error", f"{f.code} {f.module}: {f.message}{where}", command))
    return out


def _by_state(rows: list[dict], key: str) -> list[str]:
    """`<state> <name>, …` per `packs sync` status that is not in sync, in COPY_STATES order."""
    parts = []
    for status, label in COPY_STATES:
        names = sorted({r[key] for r in rows if r["status"] == status})
        if names:
            parts.append(f"{label} {', '.join(names)}")
    return parts


def skill_copies(ws) -> list[tuple]:
    """The copies a bare `packs sync --check` finds not in sync (its agents, its delivery
    rules), named by state — and, when it syncs for codex, the agent files in `.codex/agents`
    it finds so (under `builtin_delivery = "plugin"` they can be all it writes): one item. Under
    that delivery a `.codex/agents/` holding a marked agent file means codex when no agent is
    named and no `.agents/skills` copy holds a marker (`managed_agents`)."""
    if not ((ws.config.get("packs") or {}).get("agents")
            or managed_agents(ws.root, delivery_for(ws.config, "codex") == "plugin")):
        raise Skip(NO_AGENT)
    data = packs_sync(ws, None, check=True, dry_run=False)
    parts = _by_state(data["skills"], "skill")
    files = _by_state(data.get("agent_files") or [], "name")
    summary = ([f"skill copies not in sync ({', '.join(data['agents'])}): {'; '.join(parts)}"]
               if parts else [])
    summary += [f"agent files not in sync ({CODEX_AGENTS}): {'; '.join(files)}"] if files else []
    return [("skills", "; ".join(summary), "segmently-modules packs sync")] if summary else []


def _holds_block(path: Path) -> bool:
    text = path.read_bytes().decode("utf-8", errors="replace")
    return any(_BEGIN.fullmatch(_bare(line)) or _bare(line) == END for line in _lines(text))


def block_files(root: Path, skipped: list[str] | None = None) -> Iterator[str]:
    """The instruction files at `root` (INSTRUCTION_FILES, in that order) that hold a segmently-modules
    block — a begin or an end marker, malformed ones included; a file that is another one's
    symlink counts once. One that cannot be read is left out (named in `skipped` when given,
    as the iteration reaches it). `next` checks these; `setup` refreshes them when no
    --target is given."""
    seen = set()
    for rel in INSTRUCTION_FILES:
        path = root / rel
        try:
            if not path.is_file() or os.path.realpath(path) in seen or not _holds_block(path):
                continue
        except OSError as e:
            if skipped is not None:
                skipped.append(f"agents-md: cannot read {rel}: {e.strerror or e}")
            continue
        seen.add(os.path.realpath(path))
        yield rel


def stale_blocks(ws, skipped: list[str]) -> list[tuple]:
    """One item per instruction file at the root that holds a segmently-modules block (`block_files`)
    differing from its render (`agents-md --check`); a file without a block is none of `next`'s
    business, one that cannot be checked (malformed markers, not UTF-8) is named in `skipped`."""
    out = []
    for rel in block_files(ws.root, skipped):
        try:
            status = agents_md(ws, [rel], check=True, dry_run=False)["targets"][0]["status"]
        except UsageError as e:
            skipped.append(f"agents-md: {e}")
            continue
        if status != "unchanged":
            out.append(("agents-md", f"{rel}: the segmently-modules block is stale",
                        f"segmently-modules agents-md --target {quote(rel)}"))
    return out


MODULES_SHOWN = 5


def _shown(names: list[str]) -> str:
    return ", ".join(names[:MODULES_SHOWN]) + (", …" if len(names) > MODULES_SHOWN else "")


def missing_roles(ws) -> list[tuple]:
    """One item per enabled standard role with targets (modules, children) that have no doc;
    `modules` lists them all, the summary the first few."""
    return [("role", f"{r['name']}: no doc in {len(r['missing'])} module(s): "
                     f"{_shown(r['missing'])}",
             f"segmently-modules roles add {quote(r['name'])} --all", {"modules": r["missing"]})
            for r in role_rows(ws, enabled_only=True) if r["standard"] and r["missing"]]


def no_code(findings: list) -> list[tuple]:
    """One item for the active modules that map no code file (lint MS054, info)."""
    names = [f.module for f in findings if f.code == "MS054"]
    if not names:
        return []
    return [("no-code", f"{len(names)} active module(s) map no code file, so drift never fires "
                        f"for them: {_shown(names)}", "segmently-modules lint", {"modules": names})]


def ejected(findings: list) -> list[tuple]:
    """One item per ejected skill a lint MS063 warning names, by skill id: behind its pack →
    `eject --diff`; any other MS063 warning (a symlink, no valid record, an unreadable pack
    file) → lint's message and `segmently-modules lint`."""
    out = {}
    for f in findings:
        if f.code != "MS063" or f.severity != "warning":
            continue
        name = _SKILL.search(f.message)
        sid = name.group(1) if name else f.path or ""
        if sid in out:
            continue
        if _BEHIND in f.message:
            out[sid] = ("ejected", f.message.split(_REVIEW)[0], f"segmently-modules eject --diff {quote(sid)}")
        else:
            out[sid] = ("ejected", f.message, "segmently-modules lint")
    return [out[sid] for sid in sorted(out)]


def proposals(ws) -> list[tuple]:
    files = pending(ws)
    if not files:
        return []
    items = sum(len(doc["items"]) for _, doc in files if isinstance(doc.get("items"), list))
    return [("proposals", f"{len(files)} pending proposal file(s), {items} item(s)",
             "segmently-modules proposals list")]


def lint_warnings(findings: list) -> list[tuple]:
    warnings = [f for f in findings if f.severity == "warning" and f.code != "MS063"]
    if not warnings:
        return []
    codes = ", ".join(sorted({f.code for f in warnings}))
    return [("lint-warning", f"{len(warnings)} lint warning(s): {codes}", "segmently-modules lint")]


UNMAPPED_SHOWN = 3


def unmapped(ws, no_git: str | None) -> list[tuple]:
    if not as_list(ws.config.get("code_map")):
        raise Skip("no [[code_map]] rule")
    if no_git:
        raise Skip(no_git)
    files = coverage_report(ws, repo_files(ws.root))["unmapped"]
    if not files:
        return []
    shown = ", ".join(files[:UNMAPPED_SHOWN]) + (", …" if len(files) > UNMAPPED_SHOWN else "")
    return [("unmapped", f"{len(files)} file(s) map to no module: {shown}", "segmently-modules coverage")]


@contextlib.contextmanager
def index_copy(root: Path):
    """`{"GIT_INDEX_FILE": <a copy of the repository's index>}` for the git calls of `drift`:
    `git diff` against the working tree rewrites the index (through `index.lock`) whenever a
    tracked file is stat-dirty, so it refreshes a copy in a temp dir outside the root instead —
    the same answer, the real index untouched. No index file: none is copied (git reads an
    empty one, as it would). The temp dir goes on every exit, Ctrl-C included."""
    real = Path(git(root, "rev-parse", "--git-path", "index").rstrip("\n"))
    real = real if real.is_absolute() else Path(root) / real  # relative to `-C root`
    tmp = Path(tempfile.mkdtemp(prefix="segmently-modules-next-"))
    try:
        copy = tmp / "index"
        if real.is_file():
            shutil.copy2(real, copy)  # its mtime too: git's racy-entry check reads it
        yield {"GIT_INDEX_FILE": str(copy)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def drift(ws, base: str | None, no_git: str | None) -> list[tuple]:
    """`ci`'s drift since `base` (the working tree and new files against it): the targets
    whose code changed without a doc update (MS050) and frozen snapshots changed (MS051) —
    computed against a copy of the git index (`index_copy`). The command: committed drift
    only → `sync-instructions --from-diff BASE..HEAD`; drift that includes an uncommitted or
    untracked file (which a range never sees) → `sync-instructions --module M` per drifted
    module (`drift_command`)."""
    if base is None:
        raise Skip("no --base")
    if no_git:
        raise Skip(no_git)
    with index_copy(ws.root) as env:
        findings, changed = drift_report(ws, base, [], env=env)
        dirty = (set(changed_files(ws.root, base="HEAD", env=env)) & set(changed["files"])
                 if findings else set())  # not in HEAD: edited, staged, deleted or untracked
    parts = []
    for code, what in (("MS050", "code changed without a doc update"),
                       ("MS051", "a frozen snapshot changed")):
        targets = sorted({f.module for f in findings if f.code == code})
        if targets:
            parts.append(f"{what}: {', '.join(targets)}")
    if not parts:
        return []
    return [("drift", f"drift since {base}: {'; '.join(parts)}",
             drift_command(ws, base, findings, dirty))]


def drift_command(ws, base: str, findings: list, dirty: set[str]) -> str:
    """The command for the drift `findings`: `--from-diff BASE..HEAD` when none of their files
    is `dirty` (a code file of an MS050 target, an MS051 snapshot); else `--module` per drifted
    target in registry order (a parent before its children) — or, when the only drift is a
    snapshot outside the modules dir (module `*`), `lint --changed --base BASE`."""
    touched = set(map_files(ws, sorted(dirty))["modules"]) if dirty else set()
    if not any(f.module in touched if f.code == "MS050" else f.path in dirty
               for f in findings):
        return f"segmently-modules sync-instructions --from-diff {quote(f'{base}..HEAD')}"
    order = {t: n for n, t in enumerate(all_targets(ws, ws.registry.modules))}
    names = sorted({f.module for f in findings if f.module != "*"},
                   key=lambda m: (order.get(m, len(order)), m))
    if not names:
        return f"segmently-modules lint --changed --base {quote(base)}"
    return "segmently-modules sync-instructions " + " ".join(f"--module {quote(m)}" for m in names)


def plan(ws, base: str | None) -> dict:
    """{version, items: [{rank, kind, summary, command}], skipped: ["<kind>: <reason>"]} and,
    with --base inside git, `base`: {ref, commit, notes} (`notes`: `ci`'s note when the commit
    is not an ancestor of HEAD)."""
    found: list[tuple] = []
    skipped: list[str] = []
    resolved = None
    if not _set_up(ws):
        found.append(("setup", NOT_SET_UP, "segmently-modules setup"))
    else:
        no_git = work_tree_error(ws.root)
        if base is not None and not no_git:
            base = commit_ref(ws.root, base, origin="flag")  # an unknown ref: exit 2
            commit = commit_sha(ws.root, base)
            resolved = {"ref": base, "commit": commit, "notes": base_notes(ws.root, base, commit)}
        findings = lint_registry(ws)

        def kind(name: str, compute, cannot=(Skip, UsageError)) -> None:
            try:
                found.extend(compute())
            except cannot as e:  # this kind cannot run here; the others still do
                skipped.append(f"{name}: {e}")

        found.extend(lint_errors(ws, findings))
        kind("skills", lambda: skill_copies(ws))
        found.extend(stale_blocks(ws, skipped))
        found.extend(missing_roles(ws))
        found.extend(ejected(findings))
        kind("proposals", lambda: proposals(ws))
        found.extend(lint_warnings(findings))
        kind("unmapped", lambda: unmapped(ws, no_git))
        found.extend(no_code(findings))
        kind("drift", lambda: drift(ws, base, no_git), cannot=Skip)  # git errors: exit 2
    items = [{"rank": rank, "kind": item[0], "summary": item[1], "command": item[2],
              **(item[3] if len(item) > 3 else {})} for rank, item in enumerate(found, 1)]
    data = {"version": __version__, "items": items, "skipped": skipped}
    if resolved is not None:
        data["base"] = resolved
    return data


def run(args) -> int:
    ws = Workspace.load(_root(args), args.config_dir)
    emit("next", plan(ws, args.base), args.json, _render)
    return EXIT_OK


def _render(d) -> None:
    print(f"segmently-modules {d['version']}")
    if d.get("base"):
        print(f"base {d['base']['ref']} at {d['base']['commit'][:SHORT]}")
        for note in d["base"]["notes"]:
            print(f"note: {note}")
    if not d["items"]:
        print("nothing to do")
    for item in d["items"]:
        head = f"{item['rank']}. "
        print(f"{head}{item['summary']}")
        print(f"{' ' * len(head)}{item['command']}")
