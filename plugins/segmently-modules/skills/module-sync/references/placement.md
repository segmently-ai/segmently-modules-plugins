# Placement (module-sync, step 6)

Per module to update, read the change (`git diff <base>..HEAD -- <its files>`; uncommitted:
`git diff <base> -- <its files>` and each new file in full) and its `docs_to_update` (a child's
list holds the parent's docs too). Then put each item where its readers look:

| Doc | Gets | Rule |
|---|---|---|
| module doc | what the module is, its components (name · path · purpose), usage done right and wrong, critical rules | stays short: full signatures, flows and test code go to the role docs; past about 300 lines after the edit, route the excess to them |
| developer | imports, API changes, patterns, gotchas | the session's real code paths; append to the matching section |
| qa | test scenarios, selectors, test patterns | the team's test conventions as its docs state them |
| po | user stories, business rules | only when business behaviour changed |
| architect | architecture, data flows between modules | keep the map across modules coherent |
| designer | UX invariants, anti-patterns | only when the UI changed |
| any other role | what its header says it holds | a doc a skill owns (its header or the team's config names the skill, as a `qa_acceptance` doc belongs to the skill that generates it): never hand-edited — flag it for that skill in the report |

Split modules: area content goes to the child's role doc. A child without its own doc for that
role: `segmently-modules roles add <role> <module>/<child> --json` creates and registers it — never copy the area
content into the parent's baseline, never copy the baseline into the child. Content for the whole
module goes to the parent's baseline; the parent's index gets only cross-cutting tables and the
routing table's line counts. Never touch a `*.legacy.md` file.

A "Related Modules" passage in the module doc says the same as `related_modules` after step 7:
reconcile the prose with the edges.

**Gap check** per module: a component missing from the components table, an API change missing
from the developer doc, a test pattern missing from the qa doc, an architecture or UX change no
doc records, a homeless discovery.

**Quality check** per module at the end of step 6: no template comment (`<!-- … -->`) left, no full
signature in the module doc, every component row has a path and a purpose, no legacy file
touched, each child update in the child the proposal named.

**Budget watch** — the `lint` step of step 9, for every doc in scope: MS030 (a module doc past the
split signal) → propose the trim first (dated history, API dumps and checklists into a
supplementary doc), then `module-split`; MS031 (past the hard stop) → the split is required; a split
parent's index past the signal → cross-cutting content crept in, move it to the children; a child
past it → rebalance its parent; MS032 (a role doc past its budget) → route its excess. Each one is
an action item in the report, never a silent trim.

**Registry** (step 7):
- `related_modules`: when the work made this module rely on another (or share a contract), add
  the edge after checking `related`; an unknown relation is refused with the allowed ones.
- A refused write (exit 2) names the rule it broke: fix the value, never force it.
- Where agents must not write the registry, queue each change and apply them all at once — the
  apply also runs the sync hooks, so step 8 is skipped.

```bash
segmently-modules propose --module <module> --op append --field keywords --value '"<new word>"' --reason "<why>" --json
segmently-modules sync --from-diff <base>..HEAD --apply-proposals --json
```
