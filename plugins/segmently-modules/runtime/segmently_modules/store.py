"""Registry persistence. Every writer goes through here: canonical serialization, an
advisory lock next to the file, atomic replace, and optimistic concurrency (a write is
refused when the file changed since it was read)."""
from __future__ import annotations

import contextlib
import copy
import errno
import hashlib
import json
import os
import stat
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from segmently_modules.output import UsageError
from segmently_modules.registry import Registry, load_registry

DEFAULT_LOCK_TIMEOUT_S = 10.0
# Errnos meaning "someone else holds the lock" (fcntl.flock on POSIX: EAGAIN/EWOULDBLOCK;
# msvcrt.locking on Windows: EACCES/EDEADLK). Any other errno (ENOLCK on NFS without lockd,
# ENOTSUP/EOPNOTSUPP on some FUSE/synced filesystems, EBADF, EINVAL, …) is a real failure, not
# contention, and must not be waited out.
_LOCK_CONTENTION_ERRNOS = (errno.EAGAIN, errno.EWOULDBLOCK, errno.EACCES, errno.EDEADLK)


def serialize(raw: dict) -> str:
    """The one registry serialization: 2-space indent, UTF-8 kept, trailing newline."""
    return json.dumps(raw, indent=2, ensure_ascii=False) + "\n"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str | None:
    return sha256_bytes(path.read_bytes()) if path.exists() else None


if sys.platform == "win32":  # pragma: no cover - exercised on Windows only
    import msvcrt

    def _try_lock(fh) -> None:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock(fh) -> None:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _try_lock(fh) -> None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(fh) -> None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def file_lock(path: Path, timeout_s: float = DEFAULT_LOCK_TIMEOUT_S):
    """Exclusive advisory lock on `<path>.lock` (kept on disk; add it to .gitignore)."""
    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_s
    with open(lock_path, "a+") as fh:
        while True:
            try:
                _try_lock(fh)
                break
            except OSError as e:
                if e.errno not in _LOCK_CONTENTION_ERRNOS:
                    raise UsageError(f"{lock_path}: cannot lock: {e}") from e
                if time.monotonic() >= deadline:
                    raise UsageError(f"{path}: locked by another writer ({lock_path}); "
                                     f"retry later") from None
                time.sleep(0.05)
        try:
            yield
        finally:
            _unlock(fh)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp(raw: dict, dotted_path: str, value: str) -> None:
    """Set `raw[a][b]… = value` for a dotted path like "metadata.last_updated"."""
    *parents, leaf = dotted_path.split(".")
    node = raw
    for key in parents:
        if not isinstance(node.get(key), dict):
            node[key] = {}
        node = node[key]
    node[leaf] = value


def atomic_write(path: Path, text: str) -> None:
    """Write via a temp file in the same directory + os.replace; keeps the file's mode."""
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


class RegistryStore:
    """The single-file registry (`paths.registry_layout = "single"`)."""

    def __init__(self, path: Path, lock_timeout_s: float = DEFAULT_LOCK_TIMEOUT_S,
                 updated_at_path: str = "", clock: Callable[[], str] = utc_now):
        self.path = Path(path)
        self.lock_timeout_s = lock_timeout_s
        self.updated_at_path = updated_at_path  # e.g. "metadata.last_updated"; "" = off
        self.clock = clock

    def load(self) -> Registry:
        return load_registry(self.path)

    def locked(self):
        return file_lock(self.path, self.lock_timeout_s)

    def save(self, raw: dict, expected_sha256: str | None) -> str:
        """Write `raw`; refuse when the file no longer has `expected_sha256` (None = skip the
        check). Returns the sha256 of what was written. Call it while holding `locked()`."""
        if expected_sha256 is not None:
            current = file_sha256(self.path)
            if current != expected_sha256:
                raise UsageError(f"{self.path} changed since it was read "
                                 f"(expected {expected_sha256[:12]}, found "
                                 f"{(current or 'nothing')[:12]}); reload and retry")
        text = serialize(raw)
        atomic_write(self.path, text)
        return sha256_bytes(text.encode("utf-8"))

    def commit(self, original: Registry, new_raw: dict) -> bool:
        """Persist `new_raw` if it differs from `original.raw` (as loaded); the caller holds
        `locked()`. Stamps `updated_at_path`. Updates `original` in place; True if written."""
        if serialize(new_raw) == serialize(original.raw):
            return False
        if self.updated_at_path:
            stamp(new_raw, self.updated_at_path, self.clock())
        original.sha256 = self.save(new_raw, original.sha256)
        original.raw = new_raw
        return True

    @contextlib.contextmanager
    def edit(self):
        """Lock, load, yield a working copy for in-place edits of `.raw`, then commit. A no-op
        edit leaves the file byte-for-byte untouched."""
        with locked_edit(self) as working:
            yield working


@contextlib.contextmanager
def locked_edit(store):
    """Shared edit() for every store: lock, load, yield a deep-copied working Registry,
    commit it on a clean exit (nothing is written if the block raises)."""
    with store.locked():
        original = store.load()
        working = Registry(original.path, copy.deepcopy(original.raw), original.sha256,
                           dict(original.parts))
        yield working
        store.commit(original, working.raw)
        working.sha256, working.parts = original.sha256, original.parts


def open_store(ws):
    """The store for a workspace's configured registry layout."""
    if ws.config["paths"]["registry_layout"] == "per-module":
        from segmently_modules.layout import PerModuleStore  # layout imports this module
        return PerModuleStore(ws.root, ws.config)
    return RegistryStore(ws.root / ws.config["paths"]["registry"],
                         updated_at_path=ws.config["registry"].get("updated_at_path", ""))
