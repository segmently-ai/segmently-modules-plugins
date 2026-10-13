# checklist: the review's thirteen categories

Step 7 of `designer`, after the capture (`references/review.md` picks the tier: tier 1 runs only
category 13). For each category: pass, or findings that cite the component, the file and the
screenshot. The team's rules docs and the designer docs refine every category below; where they
say nothing, the general rule here applies.

## 1. Brief and mock fidelity

- The implementation matches the approved mock's layout, hierarchy and states; no silent scope
  drift (an element added or dropped without a decision).
- **Token drift:** for each token the mock labels, compare the RENDERED value in the app (the
  computed style, alpha composited over the real background) with the mock's value. The same
  token name is not enough: a solid grey in the mock and a half-transparent white over a tinted
  header in the code are different numbers on screen.
- **Behaviour the mock could only assert** — sticky headers or columns, scroll containment, a
  side panel collapsing, dialogs stacking — is verified in the running app by scrolling and
  resizing, never from the mock or the source: a theme override can silently disable what a
  component declares.

## 2. Module UX invariants

Walk EVERY numbered invariant of the loaded designer docs; each gets an explicit verdict. A
violated invariant is automatically a **Must fix**.

## 3. Visual hierarchy

The most important content is the most prominent; the reading order is traceable (first, second,
third — if a screenshot cannot answer "where does the eye go first", the hierarchy fails). One
primary action per surface, with the team's primary button kind; everything else secondary.

## 4. Consistency

Spacing on the team's spacing scale, with no visibly uneven gaps. The same meaning, the same
colour (primary actions, errors, disabled). Radii, shadows and the type scale come from the
tokens — no one-off values.

## 5. Token compliance

Search the diff for colour literals, hard-coded font sizes in pixels and inline style attributes;
every hit is a finding unless it is in a mock or a test. The team's own guards on its shared
components (warnings, catalogue coverage) stay green.

## 6. Component quality

The team's shared components are used, not re-implemented — check against the brief's component
inventory and the team's component catalogue. The rules the rules docs and the designer docs set
for dialogs, tables and forms hold (where the close button sits, a single dismiss affordance, an
explicit confirm on a destructive action). A new shared-looking component that copies an
existing one is a finding.

## 7. States and interactions

Default, hover, focus, active and disabled on every interactive element. Forms: empty, filled,
error, success, disabled. Lists: loading, empty, error. Visual feedback for every user action; no
dead clicks.

## 8. Responsive behaviour

Usable at every size of `[ui] sizes`; no horizontal overflow; panels reorganise rather than only
shrink. Touch surfaces: targets at least 44 × 44 px, body text at least 16 px on a phone.

## 9. Accessibility

Contrast at least 4.5:1 for body text and 3:1 for large text, checked on the RENDERED colours in
the screenshots. Every interactive element reachable and operable by keyboard, with a visible
focus ring and a logical tab order. Labels tied to their fields, icons with accessible names,
headings in order.

## 10. Colour schemes

Every colour scheme of `[ui] schemes`: each changed surface captured and inspected in each. No hard-coded
value that fails to switch; shadows and dividers still visible; contrast holds.

## 11. Typography and content

The type scale from the tokens, no arbitrary sizes; comfortable line lengths (45–75 characters);
truncation and overflow handled. Real-data robustness: the longest realistic entity name, zero
items, a thousand items or more.

## 12. Flow and IA patterns (`references/flow-patterns.md`)

- **FP-6 no dead ends:** every screen has exactly one primary next action, and no visible
  reference to an entity the user cannot reach. Any dead end is a **Must fix**.
- **FP-3, FP-4 depth:** no dialog over dialog, at most one modal level, per-item depth in a side
  panel, not a modal. Modal over modal is a **Must fix**.
- **FP-7 honest states:** an incomplete result shows a state and an action, never fake-done;
  uncertain numbers say "estimated".
- **FP-1, FP-2 disclosure:** about one input to the first value; every control above L0 has a
  working default; the old required form is now optional.
- **FP-8 confirm, not form:** first-run setup is a pre-filled confirmation, not a blank form, and
  nothing is applied silently.
- **FP-9 the downstream job** (naming, tagging, handing off, publishing) is built in, not manual.
- **Rework:** walk `AS_IS_AUDIT.md` — every D# and F# resolved, no preserve-list item regressed. A
  dead end, a fake-done state or a modal stack brought back is a **Must fix**; include a before
  and after where the surface changed shape.

## 13. The design checker (mechanical)

Run the checker: the command a designer doc's "Design checker" section names for its module,
else `[ui] checker`. No checker named: say so in the evidence line — never install a tool and
never guess one.

- Triage: the **blocking class** (contrast, clipped or overflowing text, broken images, script
  errors, values off the token set, nested containers that should be flat) → **Must fix**; the
  **taste class** (monotonous spacing, a flat type hierarchy, copy cadence) → **Should fix**.
- A finding you judge a sanctioned exception is ignored only with a recorded reason (who decided,
  on what evidence) through the checker's own ignore mechanism, and cited in the review — never
  dropped silently.
- **A source scan is not the rendered truth.** A checker reading the source cannot see alpha
  compositing, computed styles or theme overrides. From tier 2 up, also measure the rendered
  page: the smallest text size and its composited contrast, horizontal overflow per scroll
  container (the visible share of the widest table at each size), console errors. Report both.
- Paste the checker's summary (counts per rule) and the measurements into the review's "Evidence"
  section.
