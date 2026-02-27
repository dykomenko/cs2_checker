# CS2 Anti-Cheat Checker

> **[RU]** Веб-инструмент для анализа CS2 демо-файлов на подозрительную активность.
> Загрузи демо — получи оценку подозрительности по каждому игроку.

Lightweight web tool for analyzing CS2 demo files for suspicious activity.
Upload a demo — get a suspicion score for every player.

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![Flask](https://img.shields.io/badge/Flask-3.0-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

---

## Features

- **File upload** — drag & drop `.dem` / `.dem.zst` / `.dem.gz`
- **URL analysis** — paste a direct demo link (Faceit, Leetify, etc.)
- **Faceit integration** — search player by nickname, browse matches, one-click analyze
- **Steam share code** — decode `CSGO-xxxxx` codes with download instructions
- **FOV-based reaction time** — sight-to-fire, sight-to-damage (the key anti-cheat metric)
- **Pre-aim filtering** — holding angles excluded from reaction metrics to reduce false positives
- **Suspicion scoring** — composite 0-100 score per player
- **Result caching** — MD5-based cache, re-uploading the same demo returns results instantly
- **Bilingual UI** — English / Russian with one-click toggle

### Metrics analyzed

| Metric | Description |
|--------|-------------|
| FOV Sight→Fire | Time from enemy entering 80° FOV cone to first shot |
| FOV Min S→F | Fastest single reaction (pre-aims excluded) |
| Avg/Min Reaction | Damage-taken to damage-dealt timing |
| HS Rate | Headshot kill percentage + per-round variance |
| Accuracy | Hit/shot ratio for firearms |
| Smoke Kills | Kills through smoke as % of total |
| Aim Snaps | Angular velocity of crosshair before kills |
| Consistency | HS variance across rounds (bots have unnaturally low variance) |

---

## Quick Start

```bash
# Clone
git clone https://github.com/dykomenko/cs2_checker.git
cd cs2_checker

# Install dependencies
pip install -r requirements.txt

# Run
python app.py
```

Open **http://localhost:5000**

### Faceit Integration (optional)

Get an API key at [developers.faceit.com](https://developers.faceit.com) and set it:

```bash
# Linux / Mac
export FACEIT_API_KEY=your-key-here

# Windows CMD
set FACEIT_API_KEY=your-key-here

# Windows PowerShell
$env:FACEIT_API_KEY="your-key-here"
```

The app works without it — upload and URL modes are always available.

---

## How It Works

The analyzer parses CS2 demo files using [demoparser2](https://github.com/LaihoE/demoparser) (Rust-based, fast) and computes:

1. **FOV engagement timing** — walks back tick data to find when the enemy entered the player's field of view (80° cone), then measures time to first shot and damage. Pre-aim situations (player already aimed at the position) are detected and excluded.
2. **Reaction time** — time between taking damage and retaliating.
3. **Headshot rate & consistency** — per-round HS% variance. Cheats produce unnaturally stable rates.
4. **Accuracy** — hit/shot ratio for firearms (pistols, rifles, SMGs).
5. **Smoke kills** — kills through smoke as percentage of total.
6. **Aim snap detection** — maximum angular velocity of crosshair movement before kills.
7. **Composite score** — weighted sum of all anomalies: 0 = clean, 100 = high suspicion.

### Suspicion Levels

| Score | Level | Meaning |
|-------|-------|---------|
| 0–14 | Clean | Normal gameplay |
| 15–29 | Low | Slightly unusual, likely skilled player |
| 30–59 | Medium | Multiple anomalies detected |
| 60–100 | High | Strong indicators of assistance |

> **Note:** High scores don't guarantee cheating. Skilled players can trigger some flags legitimately.

---

## Project Structure

```
cs2_checker/
├── app.py              # Flask server & API routes
├── analyzer.py         # Anti-cheat parser (FOV, snaps, suspicion scoring)
├── sources.py          # Demo sources (URL download, Faceit API, share code decode)
├── cache.py            # MD5-based result caching
├── config.py           # Configuration (env vars, paths)
├── requirements.txt    # Python dependencies
├── templates/
│   └── index.html      # Single-page UI (vanilla JS, bilingual)
└── static/
    └── style.css       # Dark theme
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Web UI |
| `POST` | `/api/analyze` | Upload & analyze demo (multipart form) |
| `POST` | `/api/analyze-url` | Download demo from URL & analyze |
| `POST` | `/api/decode-sharecode` | Decode Steam share code |
| `GET` | `/api/faceit/player?nickname=` | Search Faceit player |
| `GET` | `/api/faceit/matches?player_id=` | Get player's recent matches |
| `POST` | `/api/faceit/analyze` | Download & analyze Faceit demo |

---

## Requirements

- Python 3.10+
- ~200 MB RAM per demo analysis
- No Node.js, no build step, no external databases

## License

MIT
