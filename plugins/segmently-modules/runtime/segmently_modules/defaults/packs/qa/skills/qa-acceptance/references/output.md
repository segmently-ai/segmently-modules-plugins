# output: Part A (the criteria) and Part B (the runnable scenarios)

Steps 7–9 of `qa-acceptance`. The document is written in English, whatever the conversation's
language. A section with nothing in it says so in one line ("none found"); Specification Issues
and Baseline Updates Needed are left out when empty.

## Part A — the criteria document

```markdown
# Acceptance Criteria: <task title>

## Summary
- **Prerequisites:** N | **Core criteria:** N
- **Functional:** N | **Completeness:** N | **Edge cases:** N | **Error handling:** N | **Regression:** N
- **Techniques applied:** EP: N | BVA: N | Decision Table: N | State Transition: N | Pairwise: N | Use Case: N | Error Guessing: N | Exploratory: N
- **Risk distribution:** Critical: N | High: N | Medium: N | Low: N
- **Modules consulted:** <names, or "none">
- **Spec issues found:** N | **Gaps found:** N | **Contradictions:** N (or "N resolved")

## Specification Issues
| # | Issue | Risk | Suggested Resolution |
|---|-------|------|---------------------|

## Task Decomposition
- [ ] ST-1: <a specific, verifiable sub-task> [Technique: EP + BVA, Risk: High] → AC-001, AC-002
(every sub-task links to at least one criterion, every criterion back to a sub-task)

## Dimension Enforcement Check
<the matrix of references/method.md, one row per sub-task, N/A reasons under it>

## Modules Consulted
| Module | qa doc | qa_acceptance doc | Insights added |
|--------|--------|-------------------|----------------|

## Prerequisites
### PRE-001: <title>
**Check:** <what to verify>
**Expected:** <the concrete state>

## Core Acceptance Criteria
### Functional Correctness
#### AC-001: <title>
**Sub-task:** ST-1
**Technique:** <EP | BVA | Decision Table | State Transition | Pairwise | Use Case | Error Guessing | Exploratory> (<the condition>)
**Risk:** <Critical | High | Medium | Low>
**Verification:** <unit | e2e | manual>
- **Given** <the starting state: account, data, device>
- **When** <one action>
- **Then** <the observable result: exact text, count, value, status or file>

### Completeness
### Edge Cases
### Error Handling
### Regression Safety
- baseline-ref: <module> AC-NNN — <title>
(new regression criteria in the AC form above)

## Baseline Updates Needed
| Module | Stale AC | Why stale | Refresh via |
|--------|----------|-----------|-------------|
| <module> | AC-NNN | <how the task changes it> | `qa-acceptance-baseline refresh` on <module> (a block file: its block) |

## Gap Analysis
- All N sub-tasks covered: yes / no
- Gaps found and filled: <list, or "none">; checks fixed before output: <list, or "none">
- Technique coverage: N/N sub-tasks have a formal technique
- Sufficiency verdict: passing every criterion = the task is done: yes / no (what is missing)

## Quality Score
<the table of references/method.md>
```

**PRE or AC:** a check of a second's look that tests no behaviour (a service answers, a fixture
exists, a field is present) is a PRE; anything that needs an action and checks an outcome is an
AC.

**Verification** — the value that decides Part B and the tests written next:

| The criterion checks | Verification |
|---|---|
| what a user sees or does through the product (rendering, moving between views, keyboard use) | `e2e` |
| a save and load round trip through the whole stack | `e2e` |
| a regression of an existing user-facing feature | `e2e` |
| pure logic, validation, a mapping, an architecture rule's code contract | `unit` |
| a failure hard to provoke reliably (the network dropping), a permission state that needs setup by hand | `manual` |

A team whose `qa` doc names another level (for example `integration`) may use it as well; `e2e`
is never dropped or renamed.

## Part B — runnable scenarios

One entry per `e2e` criterion (several criteria that share a path may share one scenario; the
heading names them all).

**Coverage first.** When a touched module's `qa` doc names a coverage map (criterion ids → the
tests that check them), look each `e2e` criterion up in it:
- covered by an existing test and the task does not change that behaviour → no new scenario: a
  line `coverage: covered-by: <test file> > <test name>` saying to run that test as the
  regression proof;
- covered and the task changes it → the scenario carries
  `coverage: updates-existing: <test file> > <test name>`, so the test is changed, not copied;
- not covered → `coverage: new`.
No coverage map named → every scenario is `coverage: new`, and the Part B header says so.

**Format.** The format a touched module's `qa` doc names for its scenario runner or browser
agent, with its selectors, routes and helpers. None named → this checklist:

```markdown
### Story: AC-002 + AC-003 <title>
url: <the entry URL, or the start state for a product without one>
auth: <where the test account comes from: the qa doc's credentials reference, never a secret value>
coverage: new | covered-by: <test file> > <test name> | updates-existing: <test file> > <test name>
- [ ] <a precondition step>
- [ ] <an action step, with the selector the qa doc names>
- [ ] Assert: <the expected result, as concrete as the criterion's Then>
```

The steps are executable — a runner or an agent can follow them without guessing — and every
scenario ends in at least one `Assert:` line. The scenarios are the spec for the tests written
next; tests for new behaviour fail until the work is done.

No `e2e` criterion: Part B is one line, "none: no criterion is verified by e2e".
