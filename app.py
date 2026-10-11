"""RepoHealth - Flask application entry point."""

from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, request

from config import Config
from scanner.engine import analyze_repository
from scanner.github_client import GitHubError, fetch_repo_metadata, parse_repo_url


def error_response(code, message, status):
    """Every error from our API uses the same JSON shape."""
    return jsonify({"error": {"code": code, "message": message}}), status


def create_app():
    """Build and configure the Flask application."""
    app = Flask(__name__)
    app.config.from_object(Config)

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/health")
    def health():
        return jsonify({"status": "ok", "app": "RepoHealth", "version": "0.1.0"})

    @app.route("/api/scan", methods=["POST"])
    def scan():
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or "repo_url" not in data:
            return error_response(
                "invalid_request", "Send JSON with a repo_url field.", 400
            )

        try:
            owner, repo = parse_repo_url(data["repo_url"])
            metadata = fetch_repo_metadata(owner, repo)
            analysis = analyze_repository(owner, repo, metadata)
        except GitHubError as exc:
            return error_response(exc.code, exc.message, exc.status)
        except Exception:
            # Log details on the server, but never send them to the user.
            app.logger.exception("Unexpected error during scan")
            return error_response(
                "internal_error", "Something went wrong on our side.", 500
            )

        return jsonify(
            {
                "status": "ok",
                "scanned_at": datetime.now(timezone.utc).isoformat(),
                "repository": metadata,
                "findings": analysis["findings"],
                "warnings": analysis["warnings"],
                "file_list": analysis["file_list"],
            }
        )

    @app.errorhandler(413)
    def too_large(error):
        return error_response("request_too_large", "The request was too large.", 413)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)