"""
CS2 Anti-Cheat Checker — lightweight Flask server.
Single process, no Node.js, no build step.
"""
import os
import traceback

from flask import Flask, request, jsonify, render_template

from config import FACEIT_API_KEY, HOST, PORT, DEBUG, UPLOAD_DIR, DOWNLOAD_DIR, MAX_UPLOAD_MB
from analyzer import parse_demo_anticheat
from sources import (download_demo, decode_sharecode, sharecode_info,
                     faceit_get_player, faceit_get_matches, faceit_get_match_detail)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


# ── Pages ──────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html", has_faceit=bool(FACEIT_API_KEY))


# ── Analysis API ───────────────────────────────────────────────────────────────

@app.route("/api/analyze", methods=["POST"])
def analyze_upload():
    """Upload and analyze a .dem/.dem.zst/.dem.gz file."""
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "No file provided"}), 400
    if not any(f.filename.endswith(ext) for ext in (".dem", ".dem.zst", ".dem.gz")):
        return jsonify({"error": "File must be .dem, .dem.zst or .dem.gz"}), 400

    dest = os.path.join(UPLOAD_DIR, f.filename)
    f.save(dest)

    try:
        result = parse_demo_anticheat(dest)
        return jsonify(result)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Analysis failed: {e}"}), 500


@app.route("/api/analyze-url", methods=["POST"])
def analyze_url():
    """Download demo from URL and analyze."""
    data = request.get_json(silent=True) or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    try:
        local_path = download_demo(url)
        result = parse_demo_anticheat(local_path)
        return jsonify(result)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Failed: {e}"}), 500


@app.route("/api/decode-sharecode", methods=["POST"])
def api_decode_sharecode():
    """Decode a Steam share code and return match info.

    CS2 MM demos require the Steam Game Coordinator to download —
    we can decode the share code but not fetch the demo directly.
    """
    data = request.get_json(silent=True) or {}
    sharecode = data.get("sharecode", "").strip()
    if not sharecode:
        return jsonify({"error": "No share code provided"}), 400

    try:
        matchid, outcomeid, token = decode_sharecode(sharecode)
    except Exception as e:
        return jsonify({"error": f"Invalid share code: {e}"}), 400

    info = sharecode_info(matchid, outcomeid, token)
    return jsonify(info)


# ── Faceit API ─────────────────────────────────────────────────────────────────

@app.route("/api/faceit/player")
def api_faceit_player():
    """Search Faceit player by nickname."""
    if not FACEIT_API_KEY:
        return jsonify({"error": "Faceit API key not configured"}), 503
    nickname = request.args.get("nickname", "").strip()
    if not nickname:
        return jsonify({"error": "Nickname required"}), 400
    try:
        player = faceit_get_player(nickname, FACEIT_API_KEY)
        return jsonify(player)
    except Exception as e:
        return jsonify({"error": f"Faceit lookup failed: {e}"}), 500


@app.route("/api/faceit/matches")
def api_faceit_matches():
    """Get recent matches for a Faceit player."""
    if not FACEIT_API_KEY:
        return jsonify({"error": "Faceit API key not configured"}), 503
    player_id = request.args.get("player_id", "").strip()
    if not player_id:
        return jsonify({"error": "player_id required"}), 400
    try:
        matches = faceit_get_matches(player_id, FACEIT_API_KEY)
        # Enrich each match with demo_url, map, score
        enriched = []
        for m in matches:
            try:
                detail = faceit_get_match_detail(m["match_id"], FACEIT_API_KEY)
                m["demo_url"] = detail["demo_url"]
                m["map"] = detail["map"]
                m["score"] = detail["score"]
                m["teams"] = detail["teams"]
                enriched.append(m)
            except Exception:
                m["demo_url"] = ""
                m["map"] = "?"
                m["score"] = "?"
                enriched.append(m)
        return jsonify({"matches": enriched})
    except Exception as e:
        return jsonify({"error": f"Faceit matches failed: {e}"}), 500


@app.route("/api/faceit/analyze", methods=["POST"])
def api_faceit_analyze():
    """Download and analyze a Faceit match demo."""
    data = request.get_json(silent=True) or {}
    demo_url = data.get("demo_url", "").strip()
    if not demo_url:
        return jsonify({"error": "demo_url required"}), 400
    try:
        local_path = download_demo(demo_url)
        result = parse_demo_anticheat(local_path)
        return jsonify(result)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Analysis failed: {e}"}), 500


# ── Run ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\n  CS2 Anti-Cheat Checker")
    print(f"  http://{HOST}:{PORT}")
    print(f"  Faceit: {'enabled' if FACEIT_API_KEY else 'disabled (set FACEIT_API_KEY)'}\n")
    app.run(host=HOST, port=PORT, debug=DEBUG)
