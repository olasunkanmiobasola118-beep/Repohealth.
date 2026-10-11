"""Tests for fetch_repo_tree and fetch_file_text in scanner/github_client.py.

No network access: requests.get is replaced with a fake. The small helpers
below are repeated from test_github_client.py so each test file stands alone.
"""

import json

import pytest

from scanner import github_client
from scanner.github_client import GitHubError, fetch_file_text, fetch_repo_tree


class FakeResponse:
    def __init__(self, status_code=200, body=b"", headers=None):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}

    def iter_content(self, chunk_size=8192):
        for start in range(0, len(self._body), chunk_size):
            yield self._body[start:start + chunk_size]

    def close(self):
        pass


def json_response(payload, status_code=200):
    return FakeResponse(status_code, json.dumps(payload).encode())


def install_fake_get(monkeypatch, result):
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(github_client.requests, "get", fake_get)
    return calls


def tree_payload(entries, truncated=False):
    return {"sha": "abc", "tree": entries, "truncated": truncated}


# ---------- fetch_repo_tree ----------

def test_tree_returns_only_file_paths(monkeypatch):
    entries = [
        {"path": "README.md", "type": "blob"},
        {"path": "src", "type": "tree"},            # a folder
        {"path": "src/app.py", "type": "blob"},
        {"path": "vendor/lib", "type": "commit"},   # a submodule
    ]
    install_fake_get(monkeypatch, json_response(tree_payload(entries)))

    paths, truncated = fetch_repo_tree("octo", "demo", "main")

    assert paths == ["README.md", "src/app.py"]
    assert truncated is False


def test_tree_ignores_malformed_entries(monkeypatch):
    entries = [None, "text", {"type": "blob"}, {"path": 5, "type": "blob"},
               {"path": "ok.txt", "type": "blob"}]
    install_fake_get(monkeypatch, json_response(tree_payload(entries)))

    paths, _ = fetch_repo_tree("octo", "demo", "main")

    assert paths == ["ok.txt"]


def test_tree_reports_truncation_from_github(monkeypatch):
    install_fake_get(monkeypatch, json_response(tree_payload([], truncated=True)))
    _, truncated = fetch_repo_tree("octo", "demo", "main")
    assert truncated is True


def test_tree_applies_its_own_entry_cap(monkeypatch):
    monkeypatch.setattr(github_client, "MAX_TREE_ENTRIES", 2)
    entries = [{"path": f"f{i}.txt", "type": "blob"} for i in range(3)]
    install_fake_get(monkeypatch, json_response(tree_payload(entries)))

    paths, truncated = fetch_repo_tree("octo", "demo", "main")

    assert paths == ["f0.txt", "f1.txt"]
    assert truncated is True


def test_tree_exactly_at_the_cap_is_not_truncated(monkeypatch):
    monkeypatch.setattr(github_client, "MAX_TREE_ENTRIES", 2)
    entries = [{"path": f"f{i}.txt", "type": "blob"} for i in range(2)]
    install_fake_get(monkeypatch, json_response(tree_payload(entries)))

    paths, truncated = fetch_repo_tree("octo", "demo", "main")

    assert len(paths) == 2
    assert truncated is False


def test_tree_uses_fixed_endpoint_and_safe_options(monkeypatch):
    calls = install_fake_get(monkeypatch, json_response(tree_payload([])))

    fetch_repo_tree("octo", "demo", "main")

    url, kwargs = calls[0]
    assert url == "https://api.github.com/repos/octo/demo/git/trees/main?recursive=1"
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"] == github_client.REQUEST_TIMEOUT


def test_tree_branch_name_is_url_encoded(monkeypatch):
    calls = install_fake_get(monkeypatch, json_response(tree_payload([])))

    fetch_repo_tree("octo", "demo", "release/1.0")
    assert calls[0][0].endswith("/git/trees/release%2F1.0?recursive=1")

    fetch_repo_tree("octo", "demo", "x/../../etc")
    branch_part = calls[1][0].split("/git/trees/")[1].split("?")[0]
    assert "/" not in branch_part


@pytest.mark.parametrize("branch", [None, "", 5, "a" * 300])
def test_tree_rejects_unusable_branch_names(monkeypatch, branch):
    calls = install_fake_get(monkeypatch, json_response(tree_payload([])))
    with pytest.raises(GitHubError) as excinfo:
        fetch_repo_tree("octo", "demo", branch)
    assert excinfo.value.code == "bad_response"
    assert calls == []  # no request was made


@pytest.mark.parametrize(
    "status, code",
    [(404, "not_found"), (409, "empty_repository"), (429, "rate_limited"), (500, "github_error")],
)
def test_tree_error_statuses(monkeypatch, status, code):
    install_fake_get(monkeypatch, FakeResponse(status))
    with pytest.raises(GitHubError) as excinfo:
        fetch_repo_tree("octo", "demo", "main")
    assert excinfo.value.code == code


@pytest.mark.parametrize("body", [b"not json", b"[1, 2]", b'{"tree": "nope"}'])
def test_tree_bad_bodies(monkeypatch, body):
    install_fake_get(monkeypatch, FakeResponse(200, body))
    with pytest.raises(GitHubError) as excinfo:
        fetch_repo_tree("octo", "demo", "main")
    assert excinfo.value.code == "bad_response"


def test_tree_oversized_response(monkeypatch):
    monkeypatch.setattr(github_client, "MAX_TREE_BYTES", 10)
    install_fake_get(monkeypatch, FakeResponse(200, b"x" * 100))
    with pytest.raises(GitHubError) as excinfo:
        fetch_repo_tree("octo", "demo", "main")
    assert excinfo.value.code == "response_too_large"


# ---------- fetch_file_text ----------

def test_file_text_returns_text_and_asks_for_raw_content(monkeypatch):
    calls = install_fake_get(monkeypatch, FakeResponse(200, b"# Hello\n"))

    result = fetch_file_text("octo", "demo", "README.md")

    assert result == ("# Hello\n", False)
    url, kwargs = calls[0]
    assert url == "https://api.github.com/repos/octo/demo/contents/README.md"
    assert kwargs["headers"]["Accept"] == "application/vnd.github.raw+json"
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"] == github_client.REQUEST_TIMEOUT


def test_file_path_is_url_encoded(monkeypatch):
    calls = install_fake_get(monkeypatch, FakeResponse(200, b"x"))

    fetch_file_text("octo", "demo", "docs/My File.md")
    assert calls[0][0].endswith("/contents/docs/My%20File.md")

    fetch_file_text("octo", "demo", "a?b#c")
    assert calls[1][0].endswith("/contents/a%3Fb%23c")


def test_missing_file_returns_none(monkeypatch):
    install_fake_get(monkeypatch, FakeResponse(404))
    assert fetch_file_text("octo", "demo", "README.md") is None


def test_other_errors_are_raised(monkeypatch):
    install_fake_get(monkeypatch, FakeResponse(429))
    with pytest.raises(GitHubError) as excinfo:
        fetch_file_text("octo", "demo", "README.md")
    assert excinfo.value.code == "rate_limited"


def test_long_file_is_truncated(monkeypatch):
    install_fake_get(monkeypatch, FakeResponse(200, b"x" * 100))
    text, truncated = fetch_file_text("octo", "demo", "big.txt", max_bytes=10)
    assert text == "x" * 10
    assert truncated is True


def test_file_exactly_at_the_limit_is_not_truncated(monkeypatch):
    install_fake_get(monkeypatch, FakeResponse(200, b"x" * 10))
    text, truncated = fetch_file_text("octo", "demo", "big.txt", max_bytes=10)
    assert len(text) == 10
    assert truncated is False


def test_truncation_works_across_several_chunks(monkeypatch):
    install_fake_get(monkeypatch, FakeResponse(200, b"x" * 20000))
    text, truncated = fetch_file_text("octo", "demo", "big.txt", max_bytes=9000)
    assert len(text) == 9000
    assert truncated is True


def test_invalid_utf8_is_replaced_not_fatal(monkeypatch):
    install_fake_get(monkeypatch, FakeResponse(200, b"abc\xff\xfe"))
    text, truncated = fetch_file_text("octo", "demo", "odd.txt")
    assert text.startswith("abc")
    assert "\ufffd" in text
    assert truncated is False