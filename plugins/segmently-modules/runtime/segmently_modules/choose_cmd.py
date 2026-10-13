"""`segmently-modules choose` (P8.1 S3): the work order an agent answers to pick modules by meaning, and
the validation of its answer. `choose --task T` (or `--task-file PATH|-`) prints the work order
(a prompt; `--json` the document); `choose --apply FILE|-` validates an answer offline and prints
the picks with each module's read set; `choose --task T --run` asks the user's own agent command
(`SEGMENTLY_MODULES_AGENT_COMMAND`, see `segmently_modules.agent`) and prints the same. `--apply` and `--run` read an
answer the same way (`agent.answer_from`). Read-only: no lock, no write, no cache."""
from pathlib import Path

from segmently_modules import agent, workorder
from segmently_modules.catalog_cmd import cards
from segmently_modules.config import EFFORTS
from segmently_modules.output import EXIT_OK, UsageError, emit
from segmently_modules.pipeline import read_input, task_text
from segmently_modules.query import show_target
from segmently_modules.semantic import NO_AGENT, NO_CARDS_NOTE, agent_configured
from segmently_modules.workspace import Workspace

NO_TASK = "give the task: --task TEXT or --task-file FILE (or --apply FILE to validate an answer)"


def register(sub, common) -> None:
    p = sub.add_parser("choose", parents=[common],
                       help="the work order for choosing modules by meaning, and its answer",
                       description="Print the work order for choosing modules by meaning "
                                   "(--task or --task-file), validate an agent's answer to it "
                                   "(--apply FILE|-), or ask your agent command, "
                                   "SEGMENTLY_MODULES_AGENT_COMMAND (--run).")
    t = p.add_mutually_exclusive_group()
    t.add_argument("--task", help="the task text, any language")
    t.add_argument("--task-file", type=Path, metavar="FILE",
                   help="read the task text from FILE ('-' = stdin)")
    p.add_argument("--top", type=int, help="at most N picks (default 5)")
    p.add_argument("--effort", choices=EFFORTS,
                   help="the depth of the search for this run, over [search] effort")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--apply", metavar="FILE", help="validate an answer ('-' = stdin)")
    g.add_argument("--run", action="store_true",
                   help="ask the agent command in SEGMENTLY_MODULES_AGENT_COMMAND")
    p.set_defaults(func=run)


def _source(apply: str) -> str:
    """How `--apply`'s refusals name the answer: FILE as given, or `stdin`."""
    return "stdin" if apply == "-" else apply


def _read_answer(source: str):
    """The answer object in FILE or stdin: the answer itself or an agent's JSON envelope. Its
    bytes are decoded as UTF-8 with replacement and go through `agent.answer_from`, as `--run`
    reads the agent's stdout; every refusal starts with the source."""
    name = _source(source)
    try:
        data = read_input(source)
    except OSError as e:
        raise UsageError(f"{name}: cannot read the answer: {e.strerror or e}") from None
    return agent.answer_from(data.decode("utf-8", "replace"), name, "its text",
                             f"{name}: the answer is empty (expected a JSON object)")


def _with_read_sets(ws, picks: list[dict]) -> list[dict]:
    out = []
    for p in picks:
        _, shown = show_target(ws, p["module"], None, False)
        out.append({**p, "read": shown["read"]})
    return out


def run(args) -> int:
    top = args.top
    if top is not None and top < 1:
        raise UsageError("--top must be >= 1")
    ws = Workspace.from_args(args)
    max_picks = workorder.DEFAULT_MAX_PICKS if top is None else top
    task = ""
    if args.apply is None:  # the work order and --run need the task; --apply does not
        if args.task is None and args.task_file is None:
            raise UsageError("--run needs --task TEXT or --task-file FILE" if args.run
                             else NO_TASK)
        task = task_text(args)
        if not args.run:
            order = workorder.build(ws, task, max_picks, args.effort)
            emit("choose", order, args.json, workorder.render)
            return EXIT_OK
        if not agent_configured(ws.config):
            raise UsageError(agent.NESTED if agent.nested() else NO_AGENT)
    order = workorder.build(ws, task, max_picks, args.effort)
    check = lambda answer: workorder.validate_answer(answer, order, max_picks)  # noqa: E731
    if not args.run:
        answer = _read_answer(args.apply)
        try:
            picks, none, notes = check(answer)
        except UsageError as e:  # as `--run` names the agent: `agent NAME: answer: …`
            raise UsageError(f"{_source(args.apply)}: {e}") from None
    elif not cards(ws.registry.modules):  # nothing to choose from: no agent call (M-2)
        picks, none, notes = [], False, [NO_CARDS_NOTE]
    else:
        picks, none, notes = agent.run(ws.config, order, order["answer_schema"], check,
                                       cwd=ws.root)
    data = {"picks": _with_read_sets(ws, picks), "none": none, "notes": notes,
            "max_picks": max_picks}
    emit("choose", data, args.json, _render)
    return EXIT_OK


def _render(d) -> None:
    if not d["picks"]:
        print("no module chosen")
    for p in d["picks"]:
        reason = f"  {p['reason']}" if p.get("reason") else ""
        print(f"{p['confidence']:.2f}  {p['module']}{reason}")
        for r in p["read"]:
            mark = "" if r["exists"] else "  (MISSING ON DISK)"
            print(f"      read  {r['label']:<28} {r['path']}{mark}")
    for n in d["notes"]:
        print(f"note: {n}")
