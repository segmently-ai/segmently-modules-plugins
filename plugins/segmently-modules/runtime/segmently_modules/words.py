"""Words as routing compares them, and the keyword checks built on that — shared by `match`,
`create`, `init done`, `init verify`, `init reconcile` and lint. Pure functions, no engine
import: every module may import this one."""
from __future__ import annotations

import re
from functools import lru_cache

_ASCII_WORD = re.compile(r"[a-z]+")
_VOWEL = re.compile(r"[aeiouy]")
_CVC = re.compile(r"[^aeiou][aeiouy][^aeiouwxy]")
SIBILANT = ("s", "x", "z", "ch", "sh")  # boxes, matches, classes: the plural adds -es
KEEP = frozenset({"news", "setting", "evening"})  # forms of their own: never `new`, `set`, `even`


@lru_cache(maxsize=1 << 16)  # pure: every keyword of every module, once per process
def word_keys(word: str) -> frozenset:
    """The keys of one word, shared by its endings -s, -es, -ies, -ed and -ing: `save`,
    `saves`, `saved` and `saving` all hold `save`; two words match when their keys meet. Only
    an ASCII word of 4 letters or more is cut, a stem keeps 3 letters at least, and a word
    without an ending is never cut (`theme` never meets `them`, `note` never meets `not`).
    A stem of -ed / -ing may have lost an `e`: `charging` holds `charg` and `charge`; a short
    consonant-vowel-consonant stem always did (`saving`: `save`), a doubled end never did
    (`stopped`: `stop`). Never shown to anyone: output names the words themselves."""
    w = word.lower()
    if len(w) < 4 or not _ASCII_WORD.fullmatch(w) or w in KEEP:
        return frozenset((w,))
    if w.endswith("ies") and len(w) > 4:  # entries: entry; movies: movie
        bases = {w[:-3] + "y", w[:-1]}
    elif w.endswith("es") and w[:-2].endswith(SIBILANT) and len(w) > 4:  # boxes: box
        bases = {w[:-2], w[:-1]}
    elif w.endswith("s") and not w.endswith(("ss", "us", "is")):
        bases = {w[:-1]}
    else:
        bases = {w}
    return frozenset(k for b in bases for k in _verb_keys(b))


def _verb_keys(w: str) -> set:
    if w in KEEP:
        return {w}
    for suffix in ("ing", "ed"):
        stem = w[:-len(suffix)]
        if not (w.endswith(suffix) and len(stem) >= 3 and _VOWEL.search(stem)):
            continue
        if suffix == "ed" and stem.endswith("i"):  # copied: copy
            return {stem[:-1] + "y"}
        if len(stem) >= 4 and stem[-1] == stem[-2] and stem[-1] not in "aeiouls":
            return {stem[:-1]}  # stopped: stop
        if len(stem) == 3 and _CVC.fullmatch(stem):
            return {stem + "e"}  # saving: save
        return {stem, stem + "e"}  # charging: charg, charge
    return {w}


_WORD_CHAR = re.compile(r"\w")
_TOKEN = re.compile(r"\w+")
_PART = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")
ONE_WORD = re.compile(r"\w+")


def text_words(text: str) -> set:
    """The lowercased `\\w+` words of `text` and the parts of its identifiers: `saveMeal`
    gives `savemeal`, `save` and `meal`; `delete_entry` gives `delete_entry`, `delete` and
    `entry`; `HTTPServer` gives `httpserver`, `http` and `server`."""
    out = set()
    for token in _TOKEN.findall(text):
        out.add(token.lower())
        parts = _PART.findall(token)
        if len(parts) > 1:
            out.update(p.lower() for p in parts)
    return out


def word_set_keys(words, normalize: bool) -> set:
    """Every key of `words` (`word_keys` under `normalize`, else the words themselves)."""
    if not normalize:
        return set(words)
    out: set = set()
    for w in words:
        out |= word_keys(w)
    return out


@lru_cache(maxsize=1 << 14)  # a registry has thousands of keywords: more than re's own cache
def term_pattern(term: str) -> re.Pattern:
    # Boundary only on an edge that is a word char: identical to \b for word-edged
    # terms ("book" never hits "books"), and a superset for terms with a non-word
    # edge (".epub", "c++ code", "modules/xyz"), which \b matched only by accident.
    # Verified in the 2026-09-25 dry-run: 0 parity diffs on the real corpus.
    t = term.lower()
    left = r"(?<!\w)" if t and _WORD_CHAR.match(t[0]) else ""
    right = r"(?!\w)" if t and _WORD_CHAR.match(t[-1]) else ""
    return re.compile(left + re.escape(t) + right)


class FileWords:
    """Which keywords files hold — by their text, the parts of their identifiers and their
    path — each file read once (`read(rel)`: its text, or None for none to read)."""

    def __init__(self, read, normalize: bool):
        self.read, self.normalize = read, normalize
        self.seen: dict[str, tuple[str, str, set]] = {}

    def evidence(self, rel: str) -> tuple[str, str, set]:
        if rel not in self.seen:
            text = self.read(rel) or ""
            words = text_words(text) | text_words(rel)
            self.seen[rel] = (text.lower(), rel.lower(), word_set_keys(words, self.normalize))
        return self.seen[rel]

    def holds(self, rel: str, forms) -> bool:
        """Whether file `rel` holds one of `forms`: a one-word keyword by its keys (so
        `saveMeal` holds `save`), any other by its whole text in the path or the text."""
        low, path, keys = self.evidence(rel)
        for kw in forms:
            if ONE_WORD.fullmatch(kw):
                if word_set_keys([kw.lower()], self.normalize) & keys:
                    return True
            elif (rx := term_pattern(kw)).search(path) or rx.search(low):
                return True
        return False


def normalizing(cfg: dict) -> bool:
    """Whether `[match] normalize` asks for `word_keys` (the default) — `none` is exact."""
    return cfg.get("normalize", "suffix") != "none"


# A keyword that matches too many tasks to route one: `create` and `init done` warn, `init
# verify` refuses it for a new module, lint says so (MS023, info). `[create] generic_keywords`
# adds words; a word of the module's own name is never generic for it (`module-system` keeps
# `module`). The first nine are the words `create` warned about before 0.3.0.
GENERIC_KEYWORDS = ("common", "data", "helper", "info", "item", "list", "misc", "stuff", "util",
                    "create", "edit", "add", "delete", "remove", "update", "save", "load", "get",
                    "set", "search", "select", "copy", "open", "close", "show", "user", "screen",
                    "app", "module", "test")


def generic_words(cfg: dict) -> tuple:
    """The generic words of a workspace config: the built-in list plus `[create]
    generic_keywords`."""
    extra = cfg.get("create", {}).get("generic_keywords") or []
    return tuple(dict.fromkeys([*GENERIC_KEYWORDS, *(w.strip().lower() for w in extra)]))


def _keys(word: str, normalize: bool) -> frozenset:
    return word_keys(word) if normalize else frozenset((word.lower(),))


def is_generic(keyword: str, generic, normalize: bool, own=()) -> bool:
    """Whether one-word `keyword` is a generic word (a phrase never is): under `normalize` any
    form of one (`deletes`), else the word itself; never a word of `own`, the words of the
    module's own name."""
    word = keyword.strip().lower()
    if not word or len(word.split()) != 1:
        return False
    keys = _keys(word, normalize)
    if any(keys & _keys(o, normalize) for o in own):
        return False
    return any(keys & _keys(g, normalize) for g in generic)


def generic_keywords(cfg: dict, module: str, keywords) -> list[str]:
    """The keywords of `module` that are generic words (`is_generic` with the config's words
    and normalize, the module name's words as its own), in order, each once."""
    generic, normalize = generic_words(cfg), normalizing(cfg.get("match", {}))
    own = name_words(module)
    return [k for k in dict.fromkeys(k for k in keywords if isinstance(k, str))
            if is_generic(k, generic, normalize, own)]


def name_words(name: str) -> list[str]:
    """The words of a module name (`module-system`, `payments/refunds`)."""
    return [w for w in re.split(r"[-/_]", name.lower()) if w]


def word_groups(keywords, normalize: bool) -> list[list[str]]:
    """The keywords grouped by word, first seen first: under `normalize` the one-word keywords
    whose forms meet (`save`, `saving`), anything else by its lowercased text."""
    groups: list[tuple[set, list[str]]] = []
    for kw in keywords:
        if not isinstance(kw, str) or not kw.strip():
            continue
        text = kw.strip().lower()
        keys = set(word_keys(text)) if normalize and len(text.split()) == 1 else {("=", text)}
        for g_keys, members in groups:
            if g_keys & keys:
                g_keys |= keys
                members.append(kw)
                break
        else:
            groups.append((keys, [kw]))
    return [members for _, members in groups]


def distinct_words(keywords, normalize: bool) -> int:
    """How many words `keywords` holds: every form of one word, and every case of one
    keyword, once."""
    return len(word_groups(keywords, normalize))
