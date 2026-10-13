"""Hooks: `[[hooks.<event>]]` entries with `id`, `run = [argv…]`, `enabled` (default true),
`required` (default false), `timeout_s` (default 60). A hook reads the event payload as JSON
on stdin and may print `{"proposals": [items], "messages": [text]}` on stdout; its proposals
are validated like `segmently-modules propose` and queued under agent `hook-<id>`. `./`-relative argv
items resolve against the declaring pack's directory (team/user hooks: the repo root).
A team config disables a pack hook with `[[hooks.<event>]] id = "…" enabled = false`."""
import json
import os
import subprocess
from pathlib import Path

from segmently_modules.output import UsageError
from segmently_modules.proposals import SAFE_ID, add_proposals, make_item

DEFAULT_TIMEOUT_S = 60
EVENTS = ("post_sync",)  # validated; other keys under [hooks] pass (forward compatibility)
HOOK_SCHEMA = {"id": "str", "run": "list[str]", "enabled": "bool", "required": "bool",
               "timeout_s": "int"}


def validate_hooks(layer: dict, source, check_table) -> None:
    """Config-layer validation (called from config.validate_layer)."""
    hooks = layer.get("hooks")
    if hooks is None:
        return
    if not isinstance(hooks, dict):
        raise UsageError(f"{source}: [hooks] must be a table, got {hooks!r}")
    for event in EVENTS:
        if event not in hooks:
            continue
        entries = hooks[event]
        if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
            raise UsageError(f"{source}: hooks.{event} must be an array of tables "
                             f"([[hooks.{event}]])")
        for entry in entries:
            if not isinstance(entry.get("id"), str) or not entry["id"]:
                raise UsageError(f"{source}: every [[hooks.{event}]] entry needs an id")
            if not SAFE_ID.fullmatch(entry["id"]):  # it becomes part of a queue file name
                raise UsageError(f"{source}: hooks.{event}: id {entry['id']!r} may only contain "
                                 f"letters, digits, '.', '_', '-'")
            check_table(entry, HOOK_SCHEMA, f"hooks.{event}.{entry['id']}", source)
            if "run" in entry and not entry["run"]:
                raise UsageError(f"{source}: hooks.{event}.{entry['id']}: run is empty")
            if "timeout_s" in entry and entry["timeout_s"] <= 0:
                raise UsageError(f"{source}: hooks.{event}.{entry['id']}: timeout_s must be > 0")


def hooks_for(config: dict, event: str) -> list[dict]:
    return [h for h in (config.get("hooks") or {}).get(event, []) if isinstance(h, dict)]


def _argv(ws, hook: dict) -> list[str]:
    run = hook.get("run")
    if not run:
        raise UsageError(f"hook '{hook['id']}' has no run command")
    owner = hook.get("owner")
    base = Path(ws.config["_pack_dirs"][owner]) if owner in ws.config.get("_pack_dirs", {}) \
        else ws.root
    return [str(base / a) if a.startswith(("./", "../")) else a for a in run]


def _decode(stdout: bytes) -> str:
    try:
        return stdout.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(f"stdout is not valid UTF-8 ({e.reason} at byte {e.start})") from None


def _parse(stdout: str) -> dict:
    if not stdout.strip():
        return {"proposals": [], "messages": []}
    out = json.loads(stdout)
    if not isinstance(out, dict):
        raise ValueError("stdout must be a JSON object")
    proposals, messages = out.get("proposals", []), out.get("messages", [])
    if not isinstance(proposals, list) or not isinstance(messages, list):
        raise ValueError("'proposals' and 'messages' must be arrays")
    return {"proposals": proposals, "messages": [str(m) for m in messages]}


def run_hooks(ws, event: str, payload: dict, run_id: str) -> dict:
    """Run every hook of `event` in declaration order. Returns
    {"hooks": [result…], "failed_required": bool}; never raises for a hook's own failure:
    whatever a hook prints (invalid UTF-8, wrong JSON shapes, wrongly typed proposal fields)
    fails that hook alone, and its proposals are queued all or nothing."""
    results = []
    for hook in hooks_for(ws.config, event):
        result = {"id": hook["id"], "owner": hook.get("owner", "config"),
                  "required": bool(hook.get("required", False)), "messages": [],
                  "queued": 0}
        if not hook.get("enabled", True):
            results.append({**result, "status": "skipped"})
            continue
        try:
            argv = _argv(ws, hook)
        except UsageError as e:
            results.append({**result, "status": "failed", "error": str(e)})
            continue
        timeout = hook.get("timeout_s", DEFAULT_TIMEOUT_S)
        env = {**os.environ, "SEGMENTLY_MODULES_ROOT": str(ws.root), "SEGMENTLY_MODULES_EVENT": event,
               "SEGMENTLY_MODULES_HOOK_ID": hook["id"], "SEGMENTLY_MODULES_RUN_ID": run_id}
        try:  # bytes, decoded below: invalid UTF-8 output is this hook's failure, not ours
            proc = subprocess.run(argv, input=json.dumps(payload).encode("utf-8"), cwd=ws.root,
                                  env=env, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            results.append({**result, "status": "failed", "error": f"timed out after {timeout}s"})
            continue
        except OSError as e:
            results.append({**result, "status": "failed", "error": f"cannot start: {e}"})
            continue
        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", errors="replace")
            tail = stderr.strip().splitlines()[-1:] or [""]
            results.append({**result, "status": "failed",
                            "error": f"exit {proc.returncode}: {tail[0][:200]}"})
            continue
        try:
            out = _parse(_decode(proc.stdout))
            items = [make_item(ws, p.get("op"), p.get("module"), p.get("reason"),
                               field=p.get("field"), doc=p.get("doc"), value=p.get("value"))
                     for p in out["proposals"]]
        except Exception as e:  # any garbage: this hook fails, the run goes on
            detail = e if isinstance(e, (ValueError, UsageError)) else f"{type(e).__name__}: {e}"
            results.append({**result, "status": "failed", "error": f"bad output: {detail}"})
            continue
        try:
            if items:
                add_proposals(ws, run_id, f"hook-{hook['id']}", items)
        except Exception as e:
            results.append({**result, "status": "failed",
                            "error": f"cannot queue proposals: {e}"})
            continue
        results.append({**result, "status": "ok", "messages": out["messages"],
                        "queued": len(items)})
    failed_required = any(r["status"] == "failed" and r["required"] for r in results)
    return {"hooks": results, "failed_required": failed_required}
