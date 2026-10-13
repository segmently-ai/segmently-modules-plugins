---
name: module-discover
description: Maps a confirmed task, or a change on a branch, to the modules it touches before planning or review, read-only. Runs discover to list each module as modify or reference with the docs to read and to update, lists the code files of every module to modify, and names the files that belong to no module. Can save the result as JSON at a path the user gives. Use when the user asks which modules or files a task will touch, says "do discovery", after a plan is agreed, or when a pipeline needs the touch-set of a change.
argument-hint: "[task]"
---

# module-discover

Pulls into the conversation the complete context a task needs before it is planned, so that
nothing important is missed in the discussion or the plan: the modules it touches, what their docs
say for every role that bears on the task, and the existing code it touches. It does not look for
a bug's cause — the conversation does that; discover gives it the map.

## When to use

- A task is agreed, or nearly, and the plan needs its whole context.
- A branch or changed files need their modules and docs: follow `references/from-diff.md`.

## When not to use

- The task is still being discussed and a quick load is enough: use `module-scout`.
- One question needs a deep answer with code evidence: use `module-research`.
- The change is done and the docs must catch up: use `module-sync`.

## Scope

Read-only: Segmently Modules read verbs, docs, code search. It writes only temporary files outside the
repository and, at a path the user names, the JSON result; it never edits docs or code and never
commits. It runs in the user's conversation; a caller that wants a clean context runs it through
the `module-discover-agent` agent, which returns this skill's report unchanged.

If `segmently-modules` is not found, tell the user how to install it — the `segmently-modules` plugin for Claude Code, `uv tool install git+https://github.com/segmently-ai/segmently-modules.git`, or `pipx install git+https://github.com/segmently-ai/segmently-modules.git` — and stop until it runs.

## Steps

1. **Candidates.** Follow `references/choose.md`; its terms `<file>` serves steps 6 and 7 too.

   Modules the user named join the list with a boost: they are verified like the rest but never
   dropped, and the list is never limited to them.

2. **Verify.** For each candidate read its description and main doc: `segmently-modules show <module> --json`
   (`read[0]`; a split module: its INDEX, then only the child the task is in,
   `segmently-modules show <module>/<child> --json`; a pointer stub, exit 1: read its successor, never the
   stub). A candidate whose description is clearly off-topic may be rejected from the description
   alone. Score the rest on four questions, 0–10 each, and keep a module whose average is ≥ 5:
   1. Does its stated purpose align with the task?
   2. Does it provide components or services the task needs?
   3. Does its doc hold patterns the task will use?
   4. Would doing the task without it duplicate what it does?

   The average goes in the report; a dropped candidate goes on the rejected list with its reason.

3. **One hop out.** For each kept module, `segmently-modules related <module> --json`: the targets of its
   forward `depends-on`, `implemented-in` and `shares-contract` edges become candidates under the
   same four questions; a forward `complements` target is a `reference` at most; reverse edges are
   not followed.

4. **Usage.** Each kept module (and child) is one of:
   - `modify` — the task changes its code or its contracts;
   - `consume` — the task calls its API as it is (its developer doc and API entry points matter);
   - `reference` — the task only follows its patterns or rules.

5. **Docs for every role.** For each `modify` or `consume` module: `segmently-modules show <module> --all-roles --json`
   lists its main doc and every role doc (a child's role doc together with its parent's baseline);
   read them all. A `reference` module: its main doc only, never its role docs, even when that doc
   is long or links them; a rule it points to in a role doc is extracted as that pointer, unread.
   Never read `MODULE.legacy.md` or `roles/*.legacy.md`. From each doc take what bears on the task — the rules, constraints,
   contracts and pitfalls that will affect carrying out the plan or are presumably connected with
   it — as short extracts, each with the doc's path and role. A doc with nothing for this task
   gets one line: "read, nothing for this task". Never a retelling of the doc.

6. **Code touch points.** For each `modify` or `consume` module, one targeted pass: its code
   pointers (`show`'s `code` and `code_globs`, or `segmently-modules code-map files <module> --json` — the
   files whose `via` holds more than `docs`) searched for the task's terms in their code forms
   ("trial days" → `trialDays`): `git grep -n -e <term> -- <path> …` (no shell glob; source files
   first, tests last; the rest of the repository only when that gives nothing). Record existing
   code only, as `file:line — symbol — why` (what the task does there: changes, calls, extends).
   Discover runs before the work: it never guesses the files the work will create — where new
   code goes is the plan's decision. No code search for a `reference` module.

7. **Owners and docs to update.**

   ```bash
   segmently-modules discover --files <touch-point files> --task-file <file> --match lexical --json
   ```

   `--files` takes the paths as separate arguments (`--files a.ts b/c.ts`); one quoted string is one path. Per module: its
   `docs_to_update` (role docs too, not only the main doc); a module that owns a touch point but
   is not on your list — verify it (step 2) or name it in the risks; `files_outside_modules` (no
   module owns them: each needs `module-create` or a `[[code_map]]` rule); `missing_files`. A
   module step 2 kept stays in the report even when this gives its files to another module or to
   none — its why says "code in `<owner>`" or "outside every module"; drop a kept module only
   with a stated reason, on the rejected list.

8. **Report** in the conversation, in the shape of `references/report.md` (every section there,
   the rejected candidates included). The extracts are in the report itself, so the context
   reaches the conversation even when the agent ran the skill.

9. **JSON on request**, at the path the user names: the `discovery-results.json` shape in
   `references/report.md`.

## Exit codes

`0` ok · `1` from `show` or `related` = a pointer stub · `2` = a usage or config error: read
stderr, fix the input or report it; never retry the same command.

## Gates

No gates — read-only: it reports and stops. It asks only for a missing input or a JSON file's path;
run by the agent, that question is the agent's output.
