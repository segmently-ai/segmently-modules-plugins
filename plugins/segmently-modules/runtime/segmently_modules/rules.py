"""Value rules that lint reports as ERRORs and the registry writers refuse — one definition for
both, so a validated write never produces a lint error on the value it wrote. Each rule returns
(lint code, message)."""
from __future__ import annotations

from segmently_modules.registry import as_dict


def status_problem(status, statuses: list[str]) -> tuple[str, str] | None:
    """MS003: a module status outside `[registry] statuses`."""
    if status is not None and status not in statuses:
        return "MS003", f"status {status!r} not in {statuses}"
    return None


def edge_problems(edge: dict, modules: dict, relations: list[str]) -> list[tuple[str, str]]:
    """MS006-MS010 for one `related_modules` edge (an object): relation outside `[registry]
    relations`, no description, no module target, a target module or child not in the
    registry."""
    out = []
    if edge.get("relation") not in relations:
        out.append(("MS006", f"relation {edge.get('relation')!r} not in {relations}"))
    if not edge.get("description"):
        out.append(("MS007", "missing description"))
    target = edge.get("module")
    if not isinstance(target, str) or not target:
        out.append(("MS008", "missing module target"))
        return out
    parent, _, child = target.partition("/")
    if parent not in modules:
        out.append(("MS009", f"target '{parent}' not in registry"))
    elif child and child not in as_dict(as_dict(modules[parent]).get("submodules")):
        out.append(("MS010", f"'{child}' is not a submodule of '{parent}'"))
    return out
