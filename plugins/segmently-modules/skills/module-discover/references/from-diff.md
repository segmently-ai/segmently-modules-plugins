# A change without a task: a branch or changed files

The change is known; the modules come from its files.

```bash
segmently-modules discover --from-diff <base>..HEAD --json
segmently-modules discover --files <changed files> --json
```

`<base>` is where the branch left its target: `git merge-base <target> HEAD` prints it — never the
target itself, whose later commits would count as touched. `--files` takes the paths as separate
arguments (`--files a.ts b/c.ts`); one quoted string is one path.

Per module, best first: `usage` (`modify`: its files changed; `reference`: only its keywords
matched), `touched_files`, `docs_to_read`, `docs_to_update`, on a split parent `children` (name the
one the change is in and add its doc to the docs to update); then `files_outside_modules` and
`missing_files`.

Then steps 5 and 8 of the skill: the docs of every `modify` module for every role, with what bears
on the change; the changed files are its `Code:` lines (`file:line — symbol — why` where a hunk
shows it); no scores, no rejected list (nothing was chosen).
