---
name: module-research
description: Answers one question about one or more modules in depth, from their docs and their code, read-only. Reads every role doc, the module's links in both directions, the code files Segmently Modules maps to it and its lint findings, then writes a brief with file:line evidence that names every place where the docs and the code disagree. Use for "how does X really work", "is the doc of X still true", "explain module X in depth", or before a risky change to X.
argument-hint: "[task]"
---

# module-research

## When to use

- A question about a module needs proof from the code: is its doc still true, what does it do
  before a risky change.

## When not to use

- The gist of a module while a task is discussed: use `module-scout`.
- The touch-set of a confirmed task: use `module-discover`.
- The docs must be fixed, not just checked: report the gaps here, then `module-sync` (after a
  change) or `module-lint` (for findings).

## Scope

Read-only: Segmently Modules read verbs, docs, code; it writes only temporary files outside the repository,
never edits a file — gaps are reported, not fixed — and never commits. It runs in the user's
conversation; a caller that wants a clean context runs it through the `module-research-agent`
agent, which returns this skill's brief unchanged.

If `segmently-modules` is not found, tell the user how to install it — the `segmently-modules` plugin for Claude Code, `uv tool install git+https://github.com/segmently-ai/segmently-modules.git`, or `pipx install git+https://github.com/segmently-ai/segmently-modules.git` — and stop until it runs.

## Steps

Pin the question in one sentence.

1. No module named? Choose the candidates.

   Follow `references/choose.md`.

2. Load every doc of each module: `segmently-modules show <module> --all-roles --json` (a pointer stub, exit
   1: the module was retired or merged — research its successor instead and say so). A split module
   (`submodules`): read the parent index, then the children the question touches —
   `segmently-modules show <module>/<child> --all-roles --json` (the parent's role docs are the child's
   baseline). Read the docs fully.

3. Its links, both ways: `segmently-modules related <module> --json`. `edges`: the modules it relies on;
   `reverse`: those pointing at it, which a change would affect. Read a linked module's main doc
   only when the question crosses into it.

4. Its code: `segmently-modules code-map files <module> --json` (`via`: the routing rule; `show` adds `code`
   and `code_globs`). Search it for the names the docs and the question use; read what answers it.
   Nothing routed? Say so and search by the component names its main doc lists.

5. Its lint state: `segmently-modules lint --json`. Keep the findings of the module and its children; findings
   with module `*` only when they name it.

6. Compare. For each doc statement that bears on the question — a component, a rule, a flow, a
   limit — find the code that implements it. Record each disagreement as "the docs say X
   (doc:line), the code does Y (file:line)", the doc statements the code does not show, and code
   behaviour the docs never mention.

7. Write the brief: the answer first, in a few sentences; file:line evidence for every claim; the
   gaps table (doc claim · code reality · file:line · how sure); who is affected (`reverse`) when
   it is about a change; the lint findings that matter; next: `module-sync` after a change,
   `module-lint` for findings.

## Exit codes

`0` ok · `1` from `lint` = findings at or above the fail level (a valid result: read them) · `1`
from `show` = a pointer stub · `2` = a usage or config error: read stderr, fix the command or
report it.

## Gates

No gates — read-only: it reports and stops. It asks only when the question is too broad to answer
with evidence (then it proposes a narrower one).
