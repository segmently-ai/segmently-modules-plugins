# Filling the docs (module-create, step 6)

The filled docs are the deliverable: a scaffold with template prompts left in tells a later agent
nothing, and it builds a second copy of what exists. Fill from the analysis and the user's answers;
never invent components or rules.

**Module doc**
- the description expanded to a short paragraph: what, why, when;
- the components table — name · path · purpose, every row a real path (lint MS040 checks them);
- usage: at least one example done right and one done wrong, each with why;
- critical rules: the rule, why, what to do and what not to do;
- where its files live.

Keep it short — about 200–300 lines. Route detail to the role docs before it lands here: full
signatures, return types, error cases and integration walkthroughs → developer; architecture and
flows → architect; test scenarios and test code → qa; a deep dive for one audience → that role.

**Developer doc**: the real import lines, the API patterns with code from the analysis, the
common correct uses. **PO doc**: job stories (When … I want to … so that …) from the analysis
and the user's answers, each with the conditions that change it; a story's status only from a
delivery or QA record, else Unknown. **Other role docs**: what the analysis says for that
audience; a section with nothing true to say yet is deleted.

**An active module (its code exists) — minimum:** at least three components with real paths;
at least one right-and-wrong usage example; real import lines in the developer doc.
**A planned module:** the planned functionality and its expected components or APIs, each marked
"Planned:".

**Quality check** before step 7, every doc of the module: no template comment (`<!-- … -->`)
left; the module doc holds no full signature and no architecture diagram; every component row has
a path and a purpose; a UI module has its designer doc filled (when that role is on).

**Report** (step 10): the files written, the registry entry (status, keywords) and its links, the
routing rule, the docs' quality — components documented, usage examples, template comments left
(0) —, the `match` result for the typical task, and what the docs still leave open.
