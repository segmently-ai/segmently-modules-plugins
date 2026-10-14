"""`init` phase 1, preflight: what the repository holds, deterministic and sorted.

The file set: `git ls-files --cached --others --exclude-standard` in a git work tree (ONE
listing), else a walk that skips dot-directories and the dependency / build directories
(`DEPENDENCY_DIRS`); minus `[init] exclude` globs (the `[[code_map]]` glob grammar); a listed
path missing on disk is dropped, and so is a path that is not valid UTF-8 (possible on Linux:
no output could name it). `scan` reads every file once; `build` turns both into
`preflight.json`: `{schema, root, git: {head, commits} | null, files, lines, bytes,
token_estimate, languages: [{language, files, lines}], manifests: [{path, kind, name,
workspaces}], agent_docs, adrs, top_dirs}`, every list sorted.

Counting: every file counts toward `files`; its size toward `bytes` unless it cannot be read (a
symlink is never followed: 0 bytes). A text file — at most 1,048,576 bytes (`BIG`), no NUL in
bytes 0–8191 (`SNIFF`) — counts its `len(text.splitlines())` toward `lines` and its bytes toward
`token_estimate` (`text bytes // 4`); a code file of a text kind also counts in its `languages`
row (`LANGUAGES`, by extension). A manifest (package.json, pyproject.toml, setup.cfg, go.mod,
Cargo.toml, composer.json, *.csproj) that does not parse has `name: null`, `workspaces: []`."""
from __future__ import annotations

import configparser
import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath

from segmently_modules._toml import tomllib
from segmently_modules.changes import DEPENDENCY_DIRS, git_env, glob_to_regex, work_tree_error

SCHEMA = "segmently-modules.init-preflight/1"
BIG = 1_048_576  # bytes: a larger file counts toward files and bytes only
SNIFF = 8192  # a NUL in the first SNIFF bytes: binary (files and bytes only)
AGENT_DOCS = ("AGENTS.md", "CLAUDE.md", "GEMINI.md", ".cursorrules", ".windsurfrules",
              ".github/copilot-instructions.md")  # the agents' instruction files
ADR_DIRS = ("adr", "adrs", "doc/adr", "docs/adr", "docs/adrs", "docs/decisions",
            "docs/architecture/decisions", "architecture/decisions")
MANIFESTS = ("package.json", "pyproject.toml", "setup.cfg", "go.mod", "Cargo.toml",
             "composer.json")  # plus any *.csproj
# extension -> language: the code files of the file set (lines count; map's units and
# `unassigned` hold code files only)
LANGUAGES = {
    ".c": "C", ".h": "C", ".cc": "C++", ".cpp": "C++", ".hpp": "C++", ".cs": "C#",
    ".go": "Go", ".java": "Java", ".js": "JavaScript", ".jsx": "JavaScript",
    ".mjs": "JavaScript", ".cjs": "JavaScript", ".kt": "Kotlin", ".php": "PHP",
    ".py": "Python", ".rb": "Ruby", ".rs": "Rust", ".scala": "Scala", ".sh": "Shell",
    ".swift": "Swift", ".ts": "TypeScript", ".tsx": "TypeScript", ".mts": "TypeScript",
    ".cts": "TypeScript", ".vue": "Vue", ".svelte": "Svelte", ".dart": "Dart",
    ".ex": "Elixir", ".exs": "Elixir", ".lua": "Lua", ".m": "Objective-C", ".r": "R",
    ".sql": "SQL",
}


def language(path: str) -> str | None:
    """The language of a code file by its extension (`LANGUAGES`), else None."""
    return LANGUAGES.get(PurePosixPath(path).suffix.lower())


def manifest_kind(path: str) -> str | None:
    name = PurePosixPath(path).name
    if name in MANIFESTS:
        return name
    return "csproj" if name.endswith(".csproj") else None


def _walk(root: Path) -> list[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        base = Path(dirpath)
        links = [d for d in dirnames if (base / d).is_symlink()]  # a symlink is a file entry
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".")
                             and d not in DEPENDENCY_DIRS and d not in links)
        out += [(base / n).relative_to(root).as_posix() for n in filenames + links]
    return out


def list_files(root: Path, config: dict) -> list[str]:
    """The init file set (root-relative posix paths, sorted) — see the module docstring."""
    if work_tree_error(root) is None:
        proc = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached", "--others",
                               "--exclude-standard"], capture_output=True, env=git_env())
        paths = [p.decode("utf-8", "surrogateescape") for p in proc.stdout.split(b"\0") if p]
    else:
        paths = _walk(root)
    exclude = [glob_to_regex(g) for g in config["init"]["exclude"]]
    return sorted({p for p in paths if _utf8(p) and os.path.lexists(root / p)
                   and not any(rx.match(p) for rx in exclude)})


def _utf8(path: str) -> bool:
    """False for a name the listing decoded with `surrogateescape` (not valid UTF-8)."""
    try:
        path.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _read(path: Path) -> bytes:
    """The one place preflight reads a file's bytes (tests count the calls)."""
    return path.read_bytes()


def scan(root: Path, files: list[str], keep=lambda rel: False) -> dict:
    """Read every file of `files` at most once: {files, lines, bytes, text_bytes, languages:
    {language: [files, lines]}, texts: {path: text | None}} — `texts` holds every manifest and
    every file `keep(path)` asks for that the scan read: its text, or None when it is not
    UTF-8 (the map reuses them and never reads such a file again)."""
    out = {"files": len(files), "lines": 0, "bytes": 0, "text_bytes": 0, "languages": {},
           "texts": {}}
    for rel in files:
        path = root / rel
        if path.is_symlink():
            continue  # a file of the set, never followed
        try:
            size = path.stat().st_size
            if size > BIG:
                out["bytes"] += size
                continue
            data = _read(path)
        except OSError:
            continue  # unreadable: it counts toward files only
        out["bytes"] += len(data)
        if manifest_kind(rel) or keep(rel):
            try:
                out["texts"][rel] = data.decode("utf-8")
            except UnicodeDecodeError:
                out["texts"][rel] = None  # read once: not UTF-8, nobody reads it again
        if b"\0" in data[:SNIFF]:
            continue
        text = data.decode("utf-8", errors="replace")
        lines = len(text.splitlines())
        out["lines"] += lines
        out["text_bytes"] += len(data)
        lang = language(rel)
        if lang:
            row = out["languages"].setdefault(lang, [0, 0])
            row[0] += 1
            row[1] += lines
    return out


def read_manifest(path: Path, kind: str, text: str | None = None, read: bool = True) -> dict:
    """{name, workspaces, keywords, description} of one manifest (`text`: its content, when the
    scan already read it; `read=False`: the scan read it and it is not UTF-8); a file that does
    not parse (or has no name), or a symlink (never followed), gives `name: None` and empty
    lists — never an error."""
    out = {"name": None, "workspaces": [], "keywords": [], "description": ""}
    if kind == "csproj":
        out["name"] = path.stem
        return out
    try:
        if text is None:
            if not read or path.is_symlink():
                return out
            text = _read(path).decode("utf-8")
        if kind in ("package.json", "composer.json"):
            data = json.loads(text)
            spaces = data.get("workspaces") if kind == "package.json" else None
            if isinstance(spaces, dict):
                spaces = spaces.get("packages")
            out["workspaces"] = [w for w in spaces or [] if isinstance(w, str)] \
                if isinstance(spaces, list) else []
        elif kind in ("pyproject.toml", "Cargo.toml"):
            data = tomllib.loads(text)
            data = (data.get("project") or data.get("tool", {}).get("poetry") or {}) \
                if kind == "pyproject.toml" else data.get("package") or {}
        elif kind == "setup.cfg":
            parser = configparser.ConfigParser(interpolation=None)
            parser.read_string(text)
            data = dict(parser["metadata"]) if parser.has_section("metadata") else {}
            data["keywords"] = [k.strip() for k in data.get("keywords", "").split(",")]
        else:  # go.mod
            m = re.search(r"^module\s+(\S+)", text, re.M)
            data = {"name": m.group(1).strip('"')} if m else {}
    except (OSError, UnicodeDecodeError, ValueError, configparser.Error, AttributeError):
        return out
    if isinstance(data, dict):
        name = data.get("name")
        out["name"] = name if isinstance(name, str) and name.strip() else None
        keywords = data.get("keywords")
        out["keywords"] = [k for k in keywords if isinstance(k, str) and k.strip()] \
            if isinstance(keywords, list) else []
        description = data.get("description")
        out["description"] = description if isinstance(description, str) else ""
    return out


def manifests(root: Path, files: list[str], texts: dict | None = None) -> list[dict]:
    """Every manifest of the file set, by path: {path, kind, name, workspaces, keywords,
    description} (preflight.json keeps the first four); `texts`: what the scan read."""
    texts = texts or {}
    return [{"path": f, "kind": kind, **read_manifest(root / f, kind, texts.get(f),
                                                      read=f not in texts)}
            for f in files if (kind := manifest_kind(f))]


def git_info(root: Path) -> dict | None:
    """{head, commits} in a git work tree (`head` null, `commits` 0 before the first commit);
    None outside git."""
    if work_tree_error(root) is not None:
        return None
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "--quiet", "HEAD"],
                          capture_output=True, text=True, env=git_env())
    if head.returncode != 0:
        return {"head": None, "commits": 0}
    count = subprocess.run(["git", "-C", str(root), "rev-list", "--count", "HEAD"],
                           capture_output=True, text=True, env=git_env())
    return {"head": head.stdout.strip(), "commits": int(count.stdout.strip() or 0)}


def build(root: Path, files: list[str], found: list[dict], counts: dict) -> dict:
    """preflight.json's document: the file set `files`, its manifests `found` and the `scan`
    `counts`."""
    present = set(files)
    return {"schema": SCHEMA, "root": str(root), "git": git_info(root), "files": counts["files"],
            "lines": counts["lines"], "bytes": counts["bytes"],
            "token_estimate": counts["text_bytes"] // 4,
            "languages": [{"language": lang, "files": n, "lines": lines}
                          for lang, (n, lines) in sorted(counts["languages"].items())],
            "manifests": [{k: m[k] for k in ("path", "kind", "name", "workspaces")}
                          for m in found],
            "agent_docs": sorted(d for d in AGENT_DOCS if d in present),
            "adrs": sorted(f"{d}/" for d in ADR_DIRS
                           if any(f.startswith(f"{d}/") for f in files)),
            "top_dirs": sorted({f.split("/")[0] for f in files if "/" in f})}
