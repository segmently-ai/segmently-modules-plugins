"""Search modes of `match`, `context` and `discover --task` (P8.1 S1): `lexical` (keyword routing,
the default), `semantic` (the user's agent chooses by meaning) and `hybrid` (both, fused). This
module resolves the mode (the `--match` flag wins over `[match] mode`, which wins over
`lexical`), refuses or degrades when no agent command is configured (S4), asks the agent
(`segmently_modules.agent`) with the work order of `segmently-modules choose`, and fuses the rankings (reciprocal rank
fusion, k = 60). A lexical run never reaches the agent and changes no byte. The engine holds no
model and no network code: the agent is a command the user configured."""
import os

from segmently_modules import agent
from segmently_modules.config import MATCH_MODES
from segmently_modules.output import UsageError, defer_note

ENV_ALLOW_REPO_MODE = "SEGMENTLY_MODULES_AGENT_ALLOW_REPO_MODE"
NO_AGENT = ("semantic matching needs your agent: set SEGMENTLY_MODULES_AGENT_COMMAND (a JSON array); "
            "in Claude Code / Codex the skills do it with segmently-modules choose")
NO_AGENT_NOTE = "semantic part skipped: no agent command configured"
NO_CARDS_NOTE = "the registry has no modules: the agent was not asked"
TOP_ZERO = "no module matched (--top 0)"  # semantic `match` / `context` text: no agent asked
SKIPPED = (NO_AGENT_NOTE, agent.NESTED_NOTE)  # the notes of a hybrid run without its agent part
RRF_K = 60
MIN_PICKS = 5  # picks asked from the agent per match run: at least this, else `top`


def add_match_flag(parser) -> None:
    parser.add_argument("--match", choices=MATCH_MODES, metavar="{lexical,semantic,hybrid}",
                        help="how modules are found for the task text (default: [match] mode, "
                             "else lexical)")


def configured_mode(config: dict) -> str:
    """`[match] mode` of the loaded config (validated at load), `lexical` when unset."""
    return (config.get("match") or {}).get("mode", "lexical")


def agent_configured(config: dict) -> bool:
    """An agent command is in force: a valid `SEGMENTLY_MODULES_AGENT_COMMAND`, outside an agent run."""
    return agent.settings(config) is not None


def repo_mode_allowed() -> bool:
    """`SEGMENTLY_MODULES_AGENT_ALLOW_REPO_MODE` (D6): `1` = the user lets a `[match] mode` from a config
    file run their agent command; unset, empty or `0` = no; anything else is refused. Read only
    when a config file sets a non-lexical mode."""
    raw = os.environ.get(ENV_ALLOW_REPO_MODE, "")
    if raw in ("", "0"):
        return False
    if raw == "1":
        return True
    raise UsageError(f"{ENV_ALLOW_REPO_MODE}: expected 1 or 0, got {raw[:40]!r}")


def effective_mode(flag: str | None, config: dict) -> str:
    return flag or configured_mode(config)


def resolve(ws, flag: str | None) -> tuple[str, list[str]]:
    """(mode, notes) for one run. `semantic` without an agent command is refused (exit 2);
    `hybrid` without one runs lexically and says so in `notes`. A non-lexical `[match] mode`
    without the flag runs only with the user's opt-in (D6): otherwise the run is lexical, the
    agent variables are not read, and one stderr note is deferred (`output.defer_note`)."""
    mode = effective_mode(flag, ws.config)
    if mode == "lexical":
        return mode, []
    if not flag and not repo_mode_allowed():  # a mode from a config file needs the opt-in (D6)
        defer_note(f'[match] mode "{mode}" is set in a config file; it runs your agent command '
                   f'only with {ENV_ALLOW_REPO_MODE}=1 (or pass --match {mode}) — ran lexical')
        return "lexical", []
    if agent_configured(ws.config):
        return mode, []
    if agent.nested():
        if mode == "semantic":
            raise UsageError(agent.NESTED)
        return mode, [agent.NESTED_NOTE]
    if mode == "semantic":
        raise UsageError(NO_AGENT)
    return mode, [NO_AGENT_NOTE]


def skipped(notes: list[str]) -> bool:
    """`resolve` skipped the agent part of a hybrid run."""
    return any(n in SKIPPED for n in notes)


def ask(ws, text: str, max_picks: int = MIN_PICKS) -> tuple[list[dict], list[str]]:
    """Ask the agent once: the validated picks `{module, confidence, reason?}` (confidence
    descending) and the notes of the validation. A failing agent is a usage error."""
    from segmently_modules import workorder
    order = workorder.build(ws, text, max_picks)
    picks, _, notes = agent.run(
        ws.config, order, order["answer_schema"],
        lambda answer: workorder.validate_answer(answer, order, max_picks), cwd=ws.root)
    return picks, notes


def semantic_rows(picks: list[dict]) -> list[dict]:
    return [{"module": p["module"], "confidence": p["confidence"], "sources": ["semantic"],
             **({"reason": p["reason"]} if "reason" in p else {})} for p in picks]


def fuse(lexical: list[dict], picks: list[dict]) -> list[dict]:
    """Reciprocal rank fusion of the lexical rows and the agent's picks (both best first): a
    row's score is the sum of 1/(60 + rank) over the lists it is in (rank from 1); ties break
    by lexical rank, then module name. Each row says where it came from (`sources`) and keeps
    the agent's `confidence` and `reason` where the agent listed it."""
    rows: dict[str, dict] = {}
    for rank, r in enumerate(lexical, 1):
        rows[r["module"]] = {**r, "sources": ["keyword"], "rrf": 1 / (RRF_K + rank),
                             "_lex": rank}
    for rank, p in enumerate(picks, 1):
        row = rows.setdefault(p["module"], {"module": p["module"], "sources": [], "rrf": 0.0,
                                            "_lex": len(lexical) + 1})
        row["sources"].append("semantic")
        row["rrf"] += 1 / (RRF_K + rank)
        row["confidence"] = p["confidence"]
        if "reason" in p:
            row["reason"] = p["reason"]
    out = sorted(rows.values(), key=lambda r: (-round(r["rrf"], 12), r["_lex"], r["module"]))
    for r in out:
        del r["_lex"]
        r["rrf"] = round(r["rrf"], 6)
    return out


def ranked(ws, text: str, mode: str, notes: list[str], top: int,
           min_score: int) -> tuple[list[dict], list[str]]:
    """The rows of a `semantic` / `hybrid` run (`mode`, `notes` from `resolve`) and its notes.
    Hybrid without an agent command: the plain lexical rows. Otherwise the agent is asked
    exactly once — never for `top` 0 or a registry without modules; `top` applies after
    fusion."""
    from segmently_modules.catalog_cmd import cards
    from segmently_modules.match import match_modules
    cfg = ws.config["match"]
    if skipped(notes):  # hybrid, no agent part
        return match_modules(ws.registry.modules, text, cfg, top, min_score), notes
    if top == 0:  # nothing to show: do not spend an agent call
        return [], notes
    if not cards(ws.registry.modules):  # nothing to choose from: no agent call either
        return [], notes + [NO_CARDS_NOTE]
    picks, pick_notes = ask(ws, text, max(top, MIN_PICKS))
    if mode == "semantic":
        return semantic_rows(picks)[:top], pick_notes
    lexical = match_modules(ws.registry.modules, text, cfg, 10 ** 9, min_score)
    return fuse(lexical, picks)[:top], pick_notes
