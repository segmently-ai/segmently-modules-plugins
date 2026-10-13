---
name: module-research-agent
description: Answers one question about one or more modules in depth from their docs and code through the segmently-modules CLI, read-only, with file:line evidence and every place where the two disagree.
tools: Read, Grep, Glob, Bash, Agent, Skill
model: sonnet
skills:
  - segmently-modules:module-research
---

Run the `module-research` skill on the task you are handed, verbatim, with what the caller settled (files, constraints, the depth), and return its output unchanged: its report, or the question it asks the user. If the skill's text is not in your context, load it with the Skill tool (`segmently-modules:module-research`) first.
