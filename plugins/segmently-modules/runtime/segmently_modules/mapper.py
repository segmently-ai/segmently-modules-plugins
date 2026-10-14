"""`init` phase 2, map (script only, deterministic): the candidate modules of an existing
codebase, written to `proposal.json` for gate 3.

A candidate is a unit — a directory:
  1. every package root of the manifests (a manifest at the repository root is never a unit);
     a package root inside another unit is not a candidate of its own (the outer one's
     rationale names it); a manifest that does not parse still makes its directory a unit;
  2. the code files outside every package root: the source directories one level under
     `src/`, `lib/`, `app/`, `packages/`, `services/`, `apps/` — or, when none holds one, the
     top-level directories that hold code (a code file: an extension of the preflight language
     table). A directory of this rule is a candidate only when it neither contains nor lies
     inside a package root (the code files of a directory that contains one stay `unassigned`);
     with manifests present, its rationale says it is "outside every package root".
The package roots come first (by directory), then the units of rule 2. Seed `keywords` never
hold a token of 3 characters or fewer nor the npm scope of the manifest name (`@org/…`: `org`).
Names: the manifest name without a scope (`@org/`) or path, else the directory name, normalized
to the `create` rule (lowercase words joined by '-', max 48). Every unit's name is unique: units
that share one fall back, each, to its own directory name, then parent + directory, then the
whole path (a fallback that collides again falls back further); units that still share one
after the 48-character cut keep their first name, numbered from the second on (`-2`, `-3`, …).

Signals, all deterministic:
  imports     Python `import` / `from … import` (relative ones too) and JS/TS `import … from`,
              `export … from`, `require(…)`, `import(…)` with a string literal. Relative
              specifiers resolve to files (extensions, `index` files, `__init__.py`); a
              workspace package name (`@org/pkg`, `@org/pkg/sub`) to its unit; a Python
              absolute import by its first segment to the one unit holding that package
              (`<unit>/P/__init__.py`, `<unit>/P.py`, `<unit>/src/P/`). Anything else is
              external and ignored; a file that is not UTF-8 is skipped.
  CODEOWNERS  the first of `.github/CODEOWNERS`, `CODEOWNERS`, `docs/CODEOWNERS`; the last
              matching rule wins; a rule with `!`, `[`, `]` or `\\` is skipped.
  co-change   `git log --name-only` over the last `[init] co_change_commits` commits (0: off);
              per unit pair the Jaccard index of the commit sets that touch them.
Per candidate `confidence` = round(0.4 × manifest + 0.2 × cohesion + 0.2 × owners + 0.2 ×
isolation, 2) from `signals`: manifest 1 for a package root; cohesion = intra-unit share of the
resolved imports whose source file is in the unit (0 without imports); owners 1 when every
owned file of the unit has one identical owner set; isolation = 1 − the highest Jaccard with
another unit (0 without history). `hints` (never a change to the candidates): `merge` for two
units with Jaccard >= 0.6 that import each other, `split` for a unit whose files have disjoint
owner sets — or else, for a unit with more lines of code than `[init] split_hint_lines`
(10000; 0: off), with `children`: {dir, lines} per code-holding subdirectory, a child that alone
is over the limit replaced by its own subdirectories, at most 3 levels below the unit (0.3.0:
a 65k-line Swift app was one candidate, with no import signal to split it). `unassigned`: the
code files no candidate claims."""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import PurePosixPath

from segmently_modules import preflight
from segmently_modules.changes import DEPENDENCY_DIRS, git_env, glob_to_regex, work_tree_error
from segmently_modules.create import GENERIC_KEYWORDS
from segmently_modules.preflight import language

SCHEMA = "segmently-modules.init-proposal/1"
CONTAINERS = ("src", "lib", "app", "packages", "services", "apps")
NAME_MAX = 48
WEIGHTS = {"manifest": 0.4, "cohesion": 0.2, "owners": 0.2, "isolation": 0.2}
SCANNED = (".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts")
SPLIT_HINT_LINES = 10000  # [init] split_hint_lines: a candidate with more lines of code gets a
SPLIT_DEPTH = 3           # size `split` hint, its children at most this many levels below it
JS_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")
CODEOWNERS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")
_PY_IMPORT = re.compile(r"^[ \t]*import[ \t]+([\w.]+(?:[ \t]+as[ \t]+\w+)?"
                        r"(?:[ \t]*,[ \t]*[\w.]+(?:[ \t]+as[ \t]+\w+)?)*)", re.M)
_PY_FROM = re.compile(r"^[ \t]*from[ \t]+(\.*)([\w.]*)[ \t]+import[ \t]+\(?[ \t]*([\w, \t]*)",
                      re.M)
_JS = [re.compile(r"\bimport\s+(?:[^'\";]*?\s+from\s+)?['\"]([^'\"\n]+)['\"]"),
       re.compile(r"\bexport\s+[^'\";]*?\s+from\s+['\"]([^'\"\n]+)['\"]"),
       re.compile(r"\brequire\(\s*['\"]([^'\"\n]+)['\"]\s*\)"),
       re.compile(r"\bimport\(\s*['\"]([^'\"\n]+)['\"]\s*\)")]
_WORD = re.compile(r"[a-z0-9]+")


def scanned(path: str) -> bool:
    """A file the map reads: code for the import scan (Python, JavaScript, TypeScript) and the
    CODEOWNERS files — the preflight scan keeps their text, so no file is read twice."""
    return PurePosixPath(path).suffix.lower() in SCANNED or path in CODEOWNERS


def module_name(raw: str) -> str:
    """`raw` (a manifest name or a directory) as a module name of the `create` rule."""
    last = raw.rstrip("/").split("/")[-1]
    name = re.sub(r"[^a-z0-9]+", "-", last.lower()).strip("-")
    name = re.sub(r"^[^a-z]+", "", name)[:NAME_MAX].rstrip("-")
    return name or "module"


def _dir(path: str) -> str:
    parent = PurePosixPath(path).parent.as_posix()
    return "" if parent == "." else parent


def _join(base: str, rel: str) -> str:
    return f"{base}/{rel}" if base else rel


def _hidden(path: str) -> bool:
    return any(part.startswith(".") or part in DEPENDENCY_DIRS for part in path.split("/")[:-1])


def _code_dirs(files: list[str], skip: set[str]) -> list[tuple[str, str]]:
    """Rule 2: (unit directory, rationale) of the source directories."""
    code = [f for f in files if language(f) and not _hidden(f)]
    units = []
    for container in CONTAINERS:
        subs = sorted({f.split("/")[1] for f in code
                       if f.startswith(container + "/") and f.count("/") >= 2})
        units += [(f"{container}/{s}", f"a source directory under {container}/") for s in subs]
    if not units:
        tops = sorted({f.split("/")[0] for f in code if "/" in f} - skip)
        units = [(t, "a top-level directory that holds code") for t in tops]
    return units


def units(files: list[str], manifests: list[dict], skip: set[str]) -> list[dict]:
    """The candidate units: {dir, manifest (or None), rationale} — the package roots by
    directory (rule 1), then rule 2 over the code files outside every package root."""
    by_dir: dict[str, dict] = {}
    for m in manifests:  # manifests come sorted by path: the first per directory wins
        d = _dir(m["path"])
        if d and not d.split("/")[0].startswith(".") and d.split("/")[0] not in skip:
            by_dir.setdefault(d, m)
    out = []
    for d in sorted(by_dir):
        if any(d.startswith(o + "/") for o in by_dir if o != d):
            continue  # a nested package root belongs to the unit around it
        m = by_dir[d]
        rationale = [f"a package root: {m['path']}"
                     + (f" names it '{m['name']}'" if m["name"] else " (its name did not parse)")]
        nested = [n for n in sorted(by_dir) if n.startswith(d + "/")]
        if nested:
            rationale.append(f"it holds the nested package root(s) {', '.join(nested)} — part "
                             f"of this unit, not candidates of their own")
        out.append({"dir": d, "manifest": m, "rationale": rationale})
    roots = sorted(by_dir)
    outside = [f for f in files if not any(f.startswith(r + "/") for r in roots)]
    for d, why in _code_dirs(outside, skip):
        if any(r == d or r.startswith(d + "/") or d.startswith(r + "/") for r in roots):
            continue  # it contains (or lies inside) a package root: its code stays unassigned
        out.append({"dir": d, "manifest": None,
                    "rationale": [f"{why}, outside every package root" if roots else why]})
    return out


def _name_steps(unit: dict) -> list[str]:
    """The names a unit may take, in order: the manifest name (else the directory name), the
    directory name, parent + directory, the whole path — each normalized, repeats dropped."""
    parts = unit["dir"].split("/")
    manifest = unit["manifest"]
    first = manifest["name"] if manifest and manifest["name"] else parts[-1]
    return list(dict.fromkeys(module_name(raw) for raw in (first, parts[-1],
                                                           "-".join(parts[-2:]),
                                                           "-".join(parts))))


def names(found: list[dict]) -> list[str]:
    """One unique module name per unit (see the module docstring): while names collide, every
    unit sharing one moves to its next `_name_steps` name; units still sharing one then keep
    their first name, the second and later ones numbered — never taking another unit's name."""
    steps = [_name_steps(u) for u in found]
    at = [0] * len(found)
    while True:
        out = [s[i] for s, i in zip(steps, at)]
        clash = [i for i, n in enumerate(out) if out.count(n) > 1 and at[i] + 1 < len(steps[i])]
        if not clash:
            break
        for i in clash:
            at[i] += 1
    taken = {n for n in out if out.count(n) == 1}
    result = []
    for i, name in enumerate(out):
        if out.count(name) > 1:
            name = base = steps[i][0]
            number = 1
            while name in taken:
                number += 1
                name = f"{base[:NAME_MAX - len(str(number)) - 1].rstrip('-')}-{number}"
        taken.add(name)
        result.append(name)
    return result


# --- imports --------------------------------------------------------------------------------

def specifiers(path: str, text: str) -> list[tuple]:
    """The import statements of one file: ("py", dots, module, names) or ("js", specifier)."""
    if path.endswith(".py"):
        out = []
        for m in _PY_IMPORT.finditer(text):
            out += [("py", 0, part.split()[0], []) for part in m.group(1).split(",")
                    if part.strip()]
        for m in _PY_FROM.finditer(text):
            out.append(("py", len(m.group(1)), m.group(2),
                        [n.strip() for n in m.group(3).split(",") if n.strip()]))
        return out
    return [("js", m.group(1)) for rx in _JS for m in rx.finditer(text)]


class Resolver:
    """Import statements -> the unit (directory) they reach, or None (external)."""

    def __init__(self, files: list[str], found: list[dict]):
        self.files = set(files)
        self.dirs = [u["dir"] for u in found]
        self.packages = {u["manifest"]["name"]: u["dir"] for u in found
                         if u["manifest"] and u["manifest"]["name"]
                         and u["manifest"]["kind"] in ("package.json", "composer.json")}
        holders: dict[str, set] = {}
        for f in files:
            parts = f.split("/")
            for d in self.dirs:
                if not f.startswith(d + "/"):
                    continue
                rest = parts[len(d.split("/")):]
                if len(rest) == 2 and rest[1] == "__init__.py":
                    holders.setdefault(rest[0], set()).add(d)
                elif len(rest) == 1 and rest[0].endswith(".py"):
                    holders.setdefault(rest[0][:-3], set()).add(d)
                elif len(rest) >= 3 and rest[0] == "src" and rest[-1].endswith(".py"):
                    holders.setdefault(rest[1], set()).add(d)
        self.python = {p: ds.pop() for p, ds in holders.items() if len(ds) == 1}

    def unit_of(self, path: str) -> str | None:
        return next((d for d in self.dirs if path.startswith(d + "/")), None)

    def file(self, base: str) -> str | None:
        """A relative specifier's file: itself, with an extension, or its index file."""
        for candidate in [base] + [base + e for e in JS_EXTENSIONS + (".py",)] + \
                [f"{base}/index{e}" for e in JS_EXTENSIONS] + [f"{base}/__init__.py"]:
            if candidate in self.files:
                return candidate
        return None

    def resolve(self, source: str, statement: tuple) -> set[str]:
        here = _dir(source)
        if statement[0] == "js":
            spec = statement[1]
            if spec.startswith(("./", "../")):
                target = self.file(os.path.normpath(os.path.join(here, spec)).replace("\\", "/"))
                return {self.unit_of(target)} - {None} if target else set()
            parts = spec.split("/")
            package = "/".join(parts[:2]) if spec.startswith("@") else parts[0]
            return {self.packages[package]} if package in self.packages else set()
        _, dots, module, imported = statement
        if dots:
            base = here
            for _ in range(dots - 1):
                base = _dir(base)
            if module:
                targets = [self.file(_join(base, module.replace(".", "/")))]
            else:  # `from . import a, b`: the modules a and b, else the package itself
                targets = [self.file(_join(base, n)) for n in imported]
                if not any(targets):
                    targets = [self.file(_join(base, "__init__"))]
            return {self.unit_of(t) for t in targets if t} - {None}
        first = module.split(".")[0]
        return {self.python[first]} if first in self.python else set()


def import_edges(root, found: list[dict], files: list[str], texts: dict) -> dict[str, dict]:
    """Per unit directory: {"intra": n, "cross": {other dir: n}} — resolved import statements
    whose source file is in the unit (`texts`: what the preflight scan read, None for a file
    that is not UTF-8; any other code file is read here, once)."""
    resolver = Resolver(files, found)
    out = {u["dir"]: {"intra": 0, "cross": {}} for u in found}
    for path in files:
        unit = resolver.unit_of(path)
        if unit is None or PurePosixPath(path).suffix.lower() not in SCANNED:
            continue
        if path in texts:
            text = texts[path]
        else:
            try:
                text = preflight._read(root / path).decode("utf-8")
            except (OSError, UnicodeDecodeError):
                continue
        if text is None:
            continue  # the scan read it: not UTF-8
        for statement in specifiers(path, text):
            for target in resolver.resolve(path, statement):
                if target == unit:
                    out[unit]["intra"] += 1
                else:
                    out[unit]["cross"][target] = out[unit]["cross"].get(target, 0) + 1
    return out


# --- CODEOWNERS -------------------------------------------------------------------------------

def owner_rules(text: str) -> list[tuple]:
    """(regex, owners) of every supported CODEOWNERS line, in file order."""
    rules = []
    for line in text.splitlines():
        line = line.split(" #")[0].strip()
        if not line or line.startswith("#"):
            continue
        pattern, *owners = line.split()
        if any(c in pattern for c in "![]\\"):
            continue  # a syntax outside the documented subset: skipped
        anchored = pattern.startswith("/") or "/" in pattern.strip("/")
        body = glob_to_regex(pattern.strip("/")).pattern.removesuffix(r"\Z")
        rx = ("" if anchored else "(?:.*/)?") + body + r"(?:/.*)?\Z"
        rules.append((re.compile(rx), frozenset(owners)))
    return rules


def owners_of(root, files: list[str], texts: dict) -> dict[str, frozenset] | None:
    """File -> its owner set (the last matching rule); None without a CODEOWNERS file (looked
    up on disk: outside git the file set skips `.github/`)."""
    source = next((c for c in CODEOWNERS if (root / c).is_file()), None)
    if source is None:
        return None
    if source in texts:  # the scan read it (None: not UTF-8); an empty file is read once
        text = texts[source]
    else:
        try:
            text = preflight._read(root / source).decode("utf-8")
        except (OSError, UnicodeDecodeError):
            return None
    if text is None:
        return None
    rules = owner_rules(text)
    out = {}
    for f in files:
        owners = frozenset()
        for rx, who in rules:
            if rx.match(f):
                owners = who
        out[f] = owners
    return out


# --- co-change ------------------------------------------------------------------------------

def co_change(root, commits: int) -> list[set[str]] | None:
    """The file sets of the last `commits` commits (`git log --name-only`, one run); None when
    the signal is off (0), outside git or before the first commit."""
    if commits <= 0 or work_tree_error(root) is not None:
        return None
    proc = subprocess.run(["git", "-c", "core.quotepath=off", "-C", str(root), "log",
                           "--name-only", "--no-renames", "--relative", "--format=%x1e%H",
                           "-n", str(commits)], capture_output=True, encoding="utf-8",
                          errors="replace", env=git_env())
    if proc.returncode != 0:
        return None
    return [set(line for line in chunk.splitlines()[1:] if line.strip())
            for chunk in proc.stdout.split("\x1e") if chunk.strip()]


def jaccard(a: set, b: set) -> tuple[int, int]:
    """(intersection, union) of two commit sets; two empty sets have Jaccard 0."""
    return len(a & b), len(a | b)


def co_changed(inter: int, union: int) -> bool:
    """Jaccard >= 0.6, compared exactly in integers."""
    return union > 0 and 5 * inter >= 3 * union


# --- the proposal ---------------------------------------------------------------------------

def keywords(name: str, manifest: dict | None) -> list[str]:
    """Seed words: the tokens of the name, the manifest name and keywords, then description
    words of 4+ letters that are not generic — first appearance, de-duplicated; never a token
    of 3 characters or fewer, nor the npm scope of the manifest name (`@org/…`)."""
    words = _WORD.findall(name.lower())
    scope: set[str] = set()
    if manifest:
        raw = (manifest["name"] or "").lower()
        if raw.startswith("@") and "/" in raw:
            scope = set(_WORD.findall(raw.split("/", 1)[0]))
        words += _WORD.findall(raw)
        for keyword in manifest.get("keywords") or []:
            words += _WORD.findall(keyword.lower())
        words += [w for w in _WORD.findall((manifest.get("description") or "").lower())
                  if len(w) >= 4 and w.isalpha() and w not in GENERIC_KEYWORDS]
    return [w for w in dict.fromkeys(words) if len(w) > 3 and w not in scope]


def line_count(root, rel: str, texts: dict) -> int:
    """The lines of a code file: from the scan's text when it kept one, else read (0: a
    symlink, larger than `BIG`, unreadable or binary)."""
    text = texts.get(rel)
    if text is not None:
        return len(text.splitlines())
    path = PurePosixPath(rel)
    full = root / str(path)
    try:
        if full.is_symlink() or full.stat().st_size > preflight.BIG:
            return 0
        data = full.read_bytes()
    except OSError:
        return 0
    if b"\0" in data[:preflight.SNIFF]:
        return 0
    return len(data.decode("utf-8", errors="replace").splitlines())


def split_children(base: str, sized: list[tuple[str, int]], limit: int,
                   depth: int) -> list[dict]:
    """{dir, lines} per code-holding subdirectory of `base`, in path order; one that alone holds
    more than `limit` lines is replaced by its own subdirectories while `depth` allows and it
    has two or more (files right in a directory never make a child)."""
    groups: dict[str, list[tuple[str, int]]] = {}
    for f, n in sized:
        rest = f[len(base) + 1:]
        if "/" in rest:
            groups.setdefault(f"{base}/{rest.split('/', 1)[0]}", []).append((f, n))
    out = []
    for sub, members in sorted(groups.items()):
        lines = sum(n for _, n in members)
        inner = split_children(sub, members, limit, depth - 1) \
            if lines > limit and depth > 1 else []
        out += inner if len(inner) > 1 else [{"dir": sub, "lines": lines}]
    return out


def build(root, config: dict, files: list[str], manifests: list[dict],
          texts: dict | None = None) -> dict:
    """proposal.json's document; `texts`: the code texts the preflight scan already read."""
    texts = texts or {}
    skip = {config["paths"]["modules_dir"].split("/")[0], *DEPENDENCY_DIRS}
    found = units(files, manifests, skip)
    unit_names = names(found)
    by_dir = dict(zip((u["dir"] for u in found), unit_names))
    edges = import_edges(root, found, files, texts)
    owners = owners_of(root, files, texts)
    history = co_change(root, config["init"]["co_change_commits"])
    touched = {u["dir"]: {i for i, commit in enumerate(history or [])
                          if any(f.startswith(u["dir"] + "/") for f in commit)} for u in found}
    candidates, hints = [], []
    limit = config["init"].get("split_hint_lines", SPLIT_HINT_LINES)
    for unit, name in zip(found, unit_names):
        d = unit["dir"]
        own = [f for f in files if f.startswith(d + "/")]
        intra, cross = edges[d]["intra"], sum(edges[d]["cross"].values())
        cohesion = round(intra / (intra + cross), 4) if intra + cross else 0.0
        sets = sorted({owners[f] for f in own if owners[f]}, key=sorted) if owners else []
        single = 1.0 if len(sets) == 1 else 0.0
        partner, best = None, (0, 1)
        for other in found:
            if other["dir"] != d:
                inter, union = jaccard(touched[d], touched[other["dir"]])
                if union and inter * best[1] > best[0] * union:
                    partner, best = by_dir[other["dir"]], (inter, union)
        top = best[0] / best[1]
        isolation = round(1 - top, 4) if history else 0.0
        signals = {"manifest": 1.0 if unit["manifest"] else 0.0, "cohesion": cohesion,
                   "owners": single, "isolation": isolation, "intra_imports": intra,
                   "cross_imports": cross, "owner_sets": [sorted(s) for s in sets],
                   "co_change": round(top, 4), "co_change_partner": partner}
        confidence = round(sum(WEIGHTS[k] * signals[k] for k in WEIGHTS), 2)
        rationale = list(unit["rationale"])
        if intra + cross:
            rationale.append(f"imports: {intra} within the unit, {cross} to other candidates "
                             f"(cohesion {cohesion})")
        if single:
            rationale.append(f"one owner set in CODEOWNERS: {', '.join(sorted(sets[0]))}")
        if history:
            rationale.append(f"co-change: at most {round(top, 4)} with another candidate"
                             + (f" ({partner})" if partner else ""))
        candidates.append({"name": name, "include": True, "paths": [f"{d}/**"],
                           "confidence": confidence, "rationale": rationale, "signals": signals,
                           "edges": [{"to": by_dir[t], "imports": n}
                                     for t, n in sorted(edges[d]["cross"].items(),
                                                        key=lambda kv: by_dir[kv[0]])],
                           "keywords": keywords(name, unit["manifest"])})
        if len(sets) > 1 and all(not (a & b) for i, a in enumerate(sets) for b in sets[i + 1:]):
            hints.append({"kind": "split", "candidates": [name],
                          "reason": f"its files have disjoint owner sets in CODEOWNERS: "
                                    + "; ".join(", ".join(sorted(s)) for s in sets)})
        elif limit:
            sized = [(f, line_count(root, f, texts)) for f in own if language(f)]
            total = sum(n for _, n in sized)
            children = split_children(d, sized, limit, SPLIT_DEPTH) if total > limit else []
            if len(children) > 1:
                hints.append({"kind": "split", "candidates": [name],
                              "reason": f"{total} lines of code, more than [init] "
                                        f"split_hint_lines {limit}: start from its "
                                        f"subdirectories",
                              "children": children})
    for i, a in enumerate(found):
        for b in found[i + 1:]:
            inter, union = jaccard(touched[a["dir"]], touched[b["dir"]])
            both = (edges[a["dir"]]["cross"].get(b["dir"])
                    and edges[b["dir"]]["cross"].get(a["dir"]))
            if history and co_changed(inter, union) and both:
                pair = sorted([by_dir[a["dir"]], by_dir[b["dir"]]])
                hints.append({"kind": "merge", "candidates": pair,
                              "reason": f"they import each other and change together "
                                        f"(Jaccard {inter}/{union} of the recent commits)"})
    claimed = [f"{u['dir']}/" for u in found]
    unassigned = [f for f in files if language(f) and not _hidden(f)
                  and f.split("/")[0] not in skip and not f.startswith(tuple(claimed))]
    hints.sort(key=lambda h: (h["kind"], h["candidates"]))
    return {"schema": SCHEMA, "root": str(root), "candidates": candidates,
            "unassigned": unassigned, "hints": hints}
