"""Tests for RepoSnapshot.paths and RepoSnapshot.list_in_folder."""

from scanner.models import RepoSnapshot

FILES = [
    ".github/workflows/ci.yml",
    ".github/workflows/Release.YAML",
    ".github/workflows/notes.md",
    ".github/workflows/sub/nested.yml",
    "Tests/test_a.py",
    "README.md",
]


def test_paths_are_sorted_and_keep_their_original_spelling():
    assert RepoSnapshot({}, FILES).paths == sorted(FILES)


def test_paths_is_empty_without_a_file_list():
    assert RepoSnapshot({}, files=None).paths == []


def test_list_returns_every_matching_file_sorted():
    snapshot = RepoSnapshot({}, FILES)
    found = snapshot.list_in_folder(".github/workflows", (".yml", ".yaml"))
    assert found == [".github/workflows/ci.yml", ".github/workflows/Release.YAML"]


def test_list_skips_sub_folders_and_other_extensions():
    snapshot = RepoSnapshot({}, FILES)
    found = snapshot.list_in_folder(".github/workflows", (".yml", ".yaml"))
    assert ".github/workflows/sub/nested.yml" not in found
    assert ".github/workflows/notes.md" not in found


def test_list_honors_the_ignore_list():
    snapshot = RepoSnapshot({}, FILES)
    found = snapshot.list_in_folder(".github/workflows", (".yml",), ignore=("ci.yml",))
    assert found == []


def test_list_is_empty_for_a_missing_folder_or_no_file_list():
    assert RepoSnapshot({}, FILES).list_in_folder("docs") == []
    assert RepoSnapshot({}, files=None).list_in_folder(".github/workflows") == []