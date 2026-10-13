# ${title} — ${role}

> ${role_description}

<!-- The module's acceptance baseline: the behaviour that must not break, as criteria with
stable ids. Task-level criteria point at these ids instead of restating them. Ids are never
renumbered or reused: a criterion that no longer applies moves to "Retired" with its id. -->

## Summary

<!-- Requirements: N · P0: N · P1: N · P2: N · criteria: N
Techniques: EP N · BVA N · Decision Table N · State Transition N · Pairwise N · Use Case N · Error Guessing N
Dimensions covered: N/10 · architecture rules covered: N/N -->

## Priority Matrix

| # | Block | Risk | P0 | P1 | P2 | Total |
|---|-------|------|----|----|----|-------|

## Block 1: <name>

### Requirements

| ID | Category | Requirement | Source | Technique | Risk | Dimensions |
|----|----------|-------------|--------|-----------|------|------------|

### P0 — must never break

<!-- Critical and high risk. Each criterion in this form:

#### AC-001: <title>
**REQ:** REQ-001
**Technique:** <EP | BVA | Decision Table | State Transition | Pairwise | Use Case | Error Guessing>
**Risk:** <Critical | High>
**Dimension:** <one of the ten>
**Verification:** <unit | e2e | manual>
- **Given** <the starting state>
- **When** <the action>
- **Then** <the observable result: an exact value, message, status or file>
-->

### P1 — should work

<!-- Medium risk, the same form, continuing the ids (AC-002, AC-003, …). -->

### P2 — good to keep

<!-- Low risk, the same form. -->

<!-- One "## Block N: <name>" section per functional block, each with its Requirements and
its P0 / P1 / P2 (a tier with nothing is left out). -->

## Architecture Rule Coverage

| Rule | Source | AC | Status |
|------|--------|----|--------|

## Regression Risks

| Risk | What breaks if it is violated | Related AC |
|------|-------------------------------|------------|

## Specification Issues

<!-- | # | Issue | Impact | Resolution |, or "None found". -->

## Dimension Coverage Matrix

| Dimension | P0 | P1 | P2 | Total | Status |
|-----------|----|----|----|-------|--------|

## Gap Analysis

<!-- Requirements with no criterion · architecture rules without coverage · dimensions without
coverage · contradictions: each a list, or "none". -->

## Quality Score

| Check | Result | Details |
|-------|--------|---------|

## Retired

<!-- Criteria that no longer apply: the id, what it was and why it was retired. -->
