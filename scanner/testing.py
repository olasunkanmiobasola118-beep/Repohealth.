"""Testing and CI/CD checks.

Pure functions: they receive a RepoSnapshot and return Findings. They use the
file list, plus at most MAX_WORKFLOWS_READ workflow files. They never run
anything: workflow files and documents are only read as text.

Test *configuration* files (pytest.ini, jest.config.js, ...) are shown as extra
evidence on the "tests exist" check, not scored on their own, because many
projects need none.

RepoHealth never reports a coverage percentage. It only notices whether
coverage tooling seems to be set up.
"""

import re

from scanner.contributions import CONTRIBUTING_CANDIDATES
from scanner.documentation import README_CANDIDATES, clean_for_display, extract_headings
from scanner.models import Finding

CATEGORY = "testing"

MAX_EVIDENCE_ITEMS = 3
MAX_WORKFLOWS_READ = 2        # each workflow file costs one GitHub request
MAX_WORKFLOW_LINES = 3000
MAX_DOC_LINES = 20000
MAX_COMMAND_LINE = 300        # skip longer lines: keeps the regexes fast

WORKFLOW_FOLDER = ".github/workflows"
WORKFLOW_EXTENSIONS = (".yml", ".yaml")

# Folders whose contents are tests. "spec" is not here because it often holds
# API specifications; spec files are recognized by name instead (_spec.rb, .spec.ts).
TEST_DIRECTORY_NAMES = {"tests", "test", "__tests__"}

# Folders that hold other people's code or build output. Tests in here are not ours.
IGNORED_DIRECTORIES = {
    "node_modules", "vendor", "third_party", "site-packages",
    ".venv", "venv", "dist", "build", "target",
}

_TEST_FILE = re.compile(
    r"test_.+\.py"
    r"|.+_test\.py"
    r"|tests?\.py"
    r"|.+\.(?:test|spec)\.(?:js|jsx|ts|tsx|mjs|cjs)"
    r"|.+_test\.(?:go|rs|rb|exs|dart|c|cc|cpp)"
    r"|.+_spec\.rb"
    r"|test_.+\.(?:rb|c|cc|cpp)"
    r"|.+Tests?\.(?:java|cs|kt|swift)"
    r"|.+Test\.php"
)

TEST_CONFIG_FILES = [
    "pytest.ini", "tox.ini", "noxfile.py", "conftest.py",
    "tests/conftest.py", "test/conftest.py", ".rspec",
    "phpunit.xml", "phpunit.xml.dist", "karma.conf.js",
    "jest.config.js", "jest.config.ts", "jest.config.mjs", "jest.config.cjs",
    "jest.config.json", "vitest.config.js", "vitest.config.ts", "vitest.config.mjs",
    ".mocharc.js", ".mocharc.json", ".mocharc.yml", ".mocharc.yaml",
    "playwright.config.js", "playwright.config.ts",
    "cypress.config.js", "cypress.config.ts",
]

COVERAGE_CONFIG_FILES = [
    ".coveragerc", "codecov.yml", ".codecov.yml", "codecov.yaml", ".codecov.yaml",
    "coveralls.yml", ".coveralls.yml", ".nycrc", ".nycrc.json", ".c8rc.json",
]

# (file, name of the CI system). Only the name is ever shown to the user.
OTHER_CI_FILES = [
    (".travis.yml", "Travis CI"),
    (".circleci/config.yml", "CircleCI"),
    ("azure-pipelines.yml", "Azure Pipelines"),
    (".gitlab-ci.yml", "GitLab CI"),
    ("jenkinsfile", "Jenkins"),
    ("appveyor.yml", "AppVeyor"),
    (".appveyor.yml", "AppVeyor"),
    ("bitbucket-pipelines.yml", "Bitbucket Pipelines"),
    (".drone.yml", "Drone CI"),
    (".buildkite/pipeline.yml", "Buildkite"),
]

TEST_COMMAND_PATTERN = re.compile(
    r"\b(?:python\d?\s+-m\s+(?:pytest|unittest)|pytest|py\.test|tox|nox"
    r"|(?:npm|yarn|pnpm|bun)\s+(?:run\s+)?test"
    r"|npx\s+(?:jest|vitest|mocha)|jest|vitest|mocha"
    r"|go\s+test|cargo\s+(?:test|nextest)"
    r"|dotnet\s+test|rspec|rake\s+test|phpunit|ctest"
    r"|make\s+(?:test|check)"
    r"|(?:mvnw?|gradlew?)\b.*\btest)\b",
    re.IGNORECASE,
)

COVERAGE_PATTERN = re.compile(
    r"--cov\b|\bcoverage\s+(?:run|report|xml|html)\b|\bcodecov\b|\bcoveralls\b"
    r"|--coverage\b|\bnyc\b|\bc8\b|\btarpaulin\b|llvm-cov|go\s+test\b.*-cover",
    re.IGNORECASE,
)

TEST_HEADING_PATTERN = re.compile(r"\b(?:tests?|testing)\b", re.IGNORECASE)

_RUN_KEY = re.compile(r"\s*(?:-\s+)?(?P<key>run):[ \t]*(?P<rest>.*)")


# ---------- Helpers ----------

def _unique(items):
    result = []
    for item in items:
        if item not in result:
            result.append(item)
    return result


def find_tests(snapshot):
    """Return (test_folders, test_files): where recognizable tests live."""
    folders_found = set()
    files_found = []

    for path in snapshot.paths:
        parts = path.split("/")
        folders, name = parts[:-1], parts[-1]
        lowered = [part.lower() for part in folders]

        if any(part in IGNORED_DIRECTORIES for part in lowered):
            continue

        for index, part in enumerate(lowered):
            if part in TEST_DIRECTORY_NAMES:
                folders_found.add("/".join(folders[: index + 1]) + "/")
                break

        if _TEST_FILE.fullmatch(name):
            files_found.append(path)

    return sorted(folders_found), files_found


def extract_run_commands(text):
    """Return the shell command lines from the `run:` steps of a workflow file.

    Handles single-line steps (run: pytest) and multi-line blocks (run: | ...).
    Comments, step names and `uses:` lines are ignored. This is not a full YAML
    parser, just enough to tell commands apart from labels.
    """
    commands = []
    block_indent = None   # column of the "run" key while inside a multi-line block

    for line in text.splitlines()[:MAX_WORKFLOW_LINES]:
        if len(line) > MAX_COMMAND_LINE:
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))

        if block_indent is not None:
            if indent > block_indent:
                commands.append(stripped)
                continue
            block_indent = None

        match = _RUN_KEY.match(line)
        if match:
            rest = match.group("rest").strip()
            if rest[:1] in ("|", ">"):
                block_indent = match.start("key")
            elif rest and not rest.startswith("#"):
                commands.append(rest)

    return commands


def _commands_in_lines(lines):
    found = []
    for line in lines:
        if len(line) > MAX_COMMAND_LINE:
            continue
        match = TEST_COMMAND_PATTERN.search(line)
        if match:
            found.append(" ".join(match.group(0).lower().split()))
    return _unique(found)


def find_test_commands_in_workflow(text):
    """Test commands that appear in the `run:` steps of a workflow file."""
    return _commands_in_lines(extract_run_commands(text))


def find_test_commands_in_docs(text):
    """Test commands mentioned anywhere in a document (including code blocks)."""
    return _commands_in_lines(text.splitlines()[:MAX_DOC_LINES])


def _mentions_coverage(text):
    for line in text.splitlines()[:MAX_WORKFLOW_LINES]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or len(stripped) > MAX_COMMAND_LINE:
            continue
        if COVERAGE_PATTERN.search(stripped):
            return True
    return False


def _pick_workflows(workflows):
    """Choose which workflow files to read: likely test workflows first."""
    def priority(path):
        name = path.rsplit("/", 1)[-1].lower()
        likely = any(word in name for word in ("test", "ci", "build", "check"))
        return (0 if likely else 1, name)

    return sorted(workflows, key=priority)[:MAX_WORKFLOWS_READ]


def _read_workflows(snapshot, workflows):
    """Read the chosen workflow files. Returns {"texts": [...], "complete": bool}.

    "complete" is True only if every workflow was read in full, so a missing
    test or coverage step can be trusted.
    """
    picked = _pick_workflows(workflows)
    texts = []
    unreadable = 0
    for path in picked:
        content = snapshot.read(path)
        if content is None:
            unreadable += 1
        else:
            texts.append(content)

    complete = (
        len(picked) == len(workflows)
        and unreadable == 0
        and not any(content.truncated for content in texts)
    )
    return {"texts": texts, "complete": complete}


_UNKNOWN = ("The repository's file list was unavailable or incomplete, "
            "so this could not be confirmed.")


# ---------- Individual checks ----------

def _check_tests_present(snapshot, test_folders, test_files):
    base = dict(
        id="testing.tests.present", category=CATEGORY, title="Automated tests exist",
        severity="high", kind="heuristic",
    )
    config = snapshot.find(TEST_CONFIG_FILES)

    if test_folders or test_files:
        evidence = [clean_for_display(folder) for folder in test_folders[:2]]
        remaining = MAX_EVIDENCE_ITEMS - len(evidence)
        evidence += [clean_for_display(path) for path in test_files[:remaining]]
        if config:
            evidence.append("Test configuration: " + clean_for_display(config))
        return Finding(
            status="passed", confidence="medium",
            detail="Test files or a test folder were found. RepoHealth does not "
                   "run them or judge their quality.",
            evidence=evidence, **base,
        )

    if config:
        return Finding(
            status="not_assessed", confidence="low",
            detail="A test configuration file was found, but no recognizable test "
                   "files. The tests may use unusual names or locations.",
            evidence=["Test configuration: " + clean_for_display(config)], **base,
        )

    if snapshot.can_confirm_absence:
        return Finding(
            status="failed", confidence="medium",
            detail="No test folder or test files with recognizable names were found. "
                   "Tests may exist under unusual names.",
            remediation="Add automated tests, for example in a tests/ folder, and "
                        "document how to run them.",
            **base,
        )

    return Finding(status="not_assessed", confidence="low", detail=_UNKNOWN, **base)


def _check_ci_present(snapshot, workflows, other_ci):
    base = dict(
        id="testing.ci.present", category=CATEGORY, title="Continuous integration is configured",
        severity="medium", kind="objective", confidence="high",
    )
    evidence = []
    if workflows:
        evidence.append(f"GitHub Actions: {len(workflows)} workflow file(s)")
    evidence += other_ci

    if evidence:
        return Finding(status="passed", detail="A CI configuration was found.",
                       evidence=evidence, **base)
    if snapshot.can_confirm_absence:
        return Finding(
            status="failed", detail="No CI configuration was found.",
            remediation="Add a GitHub Actions workflow in .github/workflows/ that "
                        "runs your tests on every push and pull request.",
            **base,
        )
    return Finding(status="not_assessed", detail=_UNKNOWN, **base)


def _check_ci_runs_tests(snapshot, workflows, other_ci, reading):
    base = dict(
        id="testing.ci.runs_tests", category=CATEGORY, title="CI workflow runs tests",
        severity="medium", kind="heuristic", confidence="medium",
    )
    remediation = ("Add a CI step that runs your test suite (for example pytest or "
                   "npm test) on every push and pull request.")

    if not workflows:
        if other_ci:
            return Finding(
                status="not_assessed",
                detail="CI is configured with " + ", ".join(other_ci) + ", but "
                       "RepoHealth only inspects GitHub Actions workflows for test steps.",
                **base,
            )
        if snapshot.can_confirm_absence:
            return Finding(
                status="failed",
                detail="No GitHub Actions workflow was found, so no automated test run "
                       "was detected.",
                remediation=remediation, **base,
            )
        return Finding(status="not_assessed", detail=_UNKNOWN, **base)

    commands = []
    for content in reading["texts"]:
        commands += find_test_commands_in_workflow(content.text)
    commands = _unique(commands)

    if commands:
        return Finding(
            status="passed",
            detail="A workflow step appears to run tests. RepoHealth does not run "
                   "workflows or check that they pass.",
            evidence=[clean_for_display(c) for c in commands[:MAX_EVIDENCE_ITEMS]],
            **base,
        )
    if not reading["complete"]:
        return Finding(
            status="not_assessed",
            detail="Not every workflow file could be read in full (RepoHealth reads at "
                   f"most {MAX_WORKFLOWS_READ}), so a missing test step could not be confirmed.",
            **base,
        )
    return Finding(
        status="failed",
        detail="No workflow step appears to run tests. Tests may be run in a way "
               "RepoHealth does not recognize.",
        remediation=remediation, **base,
    )


def _check_coverage(snapshot, reading):
    base = dict(
        id="testing.coverage", category=CATEGORY, title="Coverage configuration",
        severity="low", kind="heuristic",
    )
    config = snapshot.find(COVERAGE_CONFIG_FILES)

    if config:
        return Finding(
            status="passed", confidence="medium",
            detail="Coverage tooling appears to be configured. RepoHealth does not run "
                   "tests or measure coverage percentages.",
            evidence=[clean_for_display(config)], **base,
        )
    if any(_mentions_coverage(content.text) for content in reading["texts"]):
        return Finding(
            status="passed", confidence="medium",
            detail="A CI workflow appears to collect coverage. RepoHealth does not run "
                   "tests or measure coverage percentages.",
            evidence=["Coverage step in a CI workflow"], **base,
        )
    if snapshot.can_confirm_absence and reading["complete"]:
        return Finding(
            status="failed", confidence="low",
            detail="No coverage configuration or coverage step was recognized. Coverage "
                   "can also be configured in files RepoHealth does not inspect, such as "
                   "pyproject.toml or package.json.",
            remediation="Consider adding coverage reporting to your test run (for example "
                        "pytest-cov, or a Codecov or Coveralls step in CI) and document "
                        "how to view it.",
            **base,
        )
    return Finding(
        status="not_assessed", confidence="low",
        detail="The file list or the CI workflows were not fully inspected, so missing "
               "coverage settings could not be confirmed.",
        **base,
    )


def _check_testing_docs(snapshot, tests_found):
    base = dict(
        id="testing.docs", category=CATEGORY,
        title="Documentation explains how to run the tests",
        severity="low", kind="heuristic", confidence="low",
    )
    remediation = ("Add a 'Testing' section to the README or contributing guide that "
                   "shows the exact command to run the tests.")

    if not tests_found:
        return Finding(
            status="not_assessed",
            detail="No tests were detected, so there is nothing to document yet.",
            **base,
        )

    doc_paths = [
        path for path in (
            snapshot.find(README_CANDIDATES),
            snapshot.find(CONTRIBUTING_CANDIDATES),
        ) if path
    ]
    if not doc_paths:
        if snapshot.can_confirm_absence:
            return Finding(
                status="failed",
                detail="Tests exist, but there is neither a README nor a contributing "
                       "guide to explain how to run them.",
                remediation=remediation, **base,
            )
        return Finding(status="not_assessed", detail=_UNKNOWN, **base)

    evidence = []
    incomplete = False
    for path in doc_paths:
        content = snapshot.read(path)
        if content is None:
            incomplete = True
            continue
        if content.truncated:
            incomplete = True
        for heading in extract_headings(content.text):
            if TEST_HEADING_PATTERN.search(heading):
                evidence.append(clean_for_display(heading))
        evidence += [clean_for_display(c) for c in find_test_commands_in_docs(content.text)]

    evidence = _unique(evidence)
    if evidence:
        return Finding(
            status="passed",
            detail="The documentation has a heading or command that suggests how to run "
                   "the tests. RepoHealth does not judge how complete it is.",
            evidence=evidence[:MAX_EVIDENCE_ITEMS], **base,
        )
    if incomplete:
        return Finding(
            status="not_assessed",
            detail="The README or contributing guide could not be read in full, so a "
                   "missing testing section could not be confirmed.",
            **base,
        )
    return Finding(
        status="failed",
        detail="Neither the README nor the contributing guide has a testing heading or "
               "a recognizable test command. It may be described in plain text.",
        remediation=remediation, **base,
    )


# ---------- Entry point ----------

def run_testing_checks(snapshot):
    """Run every testing and CI check and return a list of Findings."""
    test_folders, test_files = find_tests(snapshot)
    tests_found = bool(test_folders or test_files)

    workflows = snapshot.list_in_folder(WORKFLOW_FOLDER, WORKFLOW_EXTENSIONS)
    other_ci = _unique(
        [name for path, name in OTHER_CI_FILES if snapshot.find([path])]
    )
    reading = _read_workflows(snapshot, workflows)

    return [
        _check_tests_present(snapshot, test_folders, test_files),
        _check_ci_present(snapshot, workflows, other_ci),
        _check_ci_runs_tests(snapshot, workflows, other_ci, reading),
        _check_coverage(snapshot, reading),
        _check_testing_docs(snapshot, tests_found),
    ]