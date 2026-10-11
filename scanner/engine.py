"""Scan engine: gathers repository data and runs the checks.

This module and github_client.py are the only scanner code that uses the
network. The check modules only ever receive a RepoSnapshot.
"""

import logging

from scanner.contributions import run_contribution_checks
from scanner.documentation import run_documentation_checks
from scanner.github_client import GitHubError, fetch_file_text, fetch_repo_tree
from scanner.models import RepoSnapshot
from scanner.testing import run_testing_checks

logger = logging.getLogger(__name__)

# Each runner takes a RepoSnapshot and returns a list of Findings.
# New check modules (testing, dependencies, security) are added here in later parts.
CHECK_RUNNERS = [run_documentation_checks, run_contribution_checks, run_testing_checks]


def _add_warning(warnings, message):
    if message not in warnings:
        warnings.append(message)


def _make_reader(owner, repo, known_paths, warnings):
    """Build the function a RepoSnapshot uses to read files."""

    def reader(path):
        # Defense in depth: only files that appeared in the file list can be read.
        if path not in known_paths:
            return None
        try:
            return fetch_file_text(owner, repo, path)
        except GitHubError as error:
            _add_warning(
                warnings,
                f"A file needed for some checks could not be read: {error.message}",
            )
            return None

    return reader


def build_snapshot(owner, repo, metadata):
    """Fetch the file list and return (snapshot, warnings).

    The warnings list keeps growing while checks run, because file reads
    happen later, when a check asks for them.
    """
    warnings = []
    files = None
    truncated = False

    try:
        files, truncated = fetch_repo_tree(owner, repo, metadata.get("default_branch"))
    except GitHubError as error:
        if error.code == "empty_repository":
            files = []
            _add_warning(warnings, "This repository is empty, so it has no files to check.")
        else:
            _add_warning(
                warnings,
                f"The repository's file list could not be loaded: {error.message} "
                "Checks that need it are marked 'not assessed'.",
            )

    if truncated:
        _add_warning(
            warnings,
            "The repository is very large, so its file list is incomplete. "
            "A file that seems to be missing may just be missing from the list.",
        )

    known_paths = set(files) if files is not None else set()
    reader = _make_reader(owner, repo, known_paths, warnings)
    snapshot = RepoSnapshot(metadata, files, truncated=truncated, reader=reader)
    return snapshot, warnings


def analyze_repository(owner, repo, metadata):
    """Run all checks. Returns a dict that is ready to send as JSON."""
    snapshot, warnings = build_snapshot(owner, repo, metadata)

    findings = []
    for runner in CHECK_RUNNERS:
        try:
            findings.extend(runner(snapshot))
        except Exception:
            # Details go to the server log, never to the user.
            logger.exception("A check module failed")
            _add_warning(
                warnings,
                "Some checks could not be completed because of an internal error.",
            )

    return {
        "findings": [finding.to_dict() for finding in findings],
        "warnings": warnings,
        "file_list": {
            "available": snapshot.tree_available,
            "complete": snapshot.can_confirm_absence,
        },
    }
