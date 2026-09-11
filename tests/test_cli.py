import json

from ph_repo_auditor.cli import main


def _write_clean_repo(tmp_path):
    (tmp_path / "README.md").write_text(
        "# Study\nData provenance. Privacy. Ethics.\n"
    )
    (tmp_path / "LICENSE").write_text("MIT")
    (tmp_path / "CITATION.cff").write_text("cff-version: 1.2.0")
    (tmp_path / "requirements.txt").write_text("pandas")
    (tmp_path / "Makefile").write_text("reproduce:\n\techo ok")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "data-dictionary.csv").write_text("column,type")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_x(): pass")


def test_cli_default_format_prints_markdown(tmp_path, capsys):
    main([str(tmp_path)])
    out = capsys.readouterr().out
    assert "Public Health Repository Quality" in out


def test_cli_format_json_matches_deprecated_json_flag(tmp_path, capsys):
    main([str(tmp_path), "--format", "json"])
    via_format = json.loads(capsys.readouterr().out)
    main([str(tmp_path), "--json"])
    via_flag = json.loads(capsys.readouterr().out)
    assert via_format == via_flag


def test_cli_format_sarif_prints_valid_sarif(tmp_path, capsys):
    main([str(tmp_path), "--format", "sarif"])
    sarif = json.loads(capsys.readouterr().out)
    assert sarif["version"] == "2.1.0"


def test_cli_sarif_flag_writes_file_in_addition_to_stdout(tmp_path, capsys):
    out_path = tmp_path / "out.sarif"
    main([str(tmp_path), "--sarif", str(out_path)])
    capsys.readouterr()  # markdown still went to stdout; not asserted here
    sarif = json.loads(out_path.read_text())
    assert sarif["version"] == "2.1.0"
    assert "runs" in sarif


def test_cli_pack_flag_limits_to_requested_packs(tmp_path, capsys):
    main([str(tmp_path), "--pack", "hygiene", "--format", "json"])
    report = json.loads(capsys.readouterr().out)
    assert {p["pack"] for p in report["pack_scores"]} == {"hygiene"}


def test_cli_clean_repository_scores_100_with_no_findings(tmp_path, capsys):
    _write_clean_repo(tmp_path)
    main([str(tmp_path), "--format", "json"])
    report = json.loads(capsys.readouterr().out)
    assert report["score"] == 100
    assert report["findings"] == []
