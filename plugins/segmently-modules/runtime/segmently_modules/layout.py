"""`paths.registry_layout = "per-module"`: each module's entry lives in
`<modules_dir>/<name>/<module_entry>` (source of truth, one small file per module — no single-
file write hotspot); `<registry>` becomes a generated index (`segmently-modules index build`). Readers
assemble the document from the module files, so a stale index never changes what they see."""
import contextlib
import json
from pathlib import Path

from segmently_modules.output import UsageError
from segmently_modules.registry import Registry, load_registry
from segmently_modules.store import (DEFAULT_LOCK_TIMEOUT_S, atomic_write, file_lock, file_sha256,
                          locked_edit, serialize, sha256_bytes, stamp, utc_now)


def module_files(root: Path, config: dict) -> dict[str, Path]:
    """name -> entry file, for every module directory that has one (sorted by name)."""
    mdir = root / config["paths"]["modules_dir"]
    entry_name = config["paths"]["module_entry"]
    if not mdir.is_dir():
        return {}
    return {d.name: d / entry_name for d in sorted(mdir.iterdir())
            if d.is_dir() and (d / entry_name).is_file()}


def _read_entry(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as e:
        raise UsageError(f"{path}: not valid UTF-8: {e}") from None
    except json.JSONDecodeError as e:
        raise UsageError(f"{path}: invalid JSON: {e}") from None


def _index_top_level(index: Path) -> dict:
    """Top-level keys other than `modules` live in the index and survive rebuilds."""
    if not index.exists():
        return {}
    return {k: v for k, v in load_registry(index).raw.items() if k != "modules"}


def load_per_module(root: Path, config: dict) -> Registry:
    index = root / config["paths"]["registry"]
    raw = _index_top_level(index)
    files = module_files(root, config)
    raw["modules"] = {name: _read_entry(p) for name, p in files.items()}
    return Registry(index, raw, sha256_bytes(serialize(raw).encode("utf-8")),
                    {name: file_sha256(p) for name, p in files.items()})


class PerModuleStore:
    """Same API as RegistryStore; writes only the entry files that changed."""

    def __init__(self, root: Path, config: dict, lock_timeout_s: float = DEFAULT_LOCK_TIMEOUT_S):
        self.root, self.config = Path(root), config
        self.path = self.root / config["paths"]["registry"]  # the index; also the lock anchor
        self.lock_timeout_s = lock_timeout_s

    def entry_path(self, name: str) -> Path:
        return (self.root / self.config["paths"]["modules_dir"] / name
                / self.config["paths"]["module_entry"])

    def load(self) -> Registry:
        return load_per_module(self.root, self.config)

    def locked(self):
        return file_lock(self.path, self.lock_timeout_s)

    def commit(self, original: Registry, new_raw: dict) -> bool:
        """Write the entry files whose module changed (caller holds `locked()`); refuse a file
        that changed on disk since `original` was loaded. Top-level keys live in the index."""
        def top(raw):
            return serialize({k: v for k, v in raw.items() if k != "modules"})

        if top(new_raw) != top(original.raw):
            raise UsageError("per-module layout: top-level registry keys are edited in the "
                             "index file, not through module writers")
        old = original.raw["modules"]
        changed = [n for n, e in new_raw["modules"].items()
                   if n not in old or serialize(e) != serialize(old[n])]
        for name in changed:
            path = self.entry_path(name)
            if file_sha256(path) != original.parts.get(name):
                raise UsageError(f"{path} changed since it was read; reload and retry")
        for name in changed:
            text = serialize(new_raw["modules"][name])
            atomic_write(self.entry_path(name), text)
            original.parts[name] = sha256_bytes(text.encode("utf-8"))
        original.raw = new_raw
        original.sha256 = sha256_bytes(serialize(new_raw).encode("utf-8"))
        return bool(changed)

    @contextlib.contextmanager
    def edit(self):
        with locked_edit(self) as working:
            yield working


def build_index(root: Path, config: dict, clock=utc_now) -> tuple[str, bool]:
    """(index text, stale?) — stale when the index's modules differ from the entry files.
    A rebuild stamps `registry.updated_at_path` only when the modules changed."""
    index = root / config["paths"]["registry"]
    assembled = load_per_module(root, config).raw
    current = load_registry(index).raw if index.exists() else None
    if current is not None and current.get("modules") == assembled["modules"]:
        return index.read_text(encoding="utf-8"), False
    if config["registry"].get("updated_at_path"):
        stamp(assembled, config["registry"]["updated_at_path"], clock())
    return serialize(assembled), True


def split_registry(root: Path, config: dict) -> list[tuple[Path, str]]:
    """single -> per-module: the entry files to write. Refuses to overwrite a different file."""
    registry = load_registry(root / config["paths"]["registry"])
    out = []
    for name, entry in registry.modules.items():
        path = root / config["paths"]["modules_dir"] / name / config["paths"]["module_entry"]
        text = serialize(entry)
        if path.exists() and path.read_text(encoding="utf-8") != text:
            raise UsageError(f"{path} exists with different content; remove it or reconcile first")
        out.append((path, text))
    return out
