# When a command fails

`0` ok · `1` = findings (`lint`, `ci`, `coverage --fail-under`, a `--check` that found a
difference) or a hook that failed: read the result, it is the state to plan for, not an error ·
`2` = a usage or config error, or a refused write: read stderr, fix the input (a flag `--help`
does not show, a broken `.segmently-modules/config.toml`, an unknown module or role) and run it again once.

A write refused with exit 2 in the middle of a plan stops the plan: report the command, its
stderr and what is already done, and wait for the user.
