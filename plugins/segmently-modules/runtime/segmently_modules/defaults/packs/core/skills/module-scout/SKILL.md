---
name: module-scout
description: Quick, read-only context on the modules a task is about, while the task is still being discussed. Asks the CLI what each named module is, which docs to read and which modules it is linked to, reads those docs and reports a short brief. No plan, no edits. Use when the user says "look at module X", "load the context for", "what do we know about", or describes a change and names modules before a plan exists.
argument-hint: "[task]"
---

# module-scout

Loads the context of the modules a discussion is about, fast, so the discussion is grounded —
not a touch-set and not a plan. The user usually names the modules; when none is named, scout
proposes candidates and waits.

## When to use

- A change is being discussed, or the user names modules (`parent/child` or a doc path) and wants
  their context: a short brief, no plan, no edits.

## When not to use

- The task is confirmed and needs its complete context and touch points: use `module-discover`.
- One question needs a deep answer from the docs and the code: use `module-research`.
- Work is finished and the docs must catch up: use `module-sync`.

## Scope

Read-only: Segmently Modules read verbs, reading files; it writes only temporary files outside the
repository, never edits a file, never runs a writer verb, never commits. No code search and no
touch-set claims — that is `module-discover`. The registry, layout and roles come from `segmently-modules`,
never from an assumed path. It runs in the user's conversation; run through the
`module-scout-agent` agent it returns only its brief, or its proposal when it has to ask.

If `segmently-modules` is not found, tell the user how to install it — the `segmently-modules` plugin for Claude Code, `uv tool install git+https://github.com/segmently-ai/segmently-modules.git`, or `pipx install git+https://github.com/segmently-ai/segmently-modules.git` — and stop until it runs.

## Steps

1. **The references, path first.** The user's references are module names or paths:
   - a path to a module doc (`<modules dir>/…/MODULE.md`, a child's doc too) or a module name →
     `segmently-modules show <it> --json` (it takes either and resolves a path to `module[/child]`);
   - a path outside the registry (a skill, a spec, any other doc) → not a module: read the file
     itself as part of the context.

   Never add modules to the ones the user named: a search is only for a request that names none.

2. No module named? Choose the candidates.

   Follow `references/choose.md`.

   Propose them ("looks like X, Y — load them?"), each with a line on what it owns, and load
   nothing until the user answers.

3. **Each module's docs.** From `show`: `read[]` is the docs in order; `exists: false` = a missing
   doc: say so. Read the main doc. A split module (`submodules`; its first doc is the parent
   INDEX): read the index, then only the children the topic touches
   (`segmently-modules show <module>/<child> --json`) — never all of them; never `MODULE.legacy.md` or
   `roles/*.legacy.md`. A pointer stub (exit 1, `stub`): the module was retired or merged — read
   its successor instead and say so; never guess. A role doc only when the discussion is clearly
   about that role (tests → `qa`, design → `designer`, …):
   `segmently-modules show <module> --role <role> --json` (a child's role doc comes with its parent's
   baseline: read both). A role doc the main doc points to otherwise goes in Suggested next
   reads, unread.

4. **The hard-linked modules come along.** For each named module, `segmently-modules related <module> --json`,
   one hop, forward edges only (`edges`, what this module points at):
   - a `depends-on`, `implemented-in` or `shares-contract` target → read its main doc too, each
     one, even when it looks off the topic: the edge says the module is not understood without it (a split
     target: its INDEX only; no role docs, no further hop);
   - a `complements` target and every reverse edge (`reverse`, the modules that point at it) →
     not loaded; mention it: "worth loading if the task also touches X".

5. **Read for the topic:** what the module owns, the child the topic is in, and the rules that
   bear on the topic — critical rules ("never", "always", "must"), budgets, contracts,
   invariants, pitfalls. No code.

6. **The brief**, in the conversation and short, in the shape of `references/brief.md`: per
   module what it owns and the rules that bear on the topic, the auto-pulled modules with their
   edge, **Suggested next reads**.

## Exit codes

`0` ok · `1` from `show` or `related` = a pointer stub · `2` = a usage or config error (no
registry: "run segmently-modules init"): read stderr, fix the command or report it; do not retry the same
command.

## Gates

No gates — read-only: it never stops for a confirmation. It asks only when no module is named
(the proposal of step 2) or when no module is found and the near misses leave it open; run by the
agent, that question is the agent's output.
