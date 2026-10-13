# The session's knowledge (module-sync, step 1)

The conversation that did the work is the primary source. It holds what no diff shows: why an
option was rejected, a behaviour found while debugging, a pitfall that cost an hour, a rule the
user stated. Lost here, it is lost for the next person who touches the module.

Walk the conversation in order and collect:

- **Plan goal** — the approved plan (a file or the discussion): its goal, steps and key decisions.
- **Decisions** — each choice made, with the alternatives rejected and why.
- **Discoveries** — bugs, edge cases, behaviour nobody had written down.
- **Patterns** — a new way of doing a thing that others should follow, or an anti-pattern to avoid.
- **Gotchas** — pitfalls met and their workarounds.
- **Dependencies** — new flows between modules (they become `related_modules` edges in step 7).
- **Critical rules** — constraints a later developer must know, with their reason.

Map each item to a module, first match wins: the module the conversation names > the module that
owns the file the item is about (the step-3 rows) > a module the step-4 search finds for it > a
module the dependency implies. On a split module pick the child by the parent's routing table and
the children's keywords; a rule for the whole module goes to the parent. Work in an area no
module owns: propose a child of the module whose area it extends (`module-create` with
`--parent`), a new top-level module only when no parent fits — ask (gate 2) when neither clearly
wins.

An item no module takes is a homeless discovery: report it, never drop it.

Leave out what does not help a later reader: the course of the conversation, dead ends that
taught nothing, temporary values, anything only true for this session. Keep the reason with every
rule — a rule without its why gets removed by the next person it bothers.

No conversation about the work to read (a fresh session, or only a branch handed over): say so in
the findings and sync from the change alone.
