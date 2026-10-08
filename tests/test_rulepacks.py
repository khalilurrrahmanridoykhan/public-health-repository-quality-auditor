from ph_repo_auditor.auditor import audit_repository
from ph_repo_auditor.models import AuditPolicy
from ph_repo_auditor.packs import PackRegistry, RepoView
from ph_repo_auditor.packs.rulepacks import (
    RulepackPack,
    _glob_to_regex,
    load_rulepacks,
    parse_rulepack,
    rulepack_relevant_paths,
)

# -- glob translation -------------------------------------------------------


def test_glob_star_matches_within_one_segment():
    pattern = _glob_to_regex("*.sql")
    assert pattern.match("seed.sql")
    assert not pattern.match("db/seed.sql")


def test_glob_double_star_matches_any_depth_including_zero():
    pattern = _glob_to_regex("**/.DS_Store")
    assert pattern.match(".DS_Store")
    assert pattern.match("src/nested/.DS_Store")
    assert not pattern.match("src/.DS_Storex")


def test_glob_question_mark_matches_one_character():
    pattern = _glob_to_regex("file?.txt")
    assert pattern.match("file1.txt")
    assert not pattern.match("file12.txt")


# -- parse_rulepack ----------------------------------------------------------

VALID_YAML = """
id: community/example
version: "1.0.0"
rules:
  - id: no-foo
    title: Example rule
    type: regex
    pattern: "foo"
    file_globs: ["**/*.py"]
    message: Found foo.
    fix: Remove foo.
"""


def test_parse_rulepack_happy_path():
    rulepack, warnings = parse_rulepack(VALID_YAML, "example.yml")
    assert warnings == []
    assert rulepack is not None
    assert rulepack.id == "community/example"
    assert rulepack.version == "1.0.0"
    assert len(rulepack.rules) == 1
    assert rulepack.rules[0].severity == "warning"  # default


def test_parse_rulepack_rejects_invalid_yaml():
    rulepack, warnings = parse_rulepack("not: valid: yaml: at: all:", "bad.yml")
    assert rulepack is None
    assert len(warnings) == 1
    assert "invalid YAML" in warnings[0]


def test_parse_rulepack_rejects_non_mapping():
    rulepack, warnings = parse_rulepack("- just\n- a\n- list\n", "bad.yml")
    assert rulepack is None
    assert "must be a YAML mapping" in warnings[0]


def test_parse_rulepack_requires_an_id():
    rulepack, warnings = parse_rulepack("version: '1.0.0'\nrules: []\n", "noid.yml")
    assert rulepack is None
    assert "no string `id`" in warnings[0]


def test_parse_rulepack_requires_non_empty_rules():
    rulepack, warnings = parse_rulepack("id: x\nrules: []\n", "norules.yml")
    assert rulepack is None
    assert "non-empty `rules`" in warnings[0]


def test_parse_rulepack_skips_one_bad_rule_but_keeps_the_rest():
    content = """
id: community/mixed
rules:
  - id: good-rule
    title: Good
    type: regex
    pattern: "x"
    file_globs: ["*.py"]
    message: m
  - id: bad-rule
    title: Bad
    type: not-a-real-type
    file_globs: ["*.py"]
    message: m
"""
    rulepack, warnings = parse_rulepack(content, "mixed.yml")
    assert rulepack is not None
    assert len(rulepack.rules) == 1
    assert rulepack.rules[0].id == "good-rule"
    assert len(warnings) == 1
    assert "bad-rule" in warnings[0]


def test_parse_rulepack_skips_the_whole_file_when_every_rule_is_invalid():
    content = "id: community/allbad\nrules:\n  - id: x\n    type: nope\n    file_globs: ['*']\n    title: t\n    message: m\n"
    rulepack, warnings = parse_rulepack(content, "allbad.yml")
    assert rulepack is None
    assert any("rulepack skipped" in warning for warning in warnings)


def test_parse_rulepack_rejects_invalid_regex_pattern():
    content = (
        "id: community/badregex\nrules:\n  - id: x\n    type: regex\n"
        "    pattern: '(unclosed'\n    file_globs: ['*.py']\n    title: t\n    message: m\n"
    )
    rulepack, warnings = parse_rulepack(content, "badregex.yml")
    assert rulepack is None
    assert "invalid `pattern`" in warnings[0]


def test_parse_rulepack_requires_a_recognised_when_for_presence_rules():
    content = (
        "id: community/badwhen\nrules:\n  - id: x\n    type: presence\n"
        "    when: sideways\n    file_globs: ['*']\n    title: t\n    message: m\n"
    )
    rulepack, warnings = parse_rulepack(content, "badwhen.yml")
    assert rulepack is None
    assert "`when`" in warnings[0]


# -- RulepackPack.run() -------------------------------------------------------


def _run(content: str, files: dict[str, str | None]):
    rulepack, warnings = parse_rulepack(content, "test.yml")
    assert not warnings
    return RulepackPack(rulepack).run(RepoView(files), AuditPolicy())


PRESENCE_EXISTS = """
id: community/presence-exists
rules:
  - id: no-ds-store
    title: .DS_Store committed
    type: presence
    when: exists
    file_globs: ["**/.DS_Store"]
    message: m
"""

PRESENCE_MISSING = """
id: community/presence-missing
rules:
  - id: needs-codeowners
    title: Missing CODEOWNERS
    type: presence
    when: missing
    file_globs: ["CODEOWNERS"]
    message: m
"""

REGEX_RULE = """
id: community/regex
rules:
  - id: no-todo
    title: TODO left in source
    type: regex
    pattern: "TODO"
    file_globs: ["**/*.py"]
    message: m
"""

JSON_KEY_MISSING = """
id: community/json-missing
rules:
  - id: license-field
    title: package.json missing license
    type: json_key
    when: missing
    key: license
    file_globs: ["package.json"]
    message: m
"""

JSON_KEY_PRESENT = """
id: community/json-present
rules:
  - id: has-private-flag
    title: package.json marked private
    type: json_key
    when: present
    key: private
    file_globs: ["package.json"]
    message: m
"""


def test_presence_exists_rule_fires_when_a_matching_path_exists():
    findings = _run(PRESENCE_EXISTS, {"src/nested/.DS_Store": None})
    assert len(findings) == 1
    assert findings[0].rule_id == "community/presence-exists/no-ds-store"
    assert findings[0].file == "src/nested/.DS_Store"


def test_presence_exists_rule_is_quiet_on_a_clean_repo():
    findings = _run(PRESENCE_EXISTS, {"README.md": "hi"})
    assert findings == []


def test_presence_missing_rule_fires_when_no_matching_path_exists():
    findings = _run(PRESENCE_MISSING, {"README.md": "hi"})
    assert len(findings) == 1


def test_presence_missing_rule_is_quiet_when_the_file_exists():
    findings = _run(PRESENCE_MISSING, {"CODEOWNERS": "* @owner"})
    assert findings == []


def test_regex_rule_fires_per_matching_line_with_correct_anchoring():
    content = "x = 1\n# TODO: fix this\ny = 2\n"
    findings = _run(REGEX_RULE, {"app.py": content})
    assert len(findings) == 1
    assert findings[0].file == "app.py"
    assert findings[0].line == 2


def test_regex_rule_ignores_non_matching_globs():
    findings = _run(REGEX_RULE, {"app.rb": "# TODO: fix this\n"})
    assert findings == []


def test_json_key_missing_rule_fires_when_key_absent():
    findings = _run(JSON_KEY_MISSING, {"package.json": '{"name": "x"}'})
    assert len(findings) == 1


def test_json_key_missing_rule_is_quiet_when_key_present():
    findings = _run(JSON_KEY_MISSING, {"package.json": '{"license": "MIT"}'})
    assert findings == []


def test_json_key_present_rule_fires_when_key_present():
    findings = _run(JSON_KEY_PRESENT, {"package.json": '{"private": true}'})
    assert len(findings) == 1


def test_json_key_rule_tolerates_invalid_json():
    findings = _run(JSON_KEY_MISSING, {"package.json": "{not valid json"})
    assert findings == []


# -- load_rulepacks() + registry integration --------------------------------


def test_load_rulepacks_discovers_the_bundled_example():
    packs, warnings = load_rulepacks()
    assert warnings == []
    assert any(pack.id == "rulepack:community/no-macos-cruft" for pack in packs)


def test_registry_includes_rulepacks_by_default():
    repo = RepoView({"README.md": "hi"})
    active = PackRegistry().select(repo)
    assert "rulepack:community/no-macos-cruft" in {pack.id for pack in active}


def test_registry_can_opt_out_of_rulepacks():
    repo = RepoView({"README.md": "hi"})
    active = PackRegistry(include_rulepacks=False).select(repo)
    assert not any(pack.id.startswith("rulepack:") for pack in active)


def test_audit_repository_catches_a_planted_ds_store():
    report = audit_repository("owner/repo", {".DS_Store": None, "README.md": "hi"})
    hits = [f for f in report.findings if f.rule_id.endswith("ds-store-committed")]
    assert len(hits) == 1
    assert hits[0].severity == "warning"


def test_rulepack_relevant_paths_is_empty_for_the_presence_only_bundled_example():
    # The bundled community/no-macos-cruft rule is presence-only — a path
    # merely existing in the tree listing is enough to evaluate it, so the
    # GitHub App client shouldn't need to spend a Contents API call on it.
    assert rulepack_relevant_paths(["a.py", ".DS_Store"]) == set()


def test_rulepack_relevant_paths_matches_a_regex_rule_glob(monkeypatch):
    content_rulepack = """
id: community/needs-content
rules:
  - id: no-todo
    title: TODO
    type: regex
    pattern: "TODO"
    file_globs: ["**/*.rb"]
    message: m
"""

    def fake_load_rulepacks():
        rulepack, warnings = parse_rulepack(content_rulepack, "fake.yml")
        assert not warnings
        return [RulepackPack(rulepack)], []

    monkeypatch.setattr(
        "ph_repo_auditor.packs.rulepacks.load_rulepacks", fake_load_rulepacks
    )
    relevant = rulepack_relevant_paths(["app.rb", "app.py", "lib/thing.rb"])
    assert relevant == {"app.rb", "lib/thing.rb"}


def test_disabled_packs_turns_a_rulepack_off():
    policy = AuditPolicy(disabled_packs=("rulepack:community/no-macos-cruft",))
    report = audit_repository(
        "owner/repo", {".DS_Store": None, "README.md": "hi"}, policy
    )
    assert not any(f.pack.startswith("rulepack:") for f in report.findings)
