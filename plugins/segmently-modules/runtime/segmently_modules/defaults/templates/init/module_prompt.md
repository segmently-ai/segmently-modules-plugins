# Write the docs of the module `${module}`

You document one module of an existing codebase for its module registry. Read the module's code
first, then write the files below into the staging directory `${staging_dir}/` — nothing else,
nowhere else.

## The module

- Name: `${module}`
- Code: ${paths} ${files_note}
- Neighbours (modules its code imports from):
${neighbours}
- The other modules of this repository — what they own is not this module's:
${others}

Files:
${files}

## What to write into `${staging_dir}/`

Each doc from its template below: keep the headings, fill every `<…>` placeholder, replace the
HTML comments with what they ask for.

${docs}
### `entry.json`

A JSON object with exactly these keys:

- `description`: one sentence of ${description_min}–${description_max} characters — what the module does, why
  it exists, when a task belongs here;
- `keywords`: at least ${min_keywords} and at most ${max_keywords} distinct words a developer
  would type in a task about this module — and about no other module. Give the words for what
  the module handles as a task would name them, including the things and actions its
  `## Purpose` paragraph names, even where the code names them differently (a payments module:
  `card`, `decline`, `charge`). Routing ignores word endings (`-s`, `-es`, `-ed`, `-ing`), so
  give one form per word (`charge`, not also `charges`, `charged`, `charging`; `score` and
  `scoring` are one word, `suggest` and `suggestion` two); single words,
  and a phrase of several words only when developers write exactly that phrase. Leave out:
  - generic words that fit any module: ${generic_words} (a word of this module's own name is
    fine);
  - the things another module owns (the list above), even when this module stores, caches,
    syncs or calls them: name one only when a task about it changes this module's code;
  - words that read as the developer's own tools — `module`, `test`, `build`, `commit` —
    unless this module is that tool.
  A word only this module would answer beats a word many modules would;
- `related_modules` (optional): edges `{"module": "<name>", "relation": "<relation>",
  "description": "<one sentence>"}` to the neighbours above or to other modules of the
  registry; a relation is one of: ${relations}.${ask_fields}

## Rules

- Describe only components that exist: every path you name exists in the repository, and every
  symbol you name occurs in the file you cite. When unsure, leave it out.
- Put every repository path in backticks, root-relative, exactly as the file list above shows
  it (`src/app/main.py`): backticks mark a path the check verifies. A path inside a package is
  written from the repository root, not from the package
  (`services/recommendations/recommendations/engine.py`, not `recommendations/engine.py`).
- Never backtick a path that does not exist — a test directory the module lacks, an import
  specifier such as `./lines`, a sibling doc written as `roles/qa.md`: write those in plain
  words, or give the full root-relative path of a file that exists (a sibling doc:
  `${modules_dir}/${module}/roles/qa.md`; the main doc: `${modules_dir}/${module}/${module_doc}`).
- In `MODULE.md`, list the components in the table `| Name | Path | Purpose |`: `Name` holds one
  symbol in backticks (a function, class, type or constant defined in that file) or plain words
  for a whole file, `Path` the file in backticks.
- Under `## Purpose`, write in your own words what the module is for, as a paragraph that stands
  on its own — do not repeat the description.
- Leave no placeholder of these templates behind: a dollar sign and an opening brace around
  one of their names (the title, the description, the module, the role, the files, the paths,
  the docs and the others these templates use). A dollar sign with a brace that belongs to the
  code you describe — a shell variable, a JavaScript template string — is fine; a code sample
  that uses one of these templates' names that way is refused: reword it.
- Never write outside `${staging_dir}/`; never edit code, the registry or another module's docs;
  never commit.
