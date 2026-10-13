# Shapes (module-split, steps 5–6)

Placeholders in `{braces}`; the docs keep the team's own headings below these lines.

**Child module doc** — `submodules/{child}/` next to the parent's module doc (or where `create`
put it):

```markdown
# {Module} / {Child}

> Part of [{module}](<relative path to the parent's module doc>) — {one-line scope}.
> Read together with the parent's docs; sibling areas are in the parent's routing table.

{sections moved verbatim from the parent}
```

**Child role doc** — only for a role with area content:

```markdown
# {Module} / {Child} — {Role}

> Area-specific {role} context for [{child}](<relative path to the child's module doc>).
> Read together with the parent's baseline: [{role}](<relative path to the parent's role doc>)
> (module-wide rules live there, never copied here).

{sections moved verbatim from the parent's role doc}
```

**Parent index** — the parent's module doc after the split:

```markdown
# {Module} (index)

> Split into children: this file routes; full content lives in each child's module doc.
> Pre-split snapshot: [{module doc}.legacy.md](./{module doc}.legacy.md) (frozen, never edited).

## Children

| Child | Scope | Keywords | Lines |
|---|---|---|---|
| [{child}](<relative path>) | {one line} | {routing hints} | {lines} |

{the module-wide content that stayed}
```

**Parent role baseline** — each split role doc after the split:

```markdown
# {Module} — {Role} (baseline)

> Area-specific {role} content moved to the children {child-a}, {child-b} ({date}).
> Pre-split snapshot: [{role}.legacy.md](./{role}.legacy.md) (frozen, never edited).
> This file keeps only what holds for every child.

{the module-wide sections that stayed}
```

Children sit deeper than the parent: rewrite every relative link of a moved section for the new
depth and check that its target resolves.
