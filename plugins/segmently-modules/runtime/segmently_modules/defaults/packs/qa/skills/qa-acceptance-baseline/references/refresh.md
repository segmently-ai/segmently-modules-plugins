# refresh: a module whose baseline must catch up

Step 6 of `qa-acceptance-baseline` — write the doc — when step 1 names the doc to refresh (a
`role:qa_acceptance` or `child role:qa_acceptance` row with `exists: true`, or the doc its dry
run reported as `registered` or `exists`) and you noted its highest `AC-NNN` (when step 1 names
no doc to refresh, follow `references/create.md` instead).

1. Ids, when refreshing: an unchanged criterion keeps its id and text; a changed one keeps its
   id and is edited in place; a new one takes the next id after the highest existing
   `AC-NNN` — continue the numbering, never renumber and never reuse an id; a criterion that
   no longer applies moves to the "Retired" section with its id and the reason.

2. The doc is not in the registry (step 1's dry run said `registered`): after Gate 3, run
   `segmently-modules roles add qa_acceptance <module> --json`. It adds the registry entry, status
   `registered`, and never writes the file.

3. It exists: edit it in place, block by block (its requirements and P0, P1, P2), then the
   sections after the blocks and Retired; update the Summary and the Priority Matrix last. A
   doc in the older layout (P0, P1, P2 and Retired at the top, no blocks) keeps every id; it
   moves into the block layout only on the user's yes at Gate 1, else it is edited in its own
   layout, each new or changed criterion still with REQ, Technique, Risk, Dimension and
   Verification.
