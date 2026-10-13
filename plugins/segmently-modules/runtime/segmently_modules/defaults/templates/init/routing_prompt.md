# Write routing tasks for ${count} modules

A module registry routes a developer's task to the module it belongs to. Write the tasks a
developer would type about each module below, so that routing can be measured.

For each module write ${per_module} task(s):

- one short sentence each, the way a developer asks for a change, a fix or an explanation;
- about what the module does — from its purpose and its files — in varied words;
- never the module's name alone, never a file path.

Answer with JSON only: a list of objects `{"task": "<the task>", "module": "<the module name>"}`,
${per_module} per module, every module below.

${modules}
