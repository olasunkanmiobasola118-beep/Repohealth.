"""Tests for scanner/models.py."""

import pytest

from scanner.models import Finding, RepoSnapshot


def make_finding(**overrides):
    values = dict(
        id="x.y", category="documentation", title="Example", status="passed",
        severity="low", kind="objective", confidence="high",
    )
    values.update(overrides)
    return Finding(**values)


@pytest.mark.parametrize(
    "field, bad_value",
    [
        ("status", "ok"),
        ("severity", "critical"),
        ("kind", "ai"),            # AI output must never be a scan finding
        ("confidence", "certain"),
    ],
)
def test_finding_rejects_invalid_values(field, bad_value):
    with pytest.raises(ValueError):
        make_finding(**{field: bad_value})


def test_finding_to_dict_has_all_fields():
    data = make_finding(evidence=["a"], remediation="fix it").to_dict()
    assert data["id"] == "x.y"
    assert data["evidence"] == ["a"]
    assert data["remediation"] == "fix it"
    assert set(data) == {
        "id", "category", "title", "status", "severity", "kind",
        "confidence", "detail", "evidence", "remediation",
    }


def test_finding_default_lists_are_not_shared():
    first, second = make_finding(), make_finding()
    first.evidence.append("only on first")
    assert second.evidence == []


def test_snapshot_find_ignores_case_and_matches_full_paths_only():
    snapshot = RepoSnapshot({}, ["Readme.MD", "src/README.md"])
    assert snapshot.find(["readme.md"]) == "Readme.MD"
    assert snapshot.find(["docs/readme.md"]) is None
    assert snapshot.find(["nothing.txt", "readme.md"]) == "Readme.MD"


def test_snapshot_without_file_list_finds_nothing_and_cannot_confirm_absence():
    snapshot = RepoSnapshot({}, files=None)
    assert snapshot.find(["readme.md"]) is None
    assert snapshot.tree_available is False
    assert snapshot.can_confirm_absence is False


def test_snapshot_truncated_list_cannot_confirm_absence():
    snapshot = RepoSnapshot({}, ["a.txt"], truncated=True)
    assert snapshot.can_confirm_absence is False


def test_snapshot_complete_list_can_confirm_absence():
    assert RepoSnapshot({}, ["a.txt"]).can_confirm_absence is True


def test_snapshot_read_is_cached():
    calls = []

    def reader(path):
        calls.append(path)
        return ("hello", False)

    snapshot = RepoSnapshot({}, ["a.txt"], reader=reader)
    assert snapshot.read("a.txt").text == "hello"
    assert snapshot.read("a.txt").text == "hello"
    assert calls == ["a.txt"]


def test_snapshot_read_returns_none_for_missing_file():
    snapshot = RepoSnapshot({}, ["a.txt"], reader=lambda path: None)
    assert snapshot.read("a.txt") is None


def test_snapshot_read_limit_is_enforced():
    snapshot = RepoSnapshot({}, ["a", "b", "c"], reader=lambda p: ("x", False), max_reads=2)
    assert snapshot.read("a") is not None
    assert snapshot.read("b") is not None
    assert snapshot.read("c") is None


def test_snapshot_without_reader_cannot_read():
    assert RepoSnapshot({}, ["a.txt"]).read("a.txt") is None