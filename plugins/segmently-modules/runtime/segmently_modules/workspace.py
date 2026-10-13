import os
from dataclasses import dataclass, field
from pathlib import Path

from segmently_modules.config import load_config
from segmently_modules.fields import FieldDef, load_field_defs
from segmently_modules.output import UsageError
from segmently_modules.registry import Registry, load_registry

CONFIG_DIR = ".segmently-modules"
LEGACY_CONFIG_DIR = ".modsys"  # modsys 0.1.x; the refusal goes in 0.3.0
ROOT_MARKERS = (CONFIG_DIR, LEGACY_CONFIG_DIR, "modules/registry.json")  # the legacy one: refused


def refuse_legacy_config(root: Path, config_dir_arg) -> None:
    """Exit 2 when the root still holds the config of modsys 0.1.x and no CONFIG_DIR: the engine
    defaults would replace the team's config silently. An explicit --config-dir is the user's
    choice."""
    if (config_dir_arg is None and (root / LEGACY_CONFIG_DIR).is_dir()
            and not (root / CONFIG_DIR).exists()):
        raise UsageError(f"{root / LEGACY_CONFIG_DIR} is the config of modsys 0.1.x — rename it "
                         f"first: git mv {LEGACY_CONFIG_DIR} {CONFIG_DIR} (CHANGELOG.md, 0.2.0, "
                         f"\"Upgrading from modsys 0.1.x\")")


def find_root(start: Path) -> Path:
    """Nearest directory holding a root marker; the nearest `.git` ends the search, and so does
    a directory listed in GIT_CEILING_DIRECTORIES — never entered, as git's own search does."""
    start = start.resolve()
    ceilings = {Path(p).resolve() for p in
                os.environ.get("GIT_CEILING_DIRECTORIES", "").split(os.pathsep) if p}
    for d in (start, *start.parents):
        if d != start and d in ceilings:
            break
        if any((d / marker).exists() for marker in ROOT_MARKERS):
            return d
        if (d / ".git").exists():
            return d
    raise UsageError(f"cannot find a repository root above {start}; pass --root")


@dataclass
class Workspace:
    root: Path
    config_dir: Path
    config: dict
    fields: dict[str, FieldDef]
    _registry: Registry | None = field(default=None, repr=False)
    # root-relative path -> the file that stands in for it (`init`'s staging docs, read at their
    # final paths before `init finish` moves them); empty for every verb but `init` / `eval`
    overlay: dict = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls, root: Path, config_dir: Path | None = None) -> "Workspace":
        """A workspace for programmatic callers (pipelines, hooks, tests) — no argparse needed."""
        root = Path(root).resolve()
        refuse_legacy_config(root, config_dir)
        config_dir = Path(config_dir or root / CONFIG_DIR).resolve()
        config = load_config(config_dir, root)
        return cls(root, config_dir, config, load_field_defs(config))

    @classmethod
    def from_args(cls, args) -> "Workspace":
        return cls.load(args.root or find_root(Path.cwd()), args.config_dir)

    def rel(self, path) -> str:
        """`path` as users see it: root-relative (posix) when it lies inside the root, else
        absolute."""
        path = Path(os.path.normpath(Path(path).absolute()))
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return str(path)

    def disk(self, rel: str) -> Path:
        """The file a root-relative path is read from (the overlay's stand-in, else the path)."""
        return self.overlay.get(rel, self.root / rel)

    def exists(self, rel: str) -> bool:
        """`rel` exists on disk, or in the overlay (a file, or a directory above one)."""
        rel = rel.rstrip("/")
        return (self.root / rel).exists() or rel in self.overlay or \
            any(k.startswith(rel + "/") for k in self.overlay)

    @property
    def registry(self) -> Registry:
        if self._registry is None:
            if self.config["paths"]["registry_layout"] == "per-module":
                from segmently_modules.layout import load_per_module
                self._registry = load_per_module(self.root, self.config)
            else:
                self._registry = load_registry(self.root / self.config["paths"]["registry"])
        return self._registry
