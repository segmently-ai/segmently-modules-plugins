---
name: module-create
description: Creates a new module, or a child of an existing one, with its docs and registry entry through create. Gathers the name, a one-sentence description, at least five keywords, the roles and the parent, shows a dry run and waits for a yes, then creates it, fills the scaffolded docs from what the user knows, routes its code and checks lint. Use when the user says "add a module", "create a module for X", "register this area", or when work lands in code that no module owns.
---

# module-create

Add a module (or a child of a split module) with real content, not empty templates: a module
for existing code is written from that code, so nobody builds a second copy of what exists; a
planned one says what is planned. The user confirms before anything is written.

## When to use

- The user wants a new module, or a new child under an existing module.
- `module-discover` or `module-sync` reported files that no module owns, and the user agrees
  they form a new area.

## When not to use

- The module exists and only its docs are behind: use `module-sync`.
- An existing module is too big and should become several children: use `module-split`.
- You only need to know whether a module for X already exists: use `module-scout`.

## Scope

Writes: the new module's docs (scaffolded by the `create` verb, then filled in), its registry
entry and links, a routing rule for its code in the team config (the `code-map add` verb) and,
for a child, its row in the parent's routing table. It never edits another module otherwise,
never edits a `*.legacy.md` file, and never commits.

If `segmently-modules` is not found, tell the user how to install it — the `segmently-modules` plugin for Claude Code, `uv tool install git+https://github.com/segmently-ai/segmently-modules.git`, or `pipx install git+https://github.com/segmently-ai/segmently-modules.git` — and stop until it runs.

## Steps

- **analyse** — interview, analysis (steps 2–3) → `references/analyse.md`
- **child** — a child module (steps 4–7) → `references/child.md`
- **fill** — the docs' content, the report (steps 6, 10) → `references/fill.md`

1. Check the name is free and not a duplicate in disguise.

   ```bash
   segmently-modules list --json
   segmently-modules match "<the new module's main words>" --match lexical --json
   ```

   A strong match means an existing module may own this area: show it and ask before
   going on.

2. Ask (`references/analyse.md`), one question at a time: name, status (code exists → `active`, else `planned`),
   artifacts to read, parent, whether it renders a user interface, extra roles.

3. Analyse the artifacts and show the findings (components with paths, imports, real usages,
   critical rules, dependencies both ways). From them propose the description and at least five
   keywords (a child: one); the user corrects them.

4. Show the plan and wait.

   ```bash
   segmently-modules create <name> --non-interactive --status <status> --description "<one sentence>" --keywords "<k1, k2, k3, k4, k5>" --dry-run
   ```

   Add `--tag` or `--role` as gathered; a child: `references/child.md`. Show the files, the registry entry and the findings in
   short. Exit 2 names what is wrong (a taken name, a description out of bounds, too few
   keywords): fix it with the user and show the dry run again. **Wait for an explicit yes.**

5. Create it — the same command with `--json` in place of `--dry-run`.

6. Fill the scaffolded docs (the `files` of the result) as `references/fill.md` says. Never invent
   components or rules; "Planned:" before what does not exist yet.

7. Seed its links from the dependencies found:

   ```bash
   segmently-modules related <name> --json
   segmently-modules registry append <name> related_modules '{"module": "<other>", "relation": "<relation>", "description": "<why>"}' --json
   ```

8. Route its code, when the user said where it lives.

   ```bash
   segmently-modules code-map add <rule id> --glob "<glob>" --module <name> --dry-run
   segmently-modules code-map add <rule id> --glob "<glob>" --module <name> --json
   ```

   Show the dry run first. An existing rule id is refused: pick another.

9. Check it.

   ```bash
   segmently-modules lint --json
   segmently-modules show <name> --json
   segmently-modules match "<a typical task for it>" --match lexical --json
   ```

   No error findings for the new module; every doc in `read[]` exists; the typical task ranks
   the new module first — else improve its keywords with the user.

10. Report as `references/fill.md` says. Ask the user to review and commit.

## Gates

- Each question (step 2) and the proposed description and keywords (step 3): wait for the answer.
- After the dry run (step 4): nothing is written until the user says yes.
- Before routing code (step 8): the user confirms the glob.

## Exit codes

`0` ok · `1` from `lint` = findings (fix the new module's, report the others) · `2` = a
refused input or config error: read stderr, fix with the user, run again.
