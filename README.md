# CS2 Anti-Cheat Checker

Lightweight CS2 demo analyzer focused on cheat detection.
Single Python process, no Node.js, no build step.

## Features

- Upload `.dem` / `.dem.zst` / `.dem.gz` files
- Paste direct demo URL (auto-download & analyze)
- Faceit integration (search player, browse matches, one-click analyze)
- FOV-based reaction time: sight-to-fire, sight-to-damage (TTD)
- Suspicion scoring 0-100 per player
- Metrics: HS rate, accuracy, smoke kills, aim snap angles, consistency
- Histograms for reaction time and snap angle distributions

## Quick Start

```bash
pip install -r requirements.txt
python app.py
```

Open http://localhost:5000

## Faceit Integration (optional)

Get an API key at https://developers.faceit.com and set it:

```bash
# Linux/Mac
export FACEIT_API_KEY=your-key-here

# Windows
set FACEIT_API_KEY=your-key-here
```

The app works without it — upload and URL modes are always available.

## How It Works

The analyzer parses CS2 demo files with [demoparser2](https://github.com/LaihoE/demoparser) and computes:

1. **FOV engagement timing** — walks back tick data to find when the enemy entered the player's field of view, then measures time to first shot and damage
2. **Reaction time** — time between taking damage and retaliating
3. **Headshot rate & consistency** — per-round HS% variance (bots have unnaturally stable rates)
4. **Accuracy** — hit/shot ratio for firearms
5. **Smoke kills** — kills through smoke as percentage of total
6. **Aim snap detection** — angular velocity of crosshair movement before kills
7. **Composite score** — weighted sum of all anomalies (0 = clean, 100 = high suspicion)

## Project Structure

```
cs2_checker/
├── app.py              # Flask server & API routes
├── analyzer.py         # Anti-cheat parser (FOV, snaps, suspicion scoring)
├── sources.py          # Demo download (URL, Faceit API)
├── config.py           # Configuration (env vars)
├── requirements.txt    # Python dependencies
├── templates/
│   └── index.html      # Single-page UI (vanilla JS)
└── static/
    └── style.css       # Dark theme
```
