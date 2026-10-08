# Contributing a rulepack

A rulepack is one YAML file in this directory. It's loaded automatically —
adding a new file here is enough; nothing in `src/ph_repo_auditor/` needs to
change. Open a PR that touches only this directory plus a test fixture (see
`tests/test_rulepacks.py` for the pattern).

## Schema

```yaml
id: community/your-rulepack-name   # becomes the pack id: rulepack:<id>
version: "1.0.0"
description: Optional, for humans reading this file.
rules:
  - id: your-rule-id               # becomes the rule id: <rulepack id>/<rule id>
    title: Short title shown in reports
    category: hygiene              # any string; "hygiene" if unsure
    severity: warning              # error | warning | info (default: warning)
    type: presence                 # presence | regex | json_key
    file_globs: ["**/*.py"]        # required for every type, see below
    message: What's wrong, shown in the finding.
    fix: A concrete suggested change.

    # presence-only:
    when: exists                  # exists | missing

    # regex-only:
    pattern: "TODO|FIXME"          # a Python regex, searched per line

    # json_key-only:
    when: missing                 # missing | present
    key: license                  # a top-level key, or dotted ("a.b.c") for nested
```

### `file_globs`

A small glob dialect, not a full glob library: `*` matches within one path
segment, `?` matches one character, and a leading `**/` matches any depth
(including zero directories) before the rest of the pattern. `"**/.DS_Store"`
matches both `.DS_Store` and `src/nested/.DS_Store`; `"*.sql"` matches
`seed.sql` but not `db/seed.sql`.

### Rule types

- **`presence`** — fires once if any (`when: exists`) or none
  (`when: missing`) of the matched paths exist.
- **`regex`** — fires once per matching line, in every file matching
  `file_globs`, anchored to that file and line number.
- **`json_key`** — for every matching file that parses as a JSON object,
  fires if a key is missing (`when: missing`) or present (`when: present`).
  This is a lightweight presence check on a key path, not full JSON Schema
  validation — if you need real schema validation, write a Python pack
  instead (see `packs/fhir.py` for an example of a more involved pack).

### What gets skipped, and how you'll know

A rulepack that fails to parse, or whose `id`/`rules` are missing or
malformed, is skipped — the rest of the audit still runs. An individual
rule with a bad `type`/`severity`/`pattern`/`when`/`key` is skipped on its
own; the rest of the rulepack's rules still load. Either way, a warning
naming the file and the specific problem shows up in the report's "Policy
warnings" section — run your rulepack against a test repo and check there
if a rule you added doesn't seem to be firing.

### Keep it safe

Rules only read already-scanned repository content (file paths and text) —
there's no code execution, no network access, and no path traversal outside
the repository being audited. Keep it that way: a community rulepack must
never need more than `file_globs` + a presence/regex/key check to express
what it's checking for.
