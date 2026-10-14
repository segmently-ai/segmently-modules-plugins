"""`segmently-modules create`: scaffold a module (or `--parent` child) — docs from templates plus its
registry entry. Answers come from `--answers file.json`, flags, or (on a terminal) prompts;
with `--non-interactive` a missing answer is an error that lists every missing key.

Template resolution (first hit wins), for `MODULE.md`, `roles/<role>.md` and `agents-md.md`
(`resolve_template_source` names the layer — `segmently-modules templates list` shows it):
  1. `<config_dir>/overrides/templates/<path>`                         source "override"
  2. a role's own `template` (path inside its owning pack)             "role-template:<pack>"
  3. `<pack>/templates/<path>` for packs in precedence order           "pack:<pack>"
  4. engine defaults: MODULE.md, agents-md.md and one file per         "engine"
     standard role; `roles/_role.md` for any other role                "engine-fallback"
`choose/rules.md` (the rules of the `choose` work order) resolves the same way but has no
"engine-fallback": a missing engine file stays "engine" and reading it fails (`workorder`).
Templates use `${name}` placeholders: name, title, description, status, keywords, parent,
role, role_description, article (`a` or `an` before the role)."""
from __future__ import annotations

import contextlib
import errno
import json
import os
import re
import stat
import string
import sys
from importlib import resources
from pathlib import Path

from segmently_modules.config import enabled_roles
from segmently_modules.fields import value_matches
from segmently_modules.output import UsageError
from segmently_modules.store import atomic_write, open_store

NAME = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
BASE_ANSWERS = {"description", "keywords", "status", "tags", "roles"}
# keywords that match too many tasks to route one (`create` warns; a hint, not a rule)
GENERIC_KEYWORDS = ("common", "data", "helper", "info", "item", "list", "misc", "stuff", "util")
SHORT_KEYWORD = 3  # a keyword this long or shorter matches many tasks
_WORD = re.compile(r"[a-z]{4,}")  # the plural hint applies to one lowercase word of 4+ letters


def article(word: str) -> str:
    """The indefinite article before `word`: `an` before a vowel letter, else `a`."""
    return "an" if word[:1] in ("a", "e", "i", "o", "u") else "a"


def plural(word: str) -> bool:
    """A word reads as plural when it ends in `s` but not in `ss`, `us` or `is`."""
    return word.endswith("s") and not word.endswith(("ss", "us", "is"))


def counterpart(word: str) -> str:
    """The plain English singular of a plural word or the plural of a singular one, by suffix
    only (a hint, not linguistics): `ies` <-> consonant + `y`; `sses`, `xes`, `zes`, `ches`,
    `shes` <-> the word without `es`; otherwise `s`."""
    if plural(word):
        if word.endswith("ies"):
            return word[:-3] + "y"
        if word.endswith(("sses", "xes", "zes", "ches", "shes")):
            return word[:-2]
        return word[:-1]
    if word.endswith("y") and word[-2:-1] not in ("a", "e", "i", "o", "u"):
        return word[:-1] + "ies"
    if word.endswith(("s", "x", "z", "ch", "sh")):
        return word + "es"
    return word + "s"


def keyword_notes(keywords: list[str]) -> list[tuple[str, str, tuple[str, str] | None]]:
    """(kind, warning, (keyword, counterpart) for a plural hint) per keyword that may route
    poorly — never a refusal: `short` (3 characters or fewer), `generic` (`GENERIC_KEYWORDS`),
    or `plural`: a single lowercase word of 4+ letters whose plain singular / plural counterpart
    is missing (matching is exact-token) and is not itself a generic word (`utils` never
    suggests `util`)."""
    have = {k.strip() for k in keywords if isinstance(k, str)}
    out = []
    for keyword in dict.fromkeys(k for k in keywords if isinstance(k, str)):
        word = keyword.strip()
        if len(word) <= SHORT_KEYWORD:
            out.append(("short", f"keyword '{keyword}' is short ({len(word)} characters): it "
                                 f"matches many tasks — prefer a longer domain word", None))
        elif word.lower() in GENERIC_KEYWORDS:
            out.append(("generic", f"keyword '{keyword}' is a generic word: it matches many "
                                   f"tasks — prefer a domain word", None))
        elif _WORD.fullmatch(word):
            other = counterpart(word)
            if other not in have and other not in GENERIC_KEYWORDS:
                form = "singular" if plural(word) else "plural"
                out.append(("plural", f"keyword '{keyword}' has no {form} '{other}': matching "
                                      f"is exact, so a task that says '{other}' does not match "
                                      f"it — add it if tasks use it", (keyword, other)))
    return out


def keyword_warnings(keywords: list[str]) -> list[str]:
    """`data.warnings` of `create`: one warning per keyword (`keyword_notes`), keyword order."""
    return [text for _, text, _ in keyword_notes(keywords)]


def warning_lines(keywords: list[str]) -> list[str]:
    """The text-mode stderr lines: each short and generic warning on its own line, then ONE
    line for every plural hint of the run (the count, the first three pairs, `--json` for the
    rest)."""
    notes = keyword_notes(keywords)
    lines = [text for kind, text, _ in notes if kind != "plural"]
    pairs = [pair for kind, _, pair in notes if kind == "plural"]
    if pairs:
        shown = ", ".join(f"{a} → {b}" for a, b in pairs[:3])
        more = f" and {len(pairs) - 3} more" if len(pairs) > 3 else ""
        lines.append(f"{len(pairs)} keyword(s) without their singular / plural form (matching "
                     f"is exact: add the form tasks use): {shown}{more} — --json lists each")
    return lines


def ask_fields(ws, scope: str) -> dict:
    return {n: d for n, d in ws.fields.items() if d.ask_on_create and scope in d.scope}


def _create_cfg(ws) -> dict:
    return ws.config["create"]


def validate_answers(ws, answers: dict, scope: str) -> list[str]:
    """Missing required keys (for the error message); raises for invalid values."""
    cfg = _create_cfg(ws)
    extra = ask_fields(ws, scope)
    unknown = set(answers) - BASE_ANSWERS - set(extra)
    if unknown:
        raise UsageError(f"unknown answer key(s): {', '.join(sorted(unknown))} "
                         f"(allowed: {', '.join(sorted(BASE_ANSWERS | set(extra)))})")
    missing = [k for k in ("description", "keywords") if k not in answers]
    missing += [k for k in extra if k not in answers]
    if missing:
        return missing
    desc = answers["description"]
    if not isinstance(desc, str) or not (cfg["description_min"] <= len(desc.strip())
                                         <= cfg["description_max"]):
        raise UsageError(f"description must be {cfg['description_min']}–"
                         f"{cfg['description_max']} characters")
    kws = answers["keywords"]
    need = cfg["min_keywords"] if scope == "module" else 1
    if not (isinstance(kws, list) and all(isinstance(k, str) and k.strip() for k in kws)
            and len(set(kws)) >= need):
        raise UsageError(f"keywords must be at least {need} distinct non-empty strings")
    status = answers.get("status", cfg["default_status"])
    if scope == "module" and status not in ws.config["registry"]["statuses"]:
        raise UsageError(f"status {status!r} not in {ws.config['registry']['statuses']}")
    for key in ("tags", "roles"):
        v = answers.get(key, [])
        if not (isinstance(v, list) and all(isinstance(i, str) for i in v)):
            raise UsageError(f"{key} must be a list of strings")
    for name, fdef in extra.items():
        if not value_matches(fdef, answers[name]):
            raise UsageError(f"answer {name!r} does not match type {' | '.join(fdef.type)}")
    return []


def prompt_missing(ws, answers: dict, missing: list[str]) -> dict:
    out = dict(answers)
    for key in missing:
        fdef = ws.fields.get(key)
        hint = {"description": "one sentence: WHAT it does, WHY, WHEN to use it",
                "keywords": "comma-separated routing terms"}.get(key, fdef.description if fdef else "")
        raw = input(f"{key} ({hint}): ").strip()
        if key == "keywords":
            out[key] = [k.strip() for k in raw.split(",") if k.strip()]
        elif fdef and fdef.type != ("string",):
            try:
                out[key] = json.loads(raw)
            except json.JSONDecodeError:
                raise UsageError(f"{key}: expected JSON for type {' | '.join(fdef.type)}") from None
        else:
            out[key] = raw
    return out


def roles_to_scaffold(ws, answers: dict, standard: bool = True) -> list[str]:
    """The roles whose docs `create` writes: every standard role (unless `standard` is off — a
    child that inherits the parent's docs for them), the `applies_when` roles of the tags, and
    the roles asked for."""
    roles = ws.config.get("roles") or {}
    wanted = set(answers.get("roles", []))
    unknown = wanted - set(enabled_roles(ws.config))
    if unknown:
        raise UsageError(f"unknown role(s): {', '.join(sorted(unknown))}")
    tags = set(answers.get("tags", []))
    return [r for r in enabled_roles(ws.config)
            if (standard and roles[r].get("standard")) or roles[r].get("applies_when") in tags
            or r in wanted]


def engine_templates() -> Path:
    """The engine's default templates directory (package data)."""
    return Path(str(resources.files("segmently_modules").joinpath("defaults/templates")))


def _candidate_exists(ws, path: Path) -> bool:
    """Does a template candidate exist? `lstat` ENOENT / ENOTDIR: no, the next layer decides. A
    candidate that exists but cannot be used as a template (a directory, a FIFO, a dangling
    symlink or loop, no permission on it or a parent) is `cannot read <path>: <reason>`, exit 2."""
    def refuse(reason):
        return UsageError(f"cannot read {ws.rel(path).replace(chr(0), chr(92) + '0')}: {reason}")
    try:
        os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return False
    except ValueError:  # a NUL in the path
        raise refuse("embedded null byte") from None
    except OSError as e:
        if e.errno == errno.ENAMETOOLONG:  # a name that long cannot exist: the next layer
            return False
        raise refuse(e.strerror or e) from None
    try:
        st = os.stat(path)
        if not stat.S_ISREG(st.st_mode):  # never open a FIFO or a device
            raise refuse("not a regular file")
        with open(path, "rb"):
            pass
    except OSError as e:
        raise refuse(e.strerror or e) from None
    return True


def resolve_template_source(ws, relpath: str, role: str | None = None,
                            fallback: bool = True) -> tuple[str, Path]:
    """(source, path) of the template file that wins for `relpath` — see the module docstring
    for the order and the source names. `fallback=False` (a template that is no role's, like
    `choose/rules.md`): a missing engine file is still `engine` and its expected path, never
    the generic role template."""
    candidates = [("override", ws.config_dir / "overrides" / "templates" / relpath)]
    spec = (ws.config.get("roles") or {}).get(role or "", {})
    pack_dirs = ws.config.get("_pack_dirs", {})
    # the pack whose `template` the role uses; a template set only by the team config is a file
    # of the pack that owns the role
    owner = spec.get("template_owner", spec.get("owner"))
    if role and spec.get("template") and owner in pack_dirs:
        candidates.append((f"role-template:{owner}", Path(pack_dirs[owner]) / spec["template"]))
    candidates += [(f"pack:{p}", Path(pack_dirs[p]) / "templates" / relpath)
                   for p in ws.config.get("_packs", [])]
    for source, path in candidates:
        if _candidate_exists(ws, path):
            return source, path
    engine = engine_templates() / relpath
    if engine.is_file():
        return "engine", engine
    if not fallback:
        return "engine", engine
    return "engine-fallback", engine_templates() / "roles" / "_role.md"


def resolve_template(ws, relpath: str, role: str | None = None) -> str:
    """The text of the winning template (newlines translated, as a text-mode read gives them). A
    template that is not UTF-8, or that cannot be read after all, is `cannot read <path>:
    <reason>` (exit 2, root-relative inside the root), never an internal error."""
    path = resolve_template_source(ws, relpath, role)[1]
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise UsageError(f"cannot read {ws.rel(path)}: not valid UTF-8") from None
    except OSError as e:
        raise UsageError(f"cannot read {ws.rel(path)}: {e.strerror or e}") from None


def doc_values(name: str, parent: str | None, description: str, status: str,
               keywords: list[str]) -> dict:
    """The placeholders every generated doc of a module shares: name, title (from the name),
    description, status, keywords (joined with ', ') and parent ('' for a top-level module)."""
    return {"name": name, "title": name.replace("-", " ").title(), "description": description,
            "status": status, "keywords": ", ".join(keywords), "parent": parent or ""}


def render_role_doc(ws, role: str, values: dict) -> str:
    """The text of `roles/<role>.md` for a module with `values` (`doc_values`): the winning
    template (`resolve_template`) with the module's placeholders and role, role_description
    and article filled in, ending in a newline. `create` and `roles add` both write this."""
    spec = ws.config["roles"][role]
    text = string.Template(resolve_template(ws, f"roles/{role}.md", role)).safe_substitute(
        values, role=role, role_description=spec.get("description", ""), article=article(role))
    return text if text.endswith("\n") else text + "\n"


def _check_name(value: str) -> None:
    if not NAME.fullmatch(value) or len(value) > 48:
        raise UsageError(f"module name {value!r}: use lowercase words joined by '-' (max 48)")


def plan_create(ws, name: str, parent: str | None, answers: dict,
                standard_roles: bool = True) -> dict:
    """Validate everything and compute files + entry; writes nothing. `standard_roles=False`
    (a child only) scaffolds just the roles of `answers` (`roles`, `tags`)."""
    _check_name(name)
    if not standard_roles and not parent:
        raise UsageError("--no-standard-roles needs --parent: a top-level module gets every "
                         "standard role doc")
    modules = ws.registry.modules
    mdir = ws.config["paths"]["modules_dir"]
    if parent:
        _check_name(parent)
        if not isinstance(modules.get(parent), dict):
            raise UsageError(f"unknown parent module '{parent}'")
        if name in (modules[parent].get("submodules") or {}):
            raise UsageError(f"'{parent}/{name}' already exists")
        rel_dir = f"{mdir}/{parent}/submodules/{name}"
    else:
        if name in modules:
            raise UsageError(f"module '{name}' already exists")
        rel_dir = f"{mdir}/{name}"
    if (ws.root / rel_dir).exists():
        raise UsageError(f"{rel_dir}/ already exists (a stub or unregistered directory?)")
    scope = "submodule" if parent else "module"
    missing = validate_answers(ws, answers, scope)
    if missing:
        raise UsageError(f"missing answers: {', '.join(missing)} "
                         f"(pass --answers file.json or the matching flags)")
    status = answers.get("status", _create_cfg(ws)["default_status"])
    values = doc_values(name, parent, answers["description"].strip(), status,
                        answers["keywords"])
    doc = ws.config["paths"]["module_doc"]
    files = {f"{rel_dir}/{doc}": string.Template(resolve_template(ws, "MODULE.md"))
             .safe_substitute(values)}
    role_files = {}
    for role in roles_to_scaffold(ws, answers, standard_roles):
        rel = f"{rel_dir}/roles/{role}.md"
        files[rel] = render_role_doc(ws, role, values)
        role_files[role] = rel
    files = {p: t if t.endswith("\n") else t + "\n" for p, t in files.items()}
    entry = {} if parent else {"name": name}
    entry["description"] = values["description"]
    if not parent:
        entry["status"] = status
    entry["keywords"] = list(dict.fromkeys(answers["keywords"]))
    entry["context_files"] = {"universal": f"{rel_dir}/{doc}", "roles": role_files}
    for key in ask_fields(ws, scope):
        entry[key] = answers[key]
    return {"module": f"{parent}/{name}" if parent else name, "files": files, "entry": entry,
            "parent": parent, "name": name, "rel_dir": rel_dir}


def _check_still_free(ws, plan: dict, modules: dict) -> None:
    """Re-check existence against the just-locked registry (and the filesystem) before any
    doc is written — the plan-time check (`plan_create`) can be stale by the time the lock is
    held, since another writer may have created the same module in between."""
    parent, name = plan["parent"], plan["name"]
    if parent:
        if not isinstance(modules.get(parent), dict):
            raise UsageError(f"unknown parent module '{parent}'")
        if name in (modules[parent].get("submodules") or {}):
            raise UsageError(f"'{parent}/{name}' already exists")
    elif name in modules:
        raise UsageError(f"module '{name}' already exists")
    if (ws.root / plan["rel_dir"]).exists():
        raise UsageError(f"{plan['rel_dir']}/ already exists (a stub or unregistered directory?)")


def apply_create(ws, plan: dict) -> None:
    """Write docs, then the registry entry; on a registry failure remove what was written."""
    written: list[Path] = []
    store = open_store(ws)
    try:
        with store.edit() as reg:
            modules = reg.raw["modules"]
            _check_still_free(ws, plan, modules)
            for rel, text in plan["files"].items():
                path = ws.root / rel
                atomic_write(path, text)
                written.append(path)
            if plan["parent"]:
                modules[plan["parent"]].setdefault("submodules", {})[plan["name"]] = plan["entry"]
            else:
                modules[plan["name"]] = plan["entry"]
    except BaseException:
        stop = ws.root / ws.config["paths"]["modules_dir"]
        dirs = set()
        for path in written:
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
            dirs.update(d for d in path.parents if stop in d.parents)
        for d in sorted(dirs, key=lambda p: -len(p.parts)):  # deepest first; only empty ones go
            with contextlib.suppress(OSError):
                d.rmdir()
        raise


def interactive() -> bool:
    return sys.stdin is not None and sys.stdin.isatty()
