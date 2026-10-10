"""Read-only client for GitHub's public REST API.

Safety rules for this module:
- We never request the URL the user typed. We only extract the owner and
  repository name, then build a request to the fixed host api.github.com.
- Redirects are not followed.
- Every request has a timeout, and the response size is limited.
"""

import json
import re
from datetime import datetime, timezone

import requests

GITHUB_API = "https://api.github.com"
REQUEST_TIMEOUT = 10             # seconds
MAX_RESPONSE_BYTES = 1_000_000   # 1 MB
MAX_URL_LENGTH = 200

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


def _read_limited(response):
    """Read the response body, stopping if it grows past the size limit."""
    chunks = []
    total = 0
    for chunk in response.iter_content(chunk_size=8192):
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
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


def fetch_repo_metadata(owner, repo):
    """Fetch public metadata for one repository. Raises GitHubError on problems."""
    url = f"{GITHUB_API}/repos/{owner}/{repo}"
    headers = {
        "Accept": "application/vnd.github+json",
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

    status = response.status_code

    if status == 404:
        raise GitHubError(
            "not_found",
            "Repository not found. It may not exist, or it may be private.",
            404,
        )
    if status in (301, 302, 307, 308):
        raise GitHubError(
            "repo_moved",
            "This repository has been moved or renamed. Use its current URL.",
            404,
        )
    if status == 429 or (status == 403 and response.headers.get("X-RateLimit-Remaining") == "0"):
        raise GitHubError("rate_limited", _rate_limit_message(response), 429)
    if status != 200:
        raise GitHubError(
            "github_error", f"GitHub returned an unexpected response ({status}).", 502
        )

    body = _read_limited(response)
    try:
        data = json.loads(body)
    except ValueError:
        raise GitHubError("bad_response", "GitHub returned data we could not read.", 502)

    if not isinstance(data, dict):
        raise GitHubError("bad_response", "GitHub returned data we could not read.", 502)
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