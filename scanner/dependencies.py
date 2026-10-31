"""Dependency checks.

Pure functions: they receive a RepoSnapshot and return Findings. The only file
they ever read is a root-level requirements.txt, and only as text.

What this module does NOT do: it does not look up known vulnerabilities. The
"deps.advisories" finding says so explicitly, so a report never suggests that
dependencies were checked when they were not. Advisory lookup is planned as a
separate step.

Checks that only make sense for some projects (lockfiles, pinning, update
automation) are left out of the results when they do not apply.
"""

import re

from scanner.documentation import clean_for_display
from scanner.models import Finding
from scanner.testing import IGNORED_DIRECTORIES

CATEGORY = "dependencies"

MAX_EVIDENCE_ITEMS = 3
MAX_REQUIREMENT_LINES = 2000
MAX_REQUIREMENT_LINE = 300   # skip longer lines: keeps the regexes fast

# ecosystem -> (manifest file names, lockfile names). All lower-case.
ECOSYSTEMS = {
    "JavaScript": (
        ("package.json",),
        ("package-lock.json", "npm-shrinkwrap.json", "yarn.lock",
         "pnpm-lock.yaml", "bun.lockb", "bun.lock"),
    ),
    "Python": (
        ("requirements.txt", "pyproject.toml", "pipfile"),
        ("poetry.lock", "pipfile.lock", "uv.lock", "pdm.lock"),
    ),
    "Go": (("go.mod",), ("go.sum",)),
    "Rust": (("cargo.toml",), ("cargo.lock",)),
}

# Which package manager a lockfile belongs to.
LOCKFILE_FAMILY = {
    "package-lock.json": "npm", "npm-shrinkwrap.json": "npm",
    "yarn.lock": "yarn", "pnpm-lock.yaml": "pnpm",
    "bun.lockb": "bun", "bun.lock": "bun",
    "poetry.lock": "poetry", "pipfile.lock": "pipenv",
    "uv.lock": "uv", "pdm.lock": "pdm",
    "go.sum": "go", "cargo.lock": "cargo",
}

# The manifest that must sit in the same folder as each lockfile.
LOCKFILE_NEEDS = {
    "package-lock.json": ("package.json",),
    "npm-shrinkwrap.json": ("package.json",),
    "yarn.lock": ("package.json",),
    "pnpm-lock.yaml": ("package.json",),
    "bun.lockb": ("package.json",),
    "bun.lock": ("package.json",),
    "poetry.lock": ("pyproject.toml",),
    "uv.lock": ("pyproject.toml",),
    "pdm.lock": ("pyproject.toml",),
    "pipfile.lock": ("pipfile",),
    "go.sum": ("go.mod",),
    "cargo.lock": ("cargo.toml",),
}

MANIFEST_ECOSYSTEM = {
    name: ecosystem
    for ecosystem, (manifests, _) in ECOSYSTEMS.items()
    for name in manifests
}
LOCKFILE_ECOSYSTEM = {
    name: ecosystem
    for ecosystem, (_, lockfiles) in ECOSYSTEMS.items()
    for name in lockfiles
}

# GitHub's "main language" -> the ecosystem we expect a manifest for.
LANGUAGE_ECOSYSTEM = {
    "Python": "Python", "JavaScript": "JavaScript", "TypeScript": "JavaScript",
    "Go": "Go", "Rust": "Rust",
}

MANIFEST_HINT = {
    "Python": "Add a requirements.txt or pyproject.toml that lists the packages the project needs.",
    "JavaScript": "Add a package.json that lists the packages the project needs (npm init creates one).",
    "Go": "Add a go.mod file (go mod init creates one).",
    "Rust": "Add a Cargo.toml file (cargo init creates one).",
}

AUTOMATION_FILES = [
    ".github/dependabot.yml", ".github/dependabot.yaml",
    "renovate.json", "renovate.json5", ".renovaterc", ".renovaterc.json",
    ".github/renovate.json", ".github/renovate.json5",
]

_REQUIREMENT_LINE = re.compile(
    r"([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*([^;#]*)"
)
_EXACT_PIN = re.compile(r"===?\s*[A-Za-z0-9][A-Za-z0-9.+!_-]*")

_UNKNOWN = ("The repository's file list was unavailable or incomplete, "
            "so this could not be confirmed.")


# ---------- Helpers ----------

def _depth(directory):
    return directory.count("/") + 1 if directory else 0


def _parents(directory):
    """'a/b' -> ['a/b', 'a', ''] : the folder itself, then each parent."""
    parts = directory.split("/") if directory else []
    return ["/".join(parts[:i]) for i in range(len(parts), -1, -1)]


def _display_folder(directory):
    return "(repository root)" if not directory else clean_for_display(directory + "/")


def _unique(items):
    result = []
    for item in items:
        if item not in result:
            result.append(item)
    return result


def scan_dependency_files(snapshot):
    """Return (manifests, lockfiles), each a list of (folder, lowercase name, path).

    Files inside dependency or build folders (node_modules, vendor, ...) are ignored.
    """
    manifests = []
    lockfiles = []
    for path in snapshot.paths:
        parts = path.split("/")
        folders, name = parts[:-1], parts[-1]
        if any(part.lower() in IGNORED_DIRECTORIES for part in folders):
            continue
        lowered = name.lower()
        directory = "/".join(folders)
        if lowered in MANIFEST_ECOSYSTEM:
            manifests.append((directory, lowered, path))
        elif lowered in LOCKFILE_ECOSYSTEM:
            lockfiles.append((directory, lowered, path))
    return manifests, lockfiles


def parse_requirements(text):
    """Return [(package name, is_pinned)] for the lines of a requirements.txt.

    A requirement is "pinned" only if it uses an exact version (== or ===,
    without a wildcard). Comments, pip options (-r, -e, --hash), URLs, VCS
    links and local paths are skipped.
    """
    requirements = []
    for raw in text.splitlines()[:MAX_REQUIREMENT_LINES]:
        if len(raw) > MAX_REQUIREMENT_LINE:
            continue
        line = raw.strip()
        if not line or line.startswith(("#", "-")):
            continue
        if "://" in line or line.startswith((".", "/", "git+")):
            continue

        match = _REQUIREMENT_LINE.match(line)
        if not match:
            continue
        name = match.group(1)
        spec = re.split(r"\s+--", match.group(2))[0].strip().rstrip("\\").strip()
        requirements.append((name, bool(_EXACT_PIN.fullmatch(spec))))
    return requirements


# ---------- Individual checks ----------

def _check_manifest(snapshot, manifests):
    base = dict(
        id="deps.manifest.present", category=CATEGORY, title="Dependency manifest",
        severity="medium", kind="heuristic",
    )

    if manifests:
        ordered = sorted(manifests, key=lambda item: (_depth(item[0]), item[2]))
        shown = [clean_for_display(path) for _, _, path in ordered[:MAX_EVIDENCE_ITEMS]]
        return Finding(
            status="passed", confidence="high",
            detail=f"{len(manifests)} dependency manifest file(s) were found.",
            evidence=shown, **base,
        )

    language = snapshot.metadata.get("language")
    ecosystem = LANGUAGE_ECOSYSTEM.get(language)
    if ecosystem and snapshot.can_confirm_absence:
        return Finding(
            status="failed", confidence="medium",
            detail=f"GitHub reports {language} as the main language, but no dependency "
                   "manifest in a supported format was found.",
            remediation=MANIFEST_HINT[ecosystem], **base,
        )

    return Finding(
        status="not_assessed", confidence="low",
        detail="No dependency manifest in a supported format was found. The project may "
               "have no dependencies, or may use an ecosystem RepoHealth does not "
               "recognize yet.",
        **base,
    )


def _check_lockfile_present(snapshot, manifests, lockfiles):
    js_folders = sorted({d for d, name, _ in manifests if name == "package.json"})
    if not js_folders:
        return None

    base = dict(
        id="deps.lockfile.present", category=CATEGORY,
        title="JavaScript lockfile is committed",
        severity="low", kind="heuristic", confidence="medium",
    )
    js_lockfiles = [
        (d, name) for d, name, _ in lockfiles if LOCKFILE_ECOSYSTEM.get(name) == "JavaScript"
    ]
    lock_folders = {d for d, _ in js_lockfiles}
    missing = [
        d for d in js_folders
        if not any(parent in lock_folders for parent in _parents(d))
    ]

    if not missing:
        return Finding(
            status="passed",
            detail="Every package.json has a lockfile in its folder or a parent folder.",
            evidence=sorted({name for _, name in js_lockfiles}), **base,
        )
    if snapshot.can_confirm_absence:
        return Finding(
            status="failed",
            detail="Some package.json files have no lockfile. Libraries sometimes leave "
                   "the lockfile out on purpose; applications should commit one.",
            evidence=[_display_folder(d) for d in missing[:MAX_EVIDENCE_ITEMS]],
            remediation="Commit your lockfile (for example package-lock.json) so installs "
                        "are reproducible.",
            **base,
        )
    return Finding(status="not_assessed", detail=_UNKNOWN, **base)


def _check_lockfile_consistency(snapshot, manifests, lockfiles):
    if not lockfiles:
        return None

    base = dict(
        id="deps.lockfile.consistent", category=CATEGORY,
        title="Lockfiles match their manifests",
        severity="medium", kind="heuristic", confidence="medium",
    )
    problems = []

    names_by_folder = {}
    for directory, name, _ in lockfiles:
        names_by_folder.setdefault(directory, []).append(name)

    # More than one package manager's lockfile in the same folder.
    for directory in sorted(names_by_folder):
        families = {}
        for name in names_by_folder[directory]:
            families.setdefault(LOCKFILE_ECOSYSTEM[name], set()).add(LOCKFILE_FAMILY[name])
        for group in families.values():
            if len(group) > 1:
                problems.append(
                    f"{_display_folder(directory)}: {' and '.join(sorted(group))} lockfiles"
                )

    # A lockfile whose manifest is missing. Only reliable if the file list is complete.
    if snapshot.can_confirm_absence:
        manifests_by_folder = {}
        for directory, name, _ in manifests:
            manifests_by_folder.setdefault(directory, set()).add(name)
        for directory, name, _ in lockfiles:
            present = manifests_by_folder.get(directory, set())
            if not any(needed in present for needed in LOCKFILE_NEEDS[name]):
                problems.append(f"{_display_folder(directory)}: {name} has no matching manifest")

    if problems:
        return Finding(
            status="failed",
            detail="The lockfiles are inconsistent. Mixing package managers in one folder "
                   "or keeping a lockfile without its manifest usually means a leftover file.",
            evidence=problems[:MAX_EVIDENCE_ITEMS],
            remediation="Use one package manager per folder, delete the other lockfile, "
                        "and keep each lockfile next to its manifest.",
            **base,
        )
    if not snapshot.can_confirm_absence:
        return Finding(
            status="not_assessed",
            detail="The file list is incomplete, so a lockfile without a manifest could "
                   "not be ruled out.",
            **base,
        )
    return Finding(
        status="passed",
        detail="Each lockfile sits next to its manifest, and no folder mixes package managers.",
        **base,
    )


def _check_pinning(snapshot):
    path = snapshot.find(["requirements.txt"])   # root only: one extra request at most
    if path is None:
        return None

    base = dict(
        id="deps.pinning", category=CATEGORY,
        title="requirements.txt pins exact versions",
        severity="low", kind="heuristic",
    )
    content = snapshot.read(path)
    if content is None:
        return Finding(
            status="not_assessed", confidence="low",
            detail="requirements.txt could not be read, so its versions were not inspected.",
            **base,
        )

    requirements = parse_requirements(content.text)
    if not requirements:
        return Finding(
            status="not_assessed", confidence="low",
            detail="No requirement lines were recognized in requirements.txt.", **base,
        )

    unpinned = [name for name, pinned in requirements if not pinned]
    if unpinned:
        return Finding(
            status="failed", confidence="low",
            detail=f"{len(unpinned)} of {len(requirements)} listed requirement(s) are not "
                   "pinned to an exact version (==). Libraries often use ranges on purpose.",
            evidence=[clean_for_display(name) for name in _unique(unpinned)[:MAX_EVIDENCE_ITEMS]],
            remediation="For applications, pin exact versions (for example with pip-compile "
                        "or a lockfile) so builds are reproducible.",
            **base,
        )
    if content.truncated:
        return Finding(
            status="not_assessed", confidence="low",
            detail="requirements.txt is too large to read completely, so the remaining "
                   "lines were not inspected.",
            **base,
        )
    return Finding(
        status="passed", confidence="medium",
        detail=f"All {len(requirements)} listed requirement(s) are pinned to an exact version.",
        **base,
    )


def _check_automation(snapshot, manifests):
    if not manifests:
        return None

    base = dict(
        id="deps.automation", category=CATEGORY,
        title="Dependency update automation is configured",
        severity="low", kind="heuristic", confidence="medium",
    )
    path = snapshot.find(AUTOMATION_FILES)
    if path:
        return Finding(
            status="passed",
            detail="A Dependabot or Renovate configuration was found.",
            evidence=[clean_for_display(path)], **base,
        )
    if snapshot.can_confirm_absence:
        return Finding(
            status="failed",
            detail="No Dependabot or Renovate configuration file was found. Security alerts "
                   "may still be enabled in the repository settings, which RepoHealth "
                   "cannot see.",
            remediation="Add .github/dependabot.yml so dependency updates are proposed "
                        "automatically.",
            **base,
        )
    return Finding(status="not_assessed", detail=_UNKNOWN, **base)


def _check_advisories():
    """Always 'not assessed': this version does not look up vulnerabilities."""
    return Finding(
        id="deps.advisories", category=CATEGORY, title="Known vulnerability lookup",
        status="not_assessed", severity="high", kind="objective", confidence="high",
        detail="Vulnerability advisory lookup is not part of this version, so no dependency "
               "was checked for known vulnerabilities. This says nothing about whether "
               "vulnerabilities exist.",
        remediation="Check your dependencies yourself with a tool such as pip-audit "
                    "(Python) or npm audit (JavaScript), and enable Dependabot alerts in "
                    "the repository settings.",
    )


# ---------- Entry point ----------

def run_dependency_checks(snapshot):
    """Run every dependency check that applies and return a list of Findings."""
    manifests, lockfiles = scan_dependency_files(snapshot)

    findings = [_check_manifest(snapshot, manifests)]
    for optional in (
        _check_lockfile_present(snapshot, manifests, lockfiles),
        _check_lockfile_consistency(snapshot, manifests, lockfiles),
        _check_pinning(snapshot),
        _check_automation(snapshot, manifests),
    ):
        if optional is not None:
            findings.append(optional)
    findings.append(_check_advisories())
    return findings
