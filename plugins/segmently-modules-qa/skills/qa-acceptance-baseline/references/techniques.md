# techniques: deriving the test conditions

Both QA skills read this file. Classify each unit, apply its technique(s) mechanically — each
condition becomes one criterion — and let the risk (`references/method.md`) set the depth.
Techniques combine: a payment form takes EP + BVA for the amount, a decision table for the
method rules, and more depth than a cosmetic field.

| Unit | Technique | One criterion per |
|---|---|---|
| An input field, numeric range, text length | **EP + BVA** | partition; boundary value |
| A business rule with several conditions | **decision table** | rule (column) |
| A workflow, multi-step flow, moving between views, mode | **state transition** | valid and key invalid transition |
| A feature with 3+ independent parameters | **pairwise** | row of the pairwise set |
| An actor-system interaction | **use case** | main, alternate and exception flow |
| A known fault pattern | **error guessing** | applicable fault |
| None fits (a cross-cutting round trip, an exploratory probe) | `Exploratory` tag | finding |

A unit with only `Exploratory` criteria: check whether a formal technique would find more.

## Equivalence partitioning (EP)

Split each input into classes that behave alike — valid and invalid — and test one
representative per class. A list that holds 0–50 items: `0` (empty state), `5` (normal), `50`
(full), `51` (refused), `-1` (refused). A colour field: a 6-digit hex, a 3-digit shorthand
(expanded), empty and missing (the default), bad characters, too short, too long (refused).

## Boundary value analysis (BVA)

Bugs gather at the edges between partitions: test the boundary itself and its neighbours.
2-value (standard risk: counts, text lengths, paging): the boundary and the value past it.
3-value (high and critical risk: money, access, data loss, security limits): boundary − 1,
boundary, boundary + 1. A password of 8–20 characters, 3-value: 7 (error "too short"), 8, 9,
19, 20 (accepted), 21 (error "too long").

## Decision table

List the conditions and the outcomes, one column per combination that changes the outcome;
merge columns where a condition does not matter (`—`). Publishing, two conditions:

| | R1 | R2 | R3 | R4 |
|---|---|---|---|---|
| Unsaved changes | yes | yes | no | no |
| Validation errors | no | yes | no | yes |
| Publish allowed | yes | no | yes | no |
| "Save first" warning | yes | — | no | — |
| Errors shown | no | yes | no | yes |

Use it for permissions, conditional UI, pricing, feature flags — any two or more conditions that
drive one outcome.

## State transition

List the states, the valid moves (state + trigger → state, with any guard) and the moves that
must be refused; cover every valid move, the key invalid ones, and every state. A document:
Draft → (submit, required fields filled) → In review → (approve, reviewer's permission) →
Approved → (publish) → Published → (archive, admin only) → Archived → (restore, admin only) →
Draft; In review → (reject) → Draft; Published → (edit) refused: archive first. A multi-step
flow: next and back between steps, back hidden on the first step, back blocked after the final
step, the system back action mid-flow.

## Pairwise

When every combination is too many (more than about ten), cover every pair of parameter values
at least once. Three platforms × three view kinds × two colour schemes = 18 combinations; a pairwise
set of about 8 rows meets every platform–view, platform–scheme and view–scheme pair. Parameters that
depend on each other are a decision table instead.

## Use case

From the actor-system dialogue: the main success flow → the happy-path criterion; each
alternate flow (another valid path) → a variant criterion; each exception flow → a failure
criterion.

## Error guessing

Attack with known fault patterns: null, missing or empty input; double click or rapid repeated
submit; the back action during an async operation; the session expiring mid-operation; the
network dropping during a save; very long strings, special characters, emoji; the same record
changed from two sessions.

## Applying them, per unit

1. Classify: input → EP + BVA; rule → decision table; workflow → state transition; many
   parameters → pairwise; an actor dialogue → use case; plus error guessing on every unit
   with input or persistence.
2. Assess the risk (`references/method.md`): critical and high → deep (3-value BVA, every
   failure mode); medium → EP and the key boundaries; low → the happy path.
3. Generate: each condition the technique produced becomes one criterion; the criterion's
   Technique field names the technique and the condition ("BVA (upper boundary + 1)",
   "decision table (R2)", "state transition (In review → reject → Draft)").
4. Verify: every unit has at least one technique-derived criterion; a unit without one is a gap.
