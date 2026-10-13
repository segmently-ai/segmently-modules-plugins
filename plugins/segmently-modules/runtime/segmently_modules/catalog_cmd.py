"""`segmently-modules catalog [--json]`: one card per module and per child — name, status, description,
keywords (a child also names its parent) — the input an agent reads to choose modules by
meaning (P8.1 S2). Read-only: no lock, no write, never runs the agent. JSON carries `match: {mode,
semantic}` (`semantic` = a valid `SEGMENTLY_MODULES_AGENT_COMMAND` is set) and the `search` settings."""
from segmently_modules.output import EXIT_OK, UsageError, defer_note, emit
from segmently_modules.registry import as_dict
from segmently_modules.config import search_settings
from segmently_modules.semantic import agent_configured, configured_mode
from segmently_modules.workspace import Workspace


def _keywords(entry: dict) -> list[str]:
    kw = entry.get("keywords")
    return [k for k in kw if isinstance(k, str)] if isinstance(kw, list) else []


def _text(value) -> str:
    return value if isinstance(value, str) else ""


def cards(modules: dict) -> list[dict]:
    """Registry order, each child right after its parent. A child's description and status are
    its own, falling back to the parent's (as `show` does)."""
    out = []
    for name, entry in modules.items():
        if not isinstance(entry, dict):
            continue
        out.append({"name": name, "status": _text(entry.get("status")),
                    "description": _text(entry.get("description")),
                    "keywords": _keywords(entry)})
        for child, sub in as_dict(entry.get("submodules")).items():
            sub = as_dict(sub)
            out.append({"name": f"{name}/{child}",
                        "status": _text(sub.get("status")) or _text(entry.get("status")),
                        "description": _text(sub.get("description")) or
                        _text(entry.get("description")),
                        "keywords": _keywords(sub), "parent": name})
    return out


def register(sub, common) -> None:
    p = sub.add_parser("catalog", parents=[common],
                       help="one card per module and child, for choosing modules by meaning")
    p.set_defaults(func=run)


def _semantic(config: dict) -> bool:
    """`match.semantic`. A malformed `SEGMENTLY_MODULES_AGENT_COMMAND` / `SEGMENTLY_MODULES_AGENT_TIMEOUT` (the timeout
    is checked first) makes it false with one deferred stderr note — the refusal the verbs that
    run the agent give with exit 2: `catalog` itself reports, it never runs the agent."""
    try:
        return agent_configured(config)
    except UsageError as e:
        defer_note(f"{e} — match.semantic is false")
        return False


def run(args) -> int:
    ws = Workspace.from_args(args)
    data = {"match": {"mode": configured_mode(ws.config), "semantic": _semantic(ws.config)},
            "search": search_settings(ws.config),
            "modules": cards(ws.registry.modules)}
    emit("catalog", data, args.json, _render)
    return EXIT_OK


def _render(data) -> None:
    if not data["modules"]:
        print("no modules in the registry")
    for c in data["modules"]:
        parent = f"  (child of {c['parent']})" if "parent" in c else ""
        print(f"{c['name']}  {c['status']}  {c['description']}{parent}  "
              f"[{', '.join(c['keywords'])}]")
