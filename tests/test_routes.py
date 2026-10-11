"""Tests for the Flask routes in app.py.

GitHub is never contacted: we replace the network-using functions with fakes.
"""

import pytest

import app as app_module
from scanner.github_client import GitHubError

FAKE_ANALYSIS = {
    "findings": [{"id": "docs.readme.present", "status": "passed"}],
    "warnings": ["a note"],
    "file_list": {"available": True, "complete": True},
}


@pytest.fixture
def client():
    flask_app = app_module.create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


# ---------- Basic pages ----------

def test_home_page_loads(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"RepoHealth" in response.data


def test_health_endpoint(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_scan_rejects_get_requests(client):
    response = client.get("/api/scan")
    assert response.status_code == 405


# ---------- /api/scan: success ----------

def test_scan_success_returns_metadata_and_findings(client, monkeypatch):
    fetch_calls = []
    analyze_calls = []

    def fake_fetch(owner, repo):
        fetch_calls.append((owner, repo))
        return {"full_name": f"{owner}/{repo}", "default_branch": "main"}

    def fake_analyze(owner, repo, metadata):
        analyze_calls.append((owner, repo, metadata))
        return FAKE_ANALYSIS

    monkeypatch.setattr(app_module, "fetch_repo_metadata", fake_fetch)
    monkeypatch.setattr(app_module, "analyze_repository", fake_analyze)

    response = client.post(
        "/api/scan", json={"repo_url": "https://github.com/pallets/flask.git"}
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "ok"
    assert "scanned_at" in body
    assert body["repository"]["full_name"] == "pallets/flask"
    assert body["findings"] == FAKE_ANALYSIS["findings"]
    assert body["warnings"] == ["a note"]
    assert body["file_list"] == {"available": True, "complete": True}
    # The route passed the parsed names, not the raw URL.
    assert fetch_calls == [("pallets", "flask")]
    assert analyze_calls[0][:2] == ("pallets", "flask")


# ---------- /api/scan: bad input ----------

def test_scan_invalid_url_never_reaches_github(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        app_module, "fetch_repo_metadata", lambda owner, repo: calls.append((owner, repo))
    )

    response = client.post("/api/scan", json={"repo_url": "http://localhost:5000/admin"})

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_url"
    assert calls == []  # GitHub was never called


@pytest.mark.parametrize(
    "kwargs",
    [
        {"json": {"something_else": 1}},                       # missing repo_url
        {"json": ["https://github.com/a/b"]},                  # JSON, but not an object
        {"data": "not json", "content_type": "text/plain"},    # wrong content type
        {"data": "{bad json", "content_type": "application/json"},
    ],
)
def test_scan_rejects_malformed_requests(client, kwargs):
    response = client.post("/api/scan", **kwargs)
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_request"


def test_scan_rejects_oversized_request_body(client):
    big_body = '{"repo_url": "' + "a" * 5000 + '"}'
    response = client.post("/api/scan", data=big_body, content_type="application/json")
    assert response.status_code == 413
    assert response.get_json()["error"]["code"] == "request_too_large"


# ---------- /api/scan: error handling ----------

def test_scan_maps_github_errors_to_json(client, monkeypatch):
    def fake_fetch(owner, repo):
        raise GitHubError("not_found", "Repository not found.", 404)

    monkeypatch.setattr(app_module, "fetch_repo_metadata", fake_fetch)

    response = client.post("/api/scan", json={"repo_url": "https://github.com/a/b"})

    assert response.status_code == 404
    assert response.get_json() == {
        "error": {"code": "not_found", "message": "Repository not found."}
    }


def test_analysis_is_skipped_when_the_repository_is_not_found(client, monkeypatch):
    analyze_calls = []

    def fake_fetch(owner, repo):
        raise GitHubError("not_found", "Repository not found.", 404)

    monkeypatch.setattr(app_module, "fetch_repo_metadata", fake_fetch)
    monkeypatch.setattr(
        app_module, "analyze_repository", lambda *args: analyze_calls.append(args)
    )

    client.post("/api/scan", json={"repo_url": "https://github.com/a/b"})

    assert analyze_calls == []


def test_scan_hides_details_of_unexpected_errors(client, monkeypatch):
    monkeypatch.setattr(app_module, "fetch_repo_metadata", lambda owner, repo: {})

    def fake_analyze(owner, repo, metadata):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(app_module, "analyze_repository", fake_analyze)

    response = client.post("/api/scan", json={"repo_url": "https://github.com/a/b"})

    assert response.status_code == 500
    assert response.get_json()["error"]["code"] == "internal_error"
    assert "secret internal detail" not in response.get_data(as_text=True)