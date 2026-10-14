"""`segmently-modules templates`: which template file each generated doc comes from, and a copy-once
override.

  list               `MODULE.md`, `roles/<role>.md` of every enabled role (config order),
                     `agents-md.md`, the two `init` prompts (`init/module_prompt.md`,
                     `init/routing_prompt.md`) and `choose/rules.md` (the rules of the
                     `choose` work order), each with the layer that wins
                     (`resolve_template_source`)
  override TEMPLATE  copy the winning template's text to
                     `<config_dir>/overrides/templates/TEMPLATE`, where it wins from then on;
                     an existing override is never replaced (edit it instead)"""
from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

from segmently_modules.config import enabled_roles
from segmently_modules.create import resolve_template_source
from segmently_modules.output import EXIT_OK, UsageError, emit
from segmently_modules.workorder import RULES_TEMPLATE, choose_rules_source
from segmently_modules.workspace import Workspace

ACTIONS = ("list", "override")
INIT_PROMPTS = ("init/module_prompt.md", "init/routing_prompt.md")  # `init` renders them


def register(sub, common) -> None:
    p = sub.add_parser("templates", parents=[common],
                       help="list the templates docs are rendered from, or copy one to edit it",
                       description="list: MODULE.md, roles/<role>.md of every enabled role, "
                                   "agents-md.md, the init prompts (init/module_prompt.md, "
                                   "init/routing_prompt.md) and choose/rules.md (the rules of "
                                   "the choose work order), each with the layer that wins "
                                   "(override, "
                                   "role-template:<pack>, pack:<pack>, engine, "
                                   "engine-fallback) and its file. override TEMPLATE: copy "
                                   "the winning template to <config_dir>/overrides/templates/"
                                   "TEMPLATE, where it wins from then on; an existing override "
                                   "is never replaced.")
    p.add_argument("action", choices=ACTIONS)
    p.add_argument("template", nargs="?", metavar="TEMPLATE",
                   help="override: a name that templates list shows, e.g. roles/qa.md")
    p.add_argument("--dry-run", action="store_true",
                   help="override: show what would be written, write nothing")
    p.set_defaults(func=run)


def template_rows(ws) -> list[dict]:
    """[{template, role, source, path}] in the order `templates list` prints them."""
    wanted = ([("MODULE.md", None)] + [(f"roles/{r}.md", r) for r in enabled_roles(ws.config)]
              + [("agents-md.md", None)] + [(t, None) for t in INIT_PROMPTS])
    wanted.append((RULES_TEMPLATE, None))
    rows = []
    for template, role in wanted:
        source, path = _source(ws, template, role)
        rows.append({"template": template, "role": role, "source": source,
                     "path": ws.rel(path)})
    return rows


def _source(ws, template: str, role: str | None) -> tuple[str, Path]:
    if template == RULES_TEMPLATE:  # no role fallback for the work order's rules
        return choose_rules_source(ws)
    return resolve_template_source(ws, template, role)


def override(ws, template: str, dry_run: bool) -> dict:
    """Copy the winning template to the team's overrides; every refusal writes nothing."""
    name = PurePosixPath(template)
    if name.is_absolute() or Path(template).is_absolute() or ".." in name.parts:
        raise UsageError(f"template {template!r}: give a template name that segmently-modules templates "
                         f"list shows (e.g. roles/qa.md), not a file path")
    rows = {r["template"]: r for r in template_rows(ws)}
    if template not in rows:
        raise UsageError(f"unknown template {template!r} (templates: {', '.join(rows)})")
    source, path = _source(ws, template, rows[template]["role"])
    target = ws.config_dir / "overrides" / "templates" / template
    if os.path.lexists(target):
        raise UsageError(f"{ws.rel(target)} already exists — edit it")
    try:  # the source is read for a dry run too: it must promise only what a run can do
        text = path.read_bytes()
    except OSError as e:
        raise UsageError(f"cannot read {ws.rel(path)}: {e.strerror or e}") from None
    if not dry_run:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "xb") as fh:  # never replaces a file created in the meantime
                fh.write(text)
        except FileExistsError:
            raise UsageError(f"{ws.rel(target)} already exists — edit it") from None
        except OSError as e:
            raise UsageError(f"cannot write {ws.rel(target)}: {e.strerror}; nothing "
                             f"written") from None
    return {"template": template, "file": ws.rel(target), "from": source, "dry_run": dry_run}


def run(args) -> int:
    ws = Workspace.from_args(args)
    if args.action == "list":
        if args.template is not None:
            raise UsageError("templates list takes no TEMPLATE")
        if args.dry_run:
            raise UsageError("--dry-run applies to templates override")
        emit("templates", template_rows(ws), args.json, _render_list)
        return EXIT_OK
    if args.template is None:
        raise UsageError("templates override needs a TEMPLATE (a name that segmently-modules templates "
                         "list shows, e.g. roles/qa.md)")
    emit("templates", override(ws, args.template, args.dry_run), args.json, _render_override)
    return EXIT_OK


def _render_list(rows) -> None:
    for r in rows:
        print(f"{r['template']:<24} {r['source']:<24} {r['path']}")


def _render_override(d) -> None:
    print(f"{'would create' if d['dry_run'] else 'created'}  {d['file']}  "
          f"(a copy of the {d['from']} template)")
    print("next: edit it — from now on it wins over every pack and engine template "
          "(segmently-modules templates list)")
