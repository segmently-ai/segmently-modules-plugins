# The rules of the segmently-modules choose work order

The instruction the agent that picks modules by meaning follows: the Segmently Modules plugin's
module-chooser agent, `codex exec`, or your own agent command (SEGMENTLY_MODULES_AGENT_COMMAND).
Every line that starts with "- " is one rule, sent as written; the other lines (these) are
notes for you and are not sent. Placeholders: $max_picks (the most picks the order allows)
and $depth (the sentence for [search] effort). Change the rules in your copy:
segmently-modules templates override choose/rules.md

- Read every card before you choose: the cards are the whole catalog. Never filter them by the task's words — a module may describe the task in other words or in another language.
- Choose the modules this task needs by meaning, in any language the task is written in.
- A card with a parent is one area of a split module: when the task is in that area, pick that child; add the parent only when the task also changes what all its areas share.
- Use only module ids that appear in the cards; never invent one.
- Answer {"picks": [], "none": true} when you are not sure.
- Give at most $max_picks picks, best first, each with a confidence from 0 to 1 and a short reason.
- $depth
- Answer with one JSON object that matches the answer schema, and nothing else.
