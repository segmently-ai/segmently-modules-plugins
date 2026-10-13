# how-to: "how do I … with Segmently Modules"

Step 2 of `module-assistant` for a question about doing something with Segmently Modules.

1. **Find the topic** in the table below and read only that file.
2. **Check before you state.** Run the verb with `--help` for every command you will name: a
   flag the help does not show does not exist. When the answer depends on this repository's
   state, run the read-only command the entry names (e.g. `segmently-modules templates list --json` before
   saying which template wins here).
3. **Answer short, in plain words:** what the user gets and what it changes for them — e.g.
   "new modules will get a Metrics section in their PO doc; the existing PO docs stay as they
   are" — and what you would do. The commands and files in the topic file are yours to run;
   show them only when the user asks how to do it by hand (then drop `--json`).
4. **Offer to do it** in one line. On yes: run it, then `segmently-modules next --json`.

A question no file covers: read the top-level `--help` and the verb's, say what you checked, and
say plainly when Segmently Modules has no way to do it, naming the closest thing it has.

| Topic | File |
|---|---|
| set up, upgrade, agents, built-in packs, the agents' block in CLAUDE.md / AGENTS.md | `references/how-to/setup.md` |
| modules: create, children, status, split, remove or rename, registry layout | `references/how-to/modules.md` |
| roles and templates: add a role, mark a module that does not need a role (and undo it), change a role's or `MODULE.md`'s template | `references/how-to/roles-templates.md` |
| registry fields and code mapping: declare a field, set a value, code pointers, `[[code_map]]`, coverage | `references/how-to/fields-code.md` |
| keeping docs current: after a change, drift, proposals for pipelines, the CI gate | `references/how-to/upkeep.md` |
| packs, skills and hooks: a team pack, sync or eject a skill, `post_sync` hooks | `references/how-to/packs-hooks.md` |
| finding modules for a task: match modes, choose, keywords, routing eval | `references/how-to/search.md` |
