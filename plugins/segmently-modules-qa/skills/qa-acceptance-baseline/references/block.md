# block: a baseline split into per-block files

Step 6 of `qa-acceptance-baseline` — write the doc — for a module whose baseline is too large to
review as one file (about 100 criteria or more, many independent blocks). A small or medium
module keeps one doc (follow `references/create.md` or `references/refresh.md` instead).

## The layout

```
roles/qa_acceptance.md                       the index: one row per block file, the highest id
roles/qa_acceptance.legacy.md                (optional) the frozen pre-split baseline
roles/qa_acceptance.<category>/<name>.md     one block's requirements and criteria
```

The categories are the team's, one per kind of block (for example reusable parts, composed
views, cross-cutting lifecycle). The index stays the registered `qa_acceptance` doc; the block
files are linked from it, not registered.

The index:

```markdown
# <Module> — qa_acceptance (index)

> Highest assigned id: AC-NNN. Every block shares one id sequence.

| Block file | Scope | AC range | P0 | P1 | P2 | Last regenerated |
|---|---|---|---|---|---|---|
| [<category>/<name>](qa_acceptance.<category>/<name>.md) | <what it covers> | AC-001 – AC-024 | N | N | N | <date> |
```

A block file:

```markdown
# QA Acceptance — <block> (<module>)

> **Scope:** <what this block covers>
> **Used by:** <the contexts or views that use this block>
> **AC range:** AC-XXX – AC-YYY (N criteria)
> **Last regenerated:** <date>
```

followed by the template's sections for that one block: Summary, Requirements, P0, P1, P2,
Quality Score (and Retired when it has retired criteria).

## Which run

- **The baseline is an index and no block is named:** refresh the index only — read every block
  file, update its rows (range, counts, date) and the highest id. No criterion is written, so
  the gates of steps 3–5 are skipped; show the updated table and wait for "ok" before writing.
- **A block is named:** steps 1–5 run scoped to that one block, with the same gates. New ids
  continue from the highest id in the index; a refresh of the block keeps its ids as
  `references/method.md` says. Write the block file, then refresh the index.
- **A monolithic doc to split** (the user asked, or its size calls for it — ask first): rename it
  to `qa_acceptance.legacy.md`, which is frozen from then on and never edited; write an empty
  index with the highest id `AC-000`; then write the blocks one by one as above. The new files
  restart at AC-001 and never reuse an id among themselves; the index names the legacy file so
  old references can still be traced.

`qa-acceptance` reads the index and only the block files a task touches.
