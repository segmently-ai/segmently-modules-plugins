"""`segmently-modules roles`: the configured roles with the docs modules have for them, and a role's doc
added to EXISTING modules (a team's new role, or a role a newer engine brings).

  list  one row per configured role (enabled or not), by `order` then name: where it comes
        from (`owner`: engine, a pack id, team, user) and its targets — a module, or a child
        `parent/child`, never a pointer stub — with the role's doc registered and on disk
        (`docs`), with no registered doc (`missing`), children with none, covered by the
        parent's doc (`inherited`), and targets that need no doc for it (`skipped`: `roles
        skip`); read-only, takes no lock
  add ROLE (--all | TARGET…) [--recreate] [--dry-run]
        per target (D3): no doc and unregistered → the doc rendered as `create` renders it
        (`create.render_role_doc`) and registered (`created`); a doc on disk, unregistered →
        registered only, the file never overwritten (`registered`); registered with the file on
        disk → nothing (`exists`); registered, the file missing → nothing (`missing`, with the
        command that writes it) or, with --recreate, the doc rendered at the registered path
        (`recreated`). One registry lock; the docs are written first and removed again —
        still under the lock — when the registry write fails; every refusal comes before the
        first write: also two targets that would write one doc path. --all leaves a child
        with no doc of its own `inherited`; an explicit child TARGET writes it. An explicit TARGET is
        taken without its trailing `/` (`checkout/` is `checkout`). --all leaves a target marked
        not needed `skipped`; an explicit TARGET writes its doc in place of the mark.
  skip ROLE TARGET… [--note TEXT] [--dry-run]
        marks each target as needing no doc for the role: `context_files.roles.<role>` becomes
        `false`, or `{"skip": TEXT}` with --note (`marked`; the same mark already there:
        `unchanged`). Refused before any write: a target with the role's doc on disk (a
        registered path whose file is gone is replaced by the mark). One registry lock, all or
        nothing, as add."""
import argparse
import contextlib
import copy
import os
import tempfile
from pathlib import Path, PurePosixPath

from segmently_modules import create as creator
from segmently_modules.config import core_defaults, discover_packs, enabled_roles, read_toml
from segmently_modules.init_finish import restore
from segmently_modules.layout import build_index
from segmently_modules.output import EXIT_OK, UsageError, emit
from segmently_modules.packs_cmd import ROLE_NAME
from segmently_modules.query import role_paths, skip_mark
from segmently_modules.registry import as_dict, as_list, resolve_module_arg, stub_head
from segmently_modules.store import DEFAULT_LOCK_TIMEOUT_S, atomic_write, open_store
from segmently_modules.workspace import Workspace

ACTIONS = ("list", "add", "skip")
STATUSES = ("created", "registered", "exists", "missing", "recreated", "inherited",
            "skipped")
WRITING = {"created": "would create", "registered": "would register",
           "recreated": "would recreate"}  # the text of a --dry-run row
USAGE = "usage: segmently-modules roles add ROLE (--all | TARGET…) [--recreate] [--dry-run]"
SKIP_USAGE = "usage: segmently-modules roles skip ROLE TARGET… [--note TEXT] [--dry-run]"
LOCK_TIMEOUT_S = DEFAULT_LOCK_TIMEOUT_S  # how long `add` waits for the registry lock


class IntermixedParser(argparse.ArgumentParser):
    """A sub-parser whose positionals may follow its options on every Python: 3.11's argparse
    stops filling a `nargs="*"` positional at the first option (`roles add ROLE --all TARGET`
    would be "unrecognized arguments" there, a `--all takes no target` refusal on 3.12+).
    `parse_known_intermixed_args` calls `parse_known_args` itself, hence the guard."""
    _mixing = False

    def parse_known_args(self, args=None, namespace=None):
        if self._mixing:
            return super().parse_known_args(args, namespace)
        self._mixing = True
        try:
            return self.parse_known_intermixed_args(args, namespace)
        finally:
            self._mixing = False


def register(sub, common) -> None:
    p = sub.add_parser("roles", parents=[common],
                       help="list the roles with their docs, or add a role's doc to existing "
                            "modules",
                       description="list: every configured role by order — standard, enabled, "
                                   "applies_when, description, owner (engine, a pack id, team, "
                                   "user), the modules and children with its doc (docs) and "
                                   "without one (missing). add ROLE (--all | TARGET…): render "
                                   "the role's doc as create does and register it for each "
                                   "target (a module or parent/child); an existing doc file is "
                                   "never overwritten, it is only registered; a registered doc "
                                   "whose file is missing is written only with --recreate; "
                                   "--all = every module and child, a split module's INDEX "
                                   "parent included, never a pointer stub; it leaves a target "
                                   "marked not needed. skip ROLE TARGET… [--note TEXT]: mark "
                                   "each target as needing no doc for the role (false in the "
                                   "registry, or {\"skip\": TEXT} with --note); roles add "
                                   "TARGET lifts the mark.")
    p.add_argument("action", choices=ACTIONS)
    p.add_argument("role", nargs="?", metavar="ROLE",
                   help="add: a role that segmently-modules roles list shows")
    p.add_argument("targets", nargs="*", metavar="TARGET",
                   help="add, skip: a module or parent/child (or a path into the modules dir)")
    p.add_argument("--all", action="store_true", dest="all_targets",
                   help="add: every module and child, never a pointer stub")
    p.add_argument("--recreate", action="store_true",
                   help="add: also write a registered doc whose file is missing")
    p.add_argument("--dry-run", action="store_true",
                   help="add, skip: report what would be written, write nothing")
    p.add_argument("--note", metavar="TEXT",
                   help="skip: why the module needs no doc for the role (kept with the mark)")
    p.set_defaults(func=run)
    p.__class__ = IntermixedParser  # the sub-parser argparse built, parsing intermixed


# ---------------------------------------------------------------- targets and the role scan

def _rel_dir(ws, target: str) -> str:
    """The target's directory by `create`'s path rule."""
    parent, _, child = target.partition("/")
    mdir = ws.config["paths"]["modules_dir"]
    return f"{mdir}/{parent}/submodules/{child}" if child else f"{mdir}/{parent}"


def _is_stub(ws, target: str) -> bool:
    """The target's doc (by `create`'s path rule) is a pointer stub (`registry.stub_head`)."""
    parent, _, child = target.partition("/")
    return stub_head(ws.root, ws.config, f"{parent}/submodules/{child}" if child
                     else parent) is not None


def _holder(modules: dict, target: str):
    parent, _, child = target.partition("/")
    entry = modules[parent]
    return entry["submodules"][child] if child else entry


def all_targets(ws, modules: dict) -> list[str]:
    """Every registered module (a split module's INDEX parent included, SI-P61-3) and every
    child `parent/child`, in registry order (a parent before its children); an entry that is not
    an object and a pointer stub (with its children) are never targets."""
    out = []
    for name, entry in modules.items():
        if not isinstance(entry, dict) or _is_stub(ws, name):
            continue
        out.append(name)
        out += [f"{name}/{child}" for child, sub in as_dict(entry.get("submodules")).items()
                if isinstance(sub, dict) and not _is_stub(ws, f"{name}/{child}")]
    return out


def _resolve(ws, modules: dict, arg: str) -> str:
    """An explicit TARGET (`name`, `parent/child` or a path into the modules dir) as a target
    of `modules`; an unknown name and a pointer stub (SI-P61-2) are refusals."""
    mdir, doc = ws.config["paths"]["modules_dir"], ws.config["paths"]["module_doc"]
    target = resolve_module_arg(arg, mdir)
    target = target.rstrip("/") or target  # `checkout/` names the module `checkout`
    parent, _, child = target.partition("/")
    stub = UsageError(f"'{target}' is a pointer stub ({_rel_dir(ws, target)}/{doc}), not a "
                      f"module — roles add writes no doc into it")
    if parent not in modules:
        if not child and stub_head(ws.root, ws.config, parent):
            raise stub
        near = [n for n in modules if parent.lower() in n.lower()]
        hint = f" — closest: {', '.join(near[:5])}" if near else ""
        raise UsageError(f"unknown module '{target}'{hint}")
    if not isinstance(modules[parent], dict):
        raise UsageError(f"registry entry '{parent}' is not an object")
    if child:
        subs = as_dict(modules[parent].get("submodules"))
        if child not in subs:
            raise UsageError(f"unknown module '{target}' (children of '{parent}': "
                             f"{', '.join(subs) or 'none'})")
        if not isinstance(subs[child], dict):
            raise UsageError(f"registry entry '{target}' is not an object")
    if _is_stub(ws, target) or (child and _is_stub(ws, parent)):
        raise stub
    return target


def _registered(holder: dict, role: str) -> list | None:
    """The role's registered value of a target (a path or a list of paths), None when the role
    is not registered."""
    roles = as_dict(holder.get("context_files")).get("roles")
    return roles[role] if isinstance(roles, dict) and role in roles else None


def _layers(ws) -> list[tuple[str, str, str, dict]]:
    """(kind, owner, label, [roles] table) of every config layer, in merge order: the engine
    defaults, the packs (lowest precedence first), the team config, the user config."""
    layers = [("engine", "engine", "the engine defaults", as_dict(core_defaults().get("roles")))]
    for pack in reversed(discover_packs(ws.config_dir, ws.root)):
        where = "built-in" if pack["builtin"] else ws.rel(pack["path"])
        layers.append(("pack", pack["id"], f"pack '{pack['id']}' ({where})",
                       as_dict(pack["data"].get("roles"))))
    for owner, name in (("team", "config.toml"), ("user", "config.user.toml")):
        path = ws.config_dir / name
        if path.is_file():
            layers.append((owner, owner, ws.rel(path), as_dict(read_toml(path).get("roles"))))
    return layers


def _owner(role: str, layers: list) -> str:
    """The pack id when a pack declares the role (the highest precedence one), else `engine`
    when the engine defaults do, else `team` or `user` — the layer that first declares it."""
    packs = [owner for kind, owner, _, roles in layers if kind == "pack" and role in roles]
    if packs:
        return packs[-1]
    return next((owner for _, owner, _, roles in layers if role in roles), "engine")


def role_rows(ws, enabled_only: bool = False) -> list[dict]:
    """The role scan behind `roles list` (and `next`): one row per configured role — or per
    enabled role with `enabled_only` — sorted by order, then name: {name, order, standard,
    enabled, applies_when, description, owner, docs, missing, inherited, skipped}; `docs` = the
    targets (sorted) whose registered doc paths are all on disk, `missing` = the targets with no
    registered doc
    for the role (a registered path whose file is absent is in neither list: lint's MS004);
    `inherited` = the children with no registered doc — `show` reads the parent's role doc for
    them as the baseline, so they are covered, not missing (a parent without a doc stays in
    `missing`); `skipped` = the targets marked as needing no doc for the role (`roles skip`).
    Read-only: never writes, takes no lock."""
    roles, layers = ws.config.get("roles") or {}, _layers(ws)
    modules = ws.registry.modules
    targets = all_targets(ws, modules)
    rows = []
    for name, spec in roles.items():
        spec = as_dict(spec)
        if enabled_only and not spec.get("enabled", True):
            continue
        docs, missing, inherited, skipped = [], [], [], []
        for target in targets:
            value = _registered(_holder(modules, target), name)
            paths = role_paths({"roles": {name: value}}, name) if value is not None else []
            if value is None:
                (inherited if "/" in target else missing).append(target)
            elif skip_mark(value):
                skipped.append(target)
            elif paths and all(isinstance(p, str) and p and (ws.root / p).exists()
                               for p in paths):
                docs.append(target)
        rows.append({"name": name, "order": spec.get("order", 1000),
                     "standard": bool(spec.get("standard", False)),
                     "enabled": bool(spec.get("enabled", True)),
                     "applies_when": spec.get("applies_when"),
                     "description": spec.get("description", ""), "owner": _owner(name, layers),
                     "docs": sorted(docs), "missing": sorted(missing),
                     "inherited": sorted(inherited), "skipped": sorted(skipped)})
    return sorted(rows, key=lambda r: (r["order"], r["name"]))


# ---------------------------------------------------------------------------- roles add

def check_role(ws, role: str) -> None:
    """Refuse a role name outside the naming rule, a role no layer configures, a disabled one
    (naming the layer that disabled it last)."""
    if not ROLE_NAME.fullmatch(role) or len(role) > 48:
        raise UsageError(f"role {role!r}: use lowercase letters, digits and '_', words joined "
                         f"by '-', starting with a letter (max 48)")
    roles = ws.config.get("roles") or {}
    if role not in roles:
        raise UsageError(f"unknown role '{role}' (roles: "
                         f"{', '.join(enabled_roles(ws.config)) or 'none'})")
    if not roles[role].get("enabled", True):
        labels = [label for _, _, label, table in _layers(ws)
                  if "enabled" in as_dict(table.get(role))]
        raise UsageError(f"role '{role}' is disabled: [roles.{role}] enabled = false in "
                         f"{labels[-1] if labels else 'the config'} — enable it there first")


def _check_path(ws, rel: str) -> None:
    """Refuse a doc path `roles add` would write or register: outside the repository, a
    symlink anywhere on it (never written through, P5A-AC-012's rule), a directory on it that
    is a file, or an existing doc that is not a regular file."""
    pure = PurePosixPath(rel)
    if not pure.parts or pure.is_absolute() or Path(rel).is_absolute() or ".." in pure.parts:
        raise UsageError(f"{rel}: a role doc path must lie inside the repository; nothing "
                         f"written")
    path = ws.root
    for i, part in enumerate(pure.parts):
        path, shown = path / part, PurePosixPath(*pure.parts[:i + 1]).as_posix()
        if path.is_symlink():
            raise UsageError(f"{shown} is in the way: a symlink — roles add never writes "
                             f"through one; nothing written")
        if not os.path.lexists(path):
            return
        if i < len(pure.parts) - 1 and not path.is_dir():
            raise UsageError(f"{shown} is not a directory — {rel} cannot be written there; "
                             f"nothing written")
    if not path.is_file():
        raise UsageError(f"{rel} is not a regular file; nothing written")


def _values(ws, holder: dict, target: str) -> dict:
    """The placeholders `create` would use for this target: name, title, description, status
    (the entry's, else [create] default_status), keywords, parent."""
    parent, _, child = target.partition("/")
    desc, status = holder.get("description"), holder.get("status")
    return creator.doc_values(
        child or parent, parent if child else None,
        desc.strip() if isinstance(desc, str) else "",
        status if isinstance(status, str) else ws.config["create"]["default_status"],
        [k for k in as_list(holder.get("keywords")) if isinstance(k, str)])


def _check_holder(holder: dict, target: str) -> None:
    """Refuse a target whose `context_files`, or its `roles`, is present but not an object."""
    cf = holder.get("context_files")  # a key that is present must hold an object (null too)
    if "context_files" in holder and not isinstance(cf, dict):
        raise UsageError(f"context_files of '{target}' is not an object — fix it first "
                         f"(segmently-modules lint)")
    if "roles" in as_dict(cf) and not isinstance(cf["roles"], dict):
        raise UsageError(f"context_files.roles of '{target}' is not an object — fix it first "
                         f"(segmently-modules lint)")


def _plan_target(ws, role: str, target: str, holder: dict, recreate: bool) -> dict:
    """One target's row: {module, status, path, command?} plus what to write (`write`: root-
    relative paths, `text`) and whether to register `path` (`register`). A not-needed mark
    reads as no registration: the doc is written and registered in its place."""
    _check_holder(holder, target)
    value = _registered(holder, role)
    if value is not None and not skip_mark(value):
        paths = role_paths({"roles": {role: value}}, role)
        if not paths or not all(isinstance(p, str) and p for p in paths):
            raise UsageError(f"context_files.roles.{role} of '{target}' is not a path or a list "
                             f"of paths: {value!r} — fix it first (segmently-modules lint)")
        absent = [p for p in paths if not (ws.root / p).exists()]
        status = "exists" if not absent else "recreated" if recreate else "missing"
        row = {"module": target, "status": status, "path": absent[0] if absent else paths[0],
               "write": absent if recreate else [], "register": False}
    else:
        path = f"{_rel_dir(ws, target)}/roles/{role}.md"
        on_disk = os.path.lexists(ws.root / path)
        row = {"module": target, "status": "registered" if on_disk else "created", "path": path,
               "write": [] if on_disk else [path], "register": True}
    if row["status"] == "missing":
        row["command"] = f"segmently-modules roles add {role} {target} --recreate"
    for rel in row["write"] + ([row["path"]] if row["register"] else []):
        _check_path(ws, rel)
    row["text"] = (creator.render_role_doc(ws, role, _values(ws, holder, target))
                   if row["write"] else None)
    return row


def plan_add(ws, role: str, every: bool, names: list[str], recreate: bool,
             modules: dict) -> list[dict]:
    """Every target's row against `modules` (the registry as read, or as locked); validates
    everything — targets, registered values, paths, no doc path written for two targets — and
    writes nothing."""
    targets = all_targets(ws, modules) if every else \
        list(dict.fromkeys(_resolve(ws, modules, arg) for arg in names))
    rows = []
    for t in targets:
        holder = _holder(modules, t)
        if every and skip_mark(_registered(holder, role)):  # marked not needed (`roles skip`)
            rows.append({"module": t, "status": "skipped", "write": [], "register": False,
                         "path": f"{_rel_dir(ws, t)}/roles/{role}.md", "text": None})
            continue
        if every and "/" in t and _registered(holder, role) is None:
            # a child with no doc of its own is covered by its parent's (as `show` reads it);
            # only an explicit TARGET gives it a doc of its own (SI-P81-5)
            rows.append({"module": t, "status": "inherited", "write": [], "register": False,
                         "path": f"{_rel_dir(ws, t)}/roles/{role}.md", "text": None})
            continue
        rows.append(_plan_target(ws, role, t, holder, recreate))
    writer: dict[str, str] = {}
    for row in rows:
        for rel in row["write"]:
            if rel in writer:
                raise UsageError(f"'{writer[rel]}' and '{row['module']}' would both write {rel} "
                                 f"— a role doc path belongs to one target; nothing written")
            writer[rel] = row["module"]
    return rows


def write_new_doc(path: Path, text: str, rel: str) -> None:
    """Create `path` with `text` (UTF-8, mode 0644 as `create` writes it): a temp file hard-
    linked into place — never over a file that appeared meanwhile, never half."""
    try:
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    except OSError as e:
        raise UsageError(f"cannot write {rel}: {e.strerror or e}") from None
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o644)
        try:
            os.link(tmp, path)
        except FileExistsError:
            raise UsageError(f"{rel} appeared while roles add was running; run it again") \
                from None
    except OSError as e:
        raise UsageError(f"cannot write {rel}: {e.strerror or e}") from None
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)


def _make_dirs(ws, directory: Path, rel: str) -> list[Path]:
    """Create `directory` and its missing parents; the ones this call created, top first."""
    made = []
    for d in reversed([directory, *directory.parents]):
        if d == ws.root or ws.root not in d.parents or d.is_dir():
            continue
        try:
            d.mkdir()
        except OSError as e:
            raise UsageError(f"cannot write {rel}: {e.strerror or e}") from None
        made.append(d)
    return made


def _register(modules: dict, role: str, rows: list[dict]) -> set[str]:
    """Add each registering row's path under `context_files.roles` (an entry without
    `context_files` gains `{"roles": {ROLE: PATH}}` and nothing else); the top-level modules
    whose entries changed."""
    touched = set()
    for row in rows:
        if row["register"]:
            holder = _holder(modules, row["module"])
            holder.setdefault("context_files", {}).setdefault("roles", {})[role] = row["path"]
            touched.add(row["module"].partition("/")[0])
    return touched


def apply_add(ws, role: str, every: bool, names: list[str], recreate: bool) -> list[dict]:
    """Under one registry lock: plan again against the locked registry, write the docs, then
    the registry (per-module: the changed entry files, then the index). On any failure — a
    registry that changed since it was read, a failed write, Ctrl-C — the registry files are
    put back, then the written docs are removed with the directories this run created, both
    while the lock is still held (a writer waiting for it never plans against a doc that then
    goes), and the error is raised. Once the registry is written the run is done: a Ctrl-C
    after that point leaves every write in place (docs and entries agree)."""
    store = open_store(ws)
    store.lock_timeout_s = LOCK_TIMEOUT_S
    with store.locked():
        written: list[Path] = []
        made: list[Path] = []
        try:
            original = store.load()
            raw = copy.deepcopy(original.raw)
            rows = plan_add(ws, role, every, names, recreate, raw["modules"])
            for row in rows:
                for rel in row["write"]:
                    path = ws.root / rel
                    made += _make_dirs(ws, path.parent, rel)
                    write_new_doc(path, row["text"], rel)
                    written.append(path)
            _commit(ws, store, original, raw, _register(raw["modules"], role, rows))
        except BaseException:
            _remove(written, made)  # still under the lock
            raise
    return [_public(row) for row in rows]  # the commit point was reached


def _commit(ws, store, original, raw: dict, touched: set[str]) -> None:
    """Write `raw` over the registry read as `original` (per-module: the entry files of the
    `touched` modules, then the index); on any failure every registry file is put back and
    the error raised."""
    per_module = ws.config["paths"]["registry_layout"] == "per-module"
    files = [store.path] if not per_module else \
        [store.entry_path(m) for m in sorted(touched)] + [store.path]
    saved = {p: p.read_bytes() if p.is_file() else None for p in files}
    stage = (files[:-1] or files) if per_module else files  # being written right now
    try:
        if store.commit(original, raw) and per_module:
            stage = [store.path]
            text, stale = build_index(ws.root, ws.config)
            if stale:
                atomic_write(store.path, text)
    except BaseException as e:
        _put_back(ws, saved, stage, e)
        raise


# --------------------------------------------------------------------------- roles skip

def _mark(note: str | None):
    """The registry value of a not-needed mark."""
    return False if note is None else {"skip": note}


def plan_skip(ws, role: str, names: list[str], note: str | None, modules: dict) -> list[dict]:
    """Every target's row {module, status}: `marked` (the mark to write) or `unchanged` (the
    same mark is there); refuses — before any write — a target with the role's doc on disk."""
    rows = []
    for t in dict.fromkeys(_resolve(ws, modules, arg) for arg in names):
        holder = _holder(modules, t)
        _check_holder(holder, t)
        value = _registered(holder, role)
        if value is not None and not skip_mark(value):
            on_disk = [p for p in role_paths({"roles": {role: value}}, role)
                       if isinstance(p, str) and p and (ws.root / p).exists()]
            if on_disk:
                raise UsageError(f"'{t}' has a {role} doc ({on_disk[0]}) — roles skip marks a "
                                 f"module without one; delete the doc first")
        same = skip_mark(value) and value == _mark(note)
        rows.append({"module": t, "status": "unchanged" if same else "marked"})
    return rows


def apply_skip(ws, role: str, names: list[str], note: str | None) -> list[dict]:
    """Under one registry lock: plan again against the locked registry and write the marks
    (all or nothing, as `apply_add`)."""
    store = open_store(ws)
    store.lock_timeout_s = LOCK_TIMEOUT_S
    with store.locked():
        original = store.load()
        raw = copy.deepcopy(original.raw)
        rows = plan_skip(ws, role, names, note, raw["modules"])
        touched = set()
        for row in rows:
            if row["status"] == "marked":
                holder = _holder(raw["modules"], row["module"])
                holder.setdefault("context_files", {}).setdefault("roles", {})[role] = \
                    _mark(note)
                touched.add(row["module"].partition("/")[0])
        _commit(ws, store, original, raw, touched)
    return rows


def _remove(written: list[Path], made: list[Path]) -> None:
    """Remove the docs a failed run wrote, then the directories it created that are empty
    again (deepest first)."""
    for path in written:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
    for d in reversed(made):
        with contextlib.suppress(OSError):
            d.rmdir()


def _put_back(ws, saved: dict, stage: list[Path], error: BaseException) -> None:
    """Restore every registry file the failed commit may have written (an untouched one is
    left alone); an OSError becomes a refusal naming the file being written (its own name, or
    the target of its temp file, else the files of the `stage` that failed). What could not be
    put back is named too (restore it by hand)."""
    failed = []
    for path, data in saved.items():
        try:
            restore(path, data)
        except OSError:
            failed.append(ws.rel(path))
    note = f" — could not put back: {', '.join(failed)} (restore by hand)" if failed else ""
    if isinstance(error, OSError):
        named = Path(error.filename) if isinstance(error.filename, str) else None
        hit = [p for p in saved if named is not None and (
            p == named or (p.parent == named.parent and named.name.startswith(f".{p.name}.")))]
        where = ", ".join(ws.rel(p) for p in (hit or stage))
        raise UsageError(f"cannot write {where}: {error.strerror or error}; nothing "
                         f"written{note}") from None
    if note and isinstance(error, UsageError):
        raise UsageError(f"{error}{note}") from None


def _public(row: dict) -> dict:
    """A result row as `--json` shows it: {module, status, path, command?}."""
    return {k: row[k] for k in ("module", "status", "path", "command") if k in row}


# ------------------------------------------------------------------------------------ run

def run(args) -> int:
    if args.action == "list":
        if args.role is not None or args.targets:
            raise UsageError("roles list takes no ROLE or TARGET")
        for flag, on, verbs in (("--all", args.all_targets, "roles add"),
                                ("--recreate", args.recreate, "roles add"),
                                ("--dry-run", args.dry_run, "roles add and roles skip"),
                                ("--note", args.note is not None, "roles skip")):
            if on:
                raise UsageError(f"{flag} applies to {verbs}")
        ws = Workspace.from_args(args)
        emit("roles", {"roles": role_rows(ws)}, args.json, _render_list)
        return EXIT_OK
    if args.action == "skip":
        return _run_skip(args)
    if args.note is not None:
        raise UsageError("--note applies to roles skip")
    if args.role is None:
        raise UsageError(f"roles add needs a ROLE — {USAGE}")
    if args.all_targets and args.targets:
        raise UsageError(f"--all takes no target — {USAGE}")
    if not args.all_targets and not args.targets:
        raise UsageError(f"roles add needs --all or a TARGET — {USAGE}")
    ws = Workspace.from_args(args)
    check_role(ws, args.role)
    rows = plan_add(ws, args.role, args.all_targets, args.targets, args.recreate,
                    ws.registry.modules)  # every refusal before the lock and the first write
    if args.dry_run or not any(row["write"] or row["register"] for row in rows):
        results = [_public(row) for row in rows]  # nothing to write: no lock either
    else:
        results = apply_add(ws, args.role, args.all_targets, args.targets, args.recreate)
    emit("roles", {"role": args.role, "dry_run": args.dry_run, "results": results}, args.json,
         _render_add)
    return EXIT_OK


def _run_skip(args) -> int:
    if args.role is None:
        raise UsageError(f"roles skip needs a ROLE — {SKIP_USAGE}")
    if args.all_targets:
        raise UsageError(f"roles skip takes TARGETs, not --all — to turn a role off for every "
                         f"module, set enabled = false in [roles.{args.role}]")
    if args.recreate:
        raise UsageError("--recreate applies to roles add")
    if not args.targets:
        raise UsageError(f"roles skip needs a TARGET — {SKIP_USAGE}")
    note = None if args.note is None else args.note.strip()
    if note == "":
        raise UsageError("--note needs a text: why the module needs no doc for the role")
    ws = Workspace.from_args(args)
    check_role(ws, args.role)
    rows = plan_skip(ws, args.role, args.targets, note, ws.registry.modules)  # refusals first
    if not args.dry_run and any(r["status"] == "marked" for r in rows):
        rows = apply_skip(ws, args.role, args.targets, note)
    emit("roles", {"role": args.role, "note": note, "dry_run": args.dry_run, "results": rows},
         args.json, _render_skip)
    return EXIT_OK


def _render_list(d) -> None:
    for r in d["roles"]:
        kind = ("standard" if r["standard"] else
                f"tag {r['applies_when']}" if r["applies_when"] else "optional")
        state = "enabled" if r["enabled"] else "disabled"
        inherited = f"  {len(r['inherited'])} inherited" if r.get("inherited") else ""
        skipped = f"  not needed {len(r['skipped'])}" if r.get("skipped") else ""
        print(f"{r['name']:<20} {r['order']:>5}  {kind:<12} {state:<8}  {r['owner']:<16} "
              f"docs {len(r['docs']):<4} missing {len(r['missing'])}{inherited}{skipped}")


def _render_add(d) -> None:
    for r in d["results"]:
        status = WRITING.get(r["status"], r["status"]) if d["dry_run"] else r["status"]
        hint = f"  — {r['command']}" if "command" in r else ""
        print(f"{status:<14} {r['module']:<32} {r['path']}{hint}")
    counts = [(s, sum(r["status"] == s for r in d["results"])) for s in STATUSES]
    summary = ", ".join(f"{n} {s}" for s, n in counts if n)
    if not d["results"]:
        print(f"{d['role']}: no module to add it to")
    elif all(r["status"] == "exists" for r in d["results"]):
        print(f"{d['role']}: {summary} — nothing to do")
    else:
        print(f"{d['role']}: {summary}{' (dry run: nothing written)' if d['dry_run'] else ''}")


def _render_skip(d) -> None:
    for r in d["results"]:
        status = "would mark" if d["dry_run"] and r["status"] == "marked" else r["status"]
        print(f"{status:<14} {r['module']}")
    counts = [(s, sum(r["status"] == s for r in d["results"])) for s in ("marked", "unchanged")]
    summary = ", ".join(f"{n} {s}" for s, n in counts if n)
    if all(r["status"] == "unchanged" for r in d["results"]):
        print(f"{d['role']}: {summary} — nothing to do")
        return
    why = f" — {d['note']}" if d["note"] else ""
    dry = " (dry run: nothing written)" if d["dry_run"] else ""
    print(f"{d['role']}: {summary} not needed{why}{dry}")
