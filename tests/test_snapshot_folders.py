"""Tests for RepoSnapshot.find_in_folder."""

from scanner.models import RepoSnapshot

FILES = [
    ".github/ISSUE_TEMPLATE/bug.md",
    ".github/ISSUE_TEMPLATE/Feature.YML",
    ".github/ISSUE_TEMPLATE/config.yml",
    ".github/ISSUE_TEMPLATE/sub/deep.md",
    ".github/ISSUE_TEMPLATE_OLD/old.md",
    "README.md",
]


def test_returns_the_real_path_of_the_first_match_alphabetically():
    snapshot = RepoSnapshot({}, FILES)
    assert snapshot.find_in_folder(".github/issue_template") == ".github/ISSUE_TEMPLATE/bug.md"


def test_folder_name_may_have_a_trailing_slash():
    snapshot = RepoSnapshot({}, FILES)
    assert snapshot.find_in_folder(".github/ISSUE_TEMPLATE/") == ".github/ISSUE_TEMPLATE/bug.md"


def test_extension_filter_and_ignore_list():
    snapshot = RepoSnapshot({}, FILES)
    found = snapshot.find_in_folder(
        ".github/issue_template", extensions=(".yml", ".yaml"), ignore=("config.yml",)
    )
    assert found == ".github/ISSUE_TEMPLATE/Feature.YML"


def test_extensions_may_be_given_as_a_list():
    snapshot = RepoSnapshot({}, FILES)
    assert snapshot.find_in_folder(".github/issue_template", extensions=[".yml"]) == (
        ".github/ISSUE_TEMPLATE/config.yml"
    )


def test_files_in_sub_folders_do_not_count():
    snapshot = RepoSnapshot({}, [".github/ISSUE_TEMPLATE/sub/deep.md"])
    assert snapshot.find_in_folder(".github/issue_template") is None


def test_similar_folder_names_do_not_match():
    snapshot = RepoSnapshot({}, [".github/ISSUE_TEMPLATE_OLD/old.md"])
    assert snapshot.find_in_folder(".github/issue_template") is None


def test_nothing_found_when_the_folder_is_empty_or_missing():
    snapshot = RepoSnapshot({}, ["README.md"])
    assert snapshot.find_in_folder(".github/issue_template") is None


def test_nothing_found_without_a_file_list():
    assert RepoSnapshot({}, files=None).find_in_folder(".github/issue_template") is None