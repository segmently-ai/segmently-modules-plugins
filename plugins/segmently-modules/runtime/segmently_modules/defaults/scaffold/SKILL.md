---
name: ${skill}
description: ${description}
---

# ${skill}

<!-- Scaffolded by `segmently-modules packs new`: rewrite the description above (what the skill does and
when an agent should use it) and these steps. Keep `name` equal to the directory name. -->

## Steps

1. Find the modules the task touches and the docs to read:
${context_lines}
2. Read each module's ${read_what}:
${show_lines}
3. Read every file those commands list, then do the task.
4. After the change, `segmently-modules discover --from-diff <base>..HEAD` names the module docs to update.
   `<base>` is the commit the work branched off: the output of `git merge-base <target> HEAD`,
   where `<target>` is the branch the work will merge into.
