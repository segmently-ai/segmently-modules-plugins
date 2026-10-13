---
name: module-assistant
description: The module system's assistant. Sets Segmently Modules up in a repository, explains how to do something with the module docs in plain words and does it on the user's OK, turns what the repository needs now into a short plan and carries it out, and plans goals that take several module skills. Use when the user asks what to do next with the module docs, how to do something in Segmently Modules, to set it up, or for a plan.
argument-hint: "[scenario] [goal]"
arguments: scenario goal
---

# module-assistant

The entry point for work on the module system itself: setting it up, knowing what needs
attention, how to do something, and a plan that takes several skills. It reads the state with
Segmently Modules, proposes in the user's terms, waits for the OK, then carries the plan out — mechanical
steps with Segmently Modules verbs, judgement steps by handing them to the skill that owns them. The
commands are its own business: the user sees modules, docs, roles, templates and checks.

## When to use

| The user … | Scenario |
|---|---|
| wants Segmently Modules here: "set up", "init", "start", "adopt our registry" | start |
| asks how to do something, or whether Segmently Modules can: "how do I …", "where do I change …" | how-to |
| asks what needs attention: "what next", "what is left", "clean up the module docs", after an upgrade | next |
| has a goal bigger than one skill: "get our module docs in shape", "set up the CI gate" | plan |

## When not to use

- The user asks for one job a skill does: read a module (`module-scout`), map a task
  (`module-discover`), sync after work (`module-sync`), create, split or lint — use that skill.
- The task is about the product's code, not about the module system.

## Scope

Writes only what the plan the user approved names, through Segmently Modules verbs or by handing a step
to its skill. Read-only Segmently Modules commands (`next`, `list`, `lint`, `ci`, `roles list`,
`templates list`, `coverage`, `code-map list`, `code-map files`, any `--dry-run`, a verb's
`--help`) run without asking. It never edits code or a
`*.legacy.md` file, and never commits: ask the user to review and commit.

If `segmently-modules` is not found, tell the user how to install it — the `segmently-modules` plugin for Claude Code, `uv tool install git+https://github.com/segmently-ai/segmently-modules.git`, or `pipx install git+https://github.com/segmently-ai/segmently-modules.git` — and stop until it runs.

## Steps

**Route.** Take the scenario named by the invocation (`$scenario`) when one is given, else by
the user's words (the table above), and its file below: read it, then follow it — its steps are
step 2.

- **start** — Segmently Modules is not set up here, or the user wants it set up, adopted or mapped from
  code → `references/start.md`
- **how-to** — "how do I …", "can Segmently Modules …", a question about a command, a config key or a
  skill → `references/how-to.md`
- **next** — what needs attention now → `references/next.md`
- **plan** — a goal that takes several skills or steps (`$goal`, else the user's words) →
  `references/plan.md`

If a `segmently-modules` command exits 1 or 2, read `references/exit-codes.md`.

1. **Orient.** `segmently-modules next --json` (read-only). Its one item `setup` means Segmently Modules is not set
   up here: take the start route, unless the user only asked how to do something.
2. **Follow the scenario's file.**
3. **Close.** After any write run `segmently-modules next --json` again, then report what changed, what is
   left and the one next step you suggest.

**Replies are short and in the user's terms.** Talk about modules, their docs, roles,
templates, checks and agents — never commands, flags, config keys or file paths unless the user
asks for them. The answer in a few lines and the one question or OK you need; why, undo,
alternatives, effort and tables only when asked. No asides: what you left out or did not check,
a caveat, the rules you keep (no commits) — only when it changes the user's decision.

**Handing a step to a skill.** Invoke the skill by name with what the plan already knows (the
module, the role, the goal); where skills cannot be invoked, read its `SKILL.md` in the agent's
skill directory and follow it. The skill keeps its own gates.

## Gates

Read-only commands run without asking. Before any write, show the plan — short steps in plain
words, what each one changes — and ask for the OK in a sentence that says what will happen
("Add a Metrics section to the PO template? New modules get it; existing docs stay as they
are."); the user may approve part of it. A step that needs more than the plan said (another file, another command, a
refused write) stops for a new OK. Never present a command or a flag you have not seen in
the verb's `--help` or in this skill's files.
