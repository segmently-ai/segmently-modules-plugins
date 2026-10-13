"""The user's own agent command (P8.1 S3, layer 3): the agent command runs a program the USER
chose — never a model of the engine's — with the work order on stdin and reads its answer from
stdout. It is read ONLY from the environment: `SEGMENTLY_MODULES_AGENT_COMMAND` (a JSON array of strings)
and `SEGMENTLY_MODULES_AGENT_TIMEOUT` (seconds, 1 to 3600, default 300). An `[agent]` table in any config
file — team, personal or pack — is refused, so no committed file can make the engine run an
agent command, whatever the file system or git say about its name. The engine holds no model, no
key and no network code: whatever the command does, it does with the user's own credentials."""
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
from pathlib import Path

from segmently_modules.output import UsageError

ENV_COMMAND = "SEGMENTLY_MODULES_AGENT_COMMAND"
ENV_TIMEOUT = "SEGMENTLY_MODULES_AGENT_TIMEOUT"
DEFAULT_TIMEOUT_S = 300
MAX_TIMEOUT_S = 3600
REASONING = {"quick": "low", "standard": "medium", "deep": "high"}
PLACEHOLDERS = ("claude_model", "codex_model", "effort", "reasoning")
STDERR_CHARS = 500
MAX_STDOUT = 4 * 1024 * 1024  # an agent that prints more is stopped and refused
KEEP_STDERR = 64 * 1024
NESTED = ("already inside an agent run (SEGMENTLY_MODULES_WORK_ORDER is set): a nested agent call is "
          "refused; use lexical matching or segmently-modules choose --task")
NESTED_NOTE = "semantic part skipped: nested agent call"
TIMEOUT_UNIT = 1.0  # seconds per `timeout_s` unit — the seam the timeout tests shrink
KILL_GRACE_S = 2.0
_TOKEN = re.compile(r"\{\{|\}\}|\{(\w+)\}|[{}]")


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _scan(item: str, source: str):
    """Yield `("text", str)` and `("name", placeholder)` parts of one argv item (`{{` / `}}` are
    literal braces); any other brace use is a usage error naming the item."""
    pos = 0
    for m in _TOKEN.finditer(item):
        if m.start() > pos:
            yield "text", item[pos:m.start()]
        pos = m.end()
        token = m.group(0)
        if token in ("{{", "}}"):
            yield "text", token[0]
        elif m.group(1):
            if m.group(1) not in PLACEHOLDERS:
                raise UsageError(f"{source}: item {item!r}: unknown placeholder "
                                 f"{{{m.group(1)}}} (placeholders: "
                                 f"{', '.join('{' + p + '}' for p in PLACEHOLDERS)})")
            yield "name", m.group(1)
        else:
            raise UsageError(f"{source}: item {item!r}: unmatched brace "
                             f"{token!r} (write {token * 2} for a literal one)")
    if pos < len(item):
        yield "text", item[pos:]


def validate_command(command, source: str) -> list[str]:
    """The argv of a `SEGMENTLY_MODULES_AGENT_COMMAND` value: a non-empty list of strings whose braces are
    placeholders or escapes, argv[0] without a placeholder."""
    if not (isinstance(command, list) and command and all(isinstance(i, str) for i in command)):
        raise UsageError(f"{source}: expected a non-empty list of strings, got {command!r}")
    for n, item in enumerate(command):
        parts = list(_scan(item, source))
        if n == 0 and any(kind == "name" for kind, _ in parts):
            raise UsageError(f"{source}: argv[0] {item!r} must not contain a placeholder")
    return command


def substitute(command: list[str], values: dict) -> list[str]:
    """Each item with its placeholders replaced, one item at a time and never through a shell;
    a substituted value is not scanned again."""
    out = []
    for item in command:
        out.append("".join(values[v] if kind == "name" else v for kind, v in _scan(item, "")))
    return out


def validate_agent_table(table, source) -> None:
    """An `[agent]` table in a config layer: always refused (the command is read from the
    environment only)."""
    raise UsageError(f"{source}: [agent] is not read from files (a repository could commit it) "
                     f"— set {ENV_COMMAND} instead")


def nested() -> bool:
    """This process runs inside an agent run (the engine sets SEGMENTLY_MODULES_WORK_ORDER for its child):
    an agent that runs segmently-modules must not start the agent again."""
    return bool(os.environ.get("SEGMENTLY_MODULES_WORK_ORDER"))


def timeout_s() -> int:
    """`SEGMENTLY_MODULES_AGENT_TIMEOUT`: 1 to 3600 seconds, at most four digits (a longer value is refused
    before it is read as a number), default 300."""
    raw = os.environ.get(ENV_TIMEOUT, "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_S
    if not (len(raw) <= len(str(MAX_TIMEOUT_S)) and raw.isascii() and raw.isdigit()
            and 1 <= int(raw) <= MAX_TIMEOUT_S):
        raise UsageError(f"{ENV_TIMEOUT}: expected an integer from 1 to {MAX_TIMEOUT_S}, "
                         f"got {raw[:40]!r}")
    return int(raw)


def settings(config: dict) -> dict | None:
    """`{command, timeout_s}` of the agent command in force, or None when there is none or this
    is a nested call. Only the environment counts; an empty variable is unset; an invalid one is
    refused."""
    limit = timeout_s()
    if nested():
        return None
    raw = os.environ.get(ENV_COMMAND, "")
    if not raw.strip():
        return None
    try:
        command = json.loads(raw)
    except ValueError:
        raise UsageError(f"{ENV_COMMAND}: expected a JSON array of strings, got "
                         f"{raw[:80]!r}") from None
    if not (isinstance(command, list) and command and all(isinstance(i, str) for i in command)):
        raise UsageError(f"{ENV_COMMAND}: expected a non-empty JSON array of strings, "
                         f"got {raw[:80]!r}")
    return {"command": validate_command(command, ENV_COMMAND), "timeout_s": limit,
            "source": ENV_COMMAND}


# ---- the answer of the agent (SI-P81-12) -------------------------------------------------

_FENCE = re.compile(r"\A```(?:json)?[ \t]*\n(.*?)\n?```\Z", re.S)


def _json(text: str, who: str, what: str):
    try:
        return json.loads(text)
    except ValueError:
        raise UsageError(f"{who}: {what} is not JSON: {text[:120]!r}") from None


def answer_from(text: str, who: str, what: str, empty: str):
    """The answer object in `text` — an agent's stdout (`choose --run`, semantic matching) or the
    input of `choose --apply`, both decoded as UTF-8 with replacement: stripped of whitespace,
    parsed as JSON and unwrapped (`unwrap`). The one reader of every answer; `empty` is the
    refusal of an empty text, `who` and `what` word the others."""
    text = text.strip()
    if not text:
        raise UsageError(empty)
    return unwrap(_json(text, who, what), who, what)


def unwrap(doc, who: str, what: str):
    """The answer object in `doc`, a parsed JSON value: the answer itself, or a `claude -p
    --output-format json` envelope's `structured_output` / `result` (a string `result` may sit
    in one ```json fence). The first matching step decides; no free-text scraping (SI-P81-12).
    `answer_from` calls it for `choose --run` and `choose --apply`; `who` and `what` word the
    refusals ("agent NAME", "its output")."""
    if not isinstance(doc, dict):
        raise UsageError(f"{who}: {what} is not a JSON object")
    if "picks" in doc or "none" in doc:
        return doc
    if doc.get("is_error") is True:
        detail = doc.get("result") if isinstance(doc.get("result"), str) else ""
        raise UsageError(f"{who} reported an error" + (f": {detail[:200]}" if detail else ""))
    if isinstance(doc.get("structured_output"), dict):
        return doc["structured_output"]
    result = doc.get("result")
    if isinstance(result, str):
        body = result.strip()
        m = _FENCE.match(body)
        inner = _json(m.group(1) if m else body, who, "its `result`")
        if not isinstance(inner, dict):
            raise UsageError(f"{who}: its `result` is not a JSON object")
        return inner
    if isinstance(result, dict):
        return result
    raise UsageError(f"{who}: no answer in {what} (expected `picks`/`none`, "
                     f"`structured_output` or `result`)")


# ---- running it ---------------------------------------------------------------------------

def _kill_group(proc: subprocess.Popen) -> None:
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass
        if sig == signal.SIGTERM:
            try:
                proc.wait(timeout=KILL_GRACE_S)
            except subprocess.TimeoutExpired:
                pass
    try:
        proc.wait(timeout=KILL_GRACE_S)
    except subprocess.TimeoutExpired:
        pass


_LEAKED: list = []  # streams whose reader is still blocked: kept alive, released at exit


def _close(proc: subprocess.Popen, readers: list) -> None:
    """Close the child's pipes — but never one a reader thread is still blocked on (a helper in
    another session may hold the write end open): that stream is parked until exit."""
    for stream, reader in ((proc.stdin, None), (proc.stdout, readers[0] if readers else None),
                           (proc.stderr, readers[1] if len(readers) > 1 else None)):
        if stream is None:
            continue
        if reader is not None and reader.is_alive():
            _LEAKED.append(stream)
            continue
        try:
            stream.close()
        except OSError:
            pass


def _drain(stream, keep: int, limit: int | None, box: dict, key: str, proc) -> None:
    """Read the unbuffered `stream` (chunks land as they are written) until its end: keep the
    first `keep` bytes; past `limit` bytes stop the agent (its group) and flag it."""
    total = 0
    try:
        while True:
            chunk = stream.read(65536)
            if not chunk:
                return
            total += len(chunk)
            if len(box[key]) < keep:
                box[key] += chunk[:keep - len(box[key])]
            if limit is not None and total > limit:
                box["over"] = True
                _kill_group(proc)
                return
    except (OSError, ValueError):
        pass


def _write_files(tmp: Path, work_order: dict, schema: dict) -> tuple[Path, Path, str]:
    """The work order (compact JSON: the agent reads it, a person reads `choose --json`) and the
    answer schema, as files in `tmp`."""
    order_text = json.dumps(work_order, ensure_ascii=False, separators=(",", ":"))
    order_file, schema_file = tmp / "work-order.json", tmp / "answer-schema.json"
    for path, text in ((order_file, order_text), (schema_file, json.dumps(schema, indent=2))):
        try:
            path.write_text(text, encoding="utf-8")
        except OSError as e:
            raise UsageError(f"cannot write {path}: {e.strerror or e}") from None
    return order_file, schema_file, order_text


def run(config: dict, work_order: dict, schema: dict, check=lambda answer: answer, cwd=None):
    """Run the agent command on `work_order` (the dict of `segmently-modules choose --json`) and return
    `check(answer)`, the answer object it printed validated by the caller (a usage error of
    `check` is reported naming the agent). The work order goes to the child's stdin and, with the
    answer schema, to two files in a private temp directory (`SEGMENTLY_MODULES_WORK_ORDER`,
    `SEGMENTLY_MODULES_SCHEMA`) removed afterwards, whatever happens. The child runs in `cwd`, in its own
    process group; Ctrl-C, SIGTERM and SIGHUP stop it and its group (a repeated one cannot cut
    that short: the cleanup runs with the three ignored); its output is capped. The argv placeholders (`{effort}` …) come from the order's `search`
    (`choose --effort` overrides the config there), the merged config being the fallback."""
    from segmently_modules.config import search_settings
    cfg = settings(config)
    # the order's `search` wins: `choose --effort` overrides the config for one run
    search = {**search_settings(config), **(work_order.get("search") or {})}
    values = {**search, "reasoning": REASONING[search["effort"]]}
    argv = substitute(cfg["command"], values)
    name, timeout_s = argv[0], cfg["timeout_s"]
    try:
        tmp = Path(tempfile.mkdtemp(prefix="segmently-modules-agent-"))
    except OSError as e:
        raise UsageError(f"cannot write {tempfile.gettempdir()}: {e.strerror or e}") from None
    before: dict = {}  # filled by _set_signals before each handler is installed (N-1)
    proc, readers = None, []
    try:
        _set_signals(before)
        order_file, schema_file, _ = _write_files(tmp, work_order, schema)
        env = {**os.environ, "SEGMENTLY_MODULES_WORK_ORDER": str(order_file),
               "SEGMENTLY_MODULES_SCHEMA": str(schema_file)}
        box = {"out": b"", "err": b"", "over": False}
        with open(order_file, "rb") as stdin:
            try:
                proc = subprocess.Popen(argv, stdin=stdin, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, env=env, cwd=cwd, bufsize=0,
                                        start_new_session=True)
            except OSError as e:
                raise UsageError(f"agent {name}: cannot run it ({e.strerror or e}) — "
                                 f"check {ENV_COMMAND}") from None
        readers = [threading.Thread(target=_drain, daemon=True,
                                    args=(proc.stdout, MAX_STDOUT, MAX_STDOUT, box, "out", proc)),
                   threading.Thread(target=_drain, daemon=True,
                                    args=(proc.stderr, KEEP_STDERR, None, box, "err", proc))]
        for t in readers:
            t.start()
        try:
            proc.wait(timeout=timeout_s * TIMEOUT_UNIT)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            raise UsageError(f"agent timed out after {timeout_s} s ({name})") from None
        finally:
            _kill_group(proc)  # never a child (or a background grandchild) left behind
            for t in readers:  # a helper in another session may keep a pipe open: bounded wait
                t.join(KILL_GRACE_S)
        if box["over"]:
            raise UsageError(f"agent {name} printed more than {MAX_STDOUT} bytes")
        stdout = bytes(box["out"]).decode("utf-8", "replace")
        stderr = bytes(box["err"]).decode("utf-8", "replace")
        if proc.returncode != 0:
            tail = f": {stderr.strip()[:STDERR_CHARS]}" if stderr.strip() else ""
            raise UsageError(f"agent {name} exited {proc.returncode}{tail}")
        answer = answer_from(stdout, f"agent {name}", "its output", f"agent {name} printed nothing")
        try:
            return check(answer)
        except UsageError as e:
            raise UsageError(f"agent {name}: {e}") from None
    finally:  # nested: a first signal at any point of it still reaches the cleanup and restore
        try:
            _ignore_signals(before)  # from here a repeated Ctrl-C / SIGTERM cannot stop the cleanup
        finally:
            try:
                if proc is not None:
                    _kill_now(proc)  # the TERM grace was given above: whatever is left is killed
                    _close(proc, readers)
                shutil.rmtree(tmp, ignore_errors=True)
            finally:
                _restore_signals(before)


def _kill_now(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        proc.wait(timeout=KILL_GRACE_S)
    except subprocess.TimeoutExpired:
        pass


def _set_signals(before: dict) -> None:
    """Ctrl-C, SIGTERM and SIGHUP raise KeyboardInterrupt (exit 130) — once: a repeat while the
    run stops is a no-op. A signal already ignored (`nohup`) stays ignored; main thread only.
    Each handler in force before goes into the caller's `before` (to restore) BEFORE the new one
    is installed: a signal that fires at once still finds its old handler there."""
    fired = []

    def interrupt(signum, frame) -> None:
        if not fired:
            fired.append(signum)
            raise KeyboardInterrupt  # SIGTERM, SIGHUP: the same road as Ctrl-C

    for sig in (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGHUP", None)):
        if sig is None:
            continue
        try:
            current = signal.getsignal(sig)
            if current in (signal.SIG_IGN, None):  # `nohup` keeps it ignored;
                continue  # None: a handler set outside Python, which could not be restored
            before[sig] = current
            signal.signal(sig, interrupt)
        except ValueError:  # not the main thread: nothing installed, nothing to restore
            before.pop(sig, None)


def _ignore_signals(before: dict) -> None:
    for sig in before:
        try:
            signal.signal(sig, signal.SIG_IGN)
        except ValueError:
            pass


def _restore_signals(before: dict) -> None:
    for sig, handler in reversed(before.items()):  # SIGINT last: nothing is left ignored
        try:
            signal.signal(sig, handler)
        except ValueError:
            pass
