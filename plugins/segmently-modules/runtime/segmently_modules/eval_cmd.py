"""`segmently-modules eval routing` — does a task reach its module? (D3, verb 27, `segmently-modules.eval/1`)

  routing --tasks FILE [--top N] [--min-hit-rate R]
      FILE = a JSON list of {task, module}. Each task is ranked with `context`'s scoring (the
      same `match` rows, `--top` of them, default 3, 1–20); a hit = the expected module, or one
      of its children, among them (a parent never counts for a child). `hit_rate` = hits /
      tasks rounded DOWN to 3 decimals; the run passes when hits >= threshold × tasks
      (unrounded) — threshold: `--min-hit-rate`, else `[init] routing_min_hit_rate` (0.8);
      exit 1 below it
  routing --prompt [--per-module N]
      the prompt that asks for N tasks per module (default 5, 1–20), rendered from the template
      `init/routing_prompt.md`: per module only the first paragraph under `## Purpose` of its
      doc and its code files (the files its rules and code pointers route to it, the first 200)
      — never its keywords, its description or the registry file

While `init` is between reconcile and finish, both read the registry as `init finish` will leave
it (`segmently_modules.init_overlay`)."""
import json
import re
from fractions import Fraction
from pathlib import Path

from segmently_modules.changes import repo_files, require_work_tree, routes, target_names
from segmently_modules.create import resolve_template
from segmently_modules.init_work import fill
from segmently_modules.match import match_modules
from segmently_modules.output import EXIT_FINDINGS, EXIT_OK, UsageError, emit
from segmently_modules.registry import as_dict
from segmently_modules.workspace import Workspace

ACTIONS = ("routing",)
TOP, TOP_MAX, PER_MODULE, PER_MODULE_MAX, FILES_CAP = 3, 20, 5, 20, 200
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_MARK = "\0"  # where a comment was (purpose)


def register(sub, common) -> None:
    p = sub.add_parser("eval", parents=[common],
                       help="measure the registry: routing (does a task reach its module?)",
                       description="routing --tasks FILE: rank each {task, module} of FILE with "
                                   "context's scoring and report the hit rate (a hit: the module "
                                   "among the top --top, default 3); exit 1 below --min-hit-rate, "
                                   "else [init] routing_min_hit_rate (0.8). routing --prompt: the "
                                   "prompt that asks for --per-module tasks per module (default "
                                   "5) from each module's purpose paragraph and files alone.")
    p.add_argument("action", nargs="?", metavar="ACTION", help="routing")
    p.add_argument("--tasks", type=Path, metavar="FILE",
                   help="a JSON list of {task, module} to route")
    p.add_argument("--prompt", action="store_true",
                   help="print the prompt that asks for routing tasks")
    p.add_argument("--top", type=int, help=f"--tasks: a hit is among this many (1–{TOP_MAX}, "
                                           f"default {TOP})")
    p.add_argument("--min-hit-rate", type=float, metavar="R",
                   help="--tasks: the threshold, 0–1 (default: [init] routing_min_hit_rate)")
    p.add_argument("--per-module", type=int, metavar="N",
                   help=f"--prompt: tasks per module (1–{PER_MODULE_MAX}, default {PER_MODULE})")
    p.set_defaults(func=run)


def workspace(args) -> Workspace:
    """The workspace to measure: the overlay while an init is between reconcile and finish."""
    from segmently_modules.init_overlay import current
    ws = Workspace.from_args(args)
    return current(ws.root, ws.config_dir, ws.config) or ws


def load_tasks(path: Path, modules: set[str], shown: str | None = None) -> list[dict]:
    """The tasks of FILE; anything else is exit 2 naming the file (as `shown`, else as given)
    and the item."""
    name = shown or path
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise UsageError(f"cannot read {name}: {getattr(e, 'strerror', None) or e}") from None
    try:
        tasks = json.loads(text)
    except json.JSONDecodeError as e:
        raise UsageError(f"{name}: invalid JSON ({e})") from None
    if not isinstance(tasks, list):
        raise UsageError(f"{name}: not a list of {{task, module}} objects")
    if not tasks:
        raise UsageError(f"no tasks in {name}")
    for i, t in enumerate(tasks, 1):
        if not isinstance(t, dict) or not isinstance(t.get("task"), str) or not t["task"].strip() \
                or not isinstance(t.get("module"), str):
            raise UsageError(f"{name}: task #{i} is not a {{task, module}} object with a "
                             f"non-empty task text")
        if t["module"] not in modules:
            raise UsageError(f"unknown module '{t['module']}' in {name}")
    return tasks


def hit(expected: str, got: list[str]) -> bool:
    """The expected module is among `got`, or one of its children is."""
    return any(g == expected or g.partition("/")[0] == expected and "/" in g for g in got)


def routing(ws, tasks: list[dict], top: int, threshold: float,
            targets: set[str] | None = None) -> dict:
    """The routing report of `tasks` over the workspace's registry (`targets`: its routing
    targets, when the caller has them)."""
    cfg = ws.config["match"]
    per = {t: {"module": t, "tasks": 0, "hits": 0, "misses": []}
           for t in sorted(targets if targets is not None else target_names(ws.registry.modules))}
    hits = 0
    for t in tasks:
        got = [r["module"] for r in match_modules(ws.registry.modules, t["task"], cfg, top,
                                                  cfg["min_score"])]
        row = per[t["module"]]
        row["tasks"] += 1
        if hit(t["module"], got):
            row["hits"] += 1
            hits += 1
        else:
            row["misses"].append({"task": t["task"], "got": got})
    n = len(tasks)
    return {"hit_rate": (hits * 1000 // n) / 1000, "top": top, "tasks": n,
            "per_module": list(per.values()), "hits": hits, "min_hit_rate": threshold,
            "passed": hits >= Fraction(str(threshold)) * n}


def purpose(ws, doc: str | None) -> str | None:
    """The first paragraph under `## Purpose` of a doc; a blockquote line or a line that is only
    an HTML comment is skipped wherever it sits (before the paragraph or inside it) — only a
    blank line or a heading ends the paragraph."""
    if not isinstance(doc, str):
        return None
    try:
        text = ws.disk(doc).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    # a comment leaves a mark on every line it covered: a line of marks alone was a comment
    lines = _COMMENT.sub(lambda m: _MARK + ("\n" + _MARK) * m.group(0).count("\n"),
                         text).splitlines()
    try:
        start = next(i for i, line in enumerate(lines)
                     if line.replace(_MARK, "").strip() == "## Purpose") + 1
    except StopIteration:
        return None
    para = []
    for line in lines[start:]:
        bare = line.replace(_MARK, "")
        if bare.startswith("#"):
            break
        if (line.strip() and not bare.strip()) or bare.lstrip().startswith(">"):
            continue  # a whole-line comment or a blockquote
        if not bare.strip():
            if para:
                break
            continue
        para.append(bare.strip())
    return " ".join(para) or None


def routing_prompt(ws, per_module: int) -> tuple[list[str], str]:
    """(the modules, the prompt): per module its purpose paragraph and its code files."""
    require_work_tree(ws.root, "eval routing --prompt")
    modules = ws.registry.modules
    targets = sorted(target_names(modules))
    files: dict[str, list[str]] = {t: [] for t in targets}
    for path, target, via in routes(ws, repo_files(ws.root)):
        if via != "docs" and path not in files[target]:
            files[target].append(path)
    blocks = []
    for t in targets:
        parent, _, child = t.partition("/")
        entry = as_dict(modules[parent])
        holder = as_dict(as_dict(entry.get("submodules")).get(child)) if child else entry
        text = purpose(ws, as_dict(holder.get("context_files")).get("universal"))
        own = files[t]
        head = (f"Files ({len(own)}, the first {FILES_CAP}):" if len(own) > FILES_CAP
                else f"Files ({len(own)}):")
        listed = "\n".join(f"- `{f}`" for f in own[:FILES_CAP]) or "- (none routed to it)"
        blocks.append(f"## `{t}`\n\n{text or 'no purpose paragraph'}\n\n{head}\n{listed}\n")
    prompt = fill(resolve_template(ws, "init/routing_prompt.md"),
                  {"count": len(targets), "per_module": per_module,
                   "modules": "\n".join(blocks)})
    return targets, prompt if prompt.endswith("\n") else prompt + "\n"


def threshold_of(args, ws) -> float:
    if args.min_hit_rate is not None:
        if not 0 <= args.min_hit_rate <= 1:
            raise UsageError(f"--min-hit-rate must be from 0 to 1, got {args.min_hit_rate}")
        return args.min_hit_rate
    return ws.config["init"]["routing_min_hit_rate"]


def run(args) -> int:
    if args.action is None:
        raise UsageError(f"eval needs an action ({', '.join(ACTIONS)})")
    if args.action not in ACTIONS:
        raise UsageError(f"unknown eval action {args.action!r} (actions: {', '.join(ACTIONS)})")
    if (args.tasks is None) == (not args.prompt):
        raise UsageError("eval routing: exactly one of --tasks, --prompt")
    if args.prompt and (args.top is not None or args.min_hit_rate is not None):
        raise UsageError("--top and --min-hit-rate work with --tasks")
    if args.tasks is not None and args.per_module is not None:
        raise UsageError("--per-module works with --prompt")
    if args.top is not None and not 1 <= args.top <= TOP_MAX:
        raise UsageError(f"--top must be from 1 to {TOP_MAX}, got {args.top}")
    if args.per_module is not None and not 1 <= args.per_module <= PER_MODULE_MAX:
        raise UsageError(f"--per-module must be from 1 to {PER_MODULE_MAX}, got "
                         f"{args.per_module}")
    ws = workspace(args)
    if args.prompt:
        per = args.per_module or PER_MODULE
        modules, prompt = routing_prompt(ws, per)
        data = {"mode": "prompt", "per_module": per, "modules": modules, "prompt": prompt}
        emit("eval", data, args.json, lambda d: print(d["prompt"], end=""))
        return EXIT_OK
    threshold = threshold_of(args, ws)
    targets = target_names(ws.registry.modules)
    tasks = load_tasks(args.tasks, targets)
    data = routing(ws, tasks, args.top or TOP, threshold, targets)
    emit("eval", data, args.json, render)
    return EXIT_OK if data["passed"] else EXIT_FINDINGS


def render(d) -> None:
    print(f"hit rate {d['hit_rate']} ({d['hits']}/{d['tasks']}, top {d['top']})")
    for row in d["per_module"]:
        print(f"{row['module']}  {row['hits']}/{row['tasks']}")
        for miss in row["misses"]:
            print(f"  miss  \"{miss['task']}\" → {', '.join(miss['got']) or '(no module)'}")
    print(f"threshold {d['min_hit_rate']}: {'passed' if d['passed'] else 'FAILED'}")
