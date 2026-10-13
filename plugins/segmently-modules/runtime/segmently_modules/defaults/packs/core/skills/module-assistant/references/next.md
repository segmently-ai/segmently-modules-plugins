# next: what needs attention now

Step 2 of `module-assistant` when the user asks what to do next, what is left, or to clean up
the module docs.

1. **Read the list.** Step 1's `segmently-modules next --json` holds it. On a branch, also the drift:
   `segmently-modules next --base <base> --json`, where `<base>` is where the work branched off,
   `git merge-base <target> HEAD`. Ask which branch the work targets when it is not `main` or
   `master`. A `skipped` entry says what could not be checked and why — pass it on.

2. **Turn each item into a step.** The item's `command` is the start; who does the work depends
   on its `kind`:

   | `kind` | The step |
   |---|---|
   | `setup` | the start route (`references/start.md`) |
   | `lint-error` | `module-lint`; an MS004 item whose command is a `roles add … --recreate` is mechanical: that command |
   | `skills` | `segmently-modules packs sync --dry-run`, then without `--dry-run` — mechanical; a copy in `conflict` was edited locally: ask before anything (keep it, or eject the skill) |
   | `agents-md` | `segmently-modules agents-md --dry-run --target <file>`, then without `--dry-run` — mechanical |
   | `role` | `module-roles` (it writes and fills the docs, or marks the modules that do not need the role, after the user's OK) |
   | `ejected` | `segmently-modules eject <skill> --diff --json`; show what changed upstream; the user takes what they want by hand, then `segmently-modules eject <skill> --rebase --dry-run` and without `--dry-run` |
   | `proposals` | `segmently-modules proposals list --json`; apply or reject each run with the user (`segmently-modules proposals apply --dry-run` first) |
   | `lint-warning` | `module-lint`; a doc too long (MS030 / MS031 / MS032): offer the trim first — move its dated history ("Sprint N additions", checkpoints), API dumps and checklists into a supplementary doc and register it (`segmently-modules registry append <module> context_files.supplementary '"<path>"' --dry-run`, then with `--json`) — and `module-split` only when the doc is still too long |
   | `unmapped` | `segmently-modules coverage --json`; per directory ask: map it (`segmently-modules code-map add <id> --pattern '<dir>/{module}/**' --dry-run`) or exclude it (`[coverage] exclude`) |
   | `no-code` | per module in `modules`, ask: map its code (`segmently-modules code-map add <id> --glob '<dir>/**' --module <module> --dry-run`, then with `--json`), list it in `[coverage] doc_only` in the team config when it owns no code on purpose (after the user's OK), or retire it |
   | `drift` | `module-sync` (code changed, docs did not) |

3. **The plan.** Keep `next`'s rank, one line per step in plain words: what is wrong and what
   you would do — e.g. "the catalog's QA doc is missing: recreate it from the template" — marked
   quick or "needs your input". No commands. Nothing to do: say so and stop.

4. **Wait for the OK.** The user may approve all, some ("only the mechanical ones") or reorder.

5. **Carry it out, one step at a time.** Mechanical steps: run the command (its dry run first
   when it writes many files). Judgement steps: hand them to the skill. After each step run
   `segmently-modules next --json`: report the item gone, or why it is still there, and stop at a failure
   instead of moving on.
