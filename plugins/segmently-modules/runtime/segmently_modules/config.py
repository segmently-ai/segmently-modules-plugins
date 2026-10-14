from __future__ import annotations

import copy
import re
from importlib import resources
from pathlib import Path

from segmently_modules import __version__
from segmently_modules._toml import tomllib
from segmently_modules.merge import merge_layers
from segmently_modules.output import UsageError

PACK_META_KEYS = {"id", "version", "priority", "requires", "description", "skills", "agents"}
DEFAULT_PACK_PRIORITY = 50
BUILTIN_PACKS = ("core", "qa", "ui")  # the packs the engine ships: segmently_modules/defaults/packs/<id>/
BUILTIN_PLUGINS = {"core": "segmently-modules", "qa": "segmently-modules-qa", "ui": "segmently-modules-ui"}  # pack -> its plugin
BUILTIN_DELIVERY = ("repo", "plugin")  # [packs] builtin_delivery: packs sync, or the plugins
REGISTRY_LAYOUTS = ("single", "per-module")


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


# value type name -> (check, wording used in error messages)
_TYPES = {
    "str": (lambda v: isinstance(v, str), "a string"),
    "int": (_is_int, "an integer"),
    "int>=1": (lambda v: _is_int(v) and v >= 1, "an integer >= 1"),
    "bool": (lambda v: isinstance(v, bool), "a boolean"),
    "list[str]": (lambda v: isinstance(v, list) and all(isinstance(i, str) for i in v),
                  "a list of strings"),
    "number": (lambda v: isinstance(v, (int, float)) and not isinstance(v, bool), "a number"),
    "str|table": (lambda v: isinstance(v, (str, dict)), "a string or a table"),
}
# Only KNOWN keys are checked; unknown keys and sections pass (forward compatibility).
LAYER_SCHEMA = {
    "paths": {k: "str" for k in ("modules_dir", "registry", "registry_layout", "module_doc",
                                 "module_entry", "proposals_dir")},
    "registry": {"statuses": "list[str]", "relations": "list[str]", "dir_whitelist": "list[str]",
                 "stub_pattern": "str", "updated_at_path": "str"},
    "budgets": {**{k: "int" for k in ("module_doc_split_signal", "module_doc_hard_stop",
                                      "role_doc_max", "keywords_soft", "keyword_shared_warn")},
                "skill_split_signal": "int>=1", "pack_split_signal": "int>=1"},
    "match": {**{k: "int" for k in ("keyword_weight", "combination_weight", "negative_weight",
                                    "min_score", "top")}, "mode": "str"},
    "lint": {"fail_on": "str", "component_table_heading": "str", "drift_severity": "str",
             "overlap_severity": "str", "link_severity": "str"},
    "create": {"min_keywords": "int", "description_min": "int", "description_max": "int",
               "default_status": "str"},
    "coverage": {"include": "list[str]", "exclude": "list[str]", "doc_only": "list[str]"},
    "ci": {"fail_on": "str", "base": "str", "coverage_fail_under": "number"},
    "packs": {"agents": "list[str]", "builtin": "list[str]", "builtin_delivery": "str|table"},
    "init": {"exclude": "list[str]", "co_change_commits": "int", "max_parallel": "int",
             "routing_min_hit_rate": "number"},
}
CI_FAIL_ON = ("error", "never", "warning")
MATCH_MODES = ("lexical", "semantic", "hybrid")  # [match] mode / --match (P8.1 S1)
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,99}")
EFFORTS = ("quick", "standard", "deep")  # [search] effort (P8.1 S9)
CARD_KEYWORDS_DEFAULT = 10  # [search] card_keywords (P8.2 D2)
SEARCH_DEFAULTS = {"claude_model": "sonnet", "codex_model": "gpt-5.6-luna", "effort": "standard"}
ROLE_SCHEMA = {"order": "int", "enabled": "bool", "standard": "bool", "description": "str",
               "applies_when": "str", "template": "str"}


def _require_table(value, section: str, source) -> dict:
    if not isinstance(value, dict):
        raise UsageError(f"{source}: [{section}] must be a table, got {value!r}")
    return value


def search_settings(config: dict) -> dict:
    """`[search]` of the merged config (the user config wins per key), defaults filled in."""
    table = config.get("search") or {}
    return {key: table.get(key, default) for key, default in SEARCH_DEFAULTS.items()}


def card_keywords(config: dict) -> int:
    """`[search] card_keywords` of the merged config: how many keywords a work-order card
    carries (D2). Read apart from `search_settings` so `catalog` keeps its three keys."""
    table = config.get("search") or {}
    return table.get("card_keywords", CARD_KEYWORDS_DEFAULT)


def _validate_search(table, source) -> None:
    table = _require_table(table, "search", source)
    if "card_keywords" in table:
        v = table["card_keywords"]
        if not _is_int(v) or v < 0:
            raise UsageError(f"{source}: [search] card_keywords: expected an integer >= 0, "
                             f"got {v!r}")
    for key in ("claude_model", "codex_model"):
        if key not in table:
            continue
        v = table[key]
        if not isinstance(v, str) or not _MODEL.fullmatch(v):
            raise UsageError(f"{source}: [search] {key}: expected a model name — 1 to 100 "
                             f"characters of letters, digits and . _ : / @ + -, not starting "
                             f"with a dash (it becomes an item of your agent command), "
                             f"got {v!r}")
    if "effort" in table and table["effort"] not in EFFORTS:
        raise UsageError(f"{source}: [search] effort: expected one of {', '.join(EFFORTS)}, "
                         f"got {table['effort']!r}")


def _check_table(table: dict, schema: dict, section: str, source) -> None:
    for key, type_name in schema.items():
        if key in table:
            check, expected = _TYPES[type_name]
            if not check(table[key]):
                raise UsageError(f"{source}: [{section}] {key}: expected {expected}, "
                                 f"got {table[key]!r}")


def validate_layer(layer: dict, source) -> None:
    """Type-check the known keys of one config layer (a pack, config.toml or
    config.user.toml) before it is merged; `source` names the file in errors. `[agent]` is
    refused in every layer: the agent command comes from the environment only."""
    if "agent" in layer:
        from segmently_modules.agent import validate_agent_table  # agent reads this module
        validate_agent_table(layer["agent"], source)
    if "search" in layer:
        _validate_search(layer["search"], source)
    init = layer.get("init")
    if isinstance(init, dict) and "max_parallel" in init and \
            not (_is_int(init["max_parallel"]) and init["max_parallel"] >= 1):
        raise UsageError(f"{source}: [init] max_parallel must be an integer >= 1, got "
                         f"{init['max_parallel']!r}")
    rate = init.get("routing_min_hit_rate", 0.5) if isinstance(init, dict) else 0.5
    if not (isinstance(rate, (int, float)) and not isinstance(rate, bool) and 0 <= rate <= 1):
        raise UsageError(f"{source}: [init] routing_min_hit_rate must be a number from 0 to 1, "
                         f"got {rate!r}")
    for section, schema in LAYER_SCHEMA.items():
        if section in layer:
            _check_table(_require_table(layer[section], section, source), schema, section, source)
    pattern = layer.get("registry", {}).get("stub_pattern")
    if pattern is not None:
        try:
            re.compile(pattern)
        except re.error as e:
            raise UsageError(f"{source}: [registry] stub_pattern: invalid regular expression: "
                             f"{e}") from None
    for key in ("drift_severity", "overlap_severity", "link_severity"):
        severity = layer.get("lint", {}).get(key)
        if severity is not None and severity not in ("info", "warning", "error"):
            raise UsageError(f"{source}: [lint] {key}: expected info, warning or error, "
                             f"got {severity!r}")
    if layer.get("coverage", {}).get("include") == []:
        raise UsageError(f"{source}: [coverage] include: an empty list counts no file — omit "
                         f"include to count every file")
    ci = layer.get("ci", {})
    if "fail_on" in ci and ci["fail_on"] not in CI_FAIL_ON:
        raise UsageError(f"{source}: [ci] fail_on: expected one of {', '.join(CI_FAIL_ON)}, "
                         f"got {ci['fail_on']!r}")
    if "coverage_fail_under" in ci and not 0 <= ci["coverage_fail_under"] <= 100:
        raise UsageError(f"{source}: [ci] coverage_fail_under: expected a number 0–100, "
                         f"got {ci['coverage_fail_under']!r}")
    agents = layer.get("packs", {}).get("agents")
    if agents is not None:
        from segmently_modules.skills import AGENT_DIRS  # skills imports this module
        unknown = [a for a in agents if a not in AGENT_DIRS]
        if unknown:
            raise UsageError(f"{source}: [packs] agents: unknown agent {unknown[0]!r} "
                             f"(agents: {', '.join(AGENT_DIRS)})")
    _check_builtin(layer.get("packs", {}).get("builtin"), source)
    _check_delivery(layer.get("packs", {}).get("builtin_delivery"), source)
    layout = layer.get("paths", {}).get("registry_layout")
    if layout is not None and layout not in REGISTRY_LAYOUTS:
        raise UsageError(f"{source}: [paths] registry_layout: expected one of "
                         f"{list(REGISTRY_LAYOUTS)}, got {layout!r}")
    top = layer.get("match", {}).get("top")
    if top is not None and top < 0:
        raise UsageError(f"{source}: [match] top: expected an integer >= 0, got {top!r}")
    mode = layer.get("match", {}).get("mode")
    if mode is not None and mode not in MATCH_MODES:
        raise UsageError(f"{source}: [match] mode: expected one of {', '.join(MATCH_MODES)}, "
                         f"got {mode!r}")
    commits = layer.get("init", {}).get("co_change_commits")
    if commits is not None and commits < 0:
        raise UsageError(f"{source}: [init] co_change_commits: expected an integer >= 0, got "
                         f"{commits!r}")
    from segmently_modules.changes import glob_to_regex, validate_code_map  # lazy: keeps config light
    for glob in layer.get("init", {}).get("exclude") or []:
        try:
            glob_to_regex(glob)
        except re.error as e:
            raise UsageError(f"{source}: [init] exclude: glob {glob!r} is not a valid pattern: "
                             f"{e}") from None
    from segmently_modules.hooks import validate_hooks  # hooks imports proposals -> store; keep lazy
    validate_hooks(layer, source, _check_table)
    validate_code_map(layer, source, _check_table)
    for section in ("roles", "fields"):
        for name, spec in _require_table(layer.get(section, {}), section, source).items():
            _require_table(spec, f"{section}.{name}", source)
            if section == "roles":
                _check_table(spec, ROLE_SCHEMA, f"roles.{name}", source)


def _check_builtin(ids, source) -> None:
    unknown = [i for i in ids or [] if i not in BUILTIN_PACKS]
    if unknown:
        raise UsageError(f"{source}: [packs] builtin: unknown built-in pack {unknown[0]!r} "
                         f"(built-in packs: {', '.join(BUILTIN_PACKS)})")


def _check_delivery(value, source) -> None:
    """`[packs] builtin_delivery`: a string (every agent) or a table {agent: value}; agents that
    read the same directory (codex, cursor, gemini, copilot: `.agents/skills`) need the same
    value."""
    if value is None:
        return
    where = f"{source}: [packs] builtin_delivery"
    if isinstance(value, str):
        if value not in BUILTIN_DELIVERY:
            raise UsageError(f"{where}: expected one of {', '.join(BUILTIN_DELIVERY)}, "
                             f"got {value!r}")
        return
    from segmently_modules.skills import AGENT_DIRS  # skills imports this module
    by_dir: dict[str, tuple[str, str]] = {}
    for agent, v in value.items():
        if agent not in AGENT_DIRS:
            raise UsageError(f"{where}: unknown agent {agent!r} (agents: {', '.join(AGENT_DIRS)})")
        if v not in BUILTIN_DELIVERY:
            raise UsageError(f"{where}: {agent}: expected one of {', '.join(BUILTIN_DELIVERY)}, "
                             f"got {v!r}")
        first = by_dir.setdefault(AGENT_DIRS[agent], (agent, v))
        if first[1] != v:
            raise UsageError(f"{where}: {first[0]} and {agent} read the same directory "
                             f"({AGENT_DIRS[agent]}) and need the same delivery")


def delivery_for(config: dict, agent: str) -> str:
    """The built-in skills' delivery for one agent: "repo" — `packs sync` copies them into the
    agent's directory — or "plugin" — a segmently-modules plugin provides them there, and `packs sync`
    removes the copies it made. `[packs] builtin_delivery` is a string (every agent) or a table
    {agent: value}; an agent the table leaves out takes the value of an agent that reads the
    same directory, else "repo". Set in the team or the user config (the user's wins); a pack
    cannot set it."""
    value = (config.get("packs") or {}).get("builtin_delivery", "repo")
    if isinstance(value, str):
        return value
    if agent in value:
        return value[agent]
    from segmently_modules.skills import AGENT_DIRS  # skills imports this module
    shared = [v for a, v in value.items() if AGENT_DIRS.get(a) == AGENT_DIRS.get(agent)]
    return shared[0] if shared else "repo"


def plugin_agents(config: dict, agents) -> set[str]:
    """The agents among `agents` whose built-in skills a plugin provides (`delivery_for`)."""
    return {a for a in agents if delivery_for(config, a) == "plugin"}


def builtin_delivery(config: dict) -> str:
    """`[packs] builtin_delivery` as one word (P6 D2): "repo" (the default) or "plugin" for
    every agent, "mixed" when a table gives both (`delivery_for` answers per agent)."""
    value = (config.get("packs") or {}).get("builtin_delivery", "repo")
    if isinstance(value, str):
        return value
    from segmently_modules.skills import AGENT_DIRS  # skills imports this module
    kinds = {delivery_for(config, a) for a in AGENT_DIRS}
    return kinds.pop() if len(kinds) == 1 else "mixed"


def shown(path: Path, root: Path | None):
    """`path` as a message names it: root-relative (posix) inside `root`, else as given."""
    if root is not None:
        try:
            return Path(path).relative_to(root).as_posix()
        except ValueError:
            pass
    return path


def read_toml(path: Path) -> dict:
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise UsageError(f"{path}: invalid TOML: {e}") from e
    except OSError as e:
        raise UsageError(f"{path}: cannot read: {e}") from e


def core_defaults() -> dict:
    text = resources.files("segmently_modules").joinpath("defaults/config.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)


def builtin_packs_root() -> Path:
    """The engine's built-in packs (package data): one directory per id in BUILTIN_PACKS."""
    return Path(str(resources.files("segmently_modules").joinpath("defaults/packs")))


def enabled_builtins(config_dir: Path, root: Path | None = None, user: bool = True) -> list[str]:
    """`[packs] builtin` of the team config and the user config — appended, de-duplicated. Read
    before the merge: it decides which built-in packs are config layers at all. A refusal names
    the file root-relative when `root` is given and holds it. `user=False`: the team config
    only."""
    ids: list[str] = []
    for name in ("config.toml", "config.user.toml") if user else ("config.toml",):
        path = config_dir / name
        if path.exists():
            source = shown(path, root)
            packs = _require_table(read_toml(path).get("packs", {}), "packs", source)
            _check_table(packs, LAYER_SCHEMA["packs"], "packs", source)
            _check_builtin(packs.get("builtin"), source)
            ids += [i for i in packs.get("builtin", []) if i not in ids]
    return ids


def discover_packs(config_dir: Path, root: Path | None = None, user: bool = True) -> list[dict]:
    """Active packs, highest precedence first: the repository's packs (lowest priority number,
    then id), then the built-in packs `[packs] builtin` enables, by id — below every repository
    pack whatever its priority. A repository pack with a built-in id replaces that built-in pack.
    A built-in pack's version is the engine version. `root`: the `[packs] builtin` refusals name
    their files root-relative. `user=False`: built-in packs the user config enables do not
    count."""
    from segmently_modules.skills import validate_skills  # skills imports this module
    packs = []
    for pack_toml in sorted((config_dir / "packs").glob("*/pack.toml")):
        data = read_toml(pack_toml)
        priority = data.get("priority", DEFAULT_PACK_PRIORITY)
        if not _is_int(priority):
            raise UsageError(f"{pack_toml}: priority must be an integer, got {priority!r}")
        pack_id = data.get("id", pack_toml.parent.name)
        if not isinstance(pack_id, str) or not pack_id:
            raise UsageError(f"{pack_toml}: id must be a non-empty string, got {pack_id!r}")
        if isinstance(data.get("packs"), dict) and "builtin" in data["packs"]:
            team = shown(config_dir / "config.toml", root)
            raise UsageError(f"{shown(pack_toml, root)}: [packs] builtin: a pack cannot enable "
                             f"built-in packs — set it in {team}")
        if isinstance(data.get("packs"), dict) and "builtin_delivery" in data["packs"]:
            team = shown(config_dir / "config.toml", root)
            raise UsageError(f"{shown(pack_toml, root)}: [packs] builtin_delivery: a pack cannot "
                             f"choose how the built-in skills are delivered — set it in {team} "
                             f"(or config.user.toml)")
        validate_skills(data, pack_toml)
        packs.append({"id": pack_id, "priority": priority, "path": pack_toml, "data": data,
                      "builtin": False})
    packs.sort(key=lambda p: (p["priority"], p["id"]))
    taken = {p["id"] for p in packs}
    for pack_id in sorted(set(enabled_builtins(config_dir, root, user)) - taken):
        pack_toml = builtin_packs_root() / pack_id / "pack.toml"
        data = {**read_toml(pack_toml), "id": pack_id, "version": __version__}
        validate_skills(data, pack_toml)
        packs.append({"id": pack_id, "priority": None, "path": pack_toml, "data": data,
                      "builtin": True})
    return packs


def _pack_layer(pack: dict) -> dict:
    """The pack's config layer. A deep copy, so the parsed pack data stays untouched; every
    field, role and hook the pack declares records the pack as its `owner` (provenance for
    error messages and hook paths), and a role that declares a `template` records the pack as
    its `template_owner` (the template is a file of that pack, even when a later layer
    overrides other keys of the role)."""
    layer = {k: copy.deepcopy(v) for k, v in pack["data"].items() if k not in PACK_META_KEYS}
    validate_layer(layer, pack["path"])
    for section in ("fields", "roles"):
        for spec in (layer.get(section) or {}).values():
            spec.setdefault("owner", pack["id"])
            if section == "roles" and "template" in spec:  # the template lives in THIS pack,
                spec.setdefault("template_owner", pack["id"])  # whoever overrides the role
    for hooks in (layer.get("hooks") or {}).values():
        for hook in hooks if isinstance(hooks, list) else []:
            if isinstance(hook, dict):
                hook.setdefault("owner", pack["id"])
    return layer


def load_config(config_dir: Path, root: Path | None = None, extra: dict | None = None,
                extra_source: str = "", user: bool = True) -> dict:
    """The merged config. `extra`: one more layer right after the team config (before the user
    config) — `adopt` lints against the config it is about to write this way. `user=False`:
    without `config.user.toml` (what `adopt` infers a team file from)."""
    packs = discover_packs(config_dir, root, user)
    layers = [core_defaults()] + [_pack_layer(p) for p in reversed(packs)]
    for name in ("config.toml", "config.user.toml") if user else ("config.toml",):
        path = config_dir / name
        if path.exists():
            layer = read_toml(path)
            validate_layer(layer, path)
            layers.append(layer)
        if name == "config.toml" and extra is not None:
            validate_layer(extra, extra_source)
            layers.append(extra)
    config = merge_layers(layers)
    config["_packs"] = [p["id"] for p in packs]
    config["_pack_dirs"] = {p["id"]: str(p["path"].parent) for p in packs}
    return config


def enabled_roles(config: dict) -> list[str]:
    roles = config.get("roles") or {}
    active = [(spec.get("order", 1000), name) for name, spec in roles.items()
              if spec.get("enabled", True)]
    return [name for _, name in sorted(active)]
