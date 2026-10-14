"""Registry lint. Codes: MS001-MS004, MS006-MS015 registry/field checks · MS005, MS016, MS017,
MS041-MS043 the docs as files (segmently_modules.doc_checks) · MS020-MS023 keyword budgets and hygiene ·
MS030-MS032 doc budgets · MS040 component paths ·
MS052 a [[code_map]] rule whose `module` is not in the registry · MS053 two [[code_map]] rules
route one file to two different modules · MS054 (info) an active module that maps no code ·
MS056 `[coverage] doc_only` naming no module ·
MS060-MS062, MS064, MS065 pack checks (unknown
pack.toml keys, role templates, skills agents cannot load, skills reading unconfigured roles,
shadowed skill ids) · MS063 ejected skills behind their pack · MS066 a repository pack that
replaces a built-in pack (info) · MS067 a managed copy of a built-in skill while
`builtin_delivery = "plugin"` (info) · MS062 also: a `references/` file a skill names that does not
exist or lies outside the skill · MS068 a `SKILL.md` or `references/*.md` file over `[budgets]
skill_split_signal` · MS069 a pack's `SKILL.md` files together over `pack_split_signal` (both
warnings, plain `lint` only: a size is a decomposition signal, never a cap) ·
with --changed: MS050 code changed but no doc of its module · MS051 frozen legacy snapshot
modified or deleted (report narrowed to the changed modules)."""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import asdict, dataclass
from itertools import combinations
from pathlib import Path

from segmently_modules.changes import (changed_files, code_map_routes, diff_names, map_files, repo_files,
                            target_names, work_tree_error)
from segmently_modules.config import (BUILTIN_PACKS, PACK_META_KEYS, ROLE_SCHEMA, builtin_delivery,
                           delivery_for, discover_packs, enabled_roles)
from segmently_modules.doc_checks import doc_findings
from segmently_modules.fields import value_matches
from segmently_modules.output import EXIT_FINDINGS, EXIT_OK, UsageError, emit
from segmently_modules.query import role_paths, skip_mark
from segmently_modules.registry import as_dict, as_list, context_paths, stub_head
from segmently_modules.rules import edge_problems, status_problem
from segmently_modules.skill_sync import read_marker
from segmently_modules.skills import (AGENT_DIRS, EJECTED, SKILL_KEYS, behind_reason, declared_skills,
                           ejected_copies, ejected_symlinks, inside, pack_skills, read_ejected,
                           source_problem)
from segmently_modules.words import generic_keywords
from segmently_modules.workspace import Workspace

SEVERITY_RANK = {"info": 0, "warning": 1, "error": 2}
FAIL_ON = {"error": 2, "warning": 1, "never": 99}
_BACKTICK = re.compile(r"`([^`]+)`")
# a file a skill names (SI-P84-6): an anchor `#`, a table cell's `|` and an em or en dash end
# it; so does a `?` that follows the extension (`.md?plain=1`) or ends the name (a question mark),
# a trailing run of `*` / `_` is Markdown emphasis when what is left ends with an extension
# (`**references/x.md**`, `_see references/x.md_`). A name that still holds `*`, `?` or `[` is
# a pattern (SI-P85-10): not a file, not checked (`references/route-*`, `references/x?.md`,
# `references/[ab].md`).
_REFERENCE = re.compile(r"references/[^\s`'\")\]>|#\u2014\u2013]+")
_NOT_A_NAME = re.compile(r"[<*?\[{$…]")  # a placeholder or a glob in prose names no file
_QUERY = re.compile(r"(\.[A-Za-z0-9]+)\?.*\Z|\?+\Z")
# the top-level keys of a pack.toml besides its meta keys: every config section the engine reads
PACK_SECTIONS = ("paths", "registry", "budgets", "match", "lint", "create", "coverage", "ci",
                 "packs", "roles", "fields", "code_map", "hooks", "schema_version")


@dataclass
class Finding:
    code: str
    severity: str
    module: str
    message: str
    path: str | None = None


class RepoFiles:
    """What lint asks git, asked once per run and shared by the checks that need it (MS043,
    MS053, MS054): whether the root is in a work tree, the repository's files (git-tracked +
    new, not ignored) and the `[[code_map]]` routes of those files."""

    def __init__(self, ws):
        self.ws = ws
        self._error: list = []
        self._files: list[str] | None = None
        self._routes: list[tuple] | None = None

    def error(self) -> str | None:
        if not self._error:
            self._error.append(work_tree_error(self.ws.root))
        return self._error[0]

    def files(self) -> list[str]:
        if self._files is None:
            self._files = repo_files(self.ws.root)
        return self._files

    def rule_routes(self) -> list[tuple]:
        """(path, target, rule id) of every rule that routes each file (`code_map_routes`)."""
        if self._routes is None:
            self._routes = list(code_map_routes(self.ws, self.files()))
        return self._routes


def _role_docs(cf: dict) -> list:
    return [p for r in as_dict(cf.get("roles")) for p in role_paths(cf, r)]


def _docs(entry: dict, name: str):
    """(module label, universal doc, [role docs]) for a module and its children."""
    cf = as_dict(entry.get("context_files"))
    yield name, cf.get("universal"), _role_docs(cf)
    for child, sub in as_dict(entry.get("submodules")).items():
        if isinstance(sub, dict):
            ccf = as_dict(sub.get("context_files"))
            yield f"{name}/{child}", ccf.get("universal"), _role_docs(ccf)


def _objects(modules: dict):
    """Module entries that are objects; the others get MS013 in the entry pass."""
    return ((n, e) for n, e in modules.items() if isinstance(e, dict))


def _line_count(path: Path) -> int:
    with path.open(encoding="utf-8", errors="replace") as fh:
        return sum(1 for _ in fh)


def component_path(token: str, exists=None) -> str | None:
    """The repository path a backticked token names (MS040's rule), else None: it holds a `/`,
    no space, no `*` and no URL; an import alias (`@…`) or a placeholder (`<`, `{`, `[`) is not
    a path; `path:line` and `path#L3` name `path`. With `exists` (path -> bool), a token that
    names an existing path as a whole is that path first — a space, a `#` or a bracket in it
    included (`App/Custom cells/Row.swift`, `App/onboarding-v#1-47.json`, `app/[id]/page.tsx`)."""
    whole = token.strip()
    if exists is not None and "/" in whole and "*" not in whole and "://" not in whole \
            and not whole.startswith("@") and exists(whole):
        return whole
    if whole.startswith("@") or any(c in token for c in "<{["):
        return None
    candidate = re.split(r"[:#]", token.strip())[0]
    if "/" in candidate and " " not in candidate and "*" not in candidate and "://" not in token:
        return candidate
    return None


def lint_registry(ws, overlap: bool = True) -> list[Finding]:
    """Every registry, doc and config finding. `overlap=False` skips MS053, the one check
    that lists every repository file — `lint --changed` would drop it anyway (module `*`). A
    doc is read through `ws.disk` (the overlay of `init verify`; the path itself otherwise)."""
    out: list[Finding] = []
    cfg, root, modules = ws.config, ws.root, ws.registry.modules
    repo = RepoFiles(ws)
    statuses, relations = cfg["registry"]["statuses"], cfg["registry"]["relations"]
    budgets = cfg["budgets"]

    def add(code, severity, module, message, path=None):
        out.append(Finding(code, severity, module, message, path))

    def check_fields(label, entry, scope):
        for key, value in entry.items():
            fdef = ws.fields.get(key)
            if fdef is None:
                add("MS012", "warning", label, f"undeclared field '{key}' (declare [fields.{key}])")
            elif fdef.deprecated:
                add("MS011", "error", label, f"deprecated field '{key}': {fdef.deprecated}")
            elif not value_matches(fdef, value):
                add("MS013", "error", label,
                    f"field '{key}' does not match type {' | '.join(fdef.type)}")
        for fname, fdef in ws.fields.items():
            if scope in fdef.required and fname not in entry:
                add("MS001", "error", label, f"missing required field '{fname}'")

    def check_paths(label, cf, prefix):
        for key, p in context_paths(cf):
            if not isinstance(p, str):
                add("MS004", "error", label, f"{prefix}.{key} is not a string: {p!r}")
            elif not ws.exists(p):
                add("MS004", "error", label, f"{prefix}.{key} path missing on disk", p)

    declared_roles = set(cfg.get("roles") or {})

    def check_roles(label, cf):
        roles = cf.get("roles") if isinstance(cf, dict) else None
        if roles is not None and not isinstance(roles, dict):
            add("MS013", "error", label, "field 'context_files.roles' does not match type object")
        for r, value in as_dict(roles).items():
            if r not in declared_roles:
                add("MS015", "warning", label,
                    f"role '{r}' is not configured (declare [roles.{r}] in config or a pack)")
            if not (value is None or isinstance(value, (str, list)) or skip_mark(value)):
                add("MS013", "error", label,
                    f"context_files.roles.{r} is neither a doc path, a list of doc paths nor a "
                    f'not-needed mark (false or {{"skip": "<note>"}}): {json.dumps(value)}')

    for name, entry in modules.items():
        if not isinstance(entry, dict):
            add("MS013", "error", name, "module entry is not an object")
            continue
        check_fields(name, entry, "module")
        if entry.get("name") and entry["name"] != name:
            add("MS002", "error", name, f"'name' field mismatch: {entry['name']!r}")
        problem = status_problem(entry.get("status"), statuses)
        if problem:
            add(problem[0], "error", name, problem[1])
        check_paths(name, entry.get("context_files"), "context_files")
        check_roles(name, entry.get("context_files"))
        for child, sub in as_dict(entry.get("submodules")).items():
            if not isinstance(sub, dict):
                add("MS013", "error", f"{name}/{child}", "submodule entry is not an object")
                continue
            check_fields(f"{name}/{child}", sub, "submodule")
            check_paths(f"{name}/{child}", sub.get("context_files"),
                        f"submodules.{child}.context_files")
            check_roles(f"{name}/{child}", sub.get("context_files"))
        for i, edge in enumerate(as_list(entry.get("related_modules"))):
            if not isinstance(edge, dict):  # the field type check reports MS013
                continue
            for code, message in edge_problems(edge, modules, relations):
                add(code, "error", name, f"related_modules[{i}]: {message}")

    mdir = root / cfg["paths"]["modules_dir"]
    whitelist = set(cfg["registry"]["dir_whitelist"])
    if mdir.is_dir():
        for d in sorted(mdir.iterdir()):  # a dot-directory is never a module (MS014 skips it)
            if (d.is_dir() and not d.name.startswith(".") and d.name not in whitelist
                    and d.name not in modules and not stub_head(root, cfg, d.name)):
                add("MS014", "error", d.name, f"{cfg['paths']['modules_dir']}/{d.name}/ is "
                                              f"not registered and is not a pointer stub")

    shared: Counter = Counter()
    for name, entry in _objects(modules):
        kws = entry.get("keywords") if isinstance(entry.get("keywords"), list) else []
        if len(kws) > budgets["keywords_soft"] and "submodules" not in entry:
            add("MS020", "info", name, f"{len(kws)} keywords > soft budget {budgets['keywords_soft']}")
        for kw in {k.lower() for k in kws if isinstance(k, str)}:
            shared[kw] += 1
        subs = [(f"{name}/{c}", s) for c, s in as_dict(entry.get("submodules")).items()
                if isinstance(s, dict)]
        for label, holder in [(name, entry), *subs]:
            for kw in as_list(holder.get("keywords")):
                if isinstance(kw, str) and not kw.strip():
                    add("MS022", "warning", label, "empty keyword matches every task")
            for kw in generic_keywords(cfg, label, as_list(holder.get("keywords"))):
                add("MS023", "info", label, f"keyword '{kw}' is a generic word: it matches many "
                                            f"tasks — leave it out, or keep it if this module "
                                            f"really owns the word")
    for kw, count in sorted(shared.items()):
        if count >= budgets["keyword_shared_warn"]:
            add("MS021", "info", "*", f"keyword {kw!r} shared by {count} modules")

    heading = cfg["lint"]["component_table_heading"]
    for name, entry in _objects(modules):
        for label, universal, roles in _docs(entry, name):
            if isinstance(universal, str) and ws.disk(universal).is_file():
                n = _line_count(ws.disk(universal))
                if n > budgets["module_doc_hard_stop"]:
                    add("MS031", "error", label, f"{n} lines > hard stop "
                        f"{budgets['module_doc_hard_stop']}: split into submodules", universal)
                elif n > budgets["module_doc_split_signal"]:
                    add("MS030", "warning", label, f"{n} lines > split signal "
                        f"{budgets['module_doc_split_signal']}", universal)
                in_section = False
                for line in ws.disk(universal).read_text(encoding="utf-8",
                                                         errors="replace").splitlines():
                    if line.startswith("#"):
                        in_section = heading in line
                        continue
                    if not in_section or not line.startswith("|"):
                        continue
                    for token in _BACKTICK.findall(line):
                        candidate = component_path(token, ws.exists)
                        if candidate and not ws.exists(candidate):
                            add("MS040", "warning", label,
                                f"component path missing on disk: {candidate}", universal)
            for p in roles:
                if isinstance(p, str) and ws.disk(p).is_file():
                    n = _line_count(ws.disk(p))
                    if n > budgets["role_doc_max"]:
                        add("MS032", "warning", label,
                            f"{n} lines > role budget {budgets['role_doc_max']}", p)
    out += doc_findings(ws, heading, repo if overlap else None)  # --changed: no file list

    targets = target_names(modules)
    for rule in as_list(cfg.get("code_map")):
        if isinstance(rule, dict) and "module" in rule and rule["module"] not in targets:
            add("MS052", "warning", "*", f"[[code_map]] '{rule.get('id')}': module "
                f"'{rule['module']}' is not a registry module or child; the rule maps nothing")
    doc_only = as_list(cfg["coverage"].get("doc_only"))
    for name in doc_only:
        if isinstance(name, str) and "/" in name and name.partition("/")[0] in modules:
            add("MS056", "warning", "*", f"[coverage] doc_only names '{name}' — it takes "
                f"top-level modules (a module counts its children's code)")
        elif name not in modules:
            add("MS056", "warning", "*", f"[coverage] doc_only names '{name}', which is not a "
                f"registry module")
    out += pack_findings(ws)
    if overlap:
        out += overlap_findings(ws, repo)
        out += code_findings(ws, set(doc_only), repo)
    return out


def code_findings(ws, doc_only: set, repo: RepoFiles) -> list[Finding]:
    """MS054 (info): an `active` module that maps no code file — no file reaches it or one of
    its children through a `[[code_map]]` rule, and none of their code pointers names a path
    that exists (its docs never count); left alone when `[coverage] doc_only` names it. Only
    with a `[[code_map]]` rule (without one every module maps nothing) and inside a git work
    tree; skipped by `lint --changed`, as MS053 is."""
    if not as_list(ws.config.get("code_map")) or repo.error():
        return []
    owners = {target.partition("/")[0] for _path, target, _rule in repo.rule_routes()}
    pointers = [name for name, fdef in ws.fields.items() if fdef.kind == "code_pointer"]

    def points_at_code(holder: dict) -> bool:
        for field in pointers:
            value = holder.get(field)
            for p in value if isinstance(value, list) else [value]:
                if isinstance(p, str) and p and ws.exists(p.split(":")[0].rstrip("/")):
                    return True
        return False

    out = []
    for name, entry in _objects(ws.registry.modules):
        if entry.get("status") != "active" or name in owners or name in doc_only:
            continue
        holders = [entry] + [s for s in as_dict(entry.get("submodules")).values()
                             if isinstance(s, dict)]
        if not any(points_at_code(h) for h in holders):
            out.append(Finding("MS054", "info", name, "active module maps no code file — map its "
                               "code (segmently-modules code-map add), list it in [coverage] doc_only when "
                               "it owns no code on purpose, or retire it"))
    return out


def pack_findings(ws) -> list[Finding]:
    """The pack checks (config-level, module `*`, `path` = the offending file): MS060 unknown
    `pack.toml` keys, MS061 role templates that are missing or outside the pack, MS062 skills
    agents cannot load (a pack's, or an ejected copy's), MS063 ejected skills whose pack moved
    on (or dropped them), MS064 `reads_roles` naming a role no layer enables, MS065 a skill id
    shadowed by a higher-precedence pack, MS066 (info) a repository pack whose id is a built-in
    pack's — it replaces that pack, enabled or not."""
    out: list[Finding] = []
    for pack in discover_packs(ws.config_dir):
        data, toml, pack_dir, pid = pack["data"], ws.rel(pack["path"]), pack["path"].parent, \
            pack["id"]
        unknown = [(k, "at the top level") for k in data
                   if k not in PACK_META_KEYS and k not in PACK_SECTIONS]
        for table, schema in (("roles", ROLE_SCHEMA), ("skills", SKILL_KEYS)):
            for name, spec in as_dict(data.get(table)).items():
                unknown += [(k, f"in [{table}.{name}]") for k in as_dict(spec) if k not in schema]
        out += [Finding("MS060", "warning", "*", f"pack '{pid}': unknown key '{key}' {where}",
                        toml) for key, where in unknown]
        if not pack["builtin"] and pid in BUILTIN_PACKS:
            out.append(Finding("MS066", "info", "*", f"repository pack '{pid}' replaces the "
                               f"built-in pack '{pid}'", toml))
        for role, spec in as_dict(data.get("roles")).items():
            template = as_dict(spec).get("template")
            if not isinstance(template, str):
                continue
            path = pack_dir / template
            if not inside(path, pack_dir):
                out.append(Finding("MS061", "error", "*", f"pack '{pid}': role '{role}' template "
                                   f"'{template}' is outside the pack", toml))
            elif not path.is_file():
                out.append(Finding("MS061", "error", "*", f"pack '{pid}': role '{role}' template "
                                   f"'{template}' does not exist", ws.rel(path)))
    configured, enabled = set(ws.config.get("roles") or {}), set(enabled_roles(ws.config))
    for skill in declared_skills(ws.config_dir):
        toml = ws.rel(skill.pack_toml)
        problem = source_problem(skill.source, skill.id, skill.pack_dir)
        if problem:
            where = (toml if problem.startswith("the path") else
                     ws.rel(skill.source / "SKILL.md") if problem.startswith("SKILL.md") else
                     ws.rel(skill.source))
            out.append(Finding("MS062", "error", "*", f"skill '{skill.id}' of pack "
                               f"'{skill.pack}' is not loadable by agents: {problem}", where))
        else:
            out += reference_findings(ws, skill.source, f"skill '{skill.id}' of pack "
                                      f"'{skill.pack}': ")
        for role in skill.reads_roles:
            if role not in enabled:
                why = "is disabled" if role in configured else "no layer configures"
                out.append(Finding("MS064", "warning", "*", f"skill '{skill.id}' of pack "
                                   f"'{skill.pack}' reads role '{role}', which {why}", toml))
        if skill.shadowed_by:
            out.append(Finding("MS065", "warning", "*", f"skill '{skill.id}' of pack "
                               f"'{skill.pack}' is shadowed by pack '{skill.shadowed_by}' "
                               f"(higher precedence); rename one", toml))
    skills = pack_skills(ws.config_dir)
    for sid, link in ejected_symlinks(ws.config_dir).items():  # the target is never read
        out.append(Finding("MS063", "warning", "*", f"'{ws.rel(link)}' is a symlink, not an "
                           f"ejected copy of skill '{sid}' — packs sync and eject treat it as "
                           f"in the way; remove it (segmently-modules eject {sid} makes a real copy)",
                           ws.rel(link)))
    for sid, copy in ejected_copies(ws.config_dir).items():
        record, where = read_ejected(copy), ws.rel(copy)
        if record is None:
            out.append(Finding("MS063", "warning", "*", f"ejected skill '{sid}' has no valid "
                               f"{EJECTED} record — eject it again or restore the file", where))
            continue
        problem = source_problem(copy, sid)  # the copy `packs sync` materializes instead
        if problem:
            out.append(Finding("MS062", "error", "*", f"ejected skill '{sid}' ({where}) is not "
                               f"loadable by agents: {problem}",
                               ws.rel(copy / "SKILL.md") if problem.startswith("SKILL.md")
                               else where))
        else:
            out += reference_findings(ws, copy, f"ejected skill '{sid}' ({where}): ")
        if sid not in skills:
            out.append(Finding("MS063", "info", "*", f"ejected skill '{sid}': pack "
                               f"'{record['pack']}' no longer declares it; the ejected copy is "
                               f"its only source", where))
            continue
        skill = skills[sid]
        try:
            reason = behind_reason(skill, record)
        except OSError as e:  # an unreadable pack file: say so, never crash (P4B-AC-003)
            unreadable = ws.rel(e.filename or skill.source)
            out.append(Finding("MS063", "warning", "*", f"ejected skill '{sid}': cannot read "
                               f"{unreadable}: {e.strerror or e} — cannot tell whether pack "
                               f"'{skill.pack}' moved on since the eject", unreadable))
            continue
        if reason:
            out.append(Finding("MS063", "warning", "*", f"ejected skill '{sid}' is behind pack "
                               f"'{skill.pack}' ({reason}) — review: segmently-modules eject {sid} --diff",
                               where))
    if builtin_delivery(ws.config) != "repo":
        out += plugin_copies(ws, {sid for sid, s in skills.items() if s.builtin})
    return out + split_findings(ws)


def _text(path: Path) -> str | None:
    """A regular file's decoded text; None for a symlink, an unreadable or a non-UTF-8 file."""
    try:
        if path.is_symlink() or not path.is_file():
            return None
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _skill_files(source: Path) -> list[Path]:
    """`SKILL.md` and every `*.md` directly in `references/` (the files lint measures and
    scans; nested directories and other files are not)."""
    refs = source / "references"
    try:
        names = sorted(refs.glob("*.md")) if refs.is_dir() and not refs.is_symlink() else []
    except OSError:
        names = []
    return [source / "SKILL.md"] + names


def _reference_name(match) -> str:
    """The name a `references/...` match stands for: a query (`.md?…`) or a closing `?` cut,
    then trailing punctuation; a trailing run of `*` / `_` and sentence punctuation (any order)
    is cut when what is left ends with a file extension (emphasis). A `*`, `?` or `[` left in it
    makes it a pattern (`_NOT_A_NAME`)."""
    name = match.group(0)
    name = _QUERY.sub(lambda m: m.group(1) or "", name)
    tail = re.search(r"[*_.,;:!]*\Z", name).group(0)  # emphasis and sentence punctuation, any order
    core = name[:len(name) - len(tail)]
    if re.search(r"[*_]", tail) and re.search(r"\.[A-Za-z0-9]+\Z", core):
        return core  # emphasis around a file name: `**references/x.md.**`
    return name.rstrip(".,;:!")


def reference_findings(ws, source: Path, prefix: str) -> list[Finding]:
    """MS062 (error): a `references/...` name in `SKILL.md` or in a `references/*.md` file
    (one level of chaining) whose file does not exist or lies outside the skill directory —
    lint only; `packs sync` and `eject` do not look at names. `prefix` opens the message."""
    out: list[Finding] = []
    for file in _skill_files(source):
        text = _text(file)
        if text is None:
            continue
        label = file.relative_to(source).as_posix()
        seen: set[str] = set()
        for match in _REFERENCE.finditer(text):
            name = _reference_name(match)
            if name in seen or name.endswith("/") or _NOT_A_NAME.search(name):
                continue
            seen.add(name)
            target = source / name
            if not inside(target, source):
                why = "which is outside the skill directory"
            elif not os.path.lexists(target):
                why = "which does not exist"
            else:
                continue
            out.append(Finding("MS062", "error", "*", f"{prefix}{label} names {name}, {why}",
                               ws.rel(file)))
    return out


def split_findings(ws) -> list[Finding]:
    """MS068 / MS069 (warnings, D5): size as a decomposition signal. MS068: `SKILL.md` or a
    `references/*.md` file of a pack's skill (or of an ejected copy) over `[budgets]
    skill_split_signal`; MS069: a pack's `SKILL.md` files together over `pack_split_signal`
    (references and ejected copies are not counted)."""
    budgets = ws.config["budgets"]
    skill_max, pack_max = budgets["skill_split_signal"], budgets["pack_split_signal"]
    out: list[Finding] = []

    def measure_skill(sid: str, source: Path) -> int:
        """Warn per file over the signal; return the `SKILL.md` length (0 when unmeasured)."""
        skill_md = 0
        for file in _skill_files(source):
            text = _text(file)
            if text is None:
                continue
            is_skill = file.parent == source
            if is_skill:
                skill_md = len(text)
            if len(text) > skill_max:
                label = sid if is_skill else f"{sid}/{file.stem}"
                out.append(Finding("MS068", "warning", "*", f"{label}: {len(text)} characters "
                                   f"> skill split signal {skill_max} — route its scenarios "
                                   f"or split the skill", ws.rel(file)))
        return skill_md

    for pack in discover_packs(ws.config_dir):
        total = 0
        for sid, spec in as_dict(pack["data"].get("skills")).items():
            source = pack["path"].parent / spec["path"]
            if inside(source, pack["path"].parent) and source.is_dir():
                total += measure_skill(sid, source)
        if total > pack_max:
            out.append(Finding("MS069", "warning", "*", f"pack '{pack['id']}': {total} "
                               f"characters of skills > pack split signal {pack_max} — route, "
                               f"split a skill out, or split the pack", ws.rel(pack["path"])))
    for sid, copy in ejected_copies(ws.config_dir).items():
        measure_skill(sid, copy)
    return out


def plugin_copies(ws, builtin: set[str]) -> list[Finding]:
    """MS067 (info): under `builtin_delivery = "plugin"`, each copy `packs sync` made of a
    built-in skill (a valid marker of that skill) in an agent directory — each real directory
    once; an unreadable directory is skipped. The message names the sync that removes it: a
    bare `packs sync`, or `--agent <the directory's agent>` when `[packs] agents` leaves that
    directory out (a bare sync never touches it then)."""
    out, seen = [], set()
    configured = [a for a in (ws.config.get("packs") or {}).get("agents") or []
                  if a in AGENT_DIRS]
    covered = {os.path.realpath(ws.root / AGENT_DIRS[a]) for a in configured}
    for rel in dict.fromkeys(AGENT_DIRS.values()):
        base = ws.root / rel
        real = os.path.realpath(base)
        if real in seen:
            continue
        seen.add(real)
        agent = next(a for a, d in AGENT_DIRS.items() if d == rel)
        if delivery_for(ws.config, agent) != "plugin":  # a table: this directory gets copies
            continue
        command = ("segmently-modules packs sync" if not configured or real in covered
                   else f"segmently-modules packs sync --agent {agent}")
        try:
            dests = sorted(base.iterdir()) if base.is_dir() else []
        except OSError:
            continue
        for dest in dests:
            try:
                marker = (read_marker(dest) if dest.name in builtin and dest.is_dir()
                          and not dest.is_symlink() else None)
            except OSError:  # an entry that cannot be read: not a copy lint can vouch for
                continue
            if marker is not None and marker["skill"] == dest.name:
                out.append(Finding("MS067", "info", "*", f"'{ws.rel(dest)}' is a copy of the "
                                   f"built-in skill '{dest.name}' while builtin_delivery = "
                                   f'"plugin" (the plugin provides it) — {command} removes it '
                                   f"when it is unedited (an edited copy, or the copy of an "
                                   f"ejected skill, stays: a packs sync conflict)",
                                   ws.rel(dest)))
    return out


def _related(a: str, b: str) -> bool:
    """The same target, or one is the other's parent (`catalog` and `catalog/search`)."""
    return a == b or a == b.partition("/")[0] or b == a.partition("/")[0]


def overlap_findings(ws, repo: RepoFiles | None = None) -> list[Finding]:
    """MS053 (config-level, module `*`): per pair of `[[code_map]]` rules, the repository files
    (git-tracked + new, no coverage filters) they route — after `exclusive` precedence — to two
    targets where neither is the other's parent and neither rule is `shared = true` (a file it
    routes belongs to its module and to the others on purpose, e.g. a feature module and the
    service that ships it). Only the rules route files here (docs and `code_pointer` sources are
    never evaluated). Skipped silently with fewer than two rules (no pair can overlap) and
    outside a git work tree."""
    repo = repo or RepoFiles(ws)
    rules = [r for r in as_list(ws.config.get("code_map")) if isinstance(r, dict) and "id" in r]
    if len(rules) < 2 or repo.error():
        return []
    shared = {r["id"] for r in rules if r.get("shared") is True}  # overlaps on purpose
    per_file: dict[str, dict] = {}  # path -> {rule id: target}; repo_files order = sorted
    for path, target, rule_id in repo.rule_routes():
        per_file.setdefault(path, {})[rule_id] = target
    pairs: dict[tuple, list] = {}  # (rule a, rule b) -> [files, first path, target a, target b]
    for path, by_rule in per_file.items():
        for a, b in combinations(sorted(by_rule), 2):
            if not _related(by_rule[a], by_rule[b]) and not {a, b} & shared:
                pairs.setdefault((a, b), [0, path, by_rule[a], by_rule[b]])[0] += 1
    severity = ws.config["lint"]["overlap_severity"]
    return [Finding("MS053", severity, "*",
                    f"[[code_map]] '{a}' (-> {ta}) and '{b}' (-> {tb}) both map {n} file(s), "
                    f"e.g. {path} — mark the more specific rule exclusive = true or narrow "
                    f"its globs")
            for (a, b), (n, path, ta, tb) in sorted(pairs.items())]


def drift_findings(ws, files: list[str], frozen_touched: list[str]) -> tuple[list, set]:
    """MS050/MS051 for a change set; returns (findings, changed top-level modules)."""
    mapping = map_files(ws, files)["modules"]
    mdir = ws.config["paths"]["modules_dir"].rstrip("/") + "/"

    def is_doc(f):  # a frozen snapshot never counts as a doc update
        return f.startswith(mdir) and not f.endswith(".legacy.md")

    docs_changed = {t for t, m in mapping.items() if any(is_doc(f) for f in m["files"])}
    out = []
    for target, m in mapping.items():
        code = [f for f in m["files"] if not f.startswith(mdir)]
        # a doc of the target, of its parent, or of one of its children counts (an update of a
        # child's doc covers its parent; a parent's doc covers a child, never a sibling's)
        covered = target in docs_changed or target.partition("/")[0] in docs_changed or (
            "/" not in target and any(t.startswith(f"{target}/") for t in docs_changed))
        if code and not covered:
            out.append(Finding("MS050", ws.config["lint"]["drift_severity"], target,
                               f"code changed ({len(code)} file(s)) but none of its docs"))
    for f in frozen_touched:
        module = f[len(mdir):].split("/")[0] if f.startswith(mdir) else "*"
        out.append(Finding("MS051", "error", module,
                           "frozen legacy snapshot modified or deleted", f))
    return out, {t.partition("/")[0] for t in mapping}


def drift_report(ws, base: str, findings: list[Finding],
                 env: dict | None = None) -> tuple[list[Finding], dict]:
    """`lint --changed`: `findings` narrowed to the top-level modules the change since `base`
    touches, plus MS050/MS051; and the change as {base, files, modules}. `env`: set on top of
    the git environment of every git call (`next` points `GIT_INDEX_FILE` at a copy)."""
    files = changed_files(ws.root, base=base, env=env)
    frozen = [f for f in diff_names(ws.root, base, "--diff-filter=MD", env=env)
              if f.endswith(".legacy.md")]  # a renamed snapshot shows as D (--no-renames)
    drift, touched = drift_findings(ws, files, frozen)
    narrowed = [f for f in findings if f.module.partition("/")[0] in touched] + drift
    return narrowed, {"base": base, "files": files, "modules": sorted(touched)}


def failing(findings: list[Finding], fail_on: str) -> bool:
    return any(SEVERITY_RANK[f.severity] >= FAIL_ON[fail_on] for f in findings)


def severity_counts(findings: list[Finding]) -> dict:
    counts = Counter(f.severity for f in findings)
    return {s: counts.get(s, 0) for s in ("error", "warning", "info")}


def register(sub, common) -> None:
    p = sub.add_parser("lint", parents=[common],
                       help="check registry, fields, doc budgets and component paths")
    p.add_argument("--fail-on", choices=sorted(FAIL_ON))
    p.add_argument("--changed", action="store_true",
                   help="drift check for a change set; report only the changed modules")
    p.add_argument("--base", default="HEAD",
                   help="--changed: compare the working tree (+ untracked) with this ref")
    p.set_defaults(func=run)


def run(args) -> int:
    ws = Workspace.from_args(args)
    fail_on = args.fail_on or ws.config["lint"]["fail_on"]
    if fail_on not in FAIL_ON:
        raise UsageError(f"[lint].fail_on must be one of {sorted(FAIL_ON)}, got {fail_on!r}")
    findings = lint_registry(ws, overlap=not args.changed)  # --changed never reports MS053
    changed = None
    if args.changed:
        findings, changed = drift_report(ws, args.base, findings)
    failed = failing(findings, fail_on)
    data = {"findings": [asdict(f) for f in findings], "summary": severity_counts(findings),
            "failed": failed}
    if changed is not None:
        data["changed"] = changed
    emit("lint", data, args.json, _render)
    return EXIT_FINDINGS if failed else EXIT_OK


def _render(d) -> None:
    for f in d["findings"]:
        where = f"  ({f['path']})" if f["path"] else ""
        print(f"{f['severity'].upper():<7} {f['code']} {f['module']}: {f['message']}{where}")
    if d["findings"]:
        print()
    s = d["summary"]
    print(f"{s['error']} error(s), {s['warning']} warning(s), {s['info']} info")
