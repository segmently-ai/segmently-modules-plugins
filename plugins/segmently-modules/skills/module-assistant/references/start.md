# start: set Segmently Modules up here

Step 2 of `module-assistant` when Segmently Modules is not set up here, or the user wants it set up,
adopted from an existing registry or mapped from the code.

1. **Read the state** (read-only):
   - `segmently-modules next --json` — the one item `setup` means: no config and no registry;
   - the registry: `segmently-modules list --json` (how many modules it lists; exit 2 "registry not
     found" = none) and `.segmently-modules/config.toml` (present; its `[paths]` names the registry when
     it is not the default);
   - a registry file another tool wrote: a JSON file under the modules directory that lists
     modules (look before you decide there is none);
   - the code: `git ls-files | cut -d/ -f1 | sort | uniq -c | sort -rn | head` — where the
     source lives and how much of it there is.

2. **Pick the way in** and say why in one sentence, with the evidence from step 1:

   | State | Way in |
   |---|---|
   | A registry and module docs that other tooling wrote, no Segmently Modules config (or `segmently-modules lint --json` cannot read the registry) | `module-adopt` |
   | Code, no registry | setup (starter config, skill copies, the agents' block), then `module-init` maps the code into modules |
   | No code yet, or a new repository | setup, then `module-create` for the first module when the user names one |
   | Config and registry present, `next` lists no `setup` item | already set up: say so, then take the next route (`references/next.md`) |

3. **Ask the choices that apply, in one round, in plain words:**
   - which AI agents the team uses — Claude Code, Codex, Cursor, Gemini, Copilot (default:
     Claude Code and Codex); each gets the skills and a short Segmently Modules section in its
     instruction file (`CLAUDE.md`, `AGENTS.md`; Gemini CLI: `GEMINI.md`);
   - whether they also want the acceptance-criteria skills (the `qa` pack) and the UI design
     skill (the `ui` pack) — `[packs] builtin` in `.segmently-modules/config.toml`.

4. **The plan,** a line per step in plain words. Run the setup's dry run yourself —
   `segmently-modules setup --dry-run --agent claude --agent codex --target CLAUDE.md --target AGENTS.md`
   with the user's agents and files — and say in one line what it will create (the Segmently Modules
   settings, an empty module list, the skills for their agents, the section in the
   instruction files). Wait for the OK.

5. **Carry it out.**
   - The same setup command without `--dry-run`, with `--json` — idempotent: a second run
     writes nothing.
   - Packs besides `core`: add them to `[packs] builtin` in `.segmently-modules/config.toml`
     (`builtin = ["core", "qa", "ui"]`), then `segmently-modules packs sync --json --agent claude --agent codex` (the
     agents of step 3) and `segmently-modules agents-md --json --target <file>` for each instruction file,
     so the copies and the block follow.
   - Hand `module-adopt`, `module-init` or `module-create` its step (the skill keeps its own
     gates: init stops for the user to confirm the modules).

6. `segmently-modules next --json`; report, and suggest the next step — usually the next route.
