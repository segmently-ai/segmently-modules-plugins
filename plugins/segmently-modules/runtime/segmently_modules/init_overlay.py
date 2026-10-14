"""The registry as it will be after `init finish`, read in place (D3): between `init reconcile`
and `init finish` the staging registry is the registry, each new module's staging docs sit at
their final paths (`Workspace.overlay`) and the `[[code_map]]` rules `finish` will append
(`init-<module>`: the module's confirmed paths, when `<config_dir>/config.toml` exists) are a
config layer. Nothing is moved; `init verify` and `segmently-modules eval routing` read the result."""
from __future__ import annotations

import json

from segmently_modules.config import load_config
from segmently_modules.fields import load_field_defs
from segmently_modules.output import UsageError
from segmently_modules.registry import Registry
from segmently_modules.store import sha256_bytes
from segmently_modules.workspace import Workspace

REBUILD = "fix it, or rebuild it from the entry.json files: segmently-modules init reconcile --force"


def code_map_rules(work, state: dict) -> list[dict]:
    """The `[[code_map]]` rules `init finish` appends: one per new module."""
    confirmed = {c["name"]: c for c in work.confirmed()}
    return [{"id": f"init-{m}", "module": m, "globs": list(confirmed[m]["paths"])}
            for m, e in sorted(state["modules"].items()) if not e.get("existing")]


def staged_registry(flow, work) -> tuple[dict, bytes]:
    """(the staging registry, its bytes) — a hand edit that broke it (not JSON, no `modules`
    object) is exit 2 naming the file and the way out."""
    staged = work.staging / "registry.json"
    try:
        data = staged.read_bytes()
        raw = json.loads(data.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise UsageError(f"{flow.rel(staged)}: cannot read it as JSON ({e}) — {REBUILD}") \
            from None
    if not isinstance(raw, dict) or not isinstance(raw.get("modules"), dict) \
            or not all(isinstance(e, dict) for e in raw["modules"].values()):
        raise UsageError(f"{flow.rel(staged)}: not a registry (a 'modules' object of entries) "
                         f"— {REBUILD}")
    return raw, data


def overlay_workspace(flow, work, state: dict) -> Workspace:
    """The workspace `init finish` would leave behind, from the staging tree."""
    raw, data = staged_registry(flow, work)
    rules = []
    if (flow.config_dir / "config.toml").is_file():
        taken = {r.get("id") for r in flow.config.get("code_map") or [] if isinstance(r, dict)}
        rules = [r for r in code_map_rules(work, state) if r["id"] not in taken]
    config = load_config(flow.config_dir, flow.root, extra={"code_map": rules},
                         extra_source="init") if rules else flow.config
    ws = Workspace(flow.root, flow.config_dir, config, load_field_defs(config))
    ws._registry = Registry(flow.root / config["paths"]["registry"], raw, sha256_bytes(data))
    paths = config["paths"]
    for module, entry in sorted(state["modules"].items()):
        if entry.get("existing"):
            continue
        final = f"{paths['modules_dir']}/{module}"
        base = work.staging_dir(module)
        ws.overlay[f"{final}/{paths['module_doc']}"] = base / "MODULE.md"
        for doc in sorted((base / "roles").glob("*.md")):
            ws.overlay[f"{final}/roles/{doc.name}"] = doc
    return ws


def current(root, config_dir, config: dict | None = None):
    """The overlay workspace while an init is between reconcile and finish, else None
    (`config`: the loaded config, when the caller has it)."""
    from segmently_modules.init_cmd import workspace
    from segmently_modules.init_flow import InitFlow
    from segmently_modules.init_work import Work
    flow = InitFlow(root, config_dir, config if config is not None
                    else load_config(config_dir, root))
    if not flow.state_path.is_file():
        return None
    state = flow.load_state()
    work = Work(flow, workspace(flow))
    if state is None or state["phases"]["reconcile"]["status"] != "done" \
            or state["phases"]["finish"]["status"] == "done" \
            or not (work.staging / "registry.json").is_file():
        return None
    return overlay_workspace(flow, work, state)
