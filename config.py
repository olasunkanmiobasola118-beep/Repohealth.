"""Application configuration, loaded from environment variables."""

import os

from dotenv import load_dotenv

# Read variables from the .env file (if it exists) into the environment.
load_dotenv()


class Config:
    # Debug mode is OFF unless explicitly turned on.
    DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"

    # Listen only on this computer by default.
    HOST = os.getenv("HOST", "127.0.0.1")
    PORT = int(os.getenv("PORT", "5000"))

    # Reject request bodies larger than 4 KB. Scan requests are tiny.
    MAX_CONTENT_LENGTH = 4 * 1024