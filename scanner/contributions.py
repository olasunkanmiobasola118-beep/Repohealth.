"""Contribution-readiness checks.

Pure functions: they receive a RepoSnapshot and return Findings. They use the
file list, plus one read of the contributing guide when it exists.

File ownership (so one missing file is never counted twice):
- this module: contributing guide, code of conduct, issue and pull request templates
- documentation.py: README, license, description
- the security module (later): SECURITY.md
- the testing module (later): GitHub Actions workflows

Not included yet: beginner-friendly issue labels. Those need extra GitHub
requests, so they will be added as a separate, optional step.
"""

import re

from scanner.documentation import clean_for_display, extract_section_headings
from scanner.models import Finding

CATEGORY = "contribution"

MAX_EVIDENCE_ITEMS = 3

_STANDARD_FOLDERS = ("", ".github/", "docs/")


def _locations(names, folders=_STANDARD_FOLDERS):
    """Build candidate paths: every name in the root, .github/ and docs/."""
    return [folder + name for folder in folders for name in names]


CONTRIBUTING_CANDIDATES = _locations(
    ["contributing.md", "contributing.rst", "contributing.txt", "contributing"]
)
CONDUCT_CANDIDATES = _locations(
    ["code_of_conduct.md", "code_of_conduct.rst", "code_of_conduct.txt",
     "code_of_conduct", "code-of-conduct.md"]
)

ISSUE_TEMPLATE_FILES = _locations(["issue_template.md"])
ISSUE_TEMPLATE_FOLDERS = ["issue_template", ".github/issue_template", "docs/issue_template"]
ISSUE_TEMPLATE_EXTENSIONS = (".md", ".yml", ".yaml")
ISSUE_TEMPLATE_IGNORED = ("config.yml", "config.yaml")   # settings, not a template

PR_TEMPLATE_FILES = _locations(["pull_request_template.md"])
PR_TEMPLATE_FOLDERS = [
    "pull_request_template", ".github/pull_request_template", "docs/pull_request_template",
]
PR_TEMPLATE_EXTENSIONS = (".md",)

# Headings that suggest a guide explains how to take part.
CONTRIBUTING_PATTERN = re.compile(
    r"\b(set[ -]?up|install\w*|development|getting started|pull requests?|submitting|"
    r"tests?|testing|bugs?|issues?|workflow|code style|coding standards|how to contribute)\b",
    re.IGNORECASE,
)


def _find_template(snapshot, files, folders, extensions, ignored=()):
    """Look for a template file or a template folder.

    Returns a short piece of evidence to display, or None. For folders the
    evidence is the folder name, because file names inside it come from the
    repository and are not shown.
    """
    path = snapshot.find(files)
    if path:
        return clean_for_display(path)
    for folder in folders:
        inside = snapshot.find_in_folder(folder, extensions, ignored)
        if inside:
            return clean_for_display(inside.rsplit("/", 1)[0] + "/")
    return None


def _presence_check(snapshot, evidence, *, finding_id, title, severity,
                    found_detail, missing_detail, remediation):
    base = dict(
        id=finding_id, category=CATEGORY, title=title,
        severity=severity, kind="objective", confidence="high",
    )
    if evidence:
        return Finding(status="passed", detail=found_detail, evidence=[evidence], **base)
    if snapshot.can_confirm_absence:
        return Finding(status="failed", detail=missing_detail,
                       remediation=remediation, **base)
    return Finding(
        status="not_assessed",
        detail="The repository's file list was unavailable or incomplete, "
               "so this could not be confirmed.",
        **base,
    )


def _check_guide_content(snapshot, guide_path):
    base = dict(
        id="contrib.guide.content", category=CATEGORY,
        title="Contributing guide explains how to contribute",
        severity="low", kind="heuristic", confidence="medium",
    )
    remediation = (
        "Add sections to the contributing guide that explain how to set up the "
        "project, run the tests, report bugs, and submit a pull request."
    )

    if guide_path is None:
        if snapshot.can_confirm_absence:
            return Finding(status="failed",
                           detail="There is no contributing guide to inspect.",
                           remediation=remediation, **base)
        return Finding(
            status="not_assessed",
            detail="The contributing guide could not be located, so its content was not inspected.",
            **base,
        )

    content = snapshot.read(guide_path)
    if content is None:
        return Finding(
            status="not_assessed",
            detail="The contributing guide could not be read, so its content was not inspected.",
            **base,
        )

    matches = [h for h in extract_section_headings(content.text)
               if CONTRIBUTING_PATTERN.search(h)]
    if matches:
        shown = [clean_for_display(h) for h in matches[:MAX_EVIDENCE_ITEMS]]
        return Finding(
            status="passed",
            detail="The guide has headings that suggest practical instructions "
                   "(for example setup or pull requests). RepoHealth does not "
                   "judge how good they are.",
            evidence=shown, **base,
        )

    if content.truncated:
        return Finding(
            status="not_assessed",
            detail="The contributing guide is too large to read completely, so "
                   "missing instructions could not be confirmed.",
            **base,
        )

    return Finding(
        status="failed",
        detail="No heading in the guide looks like practical instructions. "
               "They may exist under a different heading or elsewhere.",
        remediation=remediation, **base,
    )


def run_contribution_checks(snapshot):
    """Run every contribution-readiness check and return a list of Findings."""
    guide_path = snapshot.find(CONTRIBUTING_CANDIDATES)
    conduct_path = snapshot.find(CONDUCT_CANDIDATES)

    return [
        _presence_check(
            snapshot, clean_for_display(guide_path) if guide_path else None,
            finding_id="contrib.guide.present", title="Contributing guide",
            severity="medium",
            found_detail="A contributing guide was found.",
            missing_detail="No contributing guide was found.",
            remediation="Add a CONTRIBUTING.md that explains how to set up the "
                        "project, run the tests, and submit a pull request.",
        ),
        _check_guide_content(snapshot, guide_path),
        _presence_check(
            snapshot, clean_for_display(conduct_path) if conduct_path else None,
            finding_id="contrib.conduct", title="Code of conduct",
            severity="low",
            found_detail="A code of conduct was found.",
            missing_detail="No code of conduct was found.",
            remediation="Add a CODE_OF_CONDUCT.md so contributors know what "
                        "behavior is expected. The Contributor Covenant is a "
                        "widely used starting point.",
        ),
        _presence_check(
            snapshot,
            _find_template(snapshot, ISSUE_TEMPLATE_FILES, ISSUE_TEMPLATE_FOLDERS,
                           ISSUE_TEMPLATE_EXTENSIONS, ISSUE_TEMPLATE_IGNORED),
            finding_id="contrib.issue_templates", title="Issue templates",
            severity="low",
            found_detail="Issue templates were found.",
            missing_detail="No issue templates were found.",
            remediation="Add issue templates in .github/ISSUE_TEMPLATE/ so bug "
                        "reports and feature requests include the details "
                        "maintainers need.",
        ),
        _presence_check(
            snapshot,
            _find_template(snapshot, PR_TEMPLATE_FILES, PR_TEMPLATE_FOLDERS,
                           PR_TEMPLATE_EXTENSIONS),
            finding_id="contrib.pr_template", title="Pull request template",
            severity="low",
            found_detail="A pull request template was found.",
            missing_detail="No pull request template was found.",
            remediation="Add .github/pull_request_template.md with a short "
                        "checklist so first-time contributors submit complete "
                        "pull requests.",
        ),
    ]