"""
Demo file sources — download from URL, Faceit API integration.
"""
import os
import hashlib
import requests
from config import DOWNLOAD_DIR


os.makedirs(DOWNLOAD_DIR, exist_ok=True)


# ── Direct URL download ───────────────────────────────────────────────────────

def download_demo(url: str) -> str:
    """Download a demo file from a direct URL. Returns local file path.
    Caches by URL — won't re-download if file already exists."""
    # Extract filename from URL
    filename = url.split("/")[-1].split("?")[0]
    if not filename.endswith((".dem", ".dem.zst", ".dem.gz")):
        filename = hashlib.md5(url.encode()).hexdigest() + ".dem.gz"

    dest = os.path.join(DOWNLOAD_DIR, filename)
    if os.path.exists(dest):
        return dest

    resp = requests.get(url, stream=True, timeout=300)
    resp.raise_for_status()

    # Write with temp name, rename on completion
    tmp = dest + ".tmp"
    with open(tmp, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            f.write(chunk)
    os.replace(tmp, dest)
    return dest


# ── Faceit API ─────────────────────────────────────────────────────────────────

FACEIT_API = "https://open.faceit.com/data/v4"


def _faceit_headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}"}


def faceit_get_player(nickname: str, api_key: str) -> dict:
    """Look up Faceit player by nickname."""
    resp = requests.get(
        f"{FACEIT_API}/players",
        params={"nickname": nickname, "game": "cs2"},
        headers=_faceit_headers(api_key),
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()

    cs2 = data.get("games", {}).get("cs2", {})
    return {
        "player_id": data["player_id"],
        "nickname": data["nickname"],
        "avatar": data.get("avatar", ""),
        "faceit_elo": cs2.get("faceit_elo", 0),
        "skill_level": cs2.get("skill_level", 0),
    }


def faceit_get_matches(player_id: str, api_key: str, limit: int = 20) -> list:
    """Get recent matches for a Faceit player."""
    resp = requests.get(
        f"{FACEIT_API}/players/{player_id}/history",
        params={"game": "cs2", "offset": 0, "limit": limit},
        headers=_faceit_headers(api_key),
        timeout=10,
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])

    matches = []
    for m in items:
        matches.append({
            "match_id": m["match_id"],
            "started_at": m.get("started_at", 0),
            "finished_at": m.get("finished_at", 0),
            "game_mode": m.get("game_mode", ""),
        })
    return matches


def faceit_get_match_detail(match_id: str, api_key: str) -> dict:
    """Get match details including demo_url."""
    resp = requests.get(
        f"{FACEIT_API}/matches/{match_id}",
        headers=_faceit_headers(api_key),
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()

    demo_url = data.get("demo_url", "")
    if isinstance(demo_url, list):
        demo_url = demo_url[0] if demo_url else ""

    # Map
    map_name = "unknown"
    voting = data.get("voting", {})
    if voting and "map" in voting:
        pick = voting["map"].get("pick", [])
        if isinstance(pick, list) and pick:
            map_name = pick[0]
        elif isinstance(pick, str):
            map_name = pick

    # Score
    results = data.get("results", {})
    score = ""
    if results:
        s = results.get("score", {})
        score = f"{s.get('faction1', '?')} - {s.get('faction2', '?')}"

    # Teams
    teams = {}
    for faction in ["faction1", "faction2"]:
        team_data = data.get("teams", {}).get(faction, {})
        team_name = team_data.get("name", faction)
        roster = []
        for p in team_data.get("roster", []):
            roster.append({
                "nickname": p.get("nickname", ""),
                "player_id": p.get("player_id", ""),
            })
        teams[faction] = {"name": team_name, "roster": roster}

    return {
        "match_id": match_id,
        "demo_url": demo_url,
        "map": map_name,
        "score": score,
        "finished_at": data.get("finished_at", 0),
        "teams": teams,
    }
