"""Changed files -> modules. A file belongs to a module (or `module/child`) through:
  docs          — it lives under `<modules_dir>/<module>/` (children: `…/submodules/<child>/`)
  code_pointer  — a `kind = "code_pointer"` field names the file or a directory above it
  code_map      — a `[[code_map]]` rule: `globs` for one `module` (a top-level module or a
                  `parent/child`), or a `pattern` whose `{module}` segment names a top-level
                  module (e.g. "src/{module}/**"; `{module}` captures exactly ONE path segment).
                  A file matched AND routed (to a registry target) by an `exclusive = true`
                  rule is mapped ONLY by the exclusive rules that route it; an exclusive rule
                  whose `{module}` capture names no module takes nothing. Docs and
                  code_pointer mapping are unaffected.
Glob syntax: `**` any path, `*` one segment, `?` one character."""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from segmently_modules.output import UsageError
from segmently_modules.registry import as_dict, as_list

# git location variables a parent git hook may export; they would point git at another repo
_GIT_LOCATION_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                      "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_PREFIX")
CODE_MAP_SCHEMA = {"id": "str", "module": "str", "pattern": "str", "globs": "list[str]",
                   "exclusive": "bool", "shared": "bool"}
# dependency and build directories: never code of the repository's own modules (a walk outside
# git skips them; `adopt` never takes them for a code-map prefix)
DEPENDENCY_DIRS = ("node_modules", ".venv", "venv", "__pycache__", "dist", "build", "target",
                   "vendor")


def git_env() -> dict:
    return {k: v for k, v in os.environ.items() if k not in _GIT_LOCATION_VARS}


def git(root: Path, *args: str, label: str | None = None, env: dict | None = None) -> str:
    """Run git in `root`; `label` replaces the argv in the error message; `env`: variables set
    on top of `git_env()` (e.g. `GIT_INDEX_FILE`; None = none)."""
    proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                          encoding="utf-8", errors="replace", env={**git_env(), **(env or {})})
    if proc.returncode != 0:
        raise UsageError(f"git {label or ' '.join(args)} failed: {proc.stderr.strip()[:300]}")
    return proc.stdout


def work_tree_error(root: Path) -> str | None:
    """None when `root` is inside a git work tree; otherwise why not: "not inside a work tree"
    only when git says so, else git's own error (or that git cannot run)."""
    try:
        proc = subprocess.run(["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
                              capture_output=True, encoding="utf-8", errors="replace",
                              env={**git_env(), "LC_ALL": "C"})
    except OSError as e:
        return f"git is not installed or cannot run: {e}"
    if proc.returncode == 0:
        return None if proc.stdout.strip() == "true" else f"{root} is not inside a work tree"
    err = proc.stderr.strip()
    if err.startswith("fatal: not a git repository (or any of the parent directories)"):
        return f"{root} is not inside a work tree"
    return f"git rev-parse --is-inside-work-tree failed: {err[:300]}"


def require_work_tree(root: Path, what: str) -> None:
    """Exit 2 (`<what> needs a git repository (…)`) unless `root` is inside a git work tree."""
    error = work_tree_error(root)
    if error:
        raise UsageError(f"{what} needs a git repository ({error})")


def _rev(value: str) -> str:
    """A user-given ref or `A..B` range; one that starts with '-' would be read as an option
    (e.g. `--output=FILE` makes git write a file), so it is refused."""
    if value.startswith("-"):
        raise UsageError(f"git ref or range {value!r} may not start with '-'")
    return value


def commit_ref(root: Path, ref: str, origin: str | None = None) -> str:
    """`ref` when it names a commit in the repository at `root`; else exit 2 (a ref starting
    with '-' is refused before git sees it). `origin` names where an unresolved `ref` came from
    for the error: "flag" (`--base` on the command line) or "config" (`[ci] base`, including
    its default) — the message then leads with `--base '<ref>'` or `[ci] base '<ref>'`
    (omitted, it reads `--base`). `ref` itself unresolved as literal `HEAD` means there is no
    commit yet — fetching would not help, so that gets its own message regardless of origin."""
    ref = _rev(ref)
    proc = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "--quiet",
                           f"{ref}^{{commit}}"], capture_output=True, encoding="utf-8",
                          errors="replace", env=git_env())
    if proc.returncode != 0:
        if ref == "HEAD":
            raise UsageError("the repository has no commit yet — commit first (drift compares "
                             "against a commit)")
        where = "[ci] base" if origin == "config" else "--base"
        raise UsageError(f"{where} {ref!r} is not a commit in this repository (in CI, fetch the "
                         f"target branch first, e.g. git fetch origin main)")
    return ref


def commit_sha(root: Path, ref: str) -> str:
    """The full hash of the commit `ref` names (a ref `commit_ref` accepted)."""
    return git(root, "rev-parse", "--verify", "--quiet", f"{_rev(ref)}^{{commit}}").strip()


def branch_point(root: Path, base: str) -> str | None:
    """None when the commit `base` is HEAD or one of its ancestors (drift since `base` is the
    change of this branch), or when git cannot tell; else the merge base of `base` and HEAD
    (`base` has commits HEAD does not, e.g. a target branch that moved on) — "" when none is
    found (no shared history, or a shallow clone that lacks it: `is_shallow`)."""
    proc = subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", _rev(base),
                           "HEAD"], capture_output=True, encoding="utf-8", errors="replace",
                          env=git_env())
    if proc.returncode != 1:  # 0: an ancestor; anything else: an error, nothing to say
        return None
    proc = subprocess.run(["git", "-C", str(root), "merge-base", _rev(base), "HEAD"],
                          capture_output=True, encoding="utf-8", errors="replace", env=git_env())
    return proc.stdout.strip() if proc.returncode == 0 else ""


def is_shallow(root: Path) -> bool:
    """The repository at `root` is a shallow clone (its history is cut)."""
    proc = subprocess.run(["git", "-C", str(root), "rev-parse", "--is-shallow-repository"],
                          capture_output=True, encoding="utf-8", errors="replace", env=git_env())
    return proc.stdout.strip() == "true"


def _paths(output: str) -> list[str]:
    return [p for p in output.split("\0") if p]


def diff_names(root: Path, rev: str, *options: str, env: dict | None = None) -> list[str]:
    """Paths `git diff` reports against `rev` (a ref: vs the working tree; or `A..B`):
    relative to `root` and limited to it (--relative: `root` may be a subdirectory of the git
    repository), a rename listed as delete + add (--no-renames), raw names (-z: no C-quoting
    of non-ASCII names), and `rev` after --end-of-options. `env`: as for `git`."""
    rev = _rev(rev)
    return _paths(git(root, "diff", "--name-only", "--relative", "--no-renames", "-z", *options,
                      "--end-of-options", rev,
                      label=" ".join(("diff", "--name-only", *options, rev)), env=env))


def changed_files(root: Path, diff_range: str | None = None, files=None,
                  base: str | None = None, env: dict | None = None) -> list[str]:
    """Root-relative changed paths from explicit `files`, a `diff_range` ("A..B"), or `base`
    (base vs the working tree, plus untracked files); git listings keep only files under
    `root`. Sorted, de-duplicated. A listed path may be missing on disk (a deleted file is a
    real change; see `missing_files`) but never a directory: a directory matches no file rule,
    so mapping it would silently report it unmapped. `env`: as for `git`, for every git call."""
    if files:
        out = set()
        for f in files:
            p = Path(f)
            if p.is_absolute():
                try:
                    p = p.resolve().relative_to(Path(root).resolve())
                except ValueError:
                    raise UsageError(f"{f} is outside the repository {root}") from None
            rel = Path(os.path.normpath(p)).as_posix()
            if rel == ".." or rel.startswith("../"):
                raise UsageError(f"{f} is outside the repository {root}")
            path = Path(root) / rel
            if (path.is_dir() and not path.is_symlink() and not (path / ".git").exists()):
                raise UsageError(f"{rel}: is a directory — list its files (e.g. git ls-files "
                                 f"{rel})")
            out.add(rel)
        return sorted(out)
    if diff_range:
        return sorted(set(diff_names(root, diff_range, env=env)))
    if base:
        tracked = diff_names(root, base, env=env)
        untracked = _paths(git(root, "ls-files", "-z", "--others", "--exclude-standard",
                               env=env))
        return sorted(set(tracked + untracked))
    raise UsageError("give changed files: --from-diff A..B, --files …, or --base REF")


def missing_files(root: Path, files: list[str]) -> list[str]:
    """The listed root-relative paths that do not exist on disk: a typo, or a deleted file
    (which still maps to its module — a deletion is a real change)."""
    return [f for f in files if not os.path.lexists(Path(root) / f)]


def repo_files(root: Path) -> list[str]:
    """Every git-tracked file plus every new file git does not ignore: relative to `root` and
    limited to it (`git ls-files` lists from `-C <root>` downwards), raw names (-z). Sorted."""
    tracked = _paths(git(root, "ls-files", "-z"))
    new = _paths(git(root, "ls-files", "-z", "--others", "--exclude-standard"))
    return sorted(set(tracked + new))


def glob_to_regex(pattern: str) -> re.Pattern:
    """`{module}` may appear more than once (e.g. `tests/{module}/test_{module}.py`, a
    per-feature test layer): the first occurrence captures the module, every later one is a
    backreference to it, so the file must name the same module in both places."""
    out, i, seen_module = [], 0, False
    while i < len(pattern):
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern.startswith("{module}", i):
            if seen_module:
                out.append("(?P=module)")
            else:
                out.append("(?P<module>[^/]+)")
                seen_module = True
            i += len("{module}")
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def validate_code_map(layer: dict, source, check_table) -> None:
    rules = layer.get("code_map")
    if rules is None:
        return
    if not isinstance(rules, list) or not all(isinstance(r, dict) for r in rules):
        raise UsageError(f"{source}: code_map must be an array of tables ([[code_map]])")
    for rule in rules:
        if not isinstance(rule.get("id"), str) or not rule["id"]:
            raise UsageError(f"{source}: every [[code_map]] entry needs an id")
        check_table(rule, CODE_MAP_SCHEMA, f"code_map.{rule['id']}", source)
        if "pattern" not in rule and "globs" not in rule:
            raise UsageError(f"{source}: code_map.{rule['id']}: needs a pattern or globs")
        if "module" in rule and not rule["module"]:
            raise UsageError(f"{source}: code_map.{rule['id']}: module must be a non-empty module "
                             f"or parent/child name")
        if "globs" in rule and "module" not in rule:
            raise UsageError(f"{source}: code_map.{rule['id']}: globs need a module")
        if rule.get("exclusive") is True and rule.get("shared") is True:
            raise UsageError(f"{source}: code_map.{rule['id']}: exclusive takes its files from "
                             f"the other rules and shared shares them — set one of the two")
        if "pattern" in rule and "{module}" not in rule["pattern"]:
            fixed = json.dumps(rule["pattern"], ensure_ascii=False)
            module = json.dumps(rule.get("module", "NAME"), ensure_ascii=False)
            raise UsageError(f"{source}: code_map.{rule['id']}: pattern {fixed} has no {{module}} "
                             f"segment — for a fixed module use globs = [{fixed}] and "
                             f"module = {module}")
        for glob in [rule["pattern"]] if "pattern" in rule else (rule.get("globs") or []):
            if not isinstance(glob, str):
                continue
            try:
                glob_to_regex(glob)
            except re.error as e:
                raise UsageError(f"{source}: code_map.{rule['id']}: glob "
                                 f"{json.dumps(glob, ensure_ascii=False)} is not a valid "
                                 f"pattern: {e}") from None


def _pointer_paths(value) -> list[str]:
    paths = value if isinstance(value, list) else [value]
    return [p.split(":")[0].rstrip("/") for p in paths if isinstance(p, str) and p]


def _targets(modules: dict):
    """(target, entry) for every module and child entry that is an object."""
    for name, entry in modules.items():
        if isinstance(entry, dict):
            yield name, entry
            for child, sub in as_dict(entry.get("submodules")).items():
                if isinstance(sub, dict):
                    yield f"{name}/{child}", sub


def target_names(modules: dict) -> set[str]:
    """Every module and `parent/child` name a `[[code_map]]` rule may route files to."""
    return {target for target, _ in _targets(modules)}


def rule_routes_to(rule: dict, target: str) -> bool:
    """A rule routes files to `target` when its `module` is the target, or when it is a
    `pattern` rule without a `module` and the target is top-level (`{module}` = one segment)."""
    return rule.get("module") == target or ("module" not in rule and "/" not in target)


def code_globs(config: dict, target: str) -> list[str]:
    """The `[[code_map]]` globs that route files to `target` — where its code lives, for agents
    (`show` / `context`). A `pattern` rule without a `module` contributes its pattern with
    `{module}` = the target (top-level targets only: `{module}` is one path segment); a rule
    whose `module` is the target contributes its globs or pattern (`{module}` read as `*`).
    These are routing rules, not a file list: an `exclusive` rule elsewhere may take files."""
    out = []
    for rule in as_list(config.get("code_map")):
        if not isinstance(rule, dict) or "id" not in rule or not rule_routes_to(rule, target):
            continue
        globs = [rule["pattern"]] if "pattern" in rule else as_list(rule.get("globs"))
        fill = "*" if rule.get("module") == target else target
        out += [g.replace("{module}", fill) for g in globs if isinstance(g, str)]
    return list(dict.fromkeys(out))


def _code_map_rules(ws) -> list[tuple]:
    """(id, module, compiled globs, exclusive) of every effective `[[code_map]]` rule."""
    return [(r["id"], r.get("module"), [glob_to_regex(g) for g in
                                         ([r["pattern"]] if "pattern" in r else r["globs"])],
             r.get("exclusive") is True)
            for r in as_list(ws.config.get("code_map")) if isinstance(r, dict) and "id" in r]


def _rule_targets(path: str, rules: list[tuple], targets: set[str]) -> list[tuple[str, str]]:
    """(target, rule id) of every `[[code_map]]` rule that routes `path` to a registry target,
    after `exclusive` precedence."""
    routed = []  # (target, rule id, exclusive) of every code_map rule that routes the file
    for rule_id, module, regexes, exclusive in rules:
        for rx in regexes:
            m = rx.match(path)
            if not m:
                continue
            name = module or m.group("module")
            if name in targets:
                routed.append((name, rule_id, exclusive))
    if any(exclusive for _, _, exclusive in routed):
        routed = [r for r in routed if r[2]]  # exclusive rules win the file
    return [(name, rule_id) for name, rule_id, _ in routed]


def code_map_routes(ws, files: list[str]):
    """Yield (path, target, rule id) for every `[[code_map]]` rule that routes each file, file
    by file in the given order, after `exclusive` precedence — the rules alone: a file's docs
    location and `code_pointer` fields are never evaluated (MS053 compares rules only)."""
    targets = target_names(ws.registry.modules)
    rules = _code_map_rules(ws)
    for path in files:
        for name, rule_id in _rule_targets(path, rules, targets):
            yield path, name, rule_id


def routes(ws, files: list[str]):
    """Yield (path, target, via) for every way each file maps to a module, file by file in
    the given order: docs, then code_pointer fields, then `[[code_map]]` rules after
    `exclusive` precedence. A file that yields nothing is unmapped."""
    modules = ws.registry.modules
    targets = target_names(modules)
    mdir = ws.config["paths"]["modules_dir"].rstrip("/") + "/"
    pointers = [(t, f, p) for t, e in _targets(modules)
                for f, d in ws.fields.items() if d.kind == "code_pointer" and f in e
                for p in _pointer_paths(e[f])]
    rules = _code_map_rules(ws)
    for path in files:
        if path.startswith(mdir):
            parts = path[len(mdir):].split("/")
            if parts[0] in modules:
                child = parts[2] if len(parts) > 3 and parts[1] == "submodules" else None
                target = f"{parts[0]}/{child}" if child and child in as_dict(
                    as_dict(modules[parts[0]]).get("submodules")) else parts[0]
                yield path, target, "docs"
        for target, field, pointer in pointers:
            if path == pointer or path.startswith(pointer + "/"):
                yield path, target, f"code_pointer:{field}"
        for name, rule_id in _rule_targets(path, rules, targets):
            yield path, name, f"code_map:{rule_id}"


def map_files(ws, files: list[str]) -> dict:
    """{"modules": {target: {"files": […], "via": […]}}, "unmapped": […]}"""
    hits: dict[str, dict] = {}
    seen_files: dict[str, set] = {}  # per-target seen-set, kept OUT of the slot dict that is
                                     # serialized to JSON: a list scan there would be quadratic
    mapped: set = set()
    for path, target, via in routes(ws, files):
        slot = hits.setdefault(target, {"files": [], "via": []})
        target_seen = seen_files.setdefault(target, set())
        if path not in target_seen:
            target_seen.add(path)
            slot["files"].append(path)
        if via not in slot["via"]:
            slot["via"].append(via)
        mapped.add(path)
    return {"modules": dict(sorted(hits.items())),
            "unmapped": [f for f in files if f not in mapped]}
