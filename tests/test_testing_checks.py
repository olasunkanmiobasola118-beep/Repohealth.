"""Tests for scanner/testing.py. No network access is used."""

import pytest

from scanner.models import RepoSnapshot
from scanner.testing import (
    MAX_WORKFLOWS_READ, extract_run_commands, find_test_commands_in_docs,
    find_test_commands_in_workflow, find_tests, run_testing_checks,
)

CI_PATH = ".github/workflows/ci.yml"

CI_WORKFLOW = """name: CI
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install pytest pytest-cov
      - run: pytest --cov
"""

LINT_WORKFLOW = """name: Lint
on: [push]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: ruff check .
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
    return {finding.id: finding for finding in run_testing_checks(snapshot)}


# ---------- Overall shape ----------

def test_returns_five_valid_findings_with_unique_ids():
    findings = run_testing_checks(make_snapshot(["app.py"]))
    ids = [finding.id for finding in findings]
    assert len(findings) == 5
    assert len(set(ids)) == 5
    assert all(finding.category == "testing" for finding in findings)


def test_everything_is_not_assessed_without_a_file_list():
    findings = run_testing_checks(make_snapshot([], tree_available=False))
    assert {finding.status for finding in findings} == {"not_assessed"}


def test_nothing_is_read_when_there_is_nothing_to_read():
    snapshot = make_snapshot(["app.py"])
    run_testing_checks(snapshot)
    assert snapshot.calls == []


# ---------- find_tests ----------

@pytest.mark.parametrize(
    "path",
    ["tests/test_app.py", "test/helpers.py", "src/__tests__/a.js", "app/foo_test.go",
     "web/button.test.tsx", "spec/user_spec.rb", "src/main/AppTest.java",
     "test_app.py", "pkg/tests.py", "Tests/Unit.cs"],
)
def test_recognizes_test_files_and_folders(path):
    folders, files = find_tests(make_snapshot([path]))
    assert folders or files


@pytest.mark.parametrize(
    "path",
    ["src/latest.py", "docs/contest.md", "src/attest.js", "README.md",
     "src/Latest.java", "pkg/protest.py"],
)
def test_ordinary_files_are_not_tests(path):
    assert find_tests(make_snapshot([path])) == ([], [])


@pytest.mark.parametrize(
    "path",
    ["node_modules/pkg/tests/a.js", "vendor/x/test_y.py",
     ".venv/lib/python3.14/site-packages/foo/tests/test_a.py", "dist/tests/x.js"],
)
def test_tests_inside_dependency_folders_do_not_count(path):
    assert find_tests(make_snapshot([path])) == ([], [])


# ---------- Tests exist ----------

def test_tests_found_with_examples_as_evidence():
    finding = run(make_snapshot(["tests/test_app.py", "tests/test_b.py"]))["testing.tests.present"]
    assert finding.status == "passed"
    assert finding.kind == "heuristic"
    assert "tests/" in finding.evidence
    assert "tests/test_app.py" in finding.evidence


def test_test_configuration_is_extra_evidence():
    finding = run(make_snapshot(["pytest.ini", "tests/test_app.py"]))["testing.tests.present"]
    assert finding.status == "passed"
    assert any(item.startswith("Test configuration:") for item in finding.evidence)


def test_configuration_without_any_tests_is_not_assessed():
    finding = run(make_snapshot(["pytest.ini"]))["testing.tests.present"]
    assert finding.status == "not_assessed"


def test_no_tests_fails_when_the_file_list_is_complete():
    finding = run(make_snapshot(["app.py"]))["testing.tests.present"]
    assert finding.status == "failed"
    assert finding.remediation


def test_no_tests_is_not_assessed_when_the_list_is_incomplete():
    assert run(make_snapshot(["app.py"], truncated=True))["testing.tests.present"].status == "not_assessed"


def test_tests_found_even_when_the_list_is_incomplete():
    finding = run(make_snapshot(["tests/test_app.py"], truncated=True))["testing.tests.present"]
    assert finding.status == "passed"


def test_test_file_names_are_cleaned_before_display():
    path = "tests/test_\x1b[31mevil.py"
    finding = run(make_snapshot([path]))["testing.tests.present"]
    assert all("\x1b" not in item for item in finding.evidence)


# ---------- CI present ----------

def test_github_actions_workflows_are_counted():
    result = run(make_snapshot([".github/workflows/a.yml", ".github/workflows/b.yaml"]))
    finding = result["testing.ci.present"]
    assert finding.status == "passed"
    assert finding.evidence == ["GitHub Actions: 2 workflow file(s)"]


def test_non_workflow_files_in_the_folder_do_not_count():
    assert run(make_snapshot([".github/workflows/README.md"]))["testing.ci.present"].status == "failed"
    assert run(make_snapshot([".github/workflows/sub/ci.yml"]))["testing.ci.present"].status == "failed"


@pytest.mark.parametrize(
    "path, name",
    [(".travis.yml", "Travis CI"), ("Jenkinsfile", "Jenkins"),
     (".circleci/config.yml", "CircleCI"), (".gitlab-ci.yml", "GitLab CI")],
)
def test_other_ci_systems_count_as_ci(path, name):
    finding = run(make_snapshot([path]))["testing.ci.present"]
    assert finding.status == "passed"
    assert finding.evidence == [name]


def test_github_actions_and_another_ci_are_both_listed():
    finding = run(make_snapshot([CI_PATH, ".travis.yml"]))["testing.ci.present"]
    assert finding.evidence == ["GitHub Actions: 1 workflow file(s)", "Travis CI"]


def test_missing_ci_fails_when_complete_and_is_not_assessed_otherwise():
    assert run(make_snapshot(["app.py"]))["testing.ci.present"].status == "failed"
    assert run(make_snapshot(["app.py"], truncated=True))["testing.ci.present"].status == "not_assessed"


# ---------- extract_run_commands ----------

def test_run_commands_from_single_lines_and_blocks():
    text = """name: CI
jobs:
  test:
    steps:
      - uses: actions/checkout@v4
      - name: Install
        run: |
          pip install -r requirements.txt
          # a comment
          pip install pytest
      - name: Run
        run: pytest -q
      - run: echo done
"""
    assert extract_run_commands(text) == [
        "pip install -r requirements.txt", "pip install pytest", "pytest -q", "echo done",
    ]


def test_run_block_after_a_dash_ends_at_the_next_step():
    text = "steps:\n  - run: |\n      pytest\n      tox\n  - run: echo\n"
    assert extract_run_commands(text) == ["pytest", "tox", "echo"]


def test_folded_blocks_are_read_too():
    assert extract_run_commands("    run: >\n      pytest\n      -q\n") == ["pytest", "-q"]


def test_labels_comments_and_uses_lines_are_not_commands():
    text = ("name: Run pytest\njobs:\n  a:\n    steps:\n"
            "      - name: pytest\n        uses: x/pytest-action@v1\n      # run: pytest\n")
    assert extract_run_commands(text) == []
    assert find_test_commands_in_workflow(text) == []


def test_very_long_lines_are_skipped():
    assert extract_run_commands("run: " + "x" * 1000 + "\n") == []


# ---------- Test command recognition ----------

@pytest.mark.parametrize(
    "line, expected",
    [
        ("pytest -q", ["pytest"]),
        ("python -m pytest tests/", ["python -m pytest"]),
        ("python3 -m unittest discover", ["python3 -m unittest"]),
        ("npm run test", ["npm run test"]),
        ("npm test", ["npm test"]),
        ("yarn test", ["yarn test"]),
        ("go test ./...", ["go test"]),
        ("cargo test --all", ["cargo test"]),
        ("make check", ["make check"]),
        ("dotnet test", ["dotnet test"]),
        ("mvn -B test", ["mvn -b test"]),
        ("echo hello", []),
        ("pip install -r requirements.txt", []),
    ],
)
def test_find_test_commands_in_docs(line, expected):
    assert find_test_commands_in_docs(line) == expected


# ---------- CI runs tests ----------

def test_workflow_with_a_test_command_passes():
    result = run(make_snapshot([CI_PATH], texts={CI_PATH: CI_WORKFLOW}))
    finding = result["testing.ci.runs_tests"]
    assert finding.status == "passed"
    assert finding.evidence == ["pytest"]


def test_workflow_without_test_commands_fails():
    result = run(make_snapshot([CI_PATH], texts={CI_PATH: LINT_WORKFLOW}))
    finding = result["testing.ci.runs_tests"]
    assert finding.status == "failed"
    assert finding.remediation


def test_test_command_in_a_comment_does_not_count():
    text = "steps:\n  # run: pytest\n  - run: echo hi\n"
    result = run(make_snapshot([CI_PATH], texts={CI_PATH: text}))
    assert result["testing.ci.runs_tests"].status == "failed"


def test_unreadable_workflow_is_not_assessed():
    result = run(make_snapshot([CI_PATH], texts={}))
    assert result["testing.ci.runs_tests"].status == "not_assessed"


def test_truncated_workflow_without_a_match_is_not_assessed_but_with_a_match_passes():
    lint = run(make_snapshot([CI_PATH], texts={CI_PATH: LINT_WORKFLOW}, text_truncated=True))
    full = run(make_snapshot([CI_PATH], texts={CI_PATH: CI_WORKFLOW}, text_truncated=True))
    assert lint["testing.ci.runs_tests"].status == "not_assessed"
    assert full["testing.ci.runs_tests"].status == "passed"


def test_only_a_limited_number_of_workflows_are_read():
    paths = [f".github/workflows/{name}.yml" for name in ("a", "b", "c")]
    snapshot = make_snapshot(paths, texts={path: LINT_WORKFLOW for path in paths})

    result = run(snapshot)

    assert len(snapshot.calls) == MAX_WORKFLOWS_READ
    assert result["testing.ci.runs_tests"].status == "not_assessed"   # not "failed"


def test_workflows_with_test_like_names_are_read_first():
    paths = [".github/workflows/deploy.yml", ".github/workflows/test.yml",
             ".github/workflows/docs.yml"]
    snapshot = make_snapshot(paths)

    run(snapshot)

    assert snapshot.calls == [".github/workflows/test.yml", ".github/workflows/deploy.yml"]


def test_a_test_command_in_the_second_workflow_is_found():
    first, second = ".github/workflows/a.yml", ".github/workflows/b.yml"
    snapshot = make_snapshot([first, second], texts={first: LINT_WORKFLOW, second: CI_WORKFLOW})
    assert run(snapshot)["testing.ci.runs_tests"].status == "passed"


def test_no_workflow_and_no_other_ci_fails_when_complete():
    assert run(make_snapshot(["app.py"]))["testing.ci.runs_tests"].status == "failed"


def test_other_ci_systems_are_not_inspected_for_test_steps():
    finding = run(make_snapshot([".travis.yml"]))["testing.ci.runs_tests"]
    assert finding.status == "not_assessed"
    assert "Travis CI" in finding.detail


def test_runs_tests_is_not_assessed_when_the_list_is_incomplete():
    assert run(make_snapshot(["app.py"], truncated=True))["testing.ci.runs_tests"].status == "not_assessed"


# ---------- Coverage ----------

@pytest.mark.parametrize("name", [".coveragerc", "codecov.yml", ".nycrc", "coveralls.yml"])
def test_coverage_config_files_are_recognized(name):
    finding = run(make_snapshot([name]))["testing.coverage"]
    assert finding.status == "passed"
    assert finding.evidence == [name]


def test_coverage_step_in_a_workflow_is_recognized():
    result = run(make_snapshot([CI_PATH], texts={CI_PATH: CI_WORKFLOW}))
    assert result["testing.coverage"].status == "passed"


def test_coverage_upload_action_is_recognized():
    text = LINT_WORKFLOW + "      - uses: codecov/codecov-action@v4\n"
    result = run(make_snapshot([CI_PATH], texts={CI_PATH: text}))
    assert result["testing.coverage"].status == "passed"


def test_passed_coverage_check_does_not_claim_a_percentage():
    finding = run(make_snapshot([".coveragerc"]))["testing.coverage"]
    assert "percentages" in finding.detail
    assert "%" not in finding.detail


def test_missing_coverage_fails_with_low_confidence_when_everything_was_inspected():
    finding = run(make_snapshot([CI_PATH], texts={CI_PATH: LINT_WORKFLOW}))["testing.coverage"]
    assert finding.status == "failed"
    assert finding.confidence == "low"
    assert "pyproject.toml" in finding.detail   # admits what it cannot see


def test_coverage_is_not_assessed_when_something_was_not_inspected():
    assert run(make_snapshot(["app.py"], truncated=True))["testing.coverage"].status == "not_assessed"

    paths = [f".github/workflows/{name}.yml" for name in ("a", "b", "c")]
    snapshot = make_snapshot(paths, texts={path: LINT_WORKFLOW for path in paths})
    assert run(snapshot)["testing.coverage"].status == "not_assessed"


# ---------- Testing documentation ----------

TESTS_PRESENT = ["tests/test_app.py"]


def test_docs_not_assessed_when_there_are_no_tests():
    result = run(make_snapshot(["README.md"], texts={"README.md": "# Demo\n"}))
    assert result["testing.docs"].status == "not_assessed"


def test_testing_heading_in_the_readme_passes():
    readme = "# Demo\n\n## Running tests\n\nSee below.\n"
    result = run(make_snapshot(TESTS_PRESENT + ["README.md"], texts={"README.md": readme}))
    finding = result["testing.docs"]
    assert finding.status == "passed"
    assert "Running tests" in finding.evidence


def test_test_command_in_a_code_block_passes():
    readme = "# Demo\n\nRun:\n\n```\npytest\n```\n"
    result = run(make_snapshot(TESTS_PRESENT + ["README.md"], texts={"README.md": readme}))
    finding = result["testing.docs"]
    assert finding.status == "passed"
    assert finding.evidence == ["pytest"]


def test_testing_heading_in_the_contributing_guide_passes():
    files = TESTS_PRESENT + ["README.md", "CONTRIBUTING.md"]
    texts = {"README.md": "# Demo\n\nHello.\n", "CONTRIBUTING.md": "# Contributing\n\n## Testing\n"}
    assert run(make_snapshot(files, texts=texts))["testing.docs"].status == "passed"


def test_documentation_without_any_testing_hint_fails():
    result = run(make_snapshot(TESTS_PRESENT + ["README.md"], texts={"README.md": "# Demo\n\nHello.\n"}))
    finding = result["testing.docs"]
    assert finding.status == "failed"
    assert finding.remediation


def test_tests_but_no_documents_at_all():
    assert run(make_snapshot(TESTS_PRESENT))["testing.docs"].status == "failed"
    assert run(make_snapshot(TESTS_PRESENT, truncated=True))["testing.docs"].status == "not_assessed"


def test_unreadable_readme_is_not_assessed():
    result = run(make_snapshot(TESTS_PRESENT + ["README.md"], texts={}))
    assert result["testing.docs"].status == "not_assessed"


def test_truncated_readme_without_a_match_is_not_assessed():
    result = run(make_snapshot(
        TESTS_PRESENT + ["README.md"], texts={"README.md": "# Demo\n"}, text_truncated=True
    ))
    assert result["testing.docs"].status == "not_assessed"


def test_testing_docs_evidence_is_cleaned_and_shortened():
    readme = "# Demo\n\n## Testing \x1b[31m" + "x" * 120 + "\n"
    assert max(len(line) for line in readme.splitlines()) < 200
    result = run(make_snapshot(TESTS_PRESENT + ["README.md"], texts={"README.md": readme}))
    finding = result["testing.docs"]
    assert finding.status == "passed", finding.detail
    assert "\x1b" not in finding.evidence[0]
    assert len(finding.evidence[0]) <= 80