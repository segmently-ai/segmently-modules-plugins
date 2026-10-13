# prototype: the brief and standalone HTML mocks, before any code

Step 6 of `designer`. The mock settles layout, hierarchy and states BEFORE production code is
written — cheap to throw away, faithful enough to judge. Nothing is implemented before the user
approves it.

## 1. Resolve the open questions

Interview the user about every unresolved design decision: intent, tone, the priority of the
elements, the states. A question the code or the loaded designer docs can answer, answer
yourself instead of asking. With each question you ask, give your recommended answer.

## 2. Mock or skip

**Mock required:** a new screen, page, dialog or panel; a restructured layout; a new interaction
pattern (a wizard step, a selection mode, inline editing, dragging); anything the user describes
as "not sure how it should look".

**Skip the mock** (the brief only, or nothing): a copy or label change; a token value change with
no structural change; a field added to a form on its established row pattern; a bug fix that
restores designed behaviour. When skipping, say in the conversation that the mock was skipped
and why. The review still runs.

## 3. Write the brief

`<artifacts>/<feature>/DESIGN_BRIEF.md`, from the template in `references/artifacts.md`: the
track, the surface kind, the modules, the problem, the flow patterns applied (FP-1…FP-11 are the
design defaults), the solution, the existing patterns from the designer docs, a component
inventory against the team's shared components, the states, the responsive behaviour, the
mockups, the self-check, what is out of scope and the open questions. Rework: the brief resolves
every D# and F# of `AS_IS_AUDIT.md`, keeps every preserve-list item and cites the audit.

## 4. One mock or variants

The default is one mock. When the brief still holds an open STRUCTURAL question, build two or
three mocks that each commit to a different primary axis, so the user chooses between real
alternatives:

| Axis | What differs between the variants |
|---|---|
| Hierarchy | which element takes the eye first (a key number, a table, the actions) |
| Layout topology | stacked, side by side, grid, page plus side panel |
| Density | minimal, comfortable, dense (rows per screen, lines per cell) |
| Structural decomposition | merge, split, progressive disclosure (what moves a level down) |

Variants never differ by colour or typeface: the team's identity is not an axis unless the user
asked for a visual refresh. Three variants are three DIFFERENT axes (three "denser" ones is a
failure). Squint test: two variants that read the same at arm's length → rework one. Name them
`<screen>-<state>-v<N>-<axis>.html`, with a one-line thesis each in the brief's Mockups table.
Skip variants when the audit or the brief already fixed the direction, and say so.

## 5. The mock files

One SELF-CONTAINED HTML file per screen and state: `<artifacts>/<feature>/mockups/<screen>-<state>.html`.
No build step, no CDN, no external request: inline styles, inline SVG icons (or Unicode), system
font fallbacks after the team's font. The header comment is mandatory:

```html
<!--
  MOCK — throwaway prototype, never copy into production code
  Feature:      <feature>
  Surface kind: <kind>
  Modules:      <the modules step 3 found>
  Date:         <YYYY-MM-DD>
  Brief:        ../DESIGN_BRIEF.md
-->
```

## 6. Token fidelity

Generate a `:root` block of the team's real token values (from the `[ui] tokens` files or the
rules docs) and label every value with its source token:

```css
:root {
  --color-primary: #1f6feb;   /* palette.primary (light) */
  --color-surface: #ffffff;   /* palette.surface (light) */
  --radius-card: 12px;        /* shape.card */
}
[data-theme="dark"] {
  --color-primary: #9ecbff;   /* palette.primary (dark) */
}
```

A value that maps to no token fails the brief. A surface kind whose look comes from customer
data (a theme the customer configures) takes the values of the default theme, each labelled with
the path it maps to — and its structure must look right under ANY theme.

## 7. Fidelity rules

- Look like the team's shared components (their dialog header, table chrome, button kinds, radii,
  shadows): recognisable, not pixel-perfect.
- Show the states that matter: the default plus at least one of empty, loading or error where the
  surface has them — a file per state, or a visible toggle in one file.
- Every colour scheme in `[ui] schemes`: a file each, or a script that flips a `data-theme`
  attribute on `<html>`.
- A phone-first surface: lay it out at the phone width inside a simple phone frame, so the
  proportions read right.
- Realistic content, not filler text: real entity names and numbers from the product's domain.

## 8. Self-check (a gate)

A mock is never shown to the user with an open blocking finding. Run the team's checker on the
mockups folder — `[ui] checker`, or the command a designer doc's "Design checker" section names
— and triage every finding:

- **blocking class** — low contrast, text too small, clipped or overflowing text, a value off
  the token set, a skipped heading level, a broken image → fix the mock and run it again until
  the class is clear;
- **taste class** — a flat type hierarchy, monotonous spacing, long lines, copy cadence → fix
  it, or leave it and say why in the brief.

Two traps: a flat type hierarchy on a data table is usually a real hierarchy finding; a finding
on text a designer doc declares mandatory to read (unit captions, disclaimers, "estimated"
labels) is blocking whatever its class. No checker named: walk the blocking class by eye and say
so. Record the outcome in the brief's "Checker self-check" (the counts, what was fixed, what was
left and why).

## 9. Screenshot the mocks

Capture every mock through its `file://` URL with the capture tool (`[ui] capture`), at the
primary size of `[ui] sizes` plus the smaller one when the surface must adapt, into
`<artifacts>/<feature>/screenshots/mock-<screen>-<size>[-<theme>].png`. The user confirms from
these screenshots; do not ask them to open the HTML unless they want to interact with it. No
capture tool: give the paths of the HTML files and say the screenshots are missing.

## 10. Present and wait

End the turn, in the conversation, with: the path of `DESIGN_BRIEF.md` and a paragraph on the
chosen direction (variants: one line each naming its axis, and the one you recommend); the mock
screenshots by path; the line `Checker self-check: N findings → fixed …; left …; blocking class
clear`; the open questions and an explicit request to confirm. Then **wait for the user's
approval: implementation must not start before the mock is approved.**

## Mocks are throwaway

- Production code uses the team's real shared components; never port mock markup or its CSS.
- After approval, the brief's component inventory and the screenshots are the review's reference
  ("does the build match the approved mock?"). The mock's token comments are the second: the
  review checks that each declared token survived the port as the same RENDERED value.
- A mock can be more correct than the app: sticky positioning works in a mock and may be dead in
  the app under a theme override. Anything the brief relies on that is a theme or component
  behaviour is verified in the running app at review, never assumed from the mock.
- Mocks are not maintained after the work lands; they stay as the record of what was approved.
