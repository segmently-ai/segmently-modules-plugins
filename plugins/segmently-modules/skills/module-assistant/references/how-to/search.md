# Finding the modules for a task

## How modules are found
`segmently-modules context --task-file <file> --role <role> --match lexical --json` (the read set for a
task) and `segmently-modules match "<task>" --match lexical --json` rank modules by their keywords —
lexical, the default.
`--match semantic` or `hybrid` asks the user's own agent command (`SEGMENTLY_MODULES_AGENT_COMMAND`, a JSON
argv list in the environment; a config file can never set it). A `[match] mode` committed to the
repository runs that command only with `SEGMENTLY_MODULES_AGENT_ALLOW_REPO_MODE=1` in the user's
environment.

## Choosing modules by meaning
`segmently-modules choose --task-file <file> --effort standard --json` (the task written to a file) prints a
work order for an agent to pick modules from the cards (`segmently-modules catalog --json`); `--apply <file>` checks the answer,
`--run` asks the agent command. Effort: `quick`, `standard` or `deep`; default `[search]
effort`.

## A task keeps reaching the wrong module
Tune the target's keywords: `segmently-modules registry append <module> keywords '"<word>"' --dry-run`. A
generic word that belongs elsewhere: `negative_keywords` on the module that wrongly matches; two
words that point here only together: `required_combinations`. Check with
`segmently-modules match "<task>" --match lexical --json`.

## Measure the routing
`segmently-modules eval routing --prompt --json` returns a prompt that asks for tasks per module; save the
answer (`[{task, module}]`) to a file and run `segmently-modules eval routing --tasks <file> --json` — the
hit rate per module, exit 1 below `--min-hit-rate` (default `[init] routing_min_hit_rate`, 0.8).
