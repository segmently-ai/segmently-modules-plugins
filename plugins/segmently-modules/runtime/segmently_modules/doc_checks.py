"""Lint checks over the module docs as files: MS005 a registered doc that holds NUL bytes or is
not valid UTF-8 · MS016 a `*.md` in a module's `roles/` directory that no registry entry names ·
MS017 (info) the `*.md` files directly in a module's directory that no registry entry names, one
finding per module · MS041 a relative link in a registered doc whose target is missing on disk
(`[lint] link_severity`) · MS042 (info) a `#anchor` that names no heading of its target doc ·
MS043 (info) backticked repository paths outside the components table that are missing on disk,
one finding per module."""
from __future__ import annotations

import html
import os
import posixpath
import re

from segmently_modules.changes import DEPENDENCY_DIRS, code_globs
from segmently_modules.registry import as_dict, context_paths

_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_BACKTICKS = re.compile(r"`+")
_BACKTICK = re.compile(r"`([^`]+)`")
# an inline link or image: [text](target "title") — one level of nested brackets in the text,
# one level of parentheses in the target
_LINK = re.compile(r"!?\[(?:[^\[\]]|\[[^\[\]]*\])*\]\(\s*(<[^>\n]*>|(?:[^\s()]|\([^\s()]*\))*)"
                   r"(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\s*\)")
# a reference definition `[label]: target "title"` — never a footnote `[^1]: text`, never a
# label followed by prose (`[note]: Do not edit`)
_REF_DEF = re.compile(r"^ {0,3}\[(?!\^)[^\]]+\]:[ \t]*(<[^>]*>|\S+)"
                      r"(?:[ \t]+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?[ \t]*$")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_ATX_OPEN = re.compile(r"^ {0,3}#{1,6}(?=[ \t]|$)")
_CONTAINER = re.compile(r"^ {0,3}(?:>[ ]?|(?:[-*+]|\d{1,9}[.)])[ \t]+)")  # quote, list item
_EMPHASIS_UNDERSCORE = re.compile(r"(?<!\w)_+|_+(?!\w)")
_SETEXT = re.compile(r"^ {0,3}(?:=+|-+)[ \t]*$")
_HTML_ID = re.compile(r"""\b(?:id|name)\s*=\s*["']([^"']+)["']""")
_ATTR_ID = re.compile(r"\s*\{#([^}\s]+)\}\s*$")
_LINE_ANCHOR = re.compile(r"L\d+(?:-L\d+)?")
_PLACEHOLDER = re.compile(r"[<>{}$*…]|\.\.\.")
_GLOB = re.compile(r"[*?\[{]")
GENERATED = frozenset(DEPENDENCY_DIRS) | {"coverage"}  # build output: never a stale doc path
DOC_SUFFIXES = (".md", ".markdown")  # what is read as a doc: never an image or a source file
SHOWN = 5


def unquote(text: str) -> str:
    """`%xx` escapes decoded as UTF-8 (a link's `%20`); an invalid sequence stays as written."""
    def bytes_of(m) -> str:
        try:
            return bytes.fromhex(m.group(0).replace("%", "")).decode("utf-8")
        except ValueError:
            return m.group(0)
    return re.sub(r"(?:%[0-9A-Fa-f]{2})+", bytes_of, text)


def _norm(path: str) -> str:
    return posixpath.normpath(path.replace(os.sep, "/"))


def in_repo(path: str) -> bool:
    """`path` is relative and stays inside the root once normalized (no absolute path, no drive,
    no `..` that climbs out): the only paths the doc checks read."""
    p = _norm(path)
    return not (p.startswith("/") or re.match(r"[A-Za-z]:", p) or p == ".." or
                p.startswith("../"))


def _is_doc(path: str) -> bool:
    return path.lower().endswith(DOC_SUFFIXES)


def _listed(items: list[str]) -> str:
    return ", ".join(items[:SHOWN]) + (", …" if len(items) > SHOWN else "")


def _targets(ws):
    """(target, entry, its directory by `create`'s path rule) of every module and child entry
    that is an object, in registry order; the directory is None when it would lie outside the
    root (a name with `..`) or cannot name a path (a NUL in it)."""
    mdir = ws.config["paths"]["modules_dir"].rstrip("/")

    def folder(rel: str) -> str | None:
        return rel if in_repo(rel) and "\0" not in rel else None

    for name, entry in ws.registry.modules.items():
        if not isinstance(entry, dict):
            continue
        yield name, entry, folder(f"{mdir}/{name}")
        for child, sub in as_dict(entry.get("submodules")).items():
            if isinstance(sub, dict):
                yield f"{name}/{child}", sub, folder(f"{mdir}/{name}/submodules/{child}")


def registered_docs(ws) -> dict[str, str]:
    """{normalized doc path: the first target that names it} over every `context_files` path
    (universal, roles, extras) of every module and child that lies inside the root."""
    out: dict[str, str] = {}
    for target, entry, _ in _targets(ws):
        for _, path in context_paths(entry.get("context_files")):
            if isinstance(path, str) and path and "\0" not in path and in_repo(path):
                out.setdefault(_norm(path), target)
    return out


def _decode(ws, rel: str) -> tuple[str | None, str | None]:
    """(text, None) for a readable UTF-8 doc without NUL bytes; (None, why) for a damaged one;
    (None, None) when it cannot be read (MS004 reports a missing path)."""
    path = ws.disk(rel)
    try:
        if not path.is_file():
            return None, None
        data = path.read_bytes()
    except (OSError, ValueError):
        return None, None
    nul = data.count(b"\0")
    if nul:
        return None, f"holds {nul} NUL byte(s)"
    try:
        return data.decode("utf-8").removeprefix("\ufeff"), None
    except UnicodeDecodeError as e:
        line = data[:e.start].count(b"\n") + 1
        return None, f"is not valid UTF-8 (byte 0x{data[e.start]:02x} on line {line})"


def _strip_comments(line: str, inside: bool) -> tuple[str, bool]:
    """`line` without its HTML comments (`<!-- … -->`, which may span lines) and whether a
    comment is still open at its end."""
    out, pos = [], 0
    while True:
        if inside:
            end = line.find("-->", pos)
            if end < 0:
                return "".join(out), True
            pos, inside = end + 3, False
        else:
            start = line.find("<!--", pos)
            if start < 0:
                out.append(line[pos:])
                return "".join(out), False
            out.append(line[pos:start])
            pos, inside = start + 4, True


def _outside_fences(text: str):
    """(line number, line) of every line outside fenced code blocks and HTML comments (the
    comments cut out of the line). A backtick run whose line holds another backtick is inline
    code, not a fence (```` ```js x``` ````)."""
    fence, comment = None, False
    for n, line in enumerate(text.splitlines(), 1):
        m = _FENCE.match(line)
        if fence is not None:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) \
                    and not line.strip()[len(m.group(1)):].strip():
                fence = None
            continue
        if m and not comment and not (m.group(1)[0] == "`" and
                                      "`" in line.strip()[len(m.group(1)):]):
            fence = m.group(1)
            continue
        line, comment = _strip_comments(line, comment)
        yield n, line


def _strip_code_spans(line: str) -> str:
    """`line` without its code spans: a run of N backticks up to the next run of exactly N (an
    unmatched run is text). Linear in the line's length."""
    runs = [(m.start(), m.end()) for m in _BACKTICKS.finditer(line)]
    following: list[int | None] = [None] * len(runs)
    last: dict[int, int] = {}
    for i in range(len(runs) - 1, -1, -1):  # the next run of the same length, right to left
        n = runs[i][1] - runs[i][0]
        following[i] = last.get(n)
        last[n] = i
    out, pos, i = [], 0, 0
    while i < len(runs):
        j = following[i]
        if j is None:
            i += 1
            continue
        out.append(line[pos:runs[i][0]])
        pos, i = runs[j][1], j + 1
    out.append(line[pos:])
    return "".join(out)


def _atx_title(line: str) -> str | None:
    """The text of an ATX heading (`## Title ##`), inside a block quote or a list item too;
    None for any other line."""
    for _ in range(4):  # `> - ## x`: a few container levels at most
        m = _CONTAINER.match(line)
        if not m:
            break
        line = line[m.end():]
    m = _ATX_OPEN.match(line)
    if not m:
        return None
    title = line[m.end():].strip()
    bare = title.rstrip("#")
    if bare != title and (not bare or bare[-1] in " \t"):  # a closing `##` sequence
        title = bare.rstrip()
    return title


def _slug(text: str) -> str:
    """GitHub's heading anchor: link text kept, tags dropped, entities decoded, emphasis
    underscores dropped (a `snake_case` word keeps its own), lower case, everything but letters,
    digits, `_`, `-` and spaces dropped, spaces as `-`."""
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    text = _EMPHASIS_UNDERSCORE.sub("", text)
    return re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-")


def anchors(text: str) -> set[str]:
    """Every anchor a doc offers, lower case: its headings' slugs (a repeated slug as `x-1`,
    `x-2`, …), `{#id}` heading attributes and HTML `id` / `name` attributes."""
    out: set[str] = set()
    seen: dict[str, int] = {}

    def heading(title: str) -> None:
        explicit = _ATTR_ID.search(title)
        if explicit:
            out.add(explicit.group(1).lower())
            title = title[:explicit.start()]
        slug = _slug(title)
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        out.add(slug if count == 0 else f"{slug}-{count}")

    previous = ""
    for _, line in _outside_fences(text.removeprefix("\ufeff")):
        out.update(a.lower() for a in _HTML_ID.findall(line))
        title = _atx_title(line)
        if title is not None:
            heading(title)
            previous = ""
            continue
        if _SETEXT.match(line) and previous.strip() and not previous.lstrip().startswith(
                ("|", ">", "-", "*", "+")):
            heading(previous)
            previous = ""
            continue
        previous = line
    return out


def _links(text: str):
    """(line number, target) of every inline link, image and reference definition outside code
    (fenced blocks and code spans)."""
    for n, line in _outside_fences(text):
        prose = _strip_code_spans(line)
        for m in _LINK.finditer(prose):
            yield n, m.group(1)
        ref = _REF_DEF.match(prose)
        if ref:
            yield n, ref.group(1)


def doc_findings(ws, heading: str, repo) -> list:
    """MS005, MS016, MS017, MS041, MS042 and MS043 (see the module docstring) — over `*.md`
    docs only; `heading` is the components-table heading (`[lint] component_table_heading`)
    whose table MS040 checks; `repo` = lint's `RepoFiles` (git asked once per run), None under
    `lint --changed`, which skips MS043 (it needs the repository's file list)."""
    from segmently_modules.lint import Finding  # lint imports this module
    out: list = []
    docs = registered_docs(ws)
    texts: dict[str, str | None] = {}
    for rel, target in docs.items():
        if not _is_doc(rel):
            continue
        text, why = _decode(ws, rel)
        texts[rel] = text
        if why:
            out.append(Finding("MS005", "error", target, f"doc {why} — the file is damaged; "
                               f"restore it from git history or re-save it as UTF-8", rel))
    out += _orphans(ws, docs, Finding)

    def text_of(rel: str) -> str | None:
        if rel not in texts:
            texts[rel] = _decode(ws, rel)[0]
        return texts[rel]

    severity = ws.config["lint"].get("link_severity", "warning")
    cache: dict[str, set[str] | None] = {}
    stale: dict[str, list[tuple[str, str]]] = {}  # target -> [(doc, path)]
    roots: list = []  # computed once, on the first backticked path that needs it

    def repo_root(name: str) -> bool:
        """`name` is a top-level directory holding files git does not ignore (outside git: a
        directory at the root)."""
        if not roots:
            roots.append(None if repo.error() else  # `repo` is set: MS043 runs
                         {p.split("/")[0] for p in repo.files() if "/" in p})
        return name in roots[0] if roots[0] is not None else (ws.root / name).is_dir()

    for rel, target in list(docs.items()):
        text = texts.get(rel)
        if text is None:
            continue
        for n, raw in _links(text):
            out += _check_link(ws, rel, target, n, raw, text_of, cache, severity, Finding)
        for path in (_stale_paths(ws, rel, target, text, heading, repo_root) if repo else ()):
            stale.setdefault(target, []).append((rel, path))
    for target, found in stale.items():
        doc_names = sorted({doc for doc, _ in found})
        items = [f"{path} ({posixpath.basename(doc)})" for doc, path in found]
        out.append(Finding("MS043", "info", target, f"{len(found)} backticked path(s) missing on "
                           f"disk in {len(doc_names)} doc(s): {_listed(items)}",
                           doc_names[0] if len(doc_names) == 1 else None))
    return out


def _orphans(ws, docs: dict[str, str], Finding) -> list:
    """MS016 per file in a target's `roles/` directory, MS017 per target for the files directly
    in its directory: `*.md` files (not `*.legacy.md`) that no registry entry names."""
    out = []
    roles = sorted(as_dict(ws.config.get("roles")), key=len, reverse=True)

    def unregistered(rel_dir: str) -> list[str]:
        try:
            names = sorted(p.name for p in (ws.root / rel_dir).iterdir()
                           if p.suffix == ".md" and p.is_file()
                           and not p.name.endswith(".legacy.md"))
        except (OSError, ValueError):
            return []
        return [f"{rel_dir}/{n}" for n in names if _norm(f"{rel_dir}/{n}") not in docs]

    for target, entry, base in _targets(ws):
        if base is None:
            continue
        for rel in unregistered(f"{base}/roles"):
            stem = posixpath.splitext(posixpath.basename(rel))[0]
            out.append(Finding("MS016", "warning", target, f"{rel} is not registered — agents "
                               f"never load it; " + _role_hint(entry, target, base, stem, roles),
                               rel))
        loose = unregistered(base)
        if loose:
            out.append(Finding("MS017", "info", target, f"{len(loose)} doc(s) in {base}/ are not "
                               f"registered — agents never load them: "
                               f"{_listed([posixpath.basename(r) for r in loose])}; list one "
                               f"(segmently-modules registry append {target} context_files.supplementary "
                               f"'\"<path>\"') or move it out of the module directory", base))
    return out


def _role_hint(entry: dict, target: str, base: str, stem: str, roles: list[str]) -> str:
    """How to fix an unregistered doc in `roles/`: the role its name reads as (the same name,
    or one that starts with it: ARCHITECTURE -> architect), else a supplementary doc."""
    name = stem.lower()
    role = next((r for r in roles if name == r.lower()), None) or \
        next((r for r in roles if name.startswith(r.lower())), None)
    if role is None:
        return (f"register it (segmently-modules registry append {target} context_files.supplementary "
                f"'\"{base}/roles/{stem}.md\"') or delete it")
    held = as_dict(as_dict(entry.get("context_files")).get("roles")).get(role)
    if isinstance(held, (str, list)) and held:
        return (f"it reads like the {role} doc, which is registered already — merge it into "
                f"that doc or delete it")
    if stem == role:
        return f"it is the {role} doc: segmently-modules roles add {role} {target} registers it"
    return (f"it reads like the {role} doc: rename it to {base}/roles/{role}.md, then "
            f"segmently-modules roles add {role} {target} registers it")


def _check_link(ws, doc: str, target: str, n: int, raw: str, text_of, cache, severity,
                Finding) -> list:
    """MS041 / MS042 for one link `raw` on line `n` of `doc`. A URL (a scheme or `//`), a
    placeholder and a path outside the repository are not checked; a leading `/` is the
    repository root, and a path that does not start with `./` or `../` and is missing next to
    the doc counts when it exists from the root (agents read it so); a `#L12` anchor is a line,
    not a heading."""
    link = raw[1:-1] if raw.startswith("<") and raw.endswith(">") else raw
    if not link or _SCHEME.match(link) or link.startswith("//"):
        return []
    path, _, anchor = link.partition("#")
    path = unquote(path.split("?")[0])
    if _PLACEHOLDER.search(path):
        return []
    if not path:
        rel = doc
    elif path.startswith("/"):
        rel = _norm(path.lstrip("/"))
    else:
        rel = _norm(posixpath.join(posixpath.dirname(doc), path))
        rooted = _norm(path)  # agents read `src/x.ts` from the repository root as well
        if not ws.exists(rel) and not path.startswith(("./", "../")) and ws.exists(rooted):
            rel = rooted
    bare = re.sub(r"^(?:\.\./)+", "", path)
    hint = (f" (from the repository root it is {_norm(bare)}: fix the ../ depth)"
            if bare != path and in_repo(bare) and ws.exists(_norm(bare)) else "")
    if not in_repo(rel):  # outside the repository: not checked, unless it is a depth slip
        return [Finding("MS041", severity, target, f"line {n}: link to {link} — {rel} is missing "
                        f"on disk{hint}", doc)] if hint else []
    if not ws.exists(rel):
        return [Finding("MS041", severity, target, f"line {n}: link to {link} — {rel} is missing "
                        f"on disk{hint}", doc)]
    anchor = unquote(anchor)
    if not anchor or not rel.endswith(".md") or _LINE_ANCHOR.fullmatch(anchor):
        return []
    if rel not in cache:
        text = text_of(rel)
        cache[rel] = anchors(text) if text is not None else None
    if cache[rel] is None or anchor.lower() in cache[rel]:
        return []
    return [Finding("MS042", "info", target, f"line {n}: link to {link} — {rel} has no heading "
                    f"for #{anchor}", doc)]


def _code_dirs(ws, target: str) -> list[str]:
    """The directories a target's code lives in, for reading a short backticked path: the literal
    head of each `[[code_map]]` glob of the target (and of its parent) and of each code pointer."""
    parent = target.partition("/")[0]
    out = []
    for t in dict.fromkeys([target, parent]):
        for glob in code_globs(ws.config, t):
            head = _GLOB.split(glob, 1)[0]
            out.append(head if head.endswith("/") else posixpath.dirname(head) + "/")
    modules = ws.registry.modules
    holders = [as_dict(modules.get(parent))]
    if "/" in target:
        holders.append(as_dict(as_dict(holders[0].get("submodules")).get(target.partition("/")[2])))
    for holder in holders:
        for name, fdef in ws.fields.items():
            if fdef.kind != "code_pointer":
                continue
            value = holder.get(name)
            for p in value if isinstance(value, list) else [value]:
                if isinstance(p, str) and p:
                    p = p.split(":")[0].rstrip("/")
                    out.append(p + "/" if ws.exists(p) and (ws.root / p).is_dir()
                               else posixpath.dirname(p) + "/")
    return [d for d in dict.fromkeys(out) if d not in ("/", "./")]


def _stale_paths(ws, doc: str, target: str, text: str, heading: str, repo_root) -> list[str]:
    """The backticked repository paths of a doc that are missing on disk, outside fenced code
    and outside the components table (MS040 checks that one). A path counts as a repository
    path when its first segment is a top-level directory with files git does not ignore
    (`repo_root`); it is found when it exists from the root, next to the doc or under one of the
    target's code directories. Build output (`dist/`, `node_modules/`, `coverage/`, …) is never
    checked."""
    from segmently_modules.lint import component_path  # lint imports this module
    out: list[str] = []
    dirs = None
    in_table = False
    for _, line in _outside_fences(text):
        if line.startswith("#"):
            in_table = heading in line
            continue
        if in_table and line.startswith("|"):
            continue
        for token in _BACKTICK.findall(line):
            candidate = component_path(token)
            if not candidate or candidate.startswith(("/", "./", "../")) or candidate in out \
                    or _PLACEHOLDER.search(candidate):
                continue
            parts = candidate.rstrip("/").split("/")
            if GENERATED & set(parts) or ws.exists(candidate) or not repo_root(parts[0]):
                continue
            if dirs is None:
                dirs = [posixpath.dirname(doc) + "/", *_code_dirs(ws, target)]
            if not any(ws.exists(_norm(d + candidate)) for d in dirs):
                out.append(candidate)
    return out
