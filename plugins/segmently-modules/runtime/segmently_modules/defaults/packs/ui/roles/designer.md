# ${title} — ${role}

> ${role_description}

<!-- The design context of this module's user interface: what the designer skill screenshots,
the rules every change keeps, the flows whose shape is a decision. Dense — 100 to 200 lines; the
team-wide rules stay in the docs `[ui] rules` names: link them, never repeat them. Say what users
see, not how it is built. -->

## Surface map

<!-- Every user-facing surface this module renders and how to reach it — what a design review
screenshots; a surface missing here escapes review.
| Surface | Route or entry | Entry selector | Purpose | -->

## UX invariants

<!-- Numbered rules that must never break, each with its reason. A review walks them one by one;
a broken one is a Must fix.
1. **<rule>** — <what the user sees>.
   **Why:** <the problem it prevents, or the decision that locked it>. -->

## Interaction states

<!-- Per screen or component: what loading, empty, error, success and disabled look like, and
what the user can do in each. -->

## Layout and accessibility

<!-- The sizes that must work; keyboard use, focus order, labels for assistive technology,
contrast; what must never overflow or be cut off. -->

## Visual patterns

<!-- The shared components and compositions this module uses — what each is built from, its
catalogue entry, the states that matter — and what not to build again. -->

## Key flows

<!-- Two to five journeys as numbered steps, the user's action → what the screen shows. Flows
whose shape is a design decision (entry → empty state → first action → success), not plain
create, edit and delete. -->

## Tokens and colour schemes

<!-- The surface kind; the module's own token use and any deviation with its reason; what needs
care when the colour scheme flips. -->

## Anti-patterns

<!-- What was done wrong here before, or is forbidden — one line of reason each. Review findings
graduate into this list. -->

## Design checker

<!-- Optional: the command this team runs to check a UI change of this module (a linter, a
screenshot test) and how to read its result; for this module it replaces `[ui] checker`. The
designer skill runs a checker only when one is named. -->
