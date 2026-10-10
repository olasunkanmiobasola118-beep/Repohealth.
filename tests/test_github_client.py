"""Tests for scanner/github_client.py.

These tests never touch the internet. We replace requests.get with a fake
that returns responses we control.
"""

import json

import pytest
import requests

from scanner import github_client
from scanner.github_client import GitHubError, fetch_repo_metadata, parse_repo_url


# ---------- Test helpers ----------

class FakeResponse:
    """A tiny stand-in for the response object that requests returns."""

    def __init__(self, status_code=200, body=b"", headers=None):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}

    def iter_content(self, chunk_size=8192):
        for start in range(0, len(self._body), chunk_size):
            yield self._body[start:start + chunk_size]

    def close(self):
        pass


def json_response(payload, status_code=200, headers=None):
    return FakeResponse(status_code, json.dumps(payload).encode(), headers)


def install_fake_get(monkeypatch, result):
    """Replace requests.get with a fake.

    `result` is either a FakeResponse to return or an exception to raise.
    Returns a list that records every call as (url, keyword_arguments).
    """
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(github_client.requests, "get", fake_get)
    return calls


def get_error(monkeypatch, result):
    """Run fetch_repo_metadata and return the GitHubError it raises."""
    install_fake_get(monkeypatch, result)
    with pytest.raises(GitHubError) as excinfo:
        fetch_repo_metadata("octo", "demo")
    return excinfo.value


# Fictional data, shaped like GitHub's real response.
SAMPLE_REPO = {
    "full_name": "octo/demo",
    "description": "A demo repository",
    "html_url": "https://github.com/octo/demo",
    "stargazers_count": 42,
    "forks_count": 7,
    "open_issues_count": 3,
    "language": "Python",
    "default_branch": "main",
    "license": {"spdx_id": "MIT"},
    "archived": False,
    "fork": False,
    "private": False,
    "created_at": "2020-01-01T00:00:00Z",
    "updated_at": "2026-01-01T00:00:00Z",
    "pushed_at": "2026-01-02T00:00:00Z",
    # Fields we deliberately do NOT pass along:
    "node_id": "abc123",
    "owner": {"login": "octo", "email": "someone@example.com"},
}


# ---------- parse_repo_url ----------

@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://github.com/pallets/flask", ("pallets", "flask")),
        ("https://github.com/pallets/flask.git", ("pallets", "flask")),
        ("https://github.com/pallets/flask/", ("pallets", "flask")),
        ("https://www.github.com/pallets/flask", ("pallets", "flask")),
        ("  https://github.com/pallets/flask  ", ("pallets", "flask")),
        ("https://github.com/octo/my.repo_name-2", ("octo", "my.repo_name-2")),
    ],
)
def test_parse_repo_url_accepts_valid_urls(url, expected):
    assert parse_repo_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "",
        "github.com/pallets/flask",                    # no https://
        "http://github.com/pallets/flask",             # not https
        "https://gitlab.com/pallets/flask",            # wrong site
        "https://github.com.evil.com/pallets/flask",   # look-alike host
        "https://evil.com/github.com/pallets/flask",   # host hidden in path
        "https://user@github.com/pallets/flask",       # credentials in URL
        "https://github.com:8080/pallets/flask",       # port number
        "https://localhost/pallets/flask",
        "http://127.0.0.1:5000/admin",
        "https://github.com/pallets",                  # no repository
        "https://github.com/pallets/flask/issues",     # extra path
        "https://github.com/pallets/flask?tab=readme", # query string
        "https://github.com/pallets/..",               # path trick
        "https://github.com/pallets/.",
        "https://github.com/-bad/flask",               # owner starts with hyphen
        "https://github.com/pallets/flask%2F..%2Fx",   # encoded slashes
        "https://github.com/pallets/" + "a" * 300,     # too long
    ],
)
def test_parse_repo_url_rejects_bad_urls(url):
    with pytest.raises(GitHubError) as excinfo:
        parse_repo_url(url)
    assert excinfo.value.code == "invalid_url"
    assert excinfo.value.status == 400


@pytest.mark.parametrize("value", [None, 123, ["https://github.com/a/b"], {"a": 1}])
def test_parse_repo_url_rejects_non_text(value):
    with pytest.raises(GitHubError) as excinfo:
        parse_repo_url(value)
    assert excinfo.value.code == "invalid_url"


# ---------- fetch_repo_metadata: success ----------

def test_fetch_returns_only_selected_fields(monkeypatch):
    install_fake_get(monkeypatch, json_response(SAMPLE_REPO))

    result = fetch_repo_metadata("octo", "demo")

    assert result["full_name"] == "octo/demo"
    assert result["stars"] == 42
    assert result["forks"] == 7
    assert result["open_issues_and_prs"] == 3
    assert result["language"] == "Python"
    assert result["license"] == "MIT"
    assert result["pushed_at"] == "2026-01-02T00:00:00Z"
    # Extra GitHub fields must not leak through.
    assert "owner" not in result
    assert "node_id" not in result
    assert "private" not in result


def test_fetch_handles_missing_license_and_description(monkeypatch):
    payload = dict(SAMPLE_REPO, license=None, description=None)
    install_fake_get(monkeypatch, json_response(payload))

    result = fetch_repo_metadata("octo", "demo")

    assert result["license"] is None
    assert result["description"] is None


def test_fetch_uses_fixed_endpoint_and_safe_options(monkeypatch):
    calls = install_fake_get(monkeypatch, json_response(SAMPLE_REPO))

    fetch_repo_metadata("octo", "demo")

    url, kwargs = calls[0]
    assert url == "https://api.github.com/repos/octo/demo"
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"] == github_client.REQUEST_TIMEOUT


# ---------- fetch_repo_metadata: failures ----------

def test_fetch_404_is_not_found(monkeypatch):
    error = get_error(monkeypatch, FakeResponse(404))
    assert error.code == "not_found"
    assert error.status == 404


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_fetch_redirect_is_reported_not_followed(monkeypatch, status):
    error = get_error(monkeypatch, FakeResponse(status))
    assert error.code == "repo_moved"


def test_fetch_403_with_no_requests_left_is_rate_limited(monkeypatch):
    response = FakeResponse(
        403,
        headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1760000000"},
    )
    error = get_error(monkeypatch, response)
    assert error.code == "rate_limited"
    assert error.status == 429
    assert "UTC" in error.message


def test_fetch_429_is_rate_limited_even_without_headers(monkeypatch):
    error = get_error(monkeypatch, FakeResponse(429))
    assert error.code == "rate_limited"
    assert "try again later" in error.message.lower()


def test_fetch_403_for_another_reason_is_not_called_rate_limit(monkeypatch):
    error = get_error(monkeypatch, FakeResponse(403, headers={"X-RateLimit-Remaining": "50"}))
    assert error.code == "github_error"
    assert error.status == 502


def test_fetch_server_error_becomes_github_error(monkeypatch):
    error = get_error(monkeypatch, FakeResponse(500))
    assert error.code == "github_error"
    assert error.status == 502


def test_fetch_timeout(monkeypatch):
    error = get_error(monkeypatch, requests.Timeout())
    assert error.code == "timeout"
    assert error.status == 504


def test_fetch_network_failure(monkeypatch):
    error = get_error(monkeypatch, requests.ConnectionError())
    assert error.code == "network_error"
    assert error.status == 502


def test_fetch_invalid_json(monkeypatch):
    error = get_error(monkeypatch, FakeResponse(200, b"this is not json"))
    assert error.code == "bad_response"


def test_fetch_json_that_is_not_an_object(monkeypatch):
    error = get_error(monkeypatch, json_response([1, 2, 3]))
    assert error.code == "bad_response"


def test_fetch_rejects_private_repository(monkeypatch):
    error = get_error(monkeypatch, json_response(dict(SAMPLE_REPO, private=True)))
    assert error.code == "not_public"
    assert error.status == 403


def test_fetch_rejects_oversized_response(monkeypatch):
    monkeypatch.setattr(github_client, "MAX_RESPONSE_BYTES", 10)
    error = get_error(monkeypatch, FakeResponse(200, b"x" * 100))
    assert error.code == "response_too_large"