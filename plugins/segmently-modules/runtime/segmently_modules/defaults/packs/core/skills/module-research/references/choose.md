# Choosing candidates when no module is named (step 1)

Run `segmently-modules catalog --json`; read `match.mode` and `search`. The text: the user's topic or
question. The mode: `hybrid` unless the user says otherwise ("only lexical", "by meaning", in any
language) or `match.mode` is `semantic`; a `lexical` config is only the command line's default
and never skips the search by meaning, which needs no setting; the keyword commands always pass
`--match lexical`. The user may set the model ("use opus") and the depth ("search deep":
`choose --effort deep`; `<reasoning>` follows it).

- By meaning (`semantic`, `hybrid`): write the text, verbatim, to `<task file>`. **Claude Code:**
  `segmently-modules choose --task-file <task file> > <order file>`; give `<order file>`'s path to the
  `segmently-modules:module-chooser` agent with `model: <search.claude_model>` (without that agent: a
  subagent told "this file is your whole task; answer with its JSON only; change nothing"); its
  reply is the answer. **Codex:** the same with `--json`, its `answer_schema` written to
  `<schema file>`, then
  `codex exec -m <search.codex_model> -c model_reasoning_effort=<reasoning> --sandbox read-only --output-schema <schema file> - < <order file>`
  (`low`, `medium`, `high` for `quick`, `standard`, `deep`). **Elsewhere** (no subagent, no
  `codex exec`, or it fails, as inside a sandbox): answer the order yourself, every card read, by its rules. Pipe the answer to
  `segmently-modules choose --apply - --json`.
- By keyword (`lexical`, `hybrid`):
  `segmently-modules context --task-file <the domain terms and code identifiers, in English, in a file> --match lexical --json`:
  its `modules`; none but `near_misses`: list them, ask which is meant.
- `hybrid`: merge the lists; a module found both ways ranks first.

Keep the top 3; never widen the list on your own.

If a temporary file cannot be written (a read-only sandbox), pass the task through a quoted
heredoc and read the order from stdout instead of a file:

```bash
segmently-modules choose --task-file - <<'EOF'
<the task text, verbatim>
EOF
```
