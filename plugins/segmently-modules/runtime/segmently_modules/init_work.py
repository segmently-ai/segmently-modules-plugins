"""`init fanout|next|done` — phase 4 (fan-out): one work item per confirmed module, claimed and
checked one at a time, whoever writes the docs (an agent session, a skill's subagents, a CI
executor: `init run`).

  <config_dir>/init/work/<module>.json   the work item: {module, parent, paths, files (the first
                                         200 of the module's files, in path order), files_total,
                                         neighbours (the proposal's import edges to other
                                         included modules), roles (the roles `create`
                                         scaffolds), staging_dir, prompt} — `existing: true`
                                         (and `prompt: null`) for a module that is already in
                                         the registry: done from the start, never rewritten
  <config_dir>/init/staging/<module>/    what the writer writes: MODULE.md, roles/<role>.md
                                         per role, entry.json {description, keywords,
                                         related_modules?}

The prompt is rendered from the template `init/module_prompt.md` (the template chain: team
override, packs, engine), the doc templates it embeds from `create`'s chain; no `${…}`
placeholder is left in it. A module's status in `state.json`: pending -> running (a claim:
`init next`, `init run`) -> done | failed; `init done` checks the staging output. The problems
of an output `init run` refused stay in the module's entry (`problems`) until its next claim,
which hands them to the writer (`with_problems`: `previous_problems` and `NOTE` after the
prompt; the work item file never changes). Every state change is a read-modify-write under
`state.json.lock`."""
import json
import re
import shutil
import string

from segmently_modules.changes import glob_to_regex
from segmently_modules.config import enabled_roles
from segmently_modules.create import article, ask_fields, resolve_template, resolve_template_source
from segmently_modules.fields import value_matches
from segmently_modules.init_flow import RESTART, strings
from segmently_modules.output import UsageError
from segmently_modules.store import serialize
from segmently_modules.workspace import Workspace

FILES_CAP = 200
DOC_PLACEHOLDERS = {"description": "<one sentence: what the module does, why, when to use it>",
                    "keywords": "<the keywords>", "status": "active", "parent": ""}
_LEFT = re.compile(r"\$\{(\w*)\}?")
_PLACEHOLDER = re.compile(r"\$\{([^}\s]*)\}?")  # `${name}`, or `${name` without its brace
INVENTED = {"path": "path does not exist", "symbol": "symbol not found in its row's file",
            "no-file": "no file to check"}  # the words of `init verify`'s text
PATH_HINT = " (write paths from the repository root, as in the file list)"
NOTE = ("\n## The previous attempt was refused\n\nThe files written last time did not pass "
        "`segmently-modules init done`. Fix each of these problems:\n\n")  # engine text (D3, SI-6)


class CheckError(UsageError):
    """The check itself cannot run for a module (a template it cannot read, its own work item
    missing, damaged or of the wrong shape): exit 2 at `init done`; under `init run` that module
    fails, the run goes on."""


def fence(text: str) -> str:
    """A code fence longer than every backtick run of `text`."""
    runs = [len(m) for m in re.findall(r"`{3,}", text)]
    return "`" * max(3, max(runs, default=0) + 1)


def fill(template: str, values: dict) -> str:
    """`template` with `values` substituted; any placeholder left becomes `<name>`."""
    text = string.Template(template).safe_substitute(values)
    return _LEFT.sub(lambda m: f"<{m.group(1) or 'value'}>", text)


def with_problems(item: dict, problems: list[str]) -> dict:
    """The work item a claim hands out after a refused attempt (D3): `prompt` + `NOTE` + one
    `- <problem>` line each, and `previous_problems` — appended at the claim, so the note may
    quote a `${…}` from a problem line (SI-5)."""
    note = NOTE + "".join(f"- {problem}\n" for problem in problems)
    return {**item, "prompt": (item.get("prompt") or "") + note,
            "previous_problems": list(problems)}


def item_problem(item: dict, module: str) -> str | None:
    """What is wrong with the fields the engine reads of a work item, else None: `module` (the
    name of its file: `init next` returns its path), `roles` (a list of strings: the docs `init
    done` expects, the role docs `planned` counts, the registry's `context_files`) and `prompt`
    (a string: the writer's stdin). Only the items of the modules init writes are read — an
    existing module's (`prompt: null`) never is."""
    wrong = [] if item.get("module") == module else [f"module is not '{module}'"]
    if not strings(item.get("roles")):
        wrong.append("roles is not a list of strings")
    if not isinstance(item.get("prompt"), str):
        wrong.append("prompt is not a string")
    return ", ".join(wrong) or None


def counts(state: dict) -> dict:
    statuses = [m["status"] for m in state["modules"].values()]
    return {s: statuses.count(s) for s in ("pending", "running", "done", "failed")}


class Work:
    """Phase 4 over an `InitFlow` (`flow`): work items, claims, checks."""

    def __init__(self, flow, ws):
        self.flow, self.ws, self.root = flow, ws, flow.root
        self.dir = flow.work / "work"
        self.staging = flow.work / "staging"
        self.claimed: dict[str, int] = {}  # module -> the attempt this Work's claim started

    # --- inputs ---------------------------------------------------------------------------

    def confirmed(self) -> list[dict]:
        """The included candidates of confirmed.json, in its order."""
        doc = self.flow.read_json(self.flow.output("gate-map"))
        return [c for c in (doc or {}).get("candidates", []) if c.get("include") is True]

    def registry_raw(self) -> dict:
        """The registry as the engine reads it (`{"modules": {}}` when there is none yet)."""
        path = self.root / self.ws.config["paths"]["registry"]
        if self.ws.config["paths"]["registry_layout"] == "single" and not path.is_file():
            return {"modules": {}}
        return self.ws.registry.raw

    def registry_modules(self) -> dict:
        return self.registry_raw()["modules"]

    def roles(self) -> list[str]:
        """The roles `create` scaffolds for a module without tags: the standard ones."""
        roles = self.ws.config.get("roles") or {}
        return [r for r in enabled_roles(self.ws.config) if roles[r].get("standard")]

    def targets(self) -> set[str]:
        """The modules an entry's edge may name: the included confirmed ones and the registry."""
        return {c["name"] for c in self.confirmed()} | set(self.registry_modules())

    def item_path(self, module: str):
        return self.dir / f"{module}.json"

    def staging_dir(self, module: str):
        return self.staging / module

    def item(self, module: str) -> dict | None:
        """The work item of `module`, None when its file is missing — the one place a work item
        is read: a file that is not a JSON object, or a field the engine reads of the wrong
        shape (`item_problem`), is a `UsageError` naming the file and the way out."""
        path = self.item_path(module)
        item = self.flow.read_json(path)
        problem = None if item is None else item_problem(item, module)
        if problem:
            raise UsageError(f"{self.flow.rel(path)}: {problem} — fix it, or start over: "
                             f"{RESTART}")
        return item

    # --- the work items -------------------------------------------------------------------

    def build_item(self, candidate: dict, included: set[str], files: list[str],
                   existing: bool) -> dict:
        name = candidate["name"]
        rx = [glob_to_regex(g) for g in candidate["paths"]]
        own = [f for f in files if any(r.match(f) for r in rx)]
        item = {"module": name, "parent": None, "paths": list(candidate["paths"]),
                "files": own[:FILES_CAP], "files_total": len(own),
                "neighbours": [{"to": e["to"], "imports": e["imports"]}
                               for e in candidate.get("edges") or []
                               if isinstance(e, dict) and e.get("to") in included],
                "roles": self.roles(),
                "staging_dir": self.flow.rel(self.staging_dir(name)), "prompt": None}
        if existing:
            item["existing"] = True
        else:
            item["prompt"] = self.prompt(item)
        return item

    def doc_block(self, rel: str, text: str) -> str:
        f = fence(text)
        return f"### `{rel}`\n\n{f}markdown\n{text.rstrip(chr(10))}\n{f}\n"

    def prompt(self, item: dict) -> str:
        """The writer's prompt for one work item (template `init/module_prompt.md`)."""
        name, cfg = item["module"], self.ws.config
        values = {"name": name, "title": name.replace("-", " ").title(), **DOC_PLACEHOLDERS}
        docs = [self.doc_block("MODULE.md", fill(resolve_template(self.ws, "MODULE.md"),
                                                 values))]
        for role in item["roles"]:
            spec = cfg["roles"][role]
            text = fill(resolve_template(self.ws, f"roles/{role}.md", role),
                        {**values, "role": role, "article": article(role),
                         "role_description": spec.get("description", "")})
            docs.append(self.doc_block(f"roles/{role}.md", text))
        extra = ask_fields(self.ws, "module")
        asked = "".join(f"\n  - `{n}`: {d.description or 'a field this repository asks for'} "
                        f"(type {' | '.join(d.type)}; required)" for n, d in extra.items())
        total = item["files_total"]
        note = (f"(the first {len(item['files'])} of {total} files, in path order)"
                if total > len(item["files"]) else f"({total} file{'s' * (total != 1)})")
        values = {"module": name, "staging_dir": item["staging_dir"],
                  "paths": ", ".join(f"`{p}`" for p in item["paths"]), "files_note": note,
                  "files": "\n".join(f"- `{f}`" for f in item["files"]) or "- (no file)",
                  "neighbours": "\n".join(f"- `{n['to']}` ({n['imports']} import(s))"
                                          for n in item["neighbours"]) or "- none found",
                  "docs": "\n".join(docs), "roles": ", ".join(item["roles"]) or "none",
                  "description_min": cfg["create"]["description_min"],
                  "description_max": cfg["create"]["description_max"],
                  "min_keywords": cfg["create"]["min_keywords"],
                  "relations": ", ".join(cfg["registry"]["relations"]), "ask_fields": asked,
                  "modules_dir": cfg["paths"]["modules_dir"],  # the layout init done checks
                  "module_doc": cfg["paths"]["module_doc"]}
        text = fill(resolve_template(self.ws, "init/module_prompt.md"), values)
        return text if text.endswith("\n") else text + "\n"

    def fanout(self) -> dict:
        """Write one work item per included confirmed module and every module's state entry.
        Re-run while every item is pending: the same bytes. Refused after gate 3 is open, when
        an item left pending (run `init resume` / `init run`), when a module directory exists
        without a registry entry, or when a work item file already there cannot be read
        (nothing written)."""
        flow = self.flow
        state = flow.load_state()
        if state is None or state["phases"]["gate-map"]["status"] != "done" \
                or not flow.output("gate-map").is_file():
            raise UsageError("gate 3 has not passed — edit the proposal, then run "
                             "segmently-modules init confirm")
        started = [m for m, e in state["modules"].items()
                   if e["status"] != "pending" and not e.get("existing")]
        if started:
            raise UsageError(f"the fan-out has started ({len(started)} module(s) not pending: "
                             f"{', '.join(sorted(started))}) — continue with segmently-modules init resume "
                             f"or segmently-modules init run")
        registry = self.registry_modules()
        mdir = self.ws.config["paths"]["modules_dir"]
        candidates = self.confirmed()
        conflicts = [c["name"] for c in candidates if c["name"] not in registry
                     and (self.root / mdir / c["name"]).exists()]
        if conflicts:
            raise UsageError(f"{', '.join(f'{mdir}/{n}/' for n in conflicts)} exist(s) without a "
                             f"registry entry — register it with segmently-modules create, or move it "
                             f"away, then run segmently-modules init fanout; nothing written")
        included = {c["name"] for c in candidates}
        files = flow.files()
        items = {c["name"]: self.build_item(c, included, files, c["name"] in registry)
                 for c in sorted(candidates, key=lambda c: c["name"])}
        before = {}  # the items as they are (`status`), read before anything is written
        for path in sorted(self.dir.glob("*.json")) if self.dir.is_dir() else []:
            try:
                before[path.name] = path.read_bytes()
            except OSError as e:
                raise UsageError(f"cannot read {flow.rel(path)}: {e.strerror or e} — remove it, "
                                 f"then run segmently-modules init fanout; nothing written") from None
        flow.mark(state, "fanout", "running")
        texts = {name: serialize(item) for name, item in items.items()}
        for name, text in texts.items():
            flow.write(self.item_path(name), text)
        for stale in sorted(set(before) - {f"{n}.json" for n in items}):
            try:
                (self.dir / stale).unlink()
            except OSError as e:
                raise UsageError(f"cannot write {flow.rel(self.dir / stale)}: "
                                 f"{e.strerror or e}") from None
        state["modules"] = {name: ({"status": "done", "attempts": 0, "error": None,
                                    "existing": True} if item.get("existing") else
                                   {"status": "pending", "attempts": 0, "error": None})
                            for name, item in items.items()}
        digest = "".join(f"{n}\0{flow.sha(t)}\n" for n, t in texts.items())
        flow.mark(state, "fanout", "done", flow.sha(digest))
        unchanged = before == {f"{n}.json": t.encode("utf-8") for n, t in texts.items()}
        return {"items": list(items), "existing": [n for n, i in items.items()
                                                   if i.get("existing")],
                "status": "unchanged" if unchanged else "written", "state": state}

    # --- claims and checks ----------------------------------------------------------------

    def require_fanout(self, state: dict | None) -> dict:
        if state is None or state["phases"]["gate-map"]["status"] != "done":
            raise UsageError("gate 3 has not passed — run segmently-modules init confirm first")
        if state["phases"]["fanout"]["status"] != "done":
            raise UsageError("the fan-out has not run — run segmently-modules init fanout first")
        return state

    def clear(self, module: str, make: bool = False) -> None:
        """Remove a module's staging dir (`make`: then create it empty); a symlinked one — or a
        symlinked staging root — is refused, its target left alone."""
        target = self.staging_dir(module)
        for path in (self.staging, target):
            if path.is_symlink():
                raise UsageError(f"{self.flow.rel(path)} is a symlink — remove it (its target "
                                 f"is left alone)")
        try:
            if target.exists():
                shutil.rmtree(target)
            if make:
                target.mkdir(parents=True)
        except OSError as e:
            raise UsageError(f"cannot write {self.flow.rel(target)}/: {e.strerror or e}") \
                from None

    def reset(self) -> list[str]:
        """Every running or failed module back to pending, its staging dir removed (`attempts`,
        the last error and the refused `problems` kept until the next claim); a done module is
        never touched."""
        state = self.require_fanout(self.flow.load_state())
        if not any(e["status"] in ("running", "failed") for e in state["modules"].values()):
            return []
        with self.flow.locked():
            state = self.flow.load_state()
            stale = sorted(m for m, e in state["modules"].items()
                           if e["status"] in ("running", "failed"))
            for module in stale:
                self.clear(module)
                state["modules"][module]["status"] = "pending"
            self.flow.save_state(state)
        return stale

    def claim(self, module: str | None = None) -> tuple[dict | None, dict]:
        """The first pending module in name order (or `module`, when it is pending), now
        running (attempts + 1, its staging dir cleared and created, its last error and refused
        problems dropped — the problems go to the writer: `with_problems`): (work item or None,
        counts). The item is read before the state is saved: a failure — a work item that is
        damaged, of the wrong shape or missing — leaves the claim undone."""
        self.require_fanout(self.flow.load_state())  # a refusal writes nothing, not even the lock
        with self.flow.locked():
            state = self.require_fanout(self.flow.load_state())
            pending = sorted(m for m, e in state["modules"].items() if e["status"] == "pending")
            if module is not None:
                pending = [module] if module in pending else []
            if not pending:
                return None, counts(state)
            module = pending[0]
            item = self.item(module)
            if item is None:
                raise UsageError(self.missing(state, module))
            self.clear(module, make=True)
            entry = state["modules"][module]
            previous = entry.pop("problems", None)
            entry.update(status="running", attempts=entry["attempts"] + 1, error=None)
            self.flow.save_state(state)
        self.claimed[module] = entry["attempts"]
        return (with_problems(item, previous) if previous else item), counts(state)

    def missing(self, state: dict, module: str) -> str:
        """The refusal of a claim whose work item file is missing, with the way out that works:
        `init fanout` is named only while every new module is `pending` with no attempt — no
        claim since the fan-out wrote the items (`init resume` keeps `attempts`). `init fanout`
        also runs again once `init resume` put every module back to pending, but it would reset
        `attempts` and drop the refused `problems`: then the restart is named."""
        fresh = all(e["status"] == "pending" and not e["attempts"]
                    for e in state["modules"].values() if not e.get("existing"))
        way = "write the work items again: segmently-modules init fanout" if fresh else \
            f"start over: {RESTART}"
        return f"{self.flow.rel(self.item_path(module))} is missing — {way}"

    def linked(self, module: str) -> str | None:
        """The problem of a symlinked staging dir (its target is never read), else None —
        `init done`, `init verify` and `init finish` refuse one."""
        base = self.staging_dir(module)
        if base.is_symlink():
            return (f"the staging dir {self.flow.rel(base)} is a symlink (write the files into "
                    f"a real directory)")
        return None

    def linked_staging(self, state: dict) -> list[str]:
        """`linked` of every module init writes (a module created by hand has no staging)."""
        return [p for m, e in sorted(state["modules"].items())
                if not e.get("existing") and (p := self.linked(m))]

    def template_names(self, item: dict) -> set[str]:
        """The placeholder names of the templates `init` renders for a work item (D4): the
        resolved `MODULE.md`, `roles/<role>.md` per role of the item and `init/module_prompt.md`
        (the template chain: team override, packs, engine) — `$name` and `${name}` alike. A
        template that cannot be read is a `CheckError` naming it."""
        wanted = [("MODULE.md", None), ("init/module_prompt.md", None),
                  *((f"roles/{role}.md", role) for role in item["roles"])]
        names = set()
        for relpath, role in wanted:
            path = resolve_template_source(self.ws, relpath, role)[1]
            try:
                text = path.read_bytes().decode("utf-8")
            except UnicodeDecodeError:
                raise CheckError(f"cannot read {self.flow.rel(path)}: not UTF-8 text") from None
            except OSError as e:
                raise CheckError(f"cannot read {self.flow.rel(path)}: {e.strerror or e}") \
                    from None
            names |= set(string.Template(text).get_identifiers())
        return names

    def planned(self) -> dict:
        """{final path: staging file} of every doc `init finish` will write (D2, SI-3): per new
        module of this init `<modules_dir>/<m>/<module_doc>` and `<modules_dir>/<m>/roles/
        <role>.md` for the roles of its work item — a writer may cite a sibling module's doc
        before it is written (a module created by hand is on disk). A sibling's work item that
        is missing, cannot be read or is of the wrong shape counts as its main doc only."""
        state = self.require_fanout(self.flow.load_state())
        paths = self.ws.config["paths"]
        out = {}
        for module, entry in sorted(state["modules"].items()):
            if entry.get("existing"):
                continue
            final, base = f"{paths['modules_dir']}/{module}", self.staging_dir(module)
            out[f"{final}/{paths['module_doc']}"] = base / "MODULE.md"
            try:
                item = self.item(module)
            except UsageError:  # never another module's problem: this one is judged on its docs
                item = None
            for role in item["roles"] if item is not None else []:
                out[f"{final}/roles/{role}.md"] = base / "roles" / f"{role}.md"
        return out

    def invented_problems(self, module: str, texts: dict) -> list[str]:
        """The invented-component check of `init verify` over a module's own docs (D2): `texts`
        = {`MODULE.md` / `roles/<role>.md`: its text}, read at their final paths; a path exists
        inside the root or among the `planned` docs. One line per finding, in doc and line
        order, in the words a writer can act on."""
        if not texts:
            return []
        from segmently_modules.init_verify import invented  # lazy: init_verify imports eval_cmd -> this
        paths = self.ws.config["paths"]
        final = f"{paths['modules_dir']}/{module}"
        docs = {rel: f"{final}/{paths['module_doc']}" if rel == "MODULE.md" else f"{final}/{rel}"
                for rel in texts}
        ws = Workspace(self.ws.root, self.ws.config_dir, self.ws.config, self.ws.fields,
                       overlay=self.planned())
        found = invented(ws, {doc: texts[rel] for rel, doc in docs.items()})
        back = {doc: rel for rel, doc in docs.items()}
        return [f"{back[f['doc']]}:{f['line']}: {INVENTED[f['kind']]}: {f['token']}"
                f"{PATH_HINT if f['kind'] == 'path' else ''}" for f in found]

    def problems(self, module: str) -> list[str]:
        """What keeps a module's staging output from `done` (SI-8), one line each: the files,
        then the invented components of every doc that could be read (`invented_problems`,
        SI-1), then `entry.json`; a symlinked staging dir is one problem (its target is never
        read). A doc is refused for a placeholder only when it holds `${<name>}` of one of
        `template_names` — any other `${…}` (a shell variable, a JavaScript template string) is
        text (D4). Its own work item missing, damaged or of the wrong shape is a `CheckError`
        naming the file."""
        try:
            item = self.item(module)
        except UsageError as e:  # damaged or wrong-shaped: exit 2 at init done, failed in run
            raise CheckError(str(e)) from None
        if item is None:
            raise CheckError(self.missing(self.require_fanout(self.flow.load_state()), module))
        base = self.staging_dir(module)
        linked = self.linked(module)
        if linked:
            return [linked]
        expected = ["MODULE.md", *(f"roles/{r}.md" for r in item["roles"]), "entry.json"]
        found = sorted(p.relative_to(base).as_posix() for p in base.rglob("*")
                       if p.is_file() or p.is_symlink()) if base.is_dir() else []
        out = [f"missing {rel}" for rel in expected if rel not in found]
        out += [f"unexpected file {rel}" for rel in found if rel not in expected]
        names = None  # the templates' placeholder names: resolved once, when a doc holds `${`
        texts = {}  # the docs the invented-component check reads: present, UTF-8, not empty
        for rel in expected[:-1]:
            path = base / rel
            if rel not in found:
                continue
            if path.is_symlink():
                out.append(f"{rel} is a symlink (write the file itself)")
                continue
            try:
                text = path.read_bytes().decode("utf-8")
            except (OSError, UnicodeDecodeError) as e:
                out.append(f"{rel}: cannot read it as UTF-8 text ({e})")
                continue
            if not text.strip():
                out.append(f"{rel} is empty")
                continue
            texts[rel] = text
            if "${" in text:
                names = self.template_names(item) if names is None else names
                left = next((m.group(0) for m in _PLACEHOLDER.finditer(text)
                             if m.group(1) in names), None)
                if left:
                    out.append(f"{rel}: unfilled placeholder {left}")
        out += self.invented_problems(module, texts)
        if "entry.json" in found and not (base / "entry.json").is_symlink():
            out += self.entry_problems(base / "entry.json")
        elif "entry.json" in found:
            out.append("entry.json is a symlink (write the file itself)")
        return out

    def entry_problems(self, path) -> list[str]:
        try:
            entry = json.loads(path.read_bytes().decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return ["entry.json: invalid JSON"]
        if not isinstance(entry, dict):
            return ["entry.json: not an object"]
        cfg = self.ws.config
        extra = ask_fields(self.ws, "module")
        allowed = {"description", "keywords", "related_modules", *extra}
        out = [f"entry.json: unknown key '{k}'" for k in sorted(entry) if k not in allowed]
        low, high = cfg["create"]["description_min"], cfg["create"]["description_max"]
        desc = entry.get("description")
        if not isinstance(desc, str) or not low <= len(desc.strip()) <= high:
            out.append(f"description must be {low}–{high} characters")
        kws = entry.get("keywords")
        need = cfg["create"]["min_keywords"]
        if not (isinstance(kws, list) and all(isinstance(k, str) and k.strip() for k in kws)
                and len(set(kws)) >= need):
            out.append(f"at least {need} distinct keywords (a list of non-empty strings)")
        for name, fdef in extra.items():
            if name not in entry:
                out.append(f"entry.json: missing '{name}' (a field this repository asks for)")
            elif not value_matches(fdef, entry[name]):
                out.append(f"entry.json: '{name}' does not match type {' | '.join(fdef.type)}")
        edges = entry.get("related_modules", [])
        if not isinstance(edges, list):
            return out + ["related_modules must be a list of edges"]
        targets, relations = self.targets(), cfg["registry"]["relations"]
        for i, edge in enumerate(edges):
            if not isinstance(edge, dict):
                out.append(f"related_modules[{i}]: not an object")
                continue
            if edge.get("module") not in targets:
                out.append(f"related_modules[{i}]: '{edge.get('module')}' is not a confirmed "
                           f"module")
            if edge.get("relation") not in relations:
                out.append(f"related_modules[{i}]: relation '{edge.get('relation')}' is not in "
                           f"the relations ({', '.join(relations)})")
            if not isinstance(edge.get("description"), str) or not edge["description"].strip():
                out.append(f"related_modules[{i}]: missing description")
            unknown = sorted(set(edge) - {"module", "relation", "description"})
            if unknown:
                out.append(f"related_modules[{i}]: unknown key '{unknown[0]}'")
        return out

    def done(self, module: str) -> tuple[str, list[str]]:
        """`init done <module>`: (status, problems) — `done` when the staging output is
        complete; a pending or unknown module is exit 2; an item already done stays done. The
        check runs outside the lock: the item is marked `done` only if nobody put it back or
        claimed it again meanwhile (the same attempt, still running or failed)."""
        state = self.require_fanout(self.flow.load_state())
        modules = state["modules"]
        if module not in modules:
            raise UsageError(f"unknown module '{module}' (modules: {', '.join(sorted(modules))})")
        status, attempts = modules[module]["status"], modules[module]["attempts"]
        if status == "done":
            return "already done", []
        if status == "pending":
            raise UsageError(f"'{module}' is pending — claim it first: segmently-modules init next")
        problems = self.problems(module)
        if problems:
            return status, problems
        with self.flow.locked():
            state = self.flow.load_state()
            entry = state["modules"][module]
            if entry["status"] == "done":
                return "done", []
            if entry["status"] == "pending" or entry["attempts"] != attempts:
                return entry["status"], [f"changed while it was checked (now {entry['status']}, "
                                         f"attempt {entry['attempts']}): nothing marked — check "
                                         f"it again once it is written"]
            entry.update(status="done", error=None)
            entry.pop("problems", None)  # a failed run's: a done module is never claimed again
            self.flow.save_state(state)
        return "done", []
