"""Read-only client for GitHub's public REST API.

Safety rules for this module:
- We never request the URL the user typed. We only extract the owner and
  repository name, then build requests to the fixed host api.github.com.
- Redirects are not followed.
- Every request has a timeout, and every response has a size limit.
- Nothing downloaded from a repository is ever executed.
"""

import json
import re
from datetime import datetime, timezone
from urllib.parse import quote

import requests

GITHUB_API = "https://api.github.com"
REQUEST_TIMEOUT = 10             # seconds
MAX_RESPONSE_BYTES = 1_000_000   # 1 MB for ordinary API responses
MAX_TREE_BYTES = 5_000_000       # 5 MB for the file list of a large repository
MAX_TREE_ENTRIES = 20_000        # keep at most this many file paths
MAX_FILE_BYTES = 200_000         # read at most this much of any one file
MAX_URL_LENGTH = 200
MAX_BRANCH_LENGTH = 250

JSON_ACCEPT = "application/vnd.github+json"
RAW_ACCEPT = "application/vnd.github.raw+json"   # file contents as plain text

# https://github.com/owner/repo  (optional ".git" and optional trailing "/")
REPO_URL_PATTERN = re.compile(
    r"https://(?:www\.)?github\.com/"
    r"([A-Za-z0-9][A-Za-z0-9-]{0,38})/"
    r"([A-Za-z0-9._-]{1,100}?)(?:\.git)?/?"
)


class GitHubError(Exception):
    """An expected problem, carrying a safe message for the user."""

    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code = code        # short machine-readable name, e.g. "not_found"
        self.message = message  # text that is safe to show to the user
        self.status = status    # HTTP status our API will return


def parse_repo_url(raw_url):
    """Validate a repository URL and return (owner, repo)."""
    if not isinstance(raw_url, str):
        raise GitHubError("invalid_url", "repo_url must be text.")

    value = raw_url.strip()
    if len(value) > MAX_URL_LENGTH:
        raise GitHubError("invalid_url", "That URL is too long.")

    match = REPO_URL_PATTERN.fullmatch(value)
    if not match:
        raise GitHubError(
            "invalid_url",
            "Enter a public repository URL like https://github.com/owner/repository",
        )

    owner, repo = match.group(1), match.group(2)
    if repo in (".", ".."):
        raise GitHubError("invalid_url", "That repository name is not valid.")

    return owner, repo


# ---------- Shared request helpers ----------

def _read_limited(response, limit=None):
    """Read the response body, stopping if it grows past the size limit."""
    max_bytes = MAX_RESPONSE_BYTES if limit is None else limit
    chunks = []
    total = 0
    for chunk in response.iter_content(chunk_size=8192):
        total += len(chunk)
        if total > max_bytes:
            response.close()
            raise GitHubError(
                "response_too_large", "GitHub's response was too large to process.", 502
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _rate_limit_message(response):
    message = "GitHub's rate limit for anonymous requests has been reached."
    reset = response.headers.get("X-RateLimit-Reset", "")
    if reset.isdigit():
        when = datetime.fromtimestamp(int(reset), tz=timezone.utc).strftime("%H:%M UTC")
        return f"{message} Try again after {when}."
    return f"{message} Please try again later."


def _error_for_status(response):
    """Return a GitHubError for a non-success response, or None if it is fine."""
    status = response.status_code

    if status == 200:
        return None
    if status == 404:
        return GitHubError(
            "not_found",
            "Repository not found. It may not exist, or it may be private.",
            404,
        )
    if status in (301, 302, 307, 308):
        return GitHubError(
            "repo_moved",
            "This repository has been moved or renamed. Use its current URL.",
            404,
        )
    if status == 429 or (status == 403 and response.headers.get("X-RateLimit-Remaining") == "0"):
        return GitHubError("rate_limited", _rate_limit_message(response), 429)
    if status == 409:
        # GitHub answers 409 for the file list of a repository with no commits.
        return GitHubError("empty_repository", "This repository is empty.", 422)
    return GitHubError(
        "github_error", f"GitHub returned an unexpected response ({status}).", 502
    )


def _request(url, accept=JSON_ACCEPT):
    """GET a URL on api.github.com and return the response if it succeeded."""
    headers = {
        "Accept": accept,
        "User-Agent": "RepoHealth/0.1",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=False,
            stream=True,
        )
    except requests.Timeout:
        raise GitHubError("timeout", "GitHub took too long to respond. Please try again.", 504)
    except requests.RequestException:
        raise GitHubError("network_error", "Could not reach GitHub. Please try again.", 502)

    error = _error_for_status(response)
    if error is not None:
        response.close()
        raise error
    return response


def _parse_json_object(body):
    try:
        data = json.loads(body)
    except ValueError:
        raise GitHubError("bad_response", "GitHub returned data we could not read.", 502)
    if not isinstance(data, dict):
        raise GitHubError("bad_response", "GitHub returned data we could not read.", 502)
    return data


# ---------- Public functions ----------

def fetch_repo_metadata(owner, repo):
    """Fetch public metadata for one repository. Raises GitHubError on problems."""
    response = _request(f"{GITHUB_API}/repos/{owner}/{repo}")
    data = _parse_json_object(_read_limited(response))

    if data.get("private"):
        raise GitHubError("not_public", "Only public repositories can be analyzed.", 403)

    # Keep only the fields we need, never the whole GitHub response.
    return {
        "full_name": data.get("full_name"),
        "description": data.get("description"),
        "html_url": data.get("html_url"),
        "stars": data.get("stargazers_count"),
        "forks": data.get("forks_count"),
        # GitHub's count includes open pull requests, so we name it honestly.
        "open_issues_and_prs": data.get("open_issues_count"),
        "language": data.get("language"),
        "default_branch": data.get("default_branch"),
        "license": (data.get("license") or {}).get("spdx_id"),
        "archived": data.get("archived"),
        "is_fork": data.get("fork"),
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
        "pushed_at": data.get("pushed_at"),  # time of the last push of code
    }


def fetch_repo_tree(owner, repo, branch):
    """Fetch the list of file paths on a branch.

    Returns (paths, truncated). `truncated` is True if the list is known to be
    incomplete, either because GitHub cut it off or because we hit our own cap.
    Only files are returned, not folders or submodules.
    """
    if not isinstance(branch, str) or not branch or len(branch) > MAX_BRANCH_LENGTH:
        raise GitHubError("bad_response", "The default branch name was not usable.", 502)

    # The branch name comes from the repository, so it is URL-encoded
    # (a "/" becomes %2F) and cannot change which endpoint we call.
    url = (
        f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/"
        f"{quote(branch, safe='')}?recursive=1"
    )
    response = _request(url)
    data = _parse_json_object(_read_limited(response, MAX_TREE_BYTES))

    entries = data.get("tree")
    if not isinstance(entries, list):
        raise GitHubError("bad_response", "GitHub returned data we could not read.", 502)

    truncated = bool(data.get("truncated"))
    paths = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("type") != "blob":
            continue
        path = entry.get("path")
        if not isinstance(path, str):
            continue
        if len(paths) >= MAX_TREE_ENTRIES:
            truncated = True
            break
        paths.append(path)

    return paths, truncated


def fetch_file_text(owner, repo, path, max_bytes=None):
    """Read one file as text.

    Returns (text, truncated), or None if the file does not exist. Reads at most
    `max_bytes` (default MAX_FILE_BYTES); `truncated` is True if the file was longer.
    The file is only downloaded as text and is never executed.
    """
    limit = MAX_FILE_BYTES if max_bytes is None else max_bytes
    url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{quote(path, safe='/')}"

    try:
        response = _request(url, accept=RAW_ACCEPT)
    except GitHubError as error:
        if error.code == "not_found":
            return None
        raise

    chunks = []
    total = 0
    truncated = False
    for chunk in response.iter_content(chunk_size=8192):
        remaining = limit - total
        if len(chunk) > remaining:
            chunks.append(chunk[:remaining])
            truncated = True
            break
        chunks.append(chunk)
        total += len(chunk)
    response.close()

    text = b"".join(chunks).decode("utf-8", errors="replace")
    return text, truncated