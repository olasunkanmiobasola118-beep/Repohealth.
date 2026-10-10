"""Documentation checks.

Pure functions: they receive a RepoSnapshot and return Findings. They never
touch the network, so they are easy to test.

Section checks look at the README's *headings*. A heading such as "Installation"
suggests the section exists, but we do not judge how good it is. The README's
leading level-1 heading is treated as the project title, not as a section.
"""

import re

from scanner.models import Finding

CATEGORY = "documentation"

README_CANDIDATES = [
    "readme.md", "readme.markdown", "readme.rst", "readme.txt", "readme",
    ".github/readme.md", "docs/readme.md",
]
LICENSE_CANDIDATES = [
    "license", "license.md", "license.txt", "licence", "licence.md",
    "copying", "copying.md", "unlicense",
]

MAX_HEADING_LINE = 200   # skip longer lines: headings are short, and this keeps regexes fast
MAX_EVIDENCE_CHARS = 80
MAX_EVIDENCE_ITEMS = 3

_ATX_HEADING = re.compile(r"\s{0,3}(#{1,6})\s+(.+?)(?:\s+#+)?\s*")
_HTML_HEADING = re.compile(r"<h([1-6])[^>]*>(.*?)</h[1-6]>", re.IGNORECASE)
_HTML_TAG = re.compile(r"<[^>]+>")
_SETEXT_UNDERLINE = re.compile(r"[=\-~^]{3,}")

INSTALL_PATTERN = re.compile(
    r"\b(install\w*|set[ -]?up|getting started|quick[ -]?start|prerequisites?|requirements)\b",
    re.IGNORECASE,
)
USAGE_PATTERN = re.compile(
    r"\b(usage|how to use|using|running|getting started|quick[ -]?start)\b", re.IGNORECASE
)
EXAMPLES_PATTERN = re.compile(r"\b(examples?|demo|tutorials?|samples?)\b", re.IGNORECASE)


def clean_for_display(text):
    """Make untrusted text safe to show: no control characters, short, one line."""
    text = re.sub(r"[\x00-\x1f\x7f]", " ", text)
    text = " ".join(text.split())
    if len(text) > MAX_EVIDENCE_CHARS:
        text = text[: MAX_EVIDENCE_CHARS - 1] + "…"
    return text


def _iter_headings(text):
    """Yield (level, heading_text) for every heading in a README.

    Understands Markdown (# Title), underlined titles (Markdown and
    reStructuredText) and HTML <h2> headings. Lines inside fenced code blocks
    are ignored, because "# comment" lines in code are not headings.
    """
    lines = text.splitlines()
    in_fence = False

    for index, line in enumerate(lines):
        stripped = line.strip()

        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence or not stripped or len(line) > MAX_HEADING_LINE:
            continue

        atx = _ATX_HEADING.fullmatch(line)
        if atx:
            yield len(atx.group(1)), atx.group(2)
            continue

        html = _HTML_HEADING.search(line)
        if html:
            yield int(html.group(1)), _HTML_TAG.sub("", html.group(2)).strip()
            continue

        if index + 1 < len(lines) and not stripped.startswith(("-", "*", "+", "|", ">")):
            next_line = lines[index + 1].strip()
            if len(next_line) <= MAX_HEADING_LINE and _SETEXT_UNDERLINE.fullmatch(next_line):
                yield (1 if next_line.startswith("=") else 2), stripped


def extract_headings(text):
    """Return the text of every heading in a README."""
    return [heading for _, heading in _iter_headings(text)]


def extract_section_headings(text):
    """Return headings that can name a section.

    If the first heading is level 1, it is the project title (for example
    "# Demo" or "# Installer"), so we drop it. Otherwise a project called
    "Installer" would wrongly pass the installation check.
    """
    headings = list(_iter_headings(text))
    if headings and headings[0][0] == 1:
        headings = headings[1:]
    return [heading for _, heading in headings]


# ---------- Individual checks ----------

def _check_readme_present(snapshot, readme_path):
    base = dict(
        id="docs.readme.present", category=CATEGORY, title="README file",
        severity="high", kind="objective", confidence="high",
    )
    if readme_path:
        return Finding(status="passed", detail="A README file was found.",
                       evidence=[readme_path], **base)
    if snapshot.can_confirm_absence:
        return Finding(
            status="failed", detail="No README file was found.",
            remediation="Add a README.md that explains what the project does, "
                        "how to install it, and how to use it.",
            **base,
        )
    return Finding(
        status="not_assessed",
        detail="The repository's file list was unavailable or incomplete, "
               "so the README could not be confirmed.",
        **base,
    )


def _check_license(snapshot, license_path):
    base = dict(
        id="docs.license", category=CATEGORY, title="License",
        severity="medium", kind="objective", confidence="high",
    )
    spdx = snapshot.metadata.get("license")
    evidence = []
    if spdx and spdx != "NOASSERTION":
        evidence.append(f"GitHub detected license: {spdx}")
    elif spdx:
        evidence.append("GitHub found a license it could not identify")
    if license_path:
        evidence.append(license_path)

    if evidence:
        return Finding(status="passed", detail="A license was found.",
                       evidence=evidence, **base)
    if snapshot.can_confirm_absence:
        return Finding(
            status="failed", detail="No license was found.",
            remediation="Add a LICENSE file. Without one, others have no clear "
                        "permission to use or modify the code. choosealicense.com "
                        "can help you pick one.",
            **base,
        )
    return Finding(
        status="not_assessed",
        detail="The repository's file list was unavailable or incomplete, "
               "so a license file could not be confirmed.",
        **base,
    )


def _check_description(snapshot):
    base = dict(
        id="docs.description", category=CATEGORY, title="Repository description",
        severity="low", kind="objective", confidence="high",
    )
    description = snapshot.metadata.get("description")
    if isinstance(description, str) and description.strip():
        return Finding(status="passed", detail="The repository has a description.",
                       evidence=["GitHub description is set"], **base)
    return Finding(
        status="failed", detail="The repository has no description on GitHub.",
        remediation="Add a one-line description in the repository settings so "
                    "visitors can tell what the project does.",
        **base,
    )


def _check_readme_section(snapshot, readme_path, *, finding_id, title, severity,
                          pattern, section_name, remediation):
    base = dict(
        id=finding_id, category=CATEGORY, title=title,
        severity=severity, kind="heuristic", confidence="medium",
    )

    if readme_path is None:
        if snapshot.can_confirm_absence:
            return Finding(status="failed", detail="There is no README to contain this section.",
                           remediation=remediation, **base)
        return Finding(status="not_assessed",
                       detail="The README could not be located, so its content was not inspected.",
                       **base)

    content = snapshot.read(readme_path)
    if content is None:
        return Finding(status="not_assessed",
                       detail="The README could not be read, so its content was not inspected.",
                       **base)

    matches = [h for h in extract_section_headings(content.text) if pattern.search(h)]
    if matches:
        shown = [clean_for_display(h) for h in matches[:MAX_EVIDENCE_ITEMS]]
        return Finding(
            status="passed",
            detail=f"The README has a heading that suggests a {section_name} section. "
                   "RepoHealth does not judge how good the section is.",
            evidence=shown, **base,
        )

    if content.truncated:
        return Finding(
            status="not_assessed",
            detail="The README is too large to read completely, so a missing "
                   f"{section_name} section could not be confirmed.",
            **base,
        )

    return Finding(
        status="failed",
        detail=f"No README heading looks like a {section_name} section. "
               "The information may exist under a different heading or elsewhere.",
        remediation=remediation, **base,
    )


# ---------- Entry point ----------

def run_documentation_checks(snapshot):
    """Run every documentation check and return a list of Findings."""
    readme_path = snapshot.find(README_CANDIDATES)
    license_path = snapshot.find(LICENSE_CANDIDATES)

    return [
        _check_readme_present(snapshot, readme_path),
        _check_license(snapshot, license_path),
        _check_description(snapshot),
        _check_readme_section(
            snapshot, readme_path,
            finding_id="docs.readme.installation",
            title="README has installation instructions",
            severity="medium", pattern=INSTALL_PATTERN, section_name="installation",
            remediation="Add an 'Installation' section listing requirements and "
                        "the exact commands to install the project.",
        ),
        _check_readme_section(
            snapshot, readme_path,
            finding_id="docs.readme.usage",
            title="README has usage instructions",
            severity="medium", pattern=USAGE_PATTERN, section_name="usage",
            remediation="Add a 'Usage' section showing how to run or use the project.",
        ),
        _check_readme_section(
            snapshot, readme_path,
            finding_id="docs.readme.examples",
            title="README has examples",
            severity="low", pattern=EXAMPLES_PATTERN, section_name="examples",
            remediation="Add an 'Examples' section with a short, working example.",
        ),
    ]