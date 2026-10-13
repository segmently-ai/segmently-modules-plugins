# method: the QA method both QA skills share

`qa-acceptance` applies it to a task's sub-tasks, `qa-acceptance-baseline` to a module's
functional blocks; "unit" below means either.

## The ten test dimensions

| # | Dimension | What to check | Techniques |
|---|---|---|---|
| 1 | Functional (happy path) | the specified behaviour, main and alternate flows | EP, state transition, use case |
| 2 | Negative / error handling | invalid input, a failing dependency, an error answer, a timeout | error guessing, decision table |
| 3 | Boundary / edge cases | min and max, empty, overflow, long or unusual text (Unicode, emoji) | BVA, EP |
| 4 | State management | loading and disabled states, transitions, concurrent edits, stale data | state transition |
| 5 | Data integrity | the save-and-load round trip, concurrent writes, cascading deletes, format | EP, Exploratory |
| 6 | Accessibility | keyboard use, focus, labels for assistive technology, contrast (WCAG 2.1 AA) | checklist |
| 7 | Visual / responsive | layout at each supported size, overflow with dynamic content, colour schemes, right-to-left text | pairwise, Exploratory |
| 8 | Performance | response-time thresholds, rendering, large data sets | BVA on load limits |
| 9 | Security | authorization, input sanitising (injection, script in content), another user's data, role escalation | error guessing, decision table |
| 10 | Concurrency / races | double submit, two sessions at once, rapid repeats, leaving mid-operation | error guessing, state transition |

Skip a dimension only when it does not apply, and write why (a product with no UI marks 6 and
7 N/A for that reason).

**Dimension enforcement check** — fill it after the split, before any criterion:

| Unit | Func | Neg | Bound | State | Data | Acc | Visual | Perf | Sec | Conc | Gaps? |
|---|---|---|---|---|---|---|---|---|---|---|---|

`Y` = applies, will get criteria · `N/A` = does not apply (the reason under the matrix) · `-` =
applies and has no criterion = a gap to fill. More than three N/A in one unit: look again, the
unit may be too narrow.

**Minimum per dimension**, checked once every criterion is written (below it: add targeted
criteria before the closing checks):

| Dimension | Minimum |
|---|---|
| Functional | none: always covered |
| Negative | 1 per unit with user input |
| Boundary | 1 per unit with numeric or length limits |
| State | 1 per unit with toggles or modes |
| Data | 1 per unit that persists data |
| Accessibility | 1 per interactive unit (forms, lists, drag handles, autocomplete) |
| Visual | 1 per unit with conditional rendering |
| Performance | 1 per unit with large data or async work, where a threshold exists |
| Security | 1 per unit that takes external input (markup, URLs, uploads) |
| Concurrency | 1 per unit with async persistence (remote writes, uploads, live listeners) |

## Risk

Impact = what a failure costs (data loss, money, access, a broken flow, cosmetic). Likelihood =
new code, complex logic, a third-party integration, timing.

| Likelihood \ Impact | Low | Medium | High |
|---|---|---|---|
| High | Medium | High | Critical |
| Medium | Low | Medium | High |
| Low | Low | Low | Medium |

The risk sets the depth:

| Risk | Happy path | EP / BVA | Edge cases | Error handling | Regression |
|---|---|---|---|---|---|
| Critical | required | 3-value BVA | exhaustive | every failure mode | full |
| High | required | 2-value BVA | key boundaries | main failures | key paths |
| Medium | required | EP only | 1–2 | the primary failure | spot check |
| Low | required | skip | skip | skip | skip |

In a baseline, P0 = critical and high, P1 = medium, P2 = low.

## Decomposition rules

1. **Flows first.** Before splitting, list every flow the module docs state: each user story of
   the `po` doc is at least one unit, each usage pattern of the module doc at least one, each
   data flow of the `architect` doc covered start to end; list every distinct user action
   (create, edit, delete, rename, connect, configure, open, close, save, discard, undo, redo,
   switch mode, filter, search).
2. **Granularity.** A unit with three or more distinct user interactions is split ("list
   operations" → "create by drag", "delete", "undo and redo").
3. **Minimum count.** A small module or task: 8+ units; medium: 15+; large (20+ components): 20+.
4. **Dimension cross-check.** Every unit against the ten dimensions; an applicable dimension
   with no criterion is a gap.

## Criterion quality

| Anti-pattern | Instead |
|---|---|
| A vague Then: "it works correctly" | "the dialog closes and the title shows 'Updated title'" |
| No threshold: "the page loads fast" | "the page renders within 2 s" |
| No precondition | the Given states the account, the data and the device |
| Compound: unrelated behaviours in one | one behaviour per criterion |
| Implementation-prescriptive: "the store updates" | "the screen shows the change" |
| "No crash" alone | what is shown: "the empty state renders and Add still works" |

A criterion checks what the user sees or what the work produces, never whether internal steps
were followed. **Architecture-rule exception:** a rule the module docs mark MANDATORY,
FORBIDDEN or CRITICAL may name an internal API when the rule itself is the contract ("copies the
state with a deep clone", "reports through the step callback, never the coordinator"); such a
criterion is verified by `unit`.

## Coverage first: reuse, then modify, then create

- **Task** (`qa-acceptance`): a baseline criterion covers the behaviour and the task does not
  change it → reuse it as `baseline-ref: <module> AC-NNN` in Regression Safety, never restated;
  it covers it and the task changes it → a new task criterion, and the old id goes under
  "Baseline Updates Needed" (refreshed through `qa-acceptance-baseline`); nothing covers it → a
  new criterion.
- **Baseline** (`qa-acceptance-baseline`): ids are stable, tests and coverage maps point at
  them. An unchanged criterion keeps its id and text, a changed one is edited in place under the
  same id, a new one continues after the highest id, removed behaviour moves to Retired with its
  id and the reason; never renumber or reuse an id; name the tests that point at a retired id.

## Self-verification, before anything is shown

Both skills:
- [ ] the ten dimensions addressed, or N/A with a reason
- [ ] no vague Then: every result concrete and measurable
- [ ] the technique fits the unit (input → EP + BVA, rule → decision table, workflow → state transition)
- [ ] the depth matches the risk (critical → exhaustive, low → happy path)
- [ ] new ids sequential (AC-001, AC-002, …), no gaps or duplicates
- [ ] the priority matches the risk

Baseline adds: every REQ has a criterion and every criterion traces to a REQ; every architecture
rule has a criterion; a refresh kept every existing id and moved retired ones, never deleted.

Task adds: every sub-task has a criterion and every criterion traces to a sub-task; Part B has
one entry per `e2e` criterion; every touched module's baseline loaded (or its absence said);
Regression Safety filled from the baselines; no task criterion repeats a baseline one.

A failed check is fixed before the output, and the fix is named in the Gap Analysis.

## Quality Score — the last section of every document

| Check | Result | Details |
|---|---|---|
| Dimension coverage | X/10 | each N/A with its reason |
| Criterion quality | X% (Y/Z pass) | the failures |
| Traceability | PASS / FAIL | orphans, if any |
| Technique coverage | X% | units with no formal technique |
| Risk alignment | PASS / FAIL | misaligned items |
| Format compliance | PASS / FAIL | missing sections |
| **Overall** | **PASS / FAIL** | |
