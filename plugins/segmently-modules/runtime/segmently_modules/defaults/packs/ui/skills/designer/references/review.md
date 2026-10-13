# review: screenshots of the running app against the docs and the patterns

Step 7 of `designer`: a critique of what was built, measured against the approved brief (when
one exists), the UX invariants of every loaded designer doc, the team's rules docs and the flow
patterns. **Screenshots of the running app are mandatory — reading the code alone is not a
design review.**

## 1. Pick the tier

The depth follows the change, not the mood. Pick the tier first and name it in the review.

| Tier | When | What runs |
|---|---|---|
| **1 · checker only** | a copy or label change, a token value tweak, a field added on the established row pattern, a bug fix restoring designed behaviour | category 13 on the changed files + a screenshot of the changed surface; no checklist walk |
| **2 · checklist + checker** | an existing screen changed shape, a new dialog or panel on a known pattern, any new-track task with an approved mock | all thirteen categories, every theme, every size |
| **3 · two-reviewer critique + checklist** | the rework track; a new page; any surface that shows money, verdicts or counts; a surface the user will share outside the team | tier 2 plus the critique below |

**Money, verdicts and counts always get tier 3**: a misread there costs the customer money.

**The tier 3 critique.** Two reviewers run in parallel, isolated from each other (a subagent
each): **A** reviews the design — usability heuristics, cognitive load, the user's emotional path
through the flow; **B** gathers evidence — the checker and live measurements of the rendered page.
The parent synthesises: A's findings go to categories 3, 6, 7, 11 and 12, B's to 5, 8, 9 and 13,
and a contradiction between them is a finding of its own ("the code says the header is sticky",
"the header scrolled away"). Without subagents, both passes run one after the other in this
context and the review says **degraded**. The cost is real (minutes and many tokens) — that is
why tiers 1 and 2 exist.

## 2. Gather the references

1. `<artifacts>/<feature>/DESIGN_BRIEF.md` and the approved mock screenshots, when the prototype
   ran. Several feature folders: ask which.
2. The UX invariants of every designer doc step 4 loaded.
3. What was actually built: the changed components and their diff —
   `git diff <base>..HEAD -- <files>` for committed work, `git diff <base> -- <files>` when part
   of it is still in the working tree (a new untracked file has no diff: read it whole). `<base>`
   is where the work branched off: `git merge-base <target> HEAD`.

## 3. Capture (mandatory)

Run the app (or use the running one the user names) and capture the REAL implementation with
`[ui] capture` — its command, or the browser tool it names. Reach each surface by the routes and
selectors of the designer doc's Surface map (else of the module's `qa` doc); never work out a
route by guessing.

- Every size of `[ui] sizes` and every colour scheme of `[ui] schemes` (a designer doc may narrow them for
  its surface kind); a wide table also at the widest common desktop width — the smallest
  supported width is the floor, not the typical screen.
- The interactive states the change touches: hover on the primary action, an open menu or
  dialog, a form's error state, loading and empty states where reachable.

Save each capture as `<artifacts>/<feature>/screenshots/review-<screen>-<size>[-<theme>].png` and
cite the file in every finding, so each finding traces to evidence.

**No capture tool:** ask the user for exactly these screenshots (screen, size, theme, state) and
WAIT. A screenshot the user provides is valid input. If the user declines and asks for the review
anyway, review from the code and label the run **degraded — no screenshots** in the tier line and
next to the verdict.

## 4. Run the checklist

`references/checklist.md`: the categories the tier names, each a pass or findings; every finding
cites the component, the file and the screenshot. Rework: walk `AS_IS_AUDIT.md` — EVERY D# and F#
is resolved and no preserve-list item regressed; capture a before and after where the surface
changed shape.

## 5. Write the review — always

`<artifacts>/<feature>/DESIGN_REVIEW.md`, from the template in `references/artifacts.md`, for
every tier and every verdict. Group the findings:

- **Must fix** — broken function, a violated UX invariant, an accessibility failure, a hard-coded
  value instead of a token, a major deviation from the approved mock, a blocking checker finding;
- **Should fix** — inconsistencies, missing states, responsive issues, a taste-class checker
  finding;
- **Could improve** — polish, micro-interactions, typography fine-tuning;
- **What works well** — what to keep doing (not padding: it anchors the next briefs and seeds the
  designer docs).

## 6. The verdict

- `PASS` — no Must fix: the UI task may complete.
- `BLOCKED: N must-fix` — the task is NOT done: fix, capture the affected screenshots again, run
  the affected categories again and append a `## Re-review <date>` section to the same file (never
  start a new one).

Only the user can waive a Must fix, in writing; the waiver and its reason go into the review.

End the turn, in the conversation, with: `Review tier: 1 | 2 | 3 — <why>`; the verdict `PASS` or
`BLOCKED: N must-fix`; the Must fix titles (the details are in the file); the evidence line (the
checker's counts, the smallest rendered text and its contrast, the widest table's visible share;
tier 3 adds the critique's synthesis); the path of `DESIGN_REVIEW.md` and the screenshots table.
