# Findings, proposals and the report (module-sync)

Print the findings and the proposals even when you apply them without waiting: the user audits
the run from them.

**Findings** (step 5, before any edit):
- the session's knowledge: the plan goal, then one line per item — kind · module · the fact;
- the modules to update, each with why (a session item, the change, the search) and its files;
  `parent → child` for a split module;
- files outside every module, new-module candidates, homeless items;
- what the team's sync hooks will be asked (when the config has any).

**Proposal** — one block per module:
- the module doc: what to add or correct, by section;
- per role doc: the change and its target (`child` · `parent baseline` · `parent index`); a doc
  another skill owns is listed as flagged;
- the registry: keywords, `related_modules` edges, other fields their hints name;
- the budget: each doc that crosses a signal.

Interactive mode (the user asked for it): after the findings accept `yes / add <module> /
skip <module> / cancel`; after each proposal `ok / skip / edit`.

**Final report** (step 10):
- the plan goal;
- per module: the docs changed (child or baseline), the fields and edges, the docs flagged for the
  skill that owns them;
- the hook messages and errors, the `ci` result;
- budget: each split or routing proposal as an action item (its MS030 / MS031 / MS032 line);
- files outside every module, homeless items;
- every decision you took on your own and every question you asked, with the answer;
- stats: modules, docs and fields changed;
- next: review the diff, then commit — the user commits, never you. A hook message may name a
  follow-up (another doc sync when tests changed): pass it on.
