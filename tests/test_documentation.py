
"""Tests for scanner/documentation.py. No network access is used."""

import time

import pytest

from scanner.documentation import (
    EXAMPLES_PATTERN, INSTALL_PATTERN, USAGE_PATTERN,
    clean_for_display, extract_headings, extract_section_headings,
    run_documentation_checks,
)
from scanner.models import RepoSnapshot

FULL_README = """# Demo project

Some introduction.

## Installation

pip install demo

## Usage

demo --help

## Examples

See the examples folder.
"""


def make_snapshot(files, metadata=None, texts=None, truncated=False,
                  tree_available=True, text_truncated=False):
    texts = texts or {}
    calls = []

    def reader(path):
        calls.append(path)
        if path in texts:
            return texts[path], text_truncated
        return None

    snapshot = RepoSnapshot(
        metadata or {}, files if tree_available else None,
        truncated=truncated, reader=reader,
    )
    snapshot.calls = calls
    return snapshot


def run(snapshot):
    return {finding.id: finding for finding in run_documentation_checks(snapshot)}


# ---------- extract_headings ----------

def test_extract_markdown_headings():
    assert extract_headings("# One\n\ntext\n\n## Two ##\n###Not a heading\n") == ["One", "Two"]


def test_extract_underlined_headings():
    text = "Installation\n============\n\ntext\n\nUsage\n-----\n"
    assert extract_headings(text) == ["Installation", "Usage"]


def test_extract_html_headings():
    assert extract_headings('<h2 align="center">Usage <b>Guide</b></h2>') == ["Usage Guide"]


def test_headings_inside_code_blocks_are_ignored():
    text = "# Title\n\n```bash\n# Installation\n```\n\n~~~\n# Usage\n~~~\n"
    assert extract_headings(text) == ["Title"]


def test_very_long_lines_are_skipped_quickly():
    text = "# " + "a" * 100_000 + "\n# Real heading\n" + " " * 100_000 + "\n"
    start = time.perf_counter()
    headings = extract_headings(text)
    assert time.perf_counter() - start < 1.0
    assert headings == ["Real heading"]


def test_clean_for_display_removes_control_characters_and_shortens():
    cleaned = clean_for_display("Install\x1b[31m\nnow\x00" + "x" * 200)
    assert "\x1b" not in cleaned and "\x00" not in cleaned and "\n" not in cleaned
    assert len(cleaned) <= 80


# ---------- Heading patterns ----------

@pytest.mark.parametrize(
    "heading",
    ["Installation", "How to install", "Setup", "Getting Started",
     "Quick-start guide", "Quick start", "Set-up", "Set up"],
)
def test_install_pattern_matches(heading):
    assert INSTALL_PATTERN.search(heading)


def test_install_pattern_does_not_match_set_upstream():
    assert not INSTALL_PATTERN.search("Set upstream remote")


@pytest.mark.parametrize("heading", ["Usage", "How to use it", "Using the CLI", "Quickstart"])
def test_usage_pattern_matches(heading):
    assert USAGE_PATTERN.search(heading)


@pytest.mark.parametrize("heading", ["Examples", "Demo", "Tutorial", "Sample output"])
def test_examples_pattern_matches(heading):
    assert EXAMPLES_PATTERN.search(heading)


@pytest.mark.parametrize("heading", ["Contributing", "License", "Background"])
def test_patterns_do_not_match_unrelated_headings(heading):
    assert not INSTALL_PATTERN.search(heading)
    assert not USAGE_PATTERN.search(heading)
    assert not EXAMPLES_PATTERN.search(heading)


# ---------- The project title is not a section ----------

def test_section_headings_skip_the_leading_title():
    text = "# Title\n\n## Installation\n\n## Usage\n"
    assert extract_section_headings(text) == ["Installation", "Usage"]


def test_section_headings_keep_a_leading_level_two_heading():
    assert extract_section_headings("## Installation\n") == ["Installation"]


def test_section_headings_only_skip_the_first_heading():
    assert extract_section_headings("# Project\n\n# Usage\n") == ["Usage"]


@pytest.mark.parametrize(
    "readme",
    [
        "# Installer\n\nA tool.\n",
        "Installer\n=========\n\nA tool.\n",
        '<h1 align="center">Installer</h1>\n\nA tool.\n',
    ],
)
def test_project_title_does_not_count_as_installation_section(readme):
    result = run(make_snapshot(["README.md"], texts={"README.md": readme}))
    assert result["docs.readme.installation"].status == "failed"


def test_project_called_demo_does_not_pass_the_examples_check():
    result = run(make_snapshot(["README.md"], texts={"README.md": "# Demo\n\nIntro.\n"}))
    assert result["docs.readme.examples"].status == "failed"


def test_overlong_heading_line_is_ignored_by_design():
    readme = "# Title\n\n## Installation " + "x" * 300 + "\n"
    result = run(make_snapshot(["README.md"], texts={"README.md": readme}))
    assert result["docs.readme.installation"].status == "failed"


# ---------- Overall shape ----------

def test_returns_six_valid_findings_with_unique_ids():
    findings = run_documentation_checks(make_snapshot(["README.md"], texts={"README.md": FULL_README}))
    ids = [f.id for f in findings]
    assert len(findings) == 6
    assert len(set(ids)) == 6
    assert all(f.category == "documentation" for f in findings)


# ---------- README present ----------

@pytest.mark.parametrize(
    "name", ["README.md", "readme.md", "Readme.rst", "README", ".github/README.md", "docs/README.md"]
)
def test_readme_found_in_accepted_locations(name):
    finding = run(make_snapshot([name]))["docs.readme.present"]
    assert finding.status == "passed"
    assert finding.evidence == [name]


def test_nested_readme_does_not_count():
    assert run(make_snapshot(["src/README.md"]))["docs.readme.present"].status == "failed"


def test_missing_readme_fails_when_file_list_is_complete():
    finding = run(make_snapshot(["app.py"]))["docs.readme.present"]
    assert finding.status == "failed"
    assert finding.remediation


def test_readme_not_assessed_when_file_list_unavailable():
    finding = run(make_snapshot([], tree_available=False))["docs.readme.present"]
    assert finding.status == "not_assessed"


def test_readme_not_assessed_when_file_list_truncated():
    finding = run(make_snapshot(["app.py"], truncated=True))["docs.readme.present"]
    assert finding.status == "not_assessed"


def test_readme_found_even_when_list_truncated():
    finding = run(make_snapshot(["README.md"], truncated=True))["docs.readme.present"]
    assert finding.status == "passed"


# ---------- License ----------

def test_license_from_github_metadata():
    finding = run(make_snapshot([], metadata={"license": "MIT"}))["docs.license"]
    assert finding.status == "passed"
    assert "MIT" in finding.evidence[0]


def test_license_from_file_when_github_has_no_metadata():
    finding = run(make_snapshot(["LICENSE"]))["docs.license"]
    assert finding.status == "passed"
    assert finding.evidence == ["LICENSE"]


def test_unrecognized_license_is_reported_honestly():
    finding = run(make_snapshot(["LICENSE"], metadata={"license": "NOASSERTION"}))["docs.license"]
    assert finding.status == "passed"
    assert any("could not identify" in item for item in finding.evidence)


def test_missing_license_fails_when_list_is_complete():
    assert run(make_snapshot(["app.py"]))["docs.license"].status == "failed"


def test_license_not_assessed_when_list_unavailable_or_truncated():
    assert run(make_snapshot([], tree_available=False))["docs.license"].status == "not_assessed"
    assert run(make_snapshot(["app.py"], truncated=True))["docs.license"].status == "not_assessed"


# ---------- Description ----------

def test_description_present():
    finding = run(make_snapshot([], metadata={"description": "A demo"}))["docs.description"]
    assert finding.status == "passed"
    assert "A demo" not in str(finding.evidence)  # repository text is not echoed


@pytest.mark.parametrize("value", [None, "", "   "])
def test_description_missing(value):
    assert run(make_snapshot([], metadata={"description": value}))["docs.description"].status == "failed"


# ---------- README sections ----------

def test_full_readme_passes_all_section_checks():
    result = run(make_snapshot(["README.md"], texts={"README.md": FULL_README}))
    for finding_id in ("docs.readme.installation", "docs.readme.usage", "docs.readme.examples"):
        assert result[finding_id].status == "passed"
        assert result[finding_id].kind == "heuristic"
        assert result[finding_id].evidence


def test_readme_without_sections_fails_section_checks():
    result = run(make_snapshot(["README.md"], texts={"README.md": "# Demo\n\nJust an intro.\n"}))
    for finding_id in ("docs.readme.installation", "docs.readme.usage", "docs.readme.examples"):
        assert result[finding_id].status == "failed"
        assert result[finding_id].remediation


def test_file_existing_is_not_enough():
    # README exists, but has no relevant sections.
    result = run(make_snapshot(["README.md"], texts={"README.md": "# Demo\n"}))
    assert result["docs.readme.present"].status == "passed"
    assert result["docs.readme.installation"].status == "failed"


def test_section_words_in_code_blocks_do_not_count():
    readme = "# Demo\n\n```\n# Installation\n```\n"
    result = run(make_snapshot(["README.md"], texts={"README.md": readme}))
    assert result["docs.readme.installation"].status == "failed"


def test_section_checks_fail_when_readme_is_confirmed_missing():
    result = run(make_snapshot(["app.py"]))
    assert result["docs.readme.installation"].status == "failed"


def test_section_checks_not_assessed_when_readme_unknown():
    result = run(make_snapshot([], tree_available=False))
    assert result["docs.readme.installation"].status == "not_assessed"


def test_section_checks_not_assessed_when_readme_cannot_be_read():
    result = run(make_snapshot(["README.md"], texts={}))  # reader returns None
    assert result["docs.readme.usage"].status == "not_assessed"


def test_truncated_readme_without_match_is_not_assessed():
    result = run(make_snapshot(["README.md"], texts={"README.md": "# Demo\n"}, text_truncated=True))
    assert result["docs.readme.installation"].status == "not_assessed"


def test_truncated_readme_with_match_still_passes():
    result = run(make_snapshot(["README.md"], texts={"README.md": FULL_README}, text_truncated=True))
    assert result["docs.readme.installation"].status == "passed"


def test_readme_is_read_only_once_for_all_section_checks():
    snapshot = make_snapshot(["README.md"], texts={"README.md": FULL_README})
    run_documentation_checks(snapshot)
    assert snapshot.calls == ["README.md"]


def test_no_files_are_read_when_there_is_no_readme():
    snapshot = make_snapshot(["app.py"])
    run_documentation_checks(snapshot)
    assert snapshot.calls == []


def test_displayed_evidence_is_cleaned_and_shortened():
    # Level-2 heading (so it isn't mistaken for the project title), a control
    # character to remove, and enough text to need shortening.
    readme = "# Title\n\n## Installation \x1b[31m" + "x" * 120 + "\n"

    # The scanner skips lines of 200+ characters on purpose, so this test must
    # stay below that limit or no heading will be found.
    assert max(len(line) for line in readme.splitlines()) < 200

    result = run(make_snapshot(["README.md"], texts={"README.md": readme}))
    finding = result["docs.readme.installation"]
    assert finding.status == "passed", finding.detail

    shown = finding.evidence[0]
    assert "\x1b" not in shown
    assert len(shown) <= 80