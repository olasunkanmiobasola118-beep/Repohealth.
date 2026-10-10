"""Shared data structures for the scanner.

Finding      - the result of one check (passed, failed, or not assessed)
RepoSnapshot - what we know about a repository: its metadata, its file list,
               and a safe, limited way to read a few files.

Nothing in this file touches the network.
"""

from dataclasses import asdict, dataclass, field

STATUSES = ("passed", "failed", "not_assessed")
SEVERITIES = ("low", "medium", "high")      # how serious it is if the check fails
KINDS = ("objective", "heuristic")          # AI output never uses this class
CONFIDENCES = ("low", "medium", "high")

# Used by the scoring system in Stage 5.
SEVERITY_WEIGHTS = {"low": 1, "medium": 2, "high": 3}

# Protects GitHub's anonymous rate limit (about 60 requests per hour).
MAX_FILE_READS = 8


@dataclass
class Finding:
    id: str                  # stable name, e.g. "docs.readme.present"
    category: str            # e.g. "documentation"
    title: str               # short name of the check
    status: str              # passed / failed / not_assessed
    severity: str            # importance if this check fails
    kind: str                # objective or heuristic
    confidence: str          # how much to trust this result
    detail: str = ""         # one sentence explaining the result
    evidence: list = field(default_factory=list)  # short, safe strings
    remediation: str = ""    # how to fix it (empty when the check passed)

    def __post_init__(self):
        # Catch typos early: a misspelled status would silently break scoring.
        for name, allowed in (
            ("status", STATUSES),
            ("severity", SEVERITIES),
            ("kind", KINDS),
            ("confidence", CONFIDENCES),
        ):
            if getattr(self, name) not in allowed:
                raise ValueError(f"Invalid {name}: {getattr(self, name)!r}")

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class FileText:
    text: str
    truncated: bool = False   # True if the file was longer than we read


class RepoSnapshot:
    """What the checks are allowed to know about a repository.

    metadata  - the dict from fetch_repo_metadata
    files     - list of file paths from GitHub, or None if the list is unavailable
    truncated - True if the file list is known to be incomplete
    reader    - a function path -> (text, truncated), or None if the file is
                missing. It must never raise; the code that builds the snapshot
                handles errors.
    """

    def __init__(self, metadata, files=None, truncated=False, reader=None,
                 max_reads=MAX_FILE_READS):
        self.metadata = metadata or {}
        self.tree_available = files is not None
        self.truncated = truncated
        self._paths = {path.lower(): path for path in (files or [])}
        self._reader = reader
        self._max_reads = max_reads
        self._reads = 0
        self._cache = {}

    @property
    def can_confirm_absence(self):
        """True only if the file list is complete, so 'not found' means missing."""
        return self.tree_available and not self.truncated

    def find(self, candidates):
        """Return the real path of the first matching file, or None.

        Matching ignores upper/lower case. Candidates must be full paths such as
        "readme.md" or ".github/readme.md", so nested files like "src/README.md"
        do not match.
        """
        for candidate in candidates:
            actual = self._paths.get(candidate.lower())
            if actual is not None:
                return actual
        return None

    def read(self, path):
        """Read a file (cached, and limited in number). Returns FileText or None."""
        if path in self._cache:
            return self._cache[path]
        if self._reader is None or self._reads >= self._max_reads:
            return None
        self._reads += 1
        result = self._reader(path)
        content = None if result is None else FileText(result[0], result[1])
        self._cache[path] = content
        return content