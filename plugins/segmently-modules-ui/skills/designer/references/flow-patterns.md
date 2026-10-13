# flow-patterns: how a whole flow is shaped (FP-1…FP-11)

Every `designer` run reads this file. Component rules (tokens, the dialog chrome, one primary
action) live in the team's rules docs and the designer docs; these patterns are one level up:
information architecture, progressive disclosure, where depth lives, and how a multi-step or
content-generating pipeline shows its state. The prototype applies them as design defaults, the
rework audit names the pattern each dead end breaks, and the review checks them. Each pattern
names the anti-pattern it replaces, so it works as a review rule, not only as advice.

## The eleven patterns

### FP-1 · Default-first, not configure-first

**Rule:** the shortest path to the first concrete result is ONE input; every other control has
a working default. Configuration is available, never required.
**Anti-pattern:** a "set everything up first" form of many fields before the user sees anything.
Configure-first belongs only to high-risk or regulated outputs.
**Test:** count the decisions to the first result. Target: at most one required field.

### FP-2 · A progressive-disclosure ladder, with its levels named

**Rule:** put every control on an explicit level and render only what that level's user needs.
Name the ladder in the brief:

| Level | Who | What it shows |
|---|---|---|
| L0 | first-time, in a hurry | the single primary input |
| L1 | everyone | visible, editable, remembered defaults |
| L2 | when it matters | an optional "customize" section (the old required form) |
| L3 | in the result | per-item detail, regenerate scopes, advanced pickers |
| L4 | power users, setup | settings, presets, naming templates |

Nothing below L2 is required to reach a result; every control above L0 has a default.
**Anti-pattern:** every control flattened onto one screen, so a newcomer meets the density a
power user needs.

### FP-3 · A guided workspace: page, step rail, canvas, side panel

**Rule:** a multi-step or content-generating flow is ONE page, not a stack of dialogs. Its spine
is a clickable, non-linear step rail with a live status line per step; a persistent canvas shows
the result; per-item depth opens in a side panel, never a modal. Steps are modes, not modal
pages.
**Anti-pattern:** dialog over dialog — list → dialog → tab → dialog → tab → dialog — or one large
dialog that mixes several concerns.

### FP-4 · At most three levels, at most one modal

**Rule:** the whole surface is at most three hierarchy levels deep and shows at most ONE modal
level (confirmations only). Deeper interactions go to side panels, panels or pages. More than
one modal or more than three levels is a simplification signal.
**Anti-pattern:** four to six stacked dialog levels to reach the first result.

### FP-5 · Create the intermediates inline

**Rule:** an entity the flow needs first (a workspace, a default collection, a settings profile)
is created automatically with sensible defaults and can be renamed later — never "go to another
tab and make one first".
**Anti-pattern:** an empty state that silently depends on an entity living in another part of
the app.

### FP-6 · One primary next action per screen, zero dead ends

**Rule:** every screen has exactly ONE primary action pointing at the obvious next step, and NO
visible reference to an entity the user cannot reach. A flow whose last screen has no "what now"
is a dead end.
**Anti-pattern:** a label pointing at a hidden surface ("Assigned to: none", with no way to
assign), or a generation that just stops with no path onward.
**Test:** for each screen, name its one primary action and where it leads.

### FP-7 · Honest states over fake-done

**Rule:** an incomplete result says so with a state and an action (`needs media`, `validation
failed`, `generating…`) instead of looking finished. Label any uncertain number "estimated".
**Anti-pattern:** a card that looks done because a placeholder fills the slot of content that
was never produced.

### FP-8 · Confirm, don't form (first-run setup)

**Rule:** first-run setup the product can pre-fill is a short confirmation wizard, not a blank
form: every field pre-filled from the best available source, each step confirmed by the user.
Never apply values silently; never show an empty form.
**Anti-pattern:** a blank multi-field setup form, or silent magic that applies values the user
never saw.

### FP-9 · Build in the downstream job

**Rule:** what the user does AFTER the core action (name, tag, hand off, publish, compare) is
part of the flow, not manual ceremony. Find out what users really do next and make its backbone
a first-class control (a naming convention setting, tracking tags filled in, a one-step
publish).
**Anti-pattern:** the generation ends and the user invents names, tracking tags and the path to
publish by hand.

### FP-10 · Re-architect the presentation layer

**Rule:** prefer a redesign that maps one to one onto the existing services and data. The
entity the user sees may be a new presentation of one that already exists — no new backend, no
migration. Keep new backend work for the genuinely new job.
**Anti-pattern:** a new entity or table invented to carry a UI concept an existing record
already covers.

### FP-11 · Pipeline state without a fake progress bar

**Rule:** show a pipeline's state as a step rail, a status per item and aggregate counts ("5
ready · 1 generating"), and keep the app's existing task list as the ONLY task trail.
**Anti-pattern:** one spinner or percentage for a multi-item, multi-stage pipeline, or a second
task trail competing with the app's own.

## How the tracks use them

- **New** applies FP-1…FP-11 as design defaults while shaping the flow, and as review checks at
  the end.
- **Rework** first runs the audit, which finds where the existing flow breaks these patterns
  (each dead end names its FP), then redesigns to satisfy them.

A design that breaks a pattern without a written reason is a review finding — **Must fix** when
it brings back a dead end (FP-6), a fake-done state (FP-7) or modal over modal (FP-3, FP-4).

## Delivery (both tracks)

- **Decisions before build.** Resolve every open flow question with the user and record a
  decisions table BEFORE implementing.
- **Phases behind the existing route.** Ship the redesign in phases that release on their own;
  the old UI stays reachable until a late cleanup phase — no big-bang cutover. Each phase closes
  named findings.
- **Findings to phases.** Every audit finding (D#, F#) maps to the phase that fixes it, so
  nothing is noted and forgotten.
