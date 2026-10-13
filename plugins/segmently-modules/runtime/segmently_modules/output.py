import contextlib
import json
import os
import sys
from typing import Callable

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130  # SIGINT (Ctrl-C), the shell convention 128 + 2


class UsageError(Exception):
    """Bad input, config or registry. Reported on stderr with exit code 2."""


class _QuietStream:
    """A process stream that survives a closed reader (F19): on the first EPIPE it points the
    file descriptor at `os.devnull`, so every later write, and the interpreter's flush at exit,
    land there silently — the verb runs to its end and its exit code stays its own. Any other
    write error (a full disk, a file size limit) is remembered the same way and reported once by
    `quiet_streams` (`segmently-modules: error: cannot write stdout: …`, exit 2). Only the stream's text
    methods are guarded: `.buffer` is forwarded as it is, so engine code writes through
    `print` / `write`."""

    def __init__(self, raw, fd: int):
        self._raw, self._fd = raw, fd
        self.error: OSError | None = None

    def _trip(self) -> None:
        try:
            null = os.open(os.devnull, os.O_WRONLY)
            try:
                os.dup2(null, self._fd)
            finally:
                os.close(null)
        except OSError:
            pass
        try:  # the bytes the failed write left in the buffer go to the null device too
            self._raw.flush()
        except (OSError, ValueError):
            pass

    def _failed(self, error: OSError) -> None:
        if not isinstance(error, BrokenPipeError) and self.error is None:
            self.error = error
        self._trip()

    def write(self, text):
        try:
            return self._raw.write(text)
        except OSError as e:
            self._failed(e)
            return len(text)

    def writelines(self, lines) -> None:
        for line in lines:
            self.write(line)

    def flush(self) -> None:
        try:
            self._raw.flush()
        except OSError as e:
            self._failed(e)

    def __getattr__(self, name):
        return getattr(self._raw, name)


def _null_stderr():
    """A text stream on file descriptor 2 when fd 2 is not open at start, else None. With fd 2
    closed Python sets `sys.stderr = None`, `print(..., file=None)` writes to stdout, and the next
    file the process opens would take fd 2 (a lock, a temp file, the agent's order file). So the
    null device is put on fd 2 itself: no file the run opens becomes fd 2, and a child that
    inherits stderr writes to the null device (fd 2 is made inheritable: `os.open` returns 2
    itself when fd 0 and 1 are open, and that descriptor is close-on-exec). An open fd 2 is never
    touched."""
    try:
        os.fstat(2)
        return None
    except OSError:
        pass
    try:
        null = os.open(os.devnull, os.O_WRONLY)
    except OSError:
        return None
    try:
        if null != 2:  # fd 0 or 1 may be closed too: they are given back as they were
            os.dup2(null, 2)
    except OSError:
        return None
    finally:
        if null != 2:
            os.close(null)
    with contextlib.suppress(OSError):  # in both cases: a child inherits the null device
        os.set_inheritable(2, True)
    return os.fdopen(2, "w", encoding="utf-8", errors="backslashreplace",
                     closefd=False, buffering=1)


@contextlib.contextmanager
def quiet_streams():
    """Wrap the process's own stdout and stderr in `_QuietStream` for one run (a stream a test
    or a caller swapped in is left alone) and flush them before the interpreter does. A write
    error other than a closed reader ends the run with one stderr line and exit 2."""
    wrapped = []
    sink = _null_stderr() if sys.stderr is None and sys.__stderr__ is None else None
    if sink is not None:
        sys.stderr = sink
    for name, fd in (("stdout", 1), ("stderr", 2)):
        raw = getattr(sys, name)
        if raw is not None and raw is getattr(sys, f"__{name}__"):
            guard = _QuietStream(raw, fd)
            setattr(sys, name, guard)
            wrapped.append((name, raw, guard))
    try:
        yield
    finally:
        if sink is not None:
            try:
                sink.flush()
            except (OSError, ValueError):
                pass
            sys.stderr = None
            sink.close()
        failed = False
        for name, raw, guard in wrapped:
            try:
                guard.flush()
            finally:
                setattr(sys, name, raw)
            if guard.error is not None:
                failed = True
                if name == "stdout" and sys.stderr is not None:  # None: no stderr to report on
                    reason = guard.error.strerror or guard.error
                    try:
                        print(f"segmently-modules: error: cannot write stdout: {reason}", file=sys.stderr)
                        sys.stderr.flush()
                    except (OSError, ValueError):
                        pass
        if failed:
            raise SystemExit(2)


_DEFERRED_NOTES: list[str] = []


def defer_note(line: str) -> None:
    """Queue one stderr line (without its `segmently-modules: note: ` prefix) for `flush_notes`: a verb
    that decides early but must say it only when the run succeeds, after its stdout."""
    _DEFERRED_NOTES.append(line)


def clear_notes() -> None:
    _DEFERRED_NOTES.clear()


def flush_notes() -> None:
    """Print the queued notes to stderr (`segmently-modules: note: …`, one line each) and empty the queue.
    `cli.main` calls it only after a verb returned exit 0, and a note is printed only when the
    run still ends with exit 0: a stdout write error (`quiet_streams` ends that run with exit 2
    and its one error line) drops the notes."""
    lines = list(_DEFERRED_NOTES)
    _DEFERRED_NOTES.clear()
    if not lines:
        return
    out = sys.stdout
    if out is not None:  # None: fd 1 was closed at start, there is no output to come after
        try:  # stdout is block-buffered in a pipe or a file: the note must come after it
            out.flush()
        except (OSError, ValueError):  # closed or broken stdout: not this function's contract
            pass
        if isinstance(out, _QuietStream) and out.error is not None:
            return  # a real write error: the run ends with exit 2
    if sys.stderr is None:  # fd 2 closed at start: print() would fall back to stdout
        return
    for line in lines:
        print(f"segmently-modules: note: {line}", file=sys.stderr)


def emit(verb: str, data, as_json: bool, render_text: Callable[[object], None]) -> None:
    if as_json:
        print(json.dumps({"schema": f"segmently-modules.{verb}/1", "data": data},
                         indent=2, ensure_ascii=False))
    else:
        render_text(data)
