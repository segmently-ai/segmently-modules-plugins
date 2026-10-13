# The interview and the analysis (module-create, steps 2–3)

**Interview** — one question at a time; wait for each answer the user has not given yet:

1. **name**: lowercase words joined by `-`;
2. **status**: does its code exist? yes → `active`, no → `planned` (pass `--status`; without it
   the config's default applies, often `planned` even for code that exists);
3. **artifacts**: paths to its code, specs or docs to read — or none;
4. **parent**: only for a child of an existing module (then `references/child.md`);
5. **UI**: does it render a user interface (screens, dialogs, forms, layouts)? yes → `--tag ui`
   when the config ties a role to that tag (the `roles/<role>.md` rows of
   `segmently-modules templates list --json` are the configured roles);
6. **roles**: a module gets the standard role docs; an extra role (`--role`) only for a distinct
   audience with enough of its own to say.

**Analysis** — read the artifacts before anything is created; its results fill the docs later,
so keep them:

- **components**: the services, components, hooks or commands it holds — name, path, what it
  exports, its purpose (read each file, never guess from its name);
- **imports**: the import lines other code really uses for it (aliases included);
- **usage**: two or three real call sites — file, what it calls, for what;
- **critical rules**: what the code marks as critical or warns about, the constraints and
  anti-patterns its comments and checks state;
- **dependencies**, both ways: what it imports from other modules, what imports it.

Show the findings as counted lists (components found, imports, usage examples, rules — or
"none found"). Then **propose**:

- the **description** — one sentence: what it does, why it exists, when a task belongs to it. It
  decides when a task loads the module, so make the "when" plain;
- **keywords** — at least five for a module, one for a child: the words a task about it would
  use, specific to this module, never generic ("data", "service", "component").

The user corrects them. No artifacts: ask the user for its main functionality and its known
components, and propose the description and keywords from that.
