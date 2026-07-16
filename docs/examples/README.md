# Example review profiles

The software no longer ships built-in discipline checklists — the review plan
is **authored by the model per set** (from the detected disciplines,
jurisdiction, and adopted codes) and injected through the same profile
machinery. The files here are worked examples for writing your own.

To use one (or your own office checklist), copy it into your user profiles
directory and it will appear in the GUI's profile panel and resolve by name
from the API:

```
~/.drawing_analyzer/profiles/          # default
$DRAWING_ANALYZER_PROFILES_DIR/        # override
```

A profile is a Markdown file: a small `---`-delimited frontmatter header
(`name`, `title`, `disciplines`, `version`, `author`, `date`) followed by a
flat bullet list of one-line checks. `disciplines` tags drive the GUI's
auto-suggest (matched against the set's sheet-id discipline letters). Editing
a profile automatically re-keys the critique cache.

- `fire_protection.md` — a senior fire-protection engineer's NFPA 13 sprinkler
  back-check (the former built-in starter profile).
