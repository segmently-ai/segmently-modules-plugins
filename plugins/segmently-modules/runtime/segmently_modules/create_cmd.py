import json
import sys
from pathlib import Path

from segmently_modules import create as creator
from segmently_modules.output import EXIT_OK, UsageError, emit
from segmently_modules.workspace import Workspace


def register(sub, common) -> None:
    p = sub.add_parser("create", parents=[common],
                       help="scaffold a module (or --parent child): docs + registry entry",
                       description="Scaffold a module (or a --parent child): docs from templates "
                                   "plus its registry entry. Answer limits ([create] config): a "
                                   "description of description_min–description_max characters "
                                   "(default 20–200); at least [create] min_keywords distinct "
                                   "keywords (default 5) for a top-level module, a child module "
                                   "at least 1.")
    p.add_argument("name")
    p.add_argument("--parent", help="create a child of this module")
    p.add_argument("--answers", type=Path, help="JSON object: description, keywords, status, "
                                                "tags, roles, and ask_on_create fields")
    p.add_argument("--description", help="one sentence: what it does, why, when to use it "
                                          "(default limits: 20–200 characters)")
    p.add_argument("--keyword", action="append", dest="keywords",
                   help="repeatable (default: 5 or more for a module, 1 or more for a child)")
    p.add_argument("--keywords", action="append", dest="keyword_lists", metavar="A,B,C",
                   help="comma-separated keywords, repeatable, e.g. --keywords \"book, isbn, "
                        "author\"; merged after the --keyword values, duplicates dropped; a "
                        "keyword that contains a comma needs --keyword")
    p.add_argument("--status")
    p.add_argument("--tag", action="append", dest="tags", help="repeatable (applies_when roles)")
    p.add_argument("--role", action="append", dest="roles", help="repeatable (optional roles)")
    p.add_argument("--no-standard-roles", action="store_true",
                   help="a child (--parent) only: scaffold just the --role / --tag roles; the "
                        "parent's docs cover the others")
    p.add_argument("--non-interactive", action="store_true", help="never prompt; fail on gaps")
    p.add_argument("--dry-run", action="store_true", help="show files and entry, write nothing")
    p.set_defaults(func=run)


def _answers(args) -> dict:
    answers = {}
    if args.answers:
        try:
            answers = json.loads(args.answers.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise UsageError(f"{args.answers}: cannot read answers: {e}") from None
        if not isinstance(answers, dict):
            raise UsageError(f"{args.answers}: answers must be a JSON object")
    for key in ("description", "keywords", "status", "tags", "roles"):
        if getattr(args, key) is not None:
            answers[key] = getattr(args, key)
    if args.keyword_lists:  # stripped, empties dropped, after --keyword, de-duplicated
        merged = list(args.keywords or []) + [k.strip() for value in args.keyword_lists
                                              for k in value.split(",") if k.strip()]
        if merged:
            answers["keywords"] = list(dict.fromkeys(merged))
    return answers


def run(args) -> int:
    ws = Workspace.from_args(args)
    if args.no_standard_roles and not args.parent:  # before any prompt
        raise UsageError("--no-standard-roles needs --parent: a top-level module gets every "
                         "standard role doc")
    answers = _answers(args)
    missing = creator.validate_answers(ws, answers, "submodule" if args.parent else "module")
    if missing and not args.non_interactive and creator.interactive():
        answers = creator.prompt_missing(ws, answers, missing)
    plan = creator.plan_create(ws, args.name, args.parent, answers,
                               standard_roles=not args.no_standard_roles)
    if not args.dry_run:
        creator.apply_create(ws, plan)
    warnings = creator.keyword_warnings(plan["entry"]["keywords"], ws, plan["module"])
    if not args.json:  # never blocks: --json carries them in data.warnings, stderr stays empty
        for line in creator.warning_lines(plan["entry"]["keywords"], ws, plan["module"]):
            print(f"segmently-modules: warning: {line}", file=sys.stderr)
    data = {"module": plan["module"], "files": sorted(plan["files"]), "entry": plan["entry"],
            "warnings": warnings, "dry_run": args.dry_run}
    emit("create", data, args.json, _render)
    return EXIT_OK


def _render(d) -> None:
    verb = "would create" if d["dry_run"] else "created"
    for f in d["files"]:
        print(f"{verb}  {f}")
    print(f"{'would register' if d['dry_run'] else 'registered'}  {d['module']}")
