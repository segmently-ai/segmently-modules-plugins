# An already-split module (module-split)

A module whose `show` result has `submodules` is never split again, and none of its
`*.legacy.md` files is ever overwritten. Offer the three paths below, and stop until the user
picks one.

**Add a child** — `module-create` with `--parent <module>`: it creates the child with only the
role docs that get content and adds its row to the parent's routing table. Sections that move
into the new child from a sibling or the parent follow the rebalance rules below.

**Rebalance** — move sections between children, or between a child and the parent:

1. Outline the docs involved (heading · first–last line · length) and propose a table per doc:
   section · lines · from → to. **Stop** until the user confirms.
2. Move the sections verbatim and fix their relative links for the new place. No new legacy copy:
   the moved text is unchanged and the line accounting proves nothing was lost.
3. A child that gains area content for a role it has no doc for:
   `segmently-modules roles add <role> <module>/<child> --json`. A child doc left with no area content:
   delete it and unregister it — the parent's baseline covers that role again:
   `segmently-modules registry set <module>/<child> context_files '<its current object without that role>' --json`.
4. Update the routing table's line counts (and scope, when it moved), then run the checks of
   step 8 (`references/check.md`) on every doc you touched, line accounting before → after.

**Report sizes** — per child and the parent: each doc's lines, the size findings
(`segmently-modules lint --json`: MS030 / MS031 for module docs, MS032 for role docs), and whether the
routing table lists exactly the registered children. Suggest a rebalance or a new child where a
doc crosses a signal.
