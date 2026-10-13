"""`init reconcile` — phase 5 (D2), a script: once every module is done, the staging registry
from the writers' `entry.json` files, and what the writers could not see from one module.

  <config_dir>/init/staging/registry.json  the registry `init finish` writes: the modules the
                                           registry already has, as they are, then one entry per
                                           new module in name order — {name, description,
                                           status: "active", keywords, context_files (the final
                                           paths), <asked fields>, related_modules?}
  <config_dir>/init/reconcile.json         {edges, collisions, duplicates, judgement}

Edges: the proposal's import edges between confirmed modules become `depends-on` edges ("imports
from <m> (<n> import(s), init reconcile)"), one per direction; a writer's own edge to the same
module (any relation) wins. Collisions: a keyword (any case) that two new modules or more hold
belongs to the module with the most files (under its confirmed paths) whose path or text holds
it as a whole word (a file counts once); another holder loses it from `keywords` only when
none of its own files holds it (D14: a module whose code holds the word keeps it) — never a
negative keyword, which would pull it out of every task that uses the word — unless that
leaves it below `[create] min_keywords` (a `keyword-floor` judgement item) or the most files
are a tie (a `keyword-tie` item: nothing is removed). Duplicates:
a name defined in two confirmed modules or more, at least one of them new (a module already in
the registry counts as the other) — Python top-level `def` / `class`, JS/TS
`export function|class|const|interface|type` — never a name starting with `_`, a re-export,
`export default` or a test file (`test_*.py`,
`*_test.py`, `*.test.*`, `*.spec.*`, anything under a `tests/` directory): reported with
file:line, never changed. A module already in the registry is never changed, gets no edge and
never loses a keyword. The script runs no agent and no command but git (the file set);
`judgement` holds what a person or the `module-init` skill decides. A staging registry edited
since the last reconcile is kept: `--force` rebuilds it from the `entry.json` files. Refused
once `init finish` is done."""
import json
import re
from pathlib import PurePosixPath

from segmently_modules.changes import glob_to_regex
from segmently_modules.create import ask_fields
from segmently_modules.match import term_pattern
from segmently_modules.output import UsageError
from segmently_modules.preflight import BIG, SNIFF
from segmently_modules.store import serialize

TEST_FILE = re.compile(r"(?:^|/)(?:tests/|test_[^/]*\.py$|[^/]*_test\.py$"
                       r"|[^/]*\.(?:test|spec)\.[^/]+$)")
PY_DEF = re.compile(r"^(?:async[ \t]+)?def[ \t]+([A-Za-z_]\w*)|^class[ \t]+([A-Za-z_]\w*)", re.M)
JS_DEF = re.compile(r"^export[ \t]+(?:async[ \t]+)?(?:function\*?|class|const|interface|type)"
                    r"[ \t]+([A-Za-z_$][\w$]*)", re.M)
JS = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts")


class Reconcile:
    def __init__(self, work):
        self.work, self.flow, self.ws = work, work.flow, work.ws
        self.registry_path = work.staging / "registry.json"
        self.report_path = self.flow.work / "reconcile.json"
        self.texts: dict[str, str | None] = {}

    # --- inputs ---------------------------------------------------------------------------

    def text(self, rel: str) -> str | None:
        """A file's text, read at most once (None: a symlink, too large, binary, unreadable)."""
        if rel not in self.texts:
            path, text = self.flow.root / rel, None
            if not path.is_symlink():
                try:
                    if path.stat().st_size <= BIG:
                        data = path.read_bytes()
                        if b"\0" not in data[:SNIFF]:
                            text = data.decode("utf-8", errors="replace")
                except OSError:
                    pass
            self.texts[rel] = text
        return self.texts[rel]

    def module_files(self, candidates: dict, files: list[str]) -> dict[str, list[str]]:
        out = {}
        for name, c in candidates.items():
            rx = [glob_to_regex(g) for g in c["paths"]]
            out[name] = [f for f in files if any(r.match(f) for r in rx)]
        return out

    def item(self, state: dict, module: str) -> dict:
        """A new module's work item (its `roles`): missing is the refusal a claim gives
        (`Work.missing`), damaged or of the wrong shape `Work.item`'s — exit 2, nothing
        written."""
        item = self.work.item(module)
        if item is None:
            raise UsageError(self.work.missing(state, module))
        return item

    def entry(self, module: str, item: dict) -> dict:
        written = json.loads((self.work.staging_dir(module) / "entry.json")
                             .read_text(encoding="utf-8"))
        cfg = self.ws.config["paths"]
        rel = f"{cfg['modules_dir']}/{module}"
        entry = {"name": module, "description": written["description"].strip(),
                 "status": "active", "keywords": list(dict.fromkeys(written["keywords"])),
                 "context_files": {"universal": f"{rel}/{cfg['module_doc']}",
                                   "roles": {r: f"{rel}/roles/{r}.md" for r in item["roles"]}}}
        for name in ask_fields(self.ws, "module"):
            entry[name] = written[name]
        if written.get("related_modules"):
            entry["related_modules"] = list(written["related_modules"])
        return entry

    # --- the three passes -----------------------------------------------------------------

    def edges(self, new: dict, candidates: dict) -> list[dict]:
        """The import edges added to the new entries (a writer's own edge to a module wins);
        every edge of a new module as {from, to, relation, source}."""
        out = []
        for name, entry in new.items():
            written = entry.get("related_modules", [])
            out += [{"from": name, "to": e["module"], "relation": e["relation"],
                     "source": "writer"} for e in written]
            known = {e["module"] for e in written}
            added = [{"module": e["to"], "relation": "depends-on",
                      "description": f"imports from {e['to']} ({e['imports']} import(s), "
                                     f"init reconcile)"}
                     for e in sorted(candidates[name].get("edges") or [],
                                     key=lambda e: str(e.get("to")))
                     if isinstance(e, dict) and e.get("to") in candidates
                     and e["to"] != name and e["to"] not in known]
            if added:
                entry["related_modules"] = written + added
            out += [{"from": name, "to": e["module"], "relation": "depends-on",
                     "source": "imports"} for e in added]
        return sorted(out, key=lambda e: (e["from"], e["to"], e["source"]))

    def collisions(self, new: dict, files: dict) -> tuple[list[dict], list[dict]]:
        holders: dict[str, list[str]] = {}
        for name, entry in new.items():
            for kw in dict.fromkeys(k.lower() for k in entry["keywords"]):
                holders.setdefault(kw, []).append(name)
        floor = self.ws.config["create"]["min_keywords"]
        rows, judgement = [], []
        for kw in sorted(k for k, mods in holders.items() if len(mods) > 1):
            mods = sorted(holders[kw])
            rx = term_pattern(kw)
            counts = {m: sum(1 for f in files[m] if rx.search(f.lower()) or (
                (t := self.text(f)) is not None and rx.search(t.lower()))) for m in mods}
            top = max(counts.values())
            owners = [m for m in mods if counts[m] == top]
            if len(owners) > 1:
                rows.append({"keyword": kw, "owner": None, "others": mods, "files": counts,
                             "removed": []})
                judgement.append({"kind": "keyword-tie", "keyword": kw, "modules": owners,
                                  "files": counts})
                continue
            removed = []
            for other in (m for m in mods if m != owners[0] and counts[m] == 0):
                entry = new[other]  # a holder whose own files hold the keyword keeps it (D14)
                keep = [k for k in entry["keywords"] if k.lower() != kw]
                if len(set(keep)) < floor:
                    judgement.append({"kind": "keyword-floor", "keyword": kw, "module": other,
                                      "keywords": len(set(entry["keywords"]))})
                    continue
                entry["keywords"] = keep  # every case form of it; never a negative keyword
                removed.append(other)
            rows.append({"keyword": kw, "owner": owners[0],
                         "others": [m for m in mods if m != owners[0]], "files": counts,
                         "removed": removed})
        return rows, judgement

    def duplicates(self, files: dict, new: set[str]) -> list[dict]:
        """The names defined in two modules or more, at least one of them `new` (a name only
        modules created by hand share is theirs: init never writes them)."""
        defined: dict[str, list[dict]] = {}
        for module in sorted(files):
            for rel in files[module]:
                suffix = PurePosixPath(rel).suffix
                if TEST_FILE.search(rel) or not (suffix == ".py" or suffix in JS):
                    continue
                text = self.text(rel)
                if text is None:
                    continue
                pattern = PY_DEF if suffix == ".py" else JS_DEF
                for m in pattern.finditer(text):
                    name = next(g for g in m.groups() if g)
                    if not name.startswith("_"):
                        line = text.count("\n", 0, m.start()) + 1
                        defined.setdefault(name, []).append({"module": module, "file": rel,
                                                             "line": line})
        return [{"name": n, "definitions": sorted(d, key=lambda x: (x["module"], x["file"],
                                                                    x["line"]))}
                for n, d in sorted(defined.items())
                if len(owners := {x["module"] for x in d}) > 1 and owners & new]

    # --- the phase ------------------------------------------------------------------------

    def run(self, force: bool) -> dict:
        flow = self.flow
        state = self.work.require_fanout(flow.load_state())
        if state["phases"]["finish"]["status"] == "done":
            raise UsageError("already finished — see segmently-modules init status")
        waiting = {m: e["status"] for m, e in sorted(state["modules"].items())
                   if e["status"] != "done"}
        if waiting:
            raise UsageError("init reconcile needs every module done — not done: "
                             + ", ".join(f"{m} ({s})" for m, s in waiting.items()))
        recorded = state["phases"]["reconcile"]
        if not force and recorded["status"] == "done" and self.registry_path.is_file() \
                and flow.sha(self.registry_path.read_text(encoding="utf-8")) != recorded["sha256"]:
            raise UsageError("staging registry edited since reconcile — keep the edits, or "
                             "rerun with --force to rebuild from entry.json")
        confirmed = {c["name"]: c for c in self.work.confirmed()}
        existing = {m for m, e in state["modules"].items() if e.get("existing")}
        broken = {m: self.work.entry_problems(self.work.staging_dir(m) / "entry.json")
                  for m in sorted(state["modules"]) if m not in existing}
        broken = {m: p for m, p in broken.items() if p}
        if broken:
            raise UsageError("an entry.json changed since init done — " + "; ".join(
                f"{m}: {', '.join(p)}" for m, p in broken.items()) + " — fix it, then run "
                "segmently-modules init done <module> and segmently-modules init reconcile")
        new = {m: self.entry(m, self.item(state, m)) for m in sorted(state["modules"])
               if m not in existing}
        files = self.module_files({m: confirmed[m] for m in sorted(state["modules"])
                                   if m in confirmed}, flow.files())
        edges = self.edges(new, confirmed)
        collisions, judgement = self.collisions(new, {m: files[m] for m in new})
        duplicates = self.duplicates(files, set(new))  # one created by hand counts: a row only
        judgement += [{"kind": "duplicate", "name": d["name"], "definitions": d["definitions"]}
                      for d in duplicates]
        judgement.sort(key=lambda j: (j["kind"], j.get("keyword") or j.get("name"),
                                      j.get("module", "")))
        for entry in new.values():  # the key order of `create`, then the edges
            if "related_modules" in entry:
                entry["related_modules"] = entry.pop("related_modules")
        registry = self.work.registry_modules()
        top = {k: v for k, v in self.work.registry_raw().items() if k != "modules"}
        doc = {**top, "modules": {**registry, **new}}
        report = {"edges": edges, "collisions": collisions, "duplicates": duplicates,
                  "judgement": judgement}
        flow.mark(state, "reconcile", "running")
        text = serialize(doc)
        flow.write(self.registry_path, text)
        flow.write(self.report_path, serialize(report))
        flow.mark(state, "reconcile", "done", flow.sha(text))
        return {**report, "state": state}
