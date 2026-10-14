from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from segmently_modules.output import UsageError


@dataclass
class Registry:
    path: Path
    raw: dict  # the full document, never normalized
    sha256: str = ""  # of the bytes it was loaded from; writers use it to detect concurrent edits
    parts: dict = field(default_factory=dict)  # per-module layout: module name -> entry file sha256

    @property
    def modules(self) -> dict:
        return self.raw["modules"]


def as_dict(v) -> dict:
    """A registry value where an object is expected; anything else reads as empty."""
    return v if isinstance(v, dict) else {}


def as_list(v) -> list:
    """A registry value where an array is expected; anything else reads as empty."""
    return v if isinstance(v, list) else []


def context_paths(cf) -> list[tuple[str, object]]:
    """(label, value) of every doc path in a `context_files` object: a string (`key`), an array
    (`key[]`), a map of strings or arrays (`key.name`, `key.name[]`). Values are not checked:
    lint reports a non-string (MS004); `show` reads the strings only."""
    out = []
    for key, val in as_dict(cf).items():
        if isinstance(val, str):
            out.append((key, val))
        elif isinstance(val, dict):
            for sub, path in val.items():
                if isinstance(path, str):
                    out.append((f"{key}.{sub}", path))
                elif isinstance(path, list):
                    out += [(f"{key}.{sub}[]", p) for p in path]
        elif isinstance(val, list):
            out += [(f"{key}[]", p) for p in val]
    return out


def load_registry(path: Path) -> Registry:
    try:
        data = path.read_bytes()
        raw = json.loads(data.decode("utf-8"))
    except FileNotFoundError:
        raise UsageError(f"registry not found: {path} — run `segmently-modules init` to set up segmently-modules "
                         f"here") from None
    except UnicodeDecodeError as e:
        raise UsageError(f"{path}: not valid UTF-8: {e}") from None
    except OSError as e:
        raise UsageError(f"{path}: cannot read: {e}") from None
    except json.JSONDecodeError as e:
        raise UsageError(f"{path}: invalid JSON: {e}") from None
    if not isinstance(raw, dict) or not isinstance(raw.get("modules"), dict):
        raise UsageError(f"{path}: no 'modules' object")
    return Registry(path, raw, hashlib.sha256(data).hexdigest())


def stub_head(root: Path, config: dict, name: str) -> str | None:
    """If <modules_dir>/<name>/<module_doc> is a pointer stub, return its first lines."""
    doc = root / config["paths"]["modules_dir"] / name / config["paths"]["module_doc"]
    if doc.exists():
        head = doc.read_text(encoding="utf-8", errors="replace")[:600]
        if re.search(config["registry"]["stub_pattern"], head, re.IGNORECASE):
            return "\n".join(line for line in head.splitlines()[:8] if line.strip())
    return None


def resolve_module_arg(arg: str, modules_dir: str) -> str:
    """Accept `name`, `parent/child`, or a file path inside <modules_dir>/<name>/…"""
    marker = f"{modules_dir}/"
    if "/" not in arg or not (arg.startswith("/") or arg.startswith(marker)
                              or f"/{marker}" in arg):
        return arg
    m = re.search(rf"(?:^|/){re.escape(modules_dir)}/([^/]+)"
                  rf"(?:/submodules/([^/]+))?(?:/|$)", arg)
    if m:
        return f"{m.group(1)}/{m.group(2)}" if m.group(2) else m.group(1)
    return arg
