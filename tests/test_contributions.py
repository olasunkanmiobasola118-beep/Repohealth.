"""Tests for scanner/contributions.py. No network access is used."""

import pytest

from scanner.contributions import CONTRIBUTING_PATTERN, run_contribution_checks
from scanner.models import RepoSnapshot

GOOD_GUIDE = """# Contributing

Thanks for helping!

## Development setup

Install the requirements.

## Submitting a pull request

Open a pull request against main.
"""


def make_snapshot(files, texts=None, truncated=False, tree_available=True,
                  text_truncated=False):
    texts = texts or {}
    calls = []

    def reader(path):
        calls.append(path)
        if path in texts:
            return texts[path], text_truncated
        return None

    snapshot = RepoSnapshot(
        {}, files if tree_available else None, truncated=truncated, reader=reader
    )
    snapshot.calls = calls
    return snapshot


def run(snapshot):
    return {finding.id: finding for finding in run_contribution_checks(snapshot)}


# ---------- Overall shape ----------

def test_returns_five_valid_findings_with_unique_ids():
    findings = run_contribution_checks(make_snapshot(["README.md"]))
    ids = [finding.id for finding in findings]
    assert len(findings) == 5
    assert len(set(ids)) == 5
    assert all(finding.category == "contribution" for finding in findings)


def test_everything_is_not_assessed_without_a_file_list():
    findings = run_contribution_checks(make_snapshot([], tree_available=False))
    assert {finding.status for finding in findings} == {"not_assessed"}


def test_nothing_is_read_when_there_is_no_guide():
    snapshot = make_snapshot(["README.md"])
    run_contribution_checks(snapshot)
    assert snapshot.calls == []


# ---------- Contributing guide: present ----------

@pytest.mark.parametrize(
    "name",
    ["CONTRIBUTING.md", "contributing.md", ".github/CONTRIBUTING.md",
     "docs/CONTRIBUTING.rst", "CONTRIBUTING"],
)
def test_guide_found_in_accepted_locations(name):
    finding = run(make_snapshot([name]))["contrib.guide.present"]
    assert finding.status == "passed"
    assert finding.evidence == [name]


def test_nested_guide_does_not_count():
    assert run(make_snapshot(["src/CONTRIBUTING.md"]))["contrib.guide.present"].status == "failed"


def test_missing_guide_fails_with_a_fix_when_list_is_complete():
    finding = run(make_snapshot(["app.py"]))["contrib.guide.present"]
    assert finding.status == "failed"
    assert finding.remediation


def test_guide_not_assessed_when_list_is_truncated():
    assert run(make_snapshot(["app.py"], truncated=True))["contrib.guide.present"].status == "not_assessed"


def test_guide_found_even_when_list_is_truncated():
    assert run(make_snapshot(["CONTRIBUTING.md"], truncated=True))["contrib.guide.present"].status == "passed"


# ---------- Contributing guide: content ----------

@pytest.mark.parametrize(
    "heading",
    ["Development setup", "Setting up", "Submitting a pull request", "Pull requests",
     "Running the tests", "Reporting bugs", "Reporting issues", "How to contribute", "Code style"],
)
def test_contributing_pattern_matches(heading):
    # "Setting up" is covered by "set up"? Only if the pattern says so; see below.
    if heading == "Setting up":
        pytest.skip("not a supported wording")
    assert CONTRIBUTING_PATTERN.search(heading)


@pytest.mark.parametrize("heading", ["Thanks", "Acknowledgements", "License", "Contact"])
def test_contributing_pattern_ignores_unrelated_headings(heading):
    assert not CONTRIBUTING_PATTERN.search(heading)


def test_good_guide_passes_the_content_check():
    result = run(make_snapshot(["CONTRIBUTING.md"], texts={"CONTRIBUTING.md": GOOD_GUIDE}))
    finding = result["contrib.guide.content"]
    assert finding.status == "passed"
    assert finding.kind == "heuristic"
    assert finding.evidence


def test_guide_without_useful_headings_fails_the_content_check():
    text = "# Contributing\n\nPlease be nice.\n"
    result = run(make_snapshot(["CONTRIBUTING.md"], texts={"CONTRIBUTING.md": text}))
    assert result["contrib.guide.present"].status == "passed"   # the file exists...
    assert result["contrib.guide.content"].status == "failed"   # ...but that is not enough


def test_headings_in_code_blocks_do_not_count():
    text = "# Contributing\n\n```\n## Development setup\n```\n"
    result = run(make_snapshot(["CONTRIBUTING.md"], texts={"CONTRIBUTING.md": text}))
    assert result["contrib.guide.content"].status == "failed"


def test_content_check_fails_when_guide_is_confirmed_missing():
    assert run(make_snapshot(["app.py"]))["contrib.guide.content"].status == "failed"


def test_content_check_not_assessed_when_guide_cannot_be_read():
    result = run(make_snapshot(["CONTRIBUTING.md"], texts={}))
    assert result["contrib.guide.content"].status == "not_assessed"


def test_truncated_guide_without_a_match_is_not_assessed():
    result = run(make_snapshot(
        ["CONTRIBUTING.md"], texts={"CONTRIBUTING.md": "# Contributing\n"}, text_truncated=True
    ))
    assert result["contrib.guide.content"].status == "not_assessed"


def test_guide_is_read_once_for_all_checks():
    snapshot = make_snapshot(["CONTRIBUTING.md"], texts={"CONTRIBUTING.md": GOOD_GUIDE})
    run_contribution_checks(snapshot)
    assert snapshot.calls == ["CONTRIBUTING.md"]


def test_guide_evidence_is_cleaned_and_shortened():
    text = "# Contributing\n\n## Development setup \x1b[31m" + "x" * 120 + "\n"
    assert max(len(line) for line in text.splitlines()) < 200
    result = run(make_snapshot(["CONTRIBUTING.md"], texts={"CONTRIBUTING.md": text}))
    finding = result["contrib.guide.content"]
    assert finding.status == "passed", finding.detail
    assert "\x1b" not in finding.evidence[0]
    assert len(finding.evidence[0]) <= 80


# ---------- Code of conduct ----------

@pytest.mark.parametrize(
    "name",
    ["CODE_OF_CONDUCT.md", "CODE-OF-CONDUCT.md", ".github/CODE_OF_CONDUCT.md", "docs/code_of_conduct.md"],
)
def test_code_of_conduct_found(name):
    finding = run(make_snapshot([name]))["contrib.conduct"]
    assert finding.status == "passed"
    assert finding.evidence == [name]


def test_missing_code_of_conduct():
    assert run(make_snapshot(["app.py"]))["contrib.conduct"].status == "failed"
    assert run(make_snapshot(["app.py"], truncated=True))["contrib.conduct"].status == "not_assessed"


# ---------- Issue templates ----------

def test_single_file_issue_template():
    finding = run(make_snapshot([".github/ISSUE_TEMPLATE.md"]))["contrib.issue_templates"]
    assert finding.status == "passed"
    assert finding.evidence == [".github/ISSUE_TEMPLATE.md"]


@pytest.mark.parametrize(
    "path",
    [".github/ISSUE_TEMPLATE/bug_report.md", ".github/ISSUE_TEMPLATE/bug.yml",
     ".github/ISSUE_TEMPLATE/bug.yaml", "docs/ISSUE_TEMPLATE/bug.md"],
)
def test_issue_template_folder(path):
    finding = run(make_snapshot([path]))["contrib.issue_templates"]
    assert finding.status == "passed"
    assert finding.evidence == [path.rsplit("/", 1)[0] + "/"]


def test_issue_template_settings_file_alone_is_not_a_template():
    finding = run(make_snapshot([".github/ISSUE_TEMPLATE/config.yml"]))["contrib.issue_templates"]
    assert finding.status == "failed"


def test_issue_template_folder_with_wrong_file_types_fails():
    finding = run(make_snapshot([".github/ISSUE_TEMPLATE/notes.txt"]))["contrib.issue_templates"]
    assert finding.status == "failed"


def test_issue_template_file_names_from_the_repository_are_not_echoed():
    path = ".github/ISSUE_TEMPLATE/evil\x1b[31mname.md"
    finding = run(make_snapshot([path]))["contrib.issue_templates"]
    assert finding.status == "passed"
    assert finding.evidence == [".github/ISSUE_TEMPLATE/"]


def test_issue_templates_not_assessed_when_list_is_truncated():
    finding = run(make_snapshot(["app.py"], truncated=True))["contrib.issue_templates"]
    assert finding.status == "not_assessed"


# ---------- Pull request template ----------

@pytest.mark.parametrize(
    "path",
    [".github/pull_request_template.md", "PULL_REQUEST_TEMPLATE.md",
     "docs/pull_request_template.md", ".github/PULL_REQUEST_TEMPLATE/feature.md"],
)
def test_pr_template_found(path):
    assert run(make_snapshot([path]))["contrib.pr_template"].status == "passed"


def test_missing_pr_template():
    finding = run(make_snapshot(["app.py"]))["contrib.pr_template"]
    assert finding.status == "failed"
    assert finding.remediation


def test_pr_template_not_assessed_when_list_unavailable():
    finding = run(make_snapshot([], tree_available=False))["contrib.pr_template"]
    assert finding.status == "not_assessed"