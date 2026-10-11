"""Tests for scanner/engine.py. GitHub is replaced with fakes."""

import json

import pytest

from scanner import engine
from scanner.github_client import GitHubError

README = """# Demo project

Some introduction.

## Installation

pip install demo

## Usage

demo --help

## Examples

See the examples folder.
"""

GUIDE = """# Contributing

## Development setup

Install the requirements.

## Submitting a pull request

Open a pull request.
"""

METADATA = {
    "full_name": "octo/demo",
    "description": "A demo",
    "license": "MIT",
    "default_branch": "main",
}


@pytest.fixture
def fake_github(monkeypatch):
    """Replace the two network functions the engine uses.

    Change state["tree"] or state["files"] inside a test to simulate other
    situations. A value that is an Exception is raised instead of returned.
    """
    state = {
        "tree": (["README.md", "LICENSE"], False),
        "files": {"README.md": (README, False)},
        "tree_calls": [],
        "file_calls": [],
    }

    def fake_tree(owner, repo, branch):
        state["tree_calls"].append((owner, repo, branch))
        result = state["tree"]
        if isinstance(result, Exception):
            raise result
        return result

    def fake_file(owner, repo, path):
        state["file_calls"].append((owner, repo, path))
        result = state["files"].get(path)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(engine, "fetch_repo_tree", fake_tree)
    monkeypatch.setattr(engine, "fetch_file_text", fake_file)
    return state


def statuses(result, prefix=""):
    return {
        finding["id"]: finding["status"]
        for finding in result["findings"]
        if finding["id"].startswith(prefix)
    }


# ---------- Normal scans ----------

def test_documentation_checks_pass_with_complete_data(fake_github):
    result = engine.analyze_repository("octo", "demo", METADATA)

    assert statuses(result, "docs.") == {
        "docs.readme.present": "passed",
        "docs.license": "passed",
        "docs.description": "passed",
        "docs.readme.installation": "passed",
        "docs.readme.usage": "passed",
        "docs.readme.examples": "passed",
    }
    assert result["warnings"] == []
    assert result["file_list"] == {"available": True, "complete": True}


def test_all_check_modules_contribute_findings(fake_github):
    result = engine.analyze_repository("octo", "demo", METADATA)
    assert len(result["findings"]) == 11   # 6 documentation + 5 contribution


def test_contribution_checks_fail_when_the_files_are_missing(fake_github):
    result = engine.analyze_repository("octo", "demo", METADATA)

    assert statuses(result, "contrib.") == {
        "contrib.guide.present": "failed",
        "contrib.guide.content": "failed",
        "contrib.conduct": "failed",
        "contrib.issue_templates": "failed",
        "contrib.pr_template": "failed",
    }


def test_contribution_checks_pass_and_each_file_is_read_once(fake_github):
    fake_github["tree"] = ([
        "README.md", "LICENSE", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md",
        ".github/ISSUE_TEMPLATE/bug.yml", ".github/pull_request_template.md",
    ], False)
    fake_github["files"]["CONTRIBUTING.md"] = (GUIDE, False)

    result = engine.analyze_repository("octo", "demo", METADATA)

    assert set(statuses(result, "contrib.").values()) == {"passed"}
    assert fake_github["file_calls"] == [
        ("octo", "demo", "README.md"),
        ("octo", "demo", "CONTRIBUTING.md"),
    ]


def test_result_can_be_converted_to_json(fake_github):
    json.dumps(engine.analyze_repository("octo", "demo", METADATA))


def test_tree_is_requested_for_the_default_branch_and_readme_read_once(fake_github):
    engine.analyze_repository("octo", "demo", METADATA)

    assert fake_github["tree_calls"] == [("octo", "demo", "main")]
    assert fake_github["file_calls"] == [("octo", "demo", "README.md")]


# ---------- Things going wrong ----------

def test_file_list_failure_makes_file_checks_not_assessed(fake_github):
    fake_github["tree"] = GitHubError("rate_limited", "Rate limit reached.", 429)

    result = engine.analyze_repository("octo", "demo", METADATA)

    assert statuses(result)["docs.readme.present"] == "not_assessed"
    assert statuses(result)["docs.readme.installation"] == "not_assessed"
    assert set(statuses(result, "contrib.").values()) == {"not_assessed"}
    assert any("Rate limit reached." in warning for warning in result["warnings"])
    assert result["file_list"] == {"available": False, "complete": False}
    assert fake_github["file_calls"] == []   # nothing was fetched without a file list


def test_empty_repository_is_reported_as_missing_files(fake_github):
    fake_github["tree"] = GitHubError("empty_repository", "This repository is empty.", 422)

    result = engine.analyze_repository("octo", "demo", METADATA)

    assert statuses(result)["docs.readme.present"] == "failed"
    assert any("empty" in warning for warning in result["warnings"])
    assert result["file_list"] == {"available": True, "complete": True}


def test_truncated_file_list_cannot_prove_a_file_is_missing(fake_github):
    fake_github["tree"] = (["README.md"], True)
    metadata = dict(METADATA, license=None)

    result = engine.analyze_repository("octo", "demo", metadata)

    assert statuses(result)["docs.license"] == "not_assessed"
    assert statuses(result)["docs.readme.present"] == "passed"
    assert statuses(result)["contrib.conduct"] == "not_assessed"
    assert any("incomplete" in warning for warning in result["warnings"])
    assert result["file_list"] == {"available": True, "complete": False}


def test_readme_read_failure_is_a_warning_not_a_crash(fake_github):
    fake_github["files"]["README.md"] = GitHubError("rate_limited", "Rate limit reached.", 429)

    result = engine.analyze_repository("octo", "demo", METADATA)

    assert statuses(result)["docs.readme.present"] == "passed"
    assert statuses(result)["docs.readme.installation"] == "not_assessed"
    assert any("could not be read" in warning for warning in result["warnings"])


def test_readme_missing_when_fetched_is_not_assessed(fake_github):
    fake_github["files"] = {}   # the file list says README.md exists, but fetching finds nothing

    result = engine.analyze_repository("octo", "demo", METADATA)

    assert statuses(result)["docs.readme.usage"] == "not_assessed"


def test_snapshot_only_reads_files_from_the_file_list(fake_github):
    snapshot, _ = engine.build_snapshot("octo", "demo", METADATA)

    assert snapshot.read("not-in-the-list.txt") is None
    assert fake_github["file_calls"] == []


def test_a_crashing_check_module_does_not_stop_the_others(fake_github, monkeypatch):
    def broken_runner(snapshot):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(
        engine, "CHECK_RUNNERS", [broken_runner, engine.run_documentation_checks]
    )

    result = engine.analyze_repository("octo", "demo", METADATA)

    assert len(result["findings"]) == 6
    assert len(result["warnings"]) == 1
    assert "secret internal detail" not in json.dumps(result)


def test_repeated_warnings_are_listed_once(fake_github, monkeypatch):
    def broken_runner(snapshot):
        raise RuntimeError("boom")

    monkeypatch.setattr(engine, "CHECK_RUNNERS", [broken_runner, broken_runner])

    result = engine.analyze_repository("octo", "demo", METADATA)

    assert result["findings"] == []
    assert len(result["warnings"]) == 1