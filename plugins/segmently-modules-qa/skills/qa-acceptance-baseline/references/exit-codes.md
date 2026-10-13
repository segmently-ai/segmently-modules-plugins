# When a command fails

Exit 2 "unknown role 'qa_acceptance'": the `qa` pack is not enabled — tell the user
(`[packs] builtin` in the team config) and stop.

`0` ok · `1` from `lint` = findings: fix the ones the new doc caused · `2` = a usage or config
error, or a refused write: read stderr (an unknown role means the `qa` pack is not enabled).
