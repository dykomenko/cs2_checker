"""
Simple file-hash based result cache.
Stores JSON analysis results keyed by MD5 of the .dem file.
Avoids re-parsing the same demo when uploaded/downloaded again.
"""
import os
import json
import hashlib
from config import CACHE_DIR

os.makedirs(CACHE_DIR, exist_ok=True)


def _file_md5(path: str) -> str:
    """Compute MD5 hex digest of a file (reads in 64KB chunks)."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _cache_path(md5: str) -> str:
    return os.path.join(CACHE_DIR, md5 + ".json")


def get_cached(demo_path: str) -> dict | None:
    """Return cached analysis result for this demo file, or None."""
    try:
        md5 = _file_md5(demo_path)
        cp = _cache_path(md5)
        if os.path.exists(cp):
            with open(cp, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return None


def put_cache(demo_path: str, result: dict) -> None:
    """Store analysis result in cache, keyed by file MD5."""
    try:
        md5 = _file_md5(demo_path)
        cp = _cache_path(md5)
        with open(cp, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
    except Exception:
        pass
