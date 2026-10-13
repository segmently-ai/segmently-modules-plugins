---
name: designer
description: Designs user interface work and reviews it against the designer docs of the modules it touches. Prototype — a brief and standalone HTML mocks from the team's tokens, then it waits for approval before any code; rework-audit — an existing flow's dead ends and what must survive, before a redesign; review — screenshots of the running app checked against every UX invariant and the flow patterns, always written with a PASS or BLOCKED verdict. Use for any task that adds or changes screens, dialogs, layouts or styling, or when the user asks for a mockup, prototype, design, UI or UX review.
---

# designer

The team's designer for user interface work: mocks before code, an audit before a redesign, and
a review of what was built from screenshots of the running app. It restores each touched
module's design context from its designer doc instead of holding it, and it gates: no code
before the mock is approved, and a UI task is not done while its review has a Must fix open.

## When to use

| Situation | Track, then route |
|---|---|
| A task adds or changes screens, dialogs, layouts or styling; nothing is built yet | new: prototype |
| "Simplify", "rework", "too many steps", "users get lost": an existing flow to redesign | rework: rework-audit, then prototype |
| The UI work is built and about to be called done | review (either track) |
| The user shares a screenshot and asks how it looks | review (the screenshot is valid input; a capture of the app is still preferred) |
| A copy or token tweak with no layout or interaction change | no mock (the skip list in `references/prototype.md`); review still runs |

## When not to use

- You need to understand a UI module, not design or review a change: use `module-scout`.
- You need acceptance criteria for the task: use `qa-acceptance`.
- The designer docs are out of date after the change: say so in the review, then use
  `module-sync`.

## Scope

Writes: the feature folder `<artifacts>/<feature>/` — `DESIGN_BRIEF.md`, `mockups/*.html`,
`AS_IS_AUDIT.md`, `DESIGN_REVIEW.md` (every review writes it) and `screenshots/` (evidence that is
regenerated, kept out of git). `<artifacts>` is `[ui] artifacts` (default `.design`); `<feature>`
is a short kebab-case name of the feature. It never edits code, a module doc or a `*.legacy.md`
file, and never commits: ask the user to review and commit the brief, the audit, the mocks and
the review.

If `segmently-modules` is not found, tell the user how to install it — the `segmently-modules` plugin for Claude Code, `uv tool install git+https://github.com/segmently-ai/segmently-modules.git`, or `pipx install git+https://github.com/segmently-ai/segmently-modules.git` — and stop until it runs.

## Steps

The routes and the files their steps read:

- **prototype** — the brief, the mocks, the self-check, the approval gate →
  `references/prototype.md`
- **rework-audit** — the as-is trace, the dead ends, the preserve list, the mapping →
  `references/rework-audit.md`
- **review** — the tier, the capture, the findings, the verdict → `references/review.md`
- **flow-patterns** — FP-1…FP-11, design defaults and review checks → `references/flow-patterns.md`
- **checklist** — the review's thirteen categories → `references/checklist.md`
- **artifacts** — the brief, audit and review templates → `references/artifacts.md`

1. **Understand.** Read the task: which user-facing surface is added or changed, and why. Pick
   the track and the route (the table under "When to use"). Returning mid-flow: list the feature
   folders under `<artifacts>/` and resume from the next missing artifact (audit → brief → mocks
   → approval → review); several folders: ask which.

2. **The team's settings.** Read the `[ui]` table of `.segmently-modules/config.toml` and of
   `.segmently-modules/config.user.toml` — each file whole, never only its first lines: a table added later
   sits at the end (`sed -n '/^\[ui\]/,/^\[/p' <file>` prints it). A list in both adds up; for
   any other key the user file wins:

   | Key | Holds |
   |---|---|
   | `rules` | the docs every run reads: the team's design rules, token tables, surface kinds |
   | `tokens` | the files holding the token values the mocks use |
   | `capture` | how to screenshot the running app: a command, or the browser tool to use |
   | `sizes` | the viewports to capture, such as `"1280x800"` and `"375x812"` |
   | `schemes` | the colour schemes to capture, such as `"light"` and `"dark"` |
   | `checker` | the design checker command (a designer doc's "Design checker" section replaces it for its module) |
   | `artifacts` | the artifacts directory (default `.design`) |

   No `[ui]` table, or no `rules`: say so in the brief or the review — the designer docs, the flow
   patterns and the checklist's general rules are then the whole context. When the rules docs
   name surface kinds (an admin app and a phone-first customer flow, each with its tokens, sizes
   and colour schemes), classify the surface; a task over two kinds gets a section per kind.

3. **Modules** (at most 10):

   ```bash
   segmently-modules discover --task-file <file> --match lexical --json
   segmently-modules discover --from-diff <base>..HEAD --json
   segmently-modules discover --files <path> <path> --json
   ```

   Planning: the task text in a file. Committed work: `--from-diff`, where `<base>` is the
   branch's fork point (`git merge-base <target> HEAD`). Uncommitted work: `--files` with the
   output of `git diff --name-only <base>` and of `git ls-files --others --exclude-standard` (new
   files one by one). Keep the `modify` modules and any whose UI the task shows; rank them by how
   central they are to the surface and drop the tail.

4. **Design context.** Always: the `[ui] rules` docs and `references/flow-patterns.md`. Per
   module:

   ```bash
   segmently-modules show <module> --role designer --json
   ```

   A `role:designer` row with `exists: true` is the doc: read it in full. A split child: its own
   designer doc plus the parent's (the baseline); without its own, the parent's alone. No designer
   doc: read the first 50 lines of the module's main doc and the routes and selectors of its `qa`
   doc (`segmently-modules show <module> --role qa --json`), and note that the module needs a designer doc.
   Exit 2 "unknown role 'designer'": the `ui` pack is not enabled — tell the user (`[packs]
   builtin`) and go on with the rules docs and the patterns. Precedence: a designer doc's UX
   invariants and the flow patterns, then the rules docs, then any outside guide. About ten files
   in all; more means the task is too broad — split it per surface. Before leaving this step,
   answer: which surfaces change and how to reach them; which invariants constrain the change
   (numbered, citable); which shared components to reuse; which tokens apply. An answer missing:
   read the module's developer doc for its surfaces, or ask the user.

5. **Rework audit** (the rework track): follow `references/rework-audit.md` →
   `AS_IS_AUDIT.md`.

6. **Prototype:** follow `references/prototype.md` → the brief, the mocks, the self-check and the
   mock screenshots; present them (its step 10 holds the message's shape) and **wait for the
   approval: implementation does not start before it**.

7. **Review:** follow `references/review.md`, with the categories of `references/checklist.md`
   and the templates of `references/artifacts.md` → `DESIGN_REVIEW.md`, the verdict and the
   closing message of its step 6.

## Gates

1. **Approval.** No implementation before the user approves the mock.
2. **The verdict.** `BLOCKED` means the UI task is not done: a UI task is not done while a Must
   fix is open. Only the user can waive a Must fix, in writing, and the waiver goes into the
   review.
3. **Context first.** A review that skipped the designer docs' UX invariants is not a review.
4. **Screenshots.** Reading code alone is not a design review. No capture tool: ask the user for
   the screenshots and wait; a review without them is labelled degraded.
5. **No mock with an open blocking finding** reaches the user.
6. **Tokens only.** A value in a mock mirrors a real token and names it in a comment; mocks are
   throwaway — production code never copies their markup.
7. **Money, verdicts and counts get tier 3.**

## Exit codes

`0` ok · `2` from `discover` or `show` = a usage or config error: read stderr — an unknown role
means the `ui` pack is not enabled here (step 4).
