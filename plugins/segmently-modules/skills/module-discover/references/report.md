# The report (step 8) and the JSON (step 9)

## Report

Shown in the conversation, in this shape. Modules in usage order — `modify`, `consume`,
`reference` — and by score within each.

```markdown
## Discovery: <task, one line>

### <module>[/<child>] — usage: modify | consume | reference (score <average>)
Why: <what the task needs from it; "named by the user" when it was>
Docs:
- `<path>` (<role>): <a rule, constraint, contract or pitfall that bears on the task>
- `<path>` (<role>): read, nothing for this task
Docs to update: `<path>`, …
Code:
- `<file>:<line>` — `<symbol>` — <why: what the task touches there>
Risks / unknowns: <open questions, a doc the code contradicts, an assumption the plan must check>

### Rejected
- <module> — <reason> (score <average>, or "off-topic by its description")

### Files outside every module
- `<file>` — needs `module-create` or a `[[code_map]]` rule

### Missing files
- `<file>`
```

- Every doc step 5 read is on a `Docs:` line: an extract, or "read, nothing for this task". An
  extract is short — a quote or a close paraphrase — and says what it means for this task.
- A `reference` module has its main doc's lines and no `Code:` line.
- `Code:` holds existing code only. A file the work will create is never listed: where new code
  goes is the plan's decision.
- An empty section says "none"; it is never left out.

## JSON (`discovery-results.json`)

Only when the user asks, at the path the user names — the shape a planning pipeline reads:

```json
{
  "version": "1.0",
  "task": "<the task, verbatim>",
  "modules": [
    {
      "name": "<module>[/<child>]",
      "score": 7.5,
      "confidence": "high | medium | user_specified",
      "usage_type": "MODIFY | EXTEND | READ-ONLY",
      "documentation": {"module_md": "<main doc>", "<role>_md": "<role doc>"},
      "files": [{"path": "<file>", "offset": 42, "limit": 30, "reason": "<symbol> — <why>"}]
    }
  ],
  "files_outside_modules": [{"path": "<file>", "offset": 1, "limit": 30, "reason": "<why>"}],
  "summary": "<two or three sentences: the modules, the main risks>"
}
```

`usage_type`: `modify` → `MODIFY` (`EXTEND` when the task adds new code on the module's patterns),
`consume` and `reference` → `READ-ONLY`. `confidence`: `user_specified` for a module the user
named, else `high` (average ≥ 7) or `medium`. `documentation` holds every doc step 5 read for the
module, one key per role (`developer_md`, `qa_md`, …). `files[].offset` is the touch point's line.
