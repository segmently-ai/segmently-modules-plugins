# A child of a split module (module-create)

A child is created under its parent with `--parent`, and keeps only the role docs it has content
of its own for: for every other role the parent's doc is its baseline (`segmently-modules roles list --json` shows
the child as `inherited`), so an empty scaffold would only hide it.

```bash
segmently-modules create <child> --parent <module> --non-interactive --description "<one sentence>" --keywords "<k1>" --no-standard-roles --role <role> --dry-run
segmently-modules create <child> --parent <module> --non-interactive --description "<one sentence>" --keywords "<k1>" --no-standard-roles --role <role> --json
```

One `--role` per role the child will have area content for; none at all is fine. Its keywords are
routing hints taken from the parent's; the parent's own keywords never change.

After step 6, add the child's row to the parent's routing table — child · scope · keywords ·
lines — the one edit of the parent this skill makes: the routing table must list every child.
Never edit a `*.legacy.md` file of the parent.
