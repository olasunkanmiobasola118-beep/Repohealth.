"""RepoHealth - Flask application entry point."""

from flask import Flask, jsonify, render_template

from config import Config


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

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)