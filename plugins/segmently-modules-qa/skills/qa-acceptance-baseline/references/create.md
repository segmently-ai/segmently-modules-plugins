# create: a module with no baseline yet

Step 6 of `qa-acceptance-baseline` — write the doc — when step 1 found no doc to refresh: no
`role:qa_acceptance` row with `exists: true`, and the dry run said `created` or `missing`
(when it names a doc to refresh, follow `references/refresh.md` instead).

When step 1's dry run said `missing`, write the doc at the `path` it reported and skip
`registry set`: the registry lists it already.

- It does not: start from the file of the `roles/qa_acceptance.md` row of
  `segmently-modules templates list --json`, fill it, save it next to the module's other role docs,
  and add it to the module's `context_files`:

  ```bash
  segmently-modules registry set <module> context_files '<the object with roles.qa_acceptance added>' --dry-run
  segmently-modules registry set <module> context_files '<the object with roles.qa_acceptance added>' --json
  ```

  Build the object from `show --all-roles`: `universal` is the universal row, each
  `role:<role>` row is `roles.<role>`; add `roles.qa_acceptance`. Check the dry run's diff
  changes nothing else.

Either way the template holds the doc's shape: one `## Block` section per functional block
(its requirements table and P0 / P1 / P2 criteria, each with REQ, Technique, Risk, Dimension
and Verification), then the sections after the blocks; keep every section and fill each.
