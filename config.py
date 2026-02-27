import os

# Faceit Data API key (optional — app works without it)
FACEIT_API_KEY = os.environ.get("FACEIT_API_KEY", "")

# Server
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "5000"))
DEBUG = os.environ.get("DEBUG", "0") == "1"

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")

# Limits
MAX_UPLOAD_MB = 500
