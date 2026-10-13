import re

from segmently_modules.output import EXIT_OK, UsageError, emit
from segmently_modules.registry import as_dict, as_list
from segmently_modules.semantic import NO_CARDS_NOTE, TOP_ZERO, add_match_flag, ranked, resolve
from segmently_modules.workspace import Workspace


_WORD = re.compile(r"\w")


def term_pattern(term: str) -> re.Pattern:
    # Boundary only on an edge that is a word char: identical to \b for word-edged
    # terms ("book" never hits "books"), and a superset for terms with a non-word
    # edge (".epub", "c++ code", "modules/xyz"), which \b matched only by accident.
    # Verified in the 2026-09-25 dry-run: 0 parity diffs on the real corpus.
    t = term.lower()
    left = r"(?<!\w)" if t and _WORD.match(t[0]) else ""
    right = r"(?!\w)" if t and _WORD.match(t[-1]) else ""
    return re.compile(left + re.escape(t) + right)


def matched_terms(text_lower: str, terms) -> list:
    # malformed registry values (non-list, non-str terms) are lint's job; ignore them here
    return [t for t in as_list(terms)
            if isinstance(t, str) and term_pattern(t).search(text_lower)]


def negative_phrases(entry: dict) -> list:
    """negative_keywords: {generic_word: [phrases]} or a legacy flat phrase list.
    Only phrase matches penalize."""
    nk = entry.get("negative_keywords")
    if isinstance(nk, dict):
        return [p for phrases in nk.values() for p in as_list(phrases)]
    if isinstance(nk, list):
        return nk
    return []


def score_entry(text_lower: str, entry: dict, weights: dict) -> tuple[int, list, list]:
    hits = matched_terms(text_lower, entry.get("keywords"))
    score = weights["keyword_weight"] * len(hits)
    for combo in as_list(entry.get("required_combinations")):
        terms = combo if isinstance(combo, list) else [combo]
        if terms and len(matched_terms(text_lower, terms)) == len(terms):
            score += weights["combination_weight"]
    neg = matched_terms(text_lower, negative_phrases(entry))
    score += weights["negative_weight"] * len(neg)
    return score, hits, neg


def match_modules(modules: dict, text: str, weights: dict, top: int,
                  min_score: int) -> list[dict]:
    text_lower = text.lower()
    rows = []
    for name, entry in modules.items():
        if not isinstance(entry, dict):
            continue
        score, hits, neg = score_entry(text_lower, entry, weights)
        if score >= min_score and hits:
            rows.append({"module": name, "score": score, "keywords": hits, "negative": neg})
        for child, sub in as_dict(entry.get("submodules")).items():
            if not isinstance(sub, dict):
                continue
            c_hits = matched_terms(text_lower, sub.get("keywords"))
            c_score = weights["keyword_weight"] * len(c_hits)
            if c_hits and c_score >= min_score:
                rows.append({"module": f"{name}/{child}", "score": c_score,
                             "keywords": c_hits, "negative": []})
    rows.sort(key=lambda r: (-r["score"], r["module"]))
    return rows[:top]


_TOKEN = re.compile(r"\w+")
LOOSE_MIN = 4  # words shorter than this never match loosely (too many false hints)


def _loose_words(text: str) -> list[str]:
    """Distinct `\\w+` words of at least LOOSE_MIN characters, lowercased, in text order."""
    return list(dict.fromkeys(w for w in _TOKEN.findall(text.lower()) if len(w) >= LOOSE_MIN))


def _shares_prefix(a: str, b: str) -> bool:
    p = min(5, len(a), len(b))
    return a[:p] == b[:p]


def _near(keywords, hits: list, words: list[str]) -> list[dict]:
    """{keyword, task_word} for every keyword that is not an exact hit and has a word sharing
    its first min(5, len(a), len(b)) characters with a task word (both at least LOOSE_MIN)."""
    out = []
    for kw in as_list(keywords):
        if not isinstance(kw, str) or kw in hits:
            continue
        for a in _loose_words(kw):
            match = next((b for b in words if _shares_prefix(a, b)), None)
            if match:
                out.append({"keyword": kw, "task_word": match})
                break
    return out


def near_misses(modules: dict, text: str, weights: dict, top: int, min_score: int) -> list[dict]:
    """When no target reaches `min_score`: the targets with a keyword that loosely matches a
    task word, or with exact hits whose score stays below `min_score` (negative keywords).
    Rows {module, score, keywords: [exact hits], near: [{keyword, task_word}]}, most hints
    first, at most `top`. `[]` whenever a target matched."""
    if match_modules(modules, text, weights, 1, min_score):
        return []
    text_lower, words = text.lower(), _loose_words(text)
    rows = []
    for name, entry in modules.items():
        if not isinstance(entry, dict):
            continue
        score, hits, _ = score_entry(text_lower, entry, weights)
        targets = [(name, entry, score, hits)]
        for child, sub in as_dict(entry.get("submodules")).items():
            if isinstance(sub, dict):
                c_hits = matched_terms(text_lower, sub.get("keywords"))
                targets.append((f"{name}/{child}", sub, weights["keyword_weight"] * len(c_hits),
                                c_hits))
        for target, holder, t_score, t_hits in targets:
            near = _near(holder.get("keywords"), t_hits, words)
            if near or t_hits:
                rows.append({"module": target, "score": t_score, "keywords": t_hits,
                             "near": near})
    rows.sort(key=lambda r: (-(len(r["near"]) + len(r["keywords"])), r["module"]))
    return rows[:top]


def near_lines(rows: list[dict]) -> list[str]:
    """Text lines for near misses, closed by the hint that names `segmently-modules show`."""
    out = []
    for r in rows:
        items = [f"{n['keyword']} ~ {n['task_word']}" for n in r["near"]]
        items += [f"{k} (exact)" for k in r["keywords"]]
        below = f"  (score {r['score']}, below min_score)" if r["keywords"] else ""
        out.append(f"near  {r['module']:<28} {', '.join(items)}{below}")
    if rows:
        out.append(f"re-run with the module's own keyword in the task text, or read it "
                   f"directly: segmently-modules show {rows[0]['module']}")
    return out


def register(sub, common) -> None:
    p = sub.add_parser("match", parents=[common],
                       help="rank modules by keyword match against task text")
    p.add_argument("text")
    p.add_argument("--top", type=int)
    p.add_argument("--min-score", type=int)
    add_match_flag(p)
    p.set_defaults(func=run)


def run(args) -> int:
    if args.top is not None and args.top < 0:
        raise UsageError("--top must be >= 0")
    ws = Workspace.from_args(args)
    mode, notes = resolve(ws, args.match)
    cfg = ws.config["match"]
    top = cfg["top"] if args.top is None else args.top
    min_score = cfg["min_score"] if args.min_score is None else args.min_score
    if mode == "lexical":
        rows = match_modules(ws.registry.modules, args.text, cfg, top, min_score)
        near = [] if rows or args.json else near_misses(ws.registry.modules, args.text, cfg, top,
                                                        min_score)
        emit("match", rows, args.json, lambda r: _render(r, near))  # --json: the plain list
        return EXIT_OK
    rows, notes = ranked(ws, args.text, mode, notes, top, min_score)
    near = [] if rows or args.json or mode == "semantic" else \
        near_misses(ws.registry.modules, args.text, cfg, top, min_score)
    emit("match", {"mode": mode, "rows": rows, "notes": notes}, args.json,
         lambda d: (_render(d["rows"], near, mode, d["notes"], top),
                    [print(n) for n in d["notes"]]))
    return EXIT_OK


def _render(rows, near, mode: str = "lexical", notes=(), top: int | None = None) -> None:
    if not rows and mode == "semantic":
        if top == 0:  # the agent was not asked
            print(TOP_ZERO)
        elif NO_CARDS_NOTE not in notes:  # with no module the agent was not asked: the note says so
            print("no matches (the agent chose no module; try rephrasing the task)")
        return
    if not rows:
        print("no keyword matches (try rephrasing with domain terms, or use: list)")
        for line in near_lines(near):
            print(line)
        return
    for r in rows:
        if "sources" in r:  # an agent-backed row: its confidence, keywords or reason, sources
            label = r["score"] if "score" in r else f"{r['confidence']:.2f}"
            detail = ", ".join(r.get("keywords") or []) or r.get("reason", "")
            print(f"{label:>4}  {r['module']:<42} {detail}  [{', '.join(r['sources'])}]")
            continue
        neg = f"  NEGATIVE:{','.join(r['negative'])}" if r["negative"] else ""
        print(f"{r['score']:>4}  {r['module']:<42} {', '.join(r['keywords'])}{neg}")
