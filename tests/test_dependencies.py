"""Tests for scanner/dependencies.py. No network access is used."""

import pytest

from scanner.dependencies import (
    ECOSYSTEMS, LOCKFILE_FAMILY, LOCKFILE_NEEDS, parse_requirements,
    run_dependency_checks,
)
from scanner.models import RepoSnapshot


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
    return {finding.id: finding for finding in run_dependency_checks(snapshot)}


# ---------- Tables ----------

def test_every_known_lockfile_has_a_family_and_a_required_manifest():
    for ecosystem, (manifests, lockfiles) in ECOSYSTEMS.items():
        for name in lockfiles:
            assert name in LOCKFILE_FAMILY
            assert LOCKFILE_NEEDS[name]
            assert all(needed in manifests for needed in LOCKFILE_NEEDS[name])


# ---------- Overall shape ----------

def test_advisories_finding_is_always_last_and_never_claims_results():
    for files in (["app.py"], ["package.json", "package-lock.json"]):
        findings = run_dependency_checks(make_snapshot(files))
        last = findings[-1]
        assert last.id == "deps.advisories"
        assert last.status == "not_assessed"
        assert "no dependency was checked" in last.detail
        assert last.remediation


def test_everything_is_not_assessed_without_a_file_list():
    findings = run_dependency_checks(make_snapshot([], tree_available=False))
    assert {finding.id for finding in findings} == {"deps.manifest.present", "deps.advisories"}
    assert {finding.status for finding in findings} == {"not_assessed"}


def test_nothing_is_read_when_there_is_no_requirements_file():
    snapshot = make_snapshot(["package.json", "package-lock.json"])
    run_dependency_checks(snapshot)
    assert snapshot.calls == []


# ---------- Manifest ----------

@pytest.mark.parametrize(
    "name", ["requirements.txt", "pyproject.toml", "Pipfile", "package.json", "go.mod", "Cargo.toml"]
)
def test_recognized_manifests(name):
    finding = run(make_snapshot([name]))["deps.manifest.present"]
    assert finding.status == "passed"
    assert finding.evidence == [name]


def test_manifests_in_sub_folders_count_and_the_root_comes_first():
    files = ["a/b/package.json", "package.json", "z/go.mod"]
    finding = run(make_snapshot(files))["deps.manifest.present"]
    assert finding.status == "passed"
    assert finding.evidence[0] == "package.json"
    assert "3 dependency manifest" in finding.detail


def test_manifests_inside_dependency_folders_are_ignored():
    finding = run(make_snapshot(["node_modules/left-pad/package.json"]))["deps.manifest.present"]
    assert finding.status == "not_assessed"


def test_manifest_found_even_when_the_list_is_truncated():
    finding = run(make_snapshot(["package.json"], truncated=True))["deps.manifest.present"]
    assert finding.status == "passed"


@pytest.mark.parametrize("language", ["Python", "JavaScript", "TypeScript", "Go", "Rust"])
def test_supported_language_without_a_manifest_fails(language):
    finding = run(make_snapshot(["app.py"], metadata={"language": language}))["deps.manifest.present"]
    assert finding.status == "failed"
    assert finding.remediation


@pytest.mark.parametrize("language", ["Ruby", "HTML", None])
def test_other_languages_without_a_manifest_are_not_assessed(language):
    finding = run(make_snapshot(["app.rb"], metadata={"language": language}))["deps.manifest.present"]
    assert finding.status == "not_assessed"


def test_missing_manifest_is_not_assessed_when_the_list_is_incomplete():
    finding = run(make_snapshot(["app.py"], metadata={"language": "Python"}, truncated=True))
    assert finding["deps.manifest.present"].status == "not_assessed"


# ---------- Lockfile present ----------

def test_javascript_manifest_without_a_lockfile_fails():
    finding = run(make_snapshot(["package.json"]))["deps.lockfile.present"]
    assert finding.status == "failed"
    assert finding.evidence == ["(repository root)"]
    assert finding.remediation


@pytest.mark.parametrize("lockfile", ["package-lock.json", "yarn.lock", "pnpm-lock.yaml"])
def test_javascript_manifest_with_a_lockfile_passes(lockfile):
    finding = run(make_snapshot(["package.json", lockfile]))["deps.lockfile.present"]
    assert finding.status == "passed"
    assert finding.evidence == [lockfile]


def test_a_root_lockfile_covers_packages_in_sub_folders():
    files = ["package.json", "package-lock.json", "packages/a/package.json"]
    assert run(make_snapshot(files))["deps.lockfile.present"].status == "passed"


def test_a_sub_folder_without_any_lockfile_is_named():
    finding = run(make_snapshot(["web/package.json"]))["deps.lockfile.present"]
    assert finding.status == "failed"
    assert finding.evidence == ["web/"]


def test_missing_lockfile_is_not_assessed_when_the_list_is_incomplete():
    finding = run(make_snapshot(["package.json"], truncated=True))["deps.lockfile.present"]
    assert finding.status == "not_assessed"


def test_lockfile_check_is_left_out_for_non_javascript_projects():
    assert "deps.lockfile.present" not in run(make_snapshot(["requirements.txt"]))
    assert "deps.lockfile.present" not in run(make_snapshot(["node_modules/x/package.json"]))


# ---------- Lockfile consistency ----------

def test_consistency_check_is_left_out_when_there_are_no_lockfiles():
    assert "deps.lockfile.consistent" not in run(make_snapshot(["package.json"]))


def test_matching_lockfile_and_manifest_are_consistent():
    finding = run(make_snapshot(["package.json", "package-lock.json"]))["deps.lockfile.consistent"]
    assert finding.status == "passed"


def test_two_package_managers_in_one_folder_are_reported():
    files = ["package.json", "package-lock.json", "yarn.lock"]
    finding = run(make_snapshot(files))["deps.lockfile.consistent"]
    assert finding.status == "failed"
    assert finding.evidence == ["(repository root): npm and yarn lockfiles"]
    assert finding.remediation


def test_npm_shrinkwrap_and_package_lock_are_the_same_package_manager():
    files = ["package.json", "package-lock.json", "npm-shrinkwrap.json"]
    assert run(make_snapshot(files))["deps.lockfile.consistent"].status == "passed"


def test_two_python_lock_tools_in_one_folder_are_reported():
    files = ["pyproject.toml", "poetry.lock", "uv.lock"]
    finding = run(make_snapshot(files))["deps.lockfile.consistent"]
    assert finding.status == "failed"
    assert finding.evidence == ["(repository root): poetry and uv lockfiles"]


def test_different_package_managers_in_different_folders_are_fine():
    files = ["a/package.json", "a/package-lock.json", "b/package.json", "b/yarn.lock"]
    assert run(make_snapshot(files))["deps.lockfile.consistent"].status == "passed"


def test_lockfile_without_its_manifest_is_reported():
    finding = run(make_snapshot(["package-lock.json"]))["deps.lockfile.consistent"]
    assert finding.status == "failed"
    assert finding.evidence == ["(repository root): package-lock.json has no matching manifest"]


def test_go_and_cargo_lockfiles_need_their_own_manifests():
    assert run(make_snapshot(["go.mod", "go.sum"]))["deps.lockfile.consistent"].status == "passed"
    assert run(make_snapshot(["go.sum"]))["deps.lockfile.consistent"].status == "failed"
    assert run(make_snapshot(["Cargo.toml", "Cargo.lock"]))["deps.lockfile.consistent"].status == "passed"


def test_lockfile_must_be_next_to_its_own_manifest():
    files = ["package.json", "sub/package-lock.json"]
    finding = run(make_snapshot(files))["deps.lockfile.consistent"]
    assert finding.status == "failed"
    assert finding.evidence == ["sub/: package-lock.json has no matching manifest"]


def test_orphan_lockfile_is_not_reported_when_the_list_is_incomplete():
    finding = run(make_snapshot(["package-lock.json"], truncated=True))["deps.lockfile.consistent"]
    assert finding.status == "not_assessed"


def test_a_conflict_is_still_reported_when_the_list_is_incomplete():
    files = ["package-lock.json", "yarn.lock"]
    finding = run(make_snapshot(files, truncated=True))["deps.lockfile.consistent"]
    assert finding.status == "failed"


def test_folder_names_are_cleaned_before_display():
    folder = "we\x1bird"
    files = [f"{folder}/package.json", f"{folder}/package-lock.json", f"{folder}/yarn.lock"]
    finding = run(make_snapshot(files))["deps.lockfile.consistent"]
    assert "\x1b" not in finding.evidence[0]


# ---------- parse_requirements ----------

@pytest.mark.parametrize(
    "line, expected",
    [
        ("requests==2.31.0", [("requests", True)]),
        ("requests===2.31.0", [("requests", True)]),
        ("requests >= 2", [("requests", False)]),
        ("requests", [("requests", False)]),
        ("requests~=2.31", [("requests", False)]),
        ("requests[security]==2.0", [("requests", True)]),
        ("requests==2.*", [("requests", False)]),
        ("requests==1.0,!=1.1", [("requests", False)]),
        ("numpy==1.26.0 ; python_version < '3.13'", [("numpy", True)]),
        ("numpy==1.26.0 --hash=sha256:abc123", [("numpy", True)]),
        ("flask==3.0.0  # web framework", [("flask", True)]),
        ("# just a comment", []),
        ("-r base.txt", []),
        ("-e .", []),
        ("--index-url https://example.com/simple", []),
        ("git+https://example.com/x/y.git#egg=y", []),
        ("https://example.com/pkg.whl", []),
        ("./local-package", []),
        ("", []),
    ],
)
def test_parse_requirements_lines(line, expected):
    assert parse_requirements(line) == expected


def test_parse_requirements_skips_very_long_lines():
    assert parse_requirements("requests==" + "1" * 1000) == []


# ---------- Pinning ----------

def test_mixed_requirements_fail_and_are_counted_accurately():
    text = "flask==3.0.0\nrequests>=2\nnumpy\n"
    result = run(make_snapshot(["requirements.txt"], texts={"requirements.txt": text}))
    finding = result["deps.pinning"]
    assert finding.status == "failed"
    assert "2 of 3" in finding.detail
    assert finding.evidence == ["requests", "numpy"]
    assert finding.confidence == "low"


def test_fully_pinned_requirements_pass():
    text = "flask==3.0.0\n# comment\n-r base.txt\nrequests==2.31.0\n"
    result = run(make_snapshot(["requirements.txt"], texts={"requirements.txt": text}))
    assert result["deps.pinning"].status == "passed"


def test_evidence_lists_at_most_three_package_names():
    text = "".join(f"pkg{i}\n" for i in range(5))
    result = run(make_snapshot(["requirements.txt"], texts={"requirements.txt": text}))
    assert len(result["deps.pinning"].evidence) == 3


def test_requirements_file_with_only_comments_is_not_assessed():
    result = run(make_snapshot(["requirements.txt"], texts={"requirements.txt": "# nothing\n"}))
    assert result["deps.pinning"].status == "not_assessed"


def test_unreadable_requirements_file_is_not_assessed():
    result = run(make_snapshot(["requirements.txt"], texts={}))
    assert result["deps.pinning"].status == "not_assessed"


def test_truncated_requirements_file_cannot_prove_everything_is_pinned():
    text = "flask==3.0.0\n"
    ok = run(make_snapshot(["requirements.txt"], texts={"requirements.txt": text}, text_truncated=True))
    assert ok["deps.pinning"].status == "not_assessed"

    bad = run(make_snapshot(["requirements.txt"], texts={"requirements.txt": "flask\n"}, text_truncated=True))
    assert bad["deps.pinning"].status == "failed"


def test_only_a_root_requirements_file_is_read():
    snapshot = make_snapshot(["backend/requirements.txt"])
    result = run(snapshot)
    assert "deps.pinning" not in result
    assert snapshot.calls == []


# ---------- Update automation ----------

@pytest.mark.parametrize("path", [".github/dependabot.yml", "renovate.json", ".github/renovate.json5"])
def test_update_automation_is_recognized(path):
    finding = run(make_snapshot(["package.json", path]))["deps.automation"]
    assert finding.status == "passed"
    assert finding.evidence == [path]


def test_missing_update_automation_fails_but_admits_what_it_cannot_see():
    finding = run(make_snapshot(["package.json"]))["deps.automation"]
    assert finding.status == "failed"
    assert "settings" in finding.detail
    assert finding.remediation


def test_update_automation_is_not_assessed_when_the_list_is_incomplete():
    finding = run(make_snapshot(["package.json"], truncated=True))["deps.automation"]
    assert finding.status == "not_assessed"


def test_update_automation_is_left_out_without_a_manifest():
    assert "deps.automation" not in run(make_snapshot(["app.py"]))
