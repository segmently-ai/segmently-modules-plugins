# rework-audit: diagnose the existing flow before the redesign

Step 5 of `designer`, the rework track only. Before any mock, diagnose the current flow, so the
redesign is driven by evidence, nothing good is lost and every change traces to a named problem.
The output, `<artifacts>/<feature>/AS_IS_AUDIT.md`, feeds the prototype. New work skips it; run it
whenever the task is "simplify", "rework", "this flow is too complicated", "too many steps" or
"users get lost".

## A — As-is path trace

Draw the LITERAL click path to the flow's first unit of value (the first result, the first
successful outcome). Walk it in the running app — never reconstruct it from memory or the code —
and draw it as a tree:

```
Items page
 └─ tab "Drafts" → "Generate" → DIALOG (8 fields) → task wait
     └─ history DIALOG → Apply → list row → DIALOG (5 tabs)
         └─ tab "Outputs" → "Create set" → task wait → item DIALOG (6 concerns)
```

Count and record:

| Metric | This flow | Budget |
|---|---|---|
| Required decisions or fields to the first value | ? | about 3 at most |
| Stacked modal levels | ? | 1 at most |
| Hierarchy levels | ? | 3 at most |
| Entities the user must create first | ? | 0 (created inline) |
| Background-task waits before the first value | ? | as few as possible |

Anything over budget is a simplification signal (FP-1, FP-2, FP-4 of `references/flow-patterns.md`).

## B — Friction and dead-end inventory

Table every dead end, hidden prerequisite, modal over modal, system-speak label and terminal
screen. Give each an id (`D1`, `D2`, …), a location, a severity (Critical / High / Medium) and
the flow pattern it breaks.

| # | Dead end or friction | Where | Severity | Breaks |
|---|---|---|---|---|
| D1 | the empty state needs an entity that lives in another tab | list empty state | High | FP-5 |
| D2 | the generation ends with no next action | item dialog | Critical | FP-6, FP-9 |

A **dead end** = a screen with no primary next action, or a visible reference to an entity the
user cannot reach. A **Critical** finding is any dead end on the main path, or a missing
downstream job (naming, publishing, handing off).

## C — Preserve list (what is GOOD)

Before proposing ANY change, list what already works and must survive the redesign: what the
team relies on to observe the flow, discipline the flow enforces, engines to repackage rather
than rebuild, features a secondary mode still needs. This guards against throwing out
load-bearing behaviour in a cleanup.

## D — Mapping, not demolition

Decide the fate of every existing surface. No surface is deleted silently: each is retargeted
or reused. This is the redesign's contract with the current code, and it shows how much is
presentation only (FP-10).

| Today | Target | Reuse |
|---|---|---|
| a workspace dialog with five tabs | one page with a step rail | services unchanged |
| an item dialog with six concerns | a side panel | content and validation move as they are |

Sum the Reuse column: when most rows reuse existing services, the redesign is a presentation-layer
change (cheap, low risk). New backend needs get their own short list.

## E — Live check of the current build (flows that produce content)

For a flow that generates or computes results, the audit is not complete until you run the real
flow on real data and inspect the OUTPUT, not only the clicks. Produce a few representative
results and catalogue concrete quality findings (`F1`, `F2`, …) with a severity and who fixes
each — text cut mid-word, a result that looks finished but is missing a part: problems invisible
from the click path. Map every F# to the redesign phase that fixes it, so the audit drives the
plan instead of becoming a stale list.

It may spend real provider money or touch real data: state the cost and wait for the user's go.

## The audit file

Write `<artifacts>/<feature>/AS_IS_AUDIT.md` (the skeleton in `references/artifacts.md`): the
step A trace and its metrics, the step B inventory, the step C preserve list, the step D
mapping and, when it ran, the step E findings. The prototype then designs a target where every
D# and F# is resolved and every preserve-list item survives, and the brief cites the audit, so
the review can confirm the dead ends are gone.
