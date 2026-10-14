# Lint codes: meaning and fix

Every code the `lint` and `ci` verbs report. **Safe** = a mechanical fix the skill may make;
**Ask** = a decision for the user (offer the options). Module `*` = a config-level finding.

| Code | Meaning | Fix |
|---|---|---|
| MS001 | a required field is missing from an entry | Safe when the value is known (the module's own name, a description from its doc); else Ask |
| MS002 | an entry's `name` differs from its registry key | Safe: set `name` to the key |
| MS003 | `status` is not one of the configured statuses | Ask which status; the error lists the allowed ones |
| MS004 | a `context_files` path is missing on disk | Safe when the file moved (fix the path); Ask when it was deleted |
| MS005 | a registered doc holds NUL bytes or is not valid UTF-8 (damaged) | Safe when git history has a clean version (restore it); else Ask |
| MS006 | a relation name is not one of the configured relations | Ask which relation; the writer's error lists them |
| MS007 | a relation has no `description` | Safe when the docs say why the modules are linked; else Ask |
| MS008 | a relation has no `module` target | Ask which module it points at |
| MS009 | a relation points at a module that is not in the registry | Ask: the module was renamed, merged or removed |
| MS010 | a relation points at a child that does not exist | Ask: the child was renamed or removed |
| MS011 | a deprecated field is present | Ask: the message names the replacement; moving the value is a decision |
| MS012 | a field nobody declared is present | Ask: declare it in the team config or a pack, or remove it |
| MS013 | a value does not match its field type (or a role value that is no doc path, list of doc paths or not-needed mark) | Safe when the intended value is obvious (a string that should be a list; a role value meant as "not needed": the `false` that `roles skip` writes); else Ask |
| MS014 | a directory under the modules directory is not registered | Ask: register it (`module-create`) or remove it |
| MS015 | a role doc is listed for a role that is not configured | Ask: configure the role or drop the doc from `context_files` |
| MS016 | a doc in a module's `roles/` directory that no registry entry names — agents never load it | Safe when the message names the role and it has no doc yet (rename it to `roles/<role>.md`, then `segmently-modules roles add <role> <module> --json`); else Ask: register it as a supplementary doc, merge it into the registered doc, or delete it |
| MS017 | docs directly in a module's directory that no registry entry names (info, one per module) | Ask per doc: register it (`segmently-modules registry append <module> context_files.supplementary '"<path>"' --json`) when agents need it, else leave it or move it out (plans and notes) |
| MS020 | more keywords than the soft budget (info) | Ask: keep, trim or split |
| MS021 | a keyword shared by many modules (info, `*`) | Ask which module the word really routes to |
| MS022 | an empty keyword, which matches every task | Safe: remove it |
| MS023 | a keyword is a generic word (`create`, `user`, `screen`, … in any form; info) | Ask: drop it, or keep it when the module really owns the word |
| MS030 | the module doc is past the split signal | Ask: trim first — move dated history, API dumps and checklists into a supplementary doc and register it (`segmently-modules registry append <module> context_files.supplementary '"<path>"' --json`); `module-split` when it is still too long |
| MS031 | the module doc is past the hard stop | Ask: the trim of MS030, then `module-split` |
| MS032 | a role doc is past its budget | Ask: trim (history and reference sections into a supplementary doc), or split the module |
| MS040 | a path in the components table is missing on disk | Safe when the file moved (fix the path); else Ask |
| MS041 | a link in a registered doc points at a file that is missing (`[lint] link_severity`, default warning) | Safe when the message says where the file is now ("fix the ../ depth") or the file moved; Ask when it was deleted |
| MS042 | a link's `#anchor` names no heading of its target doc (info) | Safe when the heading was renamed (link the new anchor); Ask when the section is gone |
| MS043 | backticked repository paths outside the components table that are missing on disk (info, one per module) | Ask: the code moved (fix the path) or was deleted (drop the sentence); an example path is fine |
| MS050 | code changed but none of the module's docs did (drift) | `module-sync`: the docs need a real update |
| MS051 | a frozen `*.legacy.md` snapshot was modified or deleted | Safe: restore it from git; never edit it |
| MS052 | a routing rule names a module that does not exist (`*`) | Ask: fix the rule in the team config |
| MS053 | two routing rules send one file to two modules (`*`) | Ask which rule wins (`exclusive = true`), whether both modules own the files on purpose (`shared = true` on the narrower rule) or narrow a glob |
| MS054 | an active module maps no code file, so drift never fires for it (info) | Ask: map its code (`segmently-modules code-map add <id> --glob '<dir>/**' --module <module> --dry-run`), list it in `[coverage] doc_only` when it owns no code on purpose, or retire it |
| MS056 | `[coverage] doc_only` names a module that is not in the registry (`*`) | Ask: fix the name in the team config, or drop it |
| MS060 | an unknown key in a pack's `pack.toml` (`*`) | Ask the pack's owner (usually a typo) |
| MS061 | a pack role's template is missing or outside the pack (`*`) | Ask the pack's owner |
| MS062 | a pack skill agents cannot load, or a `references/` file it names that is missing (`*`) | Ask the pack's owner; the message says what is wrong |
| MS063 | an ejected skill is behind its pack (its files changed since the eject, or a repository pack's version did), a pack file it cannot read, a symlink at the ejected path (warning: in the way), or no pack declares it (`*`) | Ask: review `segmently-modules eject <skill> --diff --json`, take what the team wants into the copy by hand, then `segmently-modules eject <skill> --rebase --json` records the pack's current state and clears it (the copy's files stay as they are). Or delete the copy and run `packs sync` (the pack's version returns). A symlink at the ejected path: ask, then remove it (`segmently-modules eject <skill> --json` then makes a real copy) |
| MS064 | a skill reads a role that is not configured or disabled (`*`) | Ask the pack's owner |
| MS065 | two packs declare one skill id; one is shadowed (`*`) | Ask: rename one of the skills |
| MS066 | a repository pack takes a built-in pack's id and replaces that pack (`*`, info) | Nothing to fix when the team owns that pack on purpose; otherwise ask to rename the repository pack |
| MS067 | a copy of a built-in skill in an agent directory while the plugin provides it (`builtin_delivery = "plugin"` for that directory's agent, `*`, info) | Safe: the sync the finding names (`segmently-modules packs sync --json`, with `--agent <agent>` when `[packs] agents` leaves that directory out) removes an unedited copy; an edited copy or an ejected skill's copy stays a conflict — ask |
| MS068 | a skill's `SKILL.md` or one `references/` file is over the skill split signal (`*`, warning) | Ask: a decomposition decision — route its scenarios, split the skill, or keep it on purpose; never trim rules to fit |
| MS069 | a pack's `SKILL.md` files together are over the pack split signal (`*`, warning) | Ask: route, split a skill out, or split the pack |
