# Checks and report (module-split, steps 8–9)

**Checks** — after the `lint`, `lint --changed` and `show` runs of step 8 (`--base HEAD` is the
state before the split while nothing is committed; after a commit, pass the commit the split
started from); fix what fails before the report:

- no MS030 / MS031 left for the parent; every child doc under its budgets;
- `lint --changed` shows no MS051: adding the legacy copies is fine, editing or deleting one is not;
- the parent's `keywords` equal what they were before step 3;
- the parent's routing table lists every child, with its line count;
- every role doc registered for a child exists and holds area content — no template comment
  (`<!-- … -->`) left; a role with no area content has no child doc at all;
- every relative link in the new and rewritten docs resolves from its own directory;
- line accounting, per split doc: the children's sections plus what the parent kept is close to
  the legacy copy's total (headers and the routing table aside) — explain any loss over 5 %.

**Report:**
- the children: scope, lines of the module doc and of each role doc;
- what stayed in the parent's index and in each baseline;
- the line accounting per split doc;
- the routing rules added;
- follow-ups: the roles left unsplit and why; a child that renders UI and should get a designer
  doc (when that role is on); a role doc another skill generates that a child now lacks.
