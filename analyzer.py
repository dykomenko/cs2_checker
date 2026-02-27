"""
CS2 Anti-Cheat Analyzer — stripped-down parser focused on cheat detection.
Extracts FOV-based reaction times, suspicion scoring, snap angles, HS consistency.
"""
import os
import math
import gzip
import zstandard
import pandas as pd
import numpy as np
from demoparser2 import DemoParser
from collections import defaultdict


# ── Constants ──────────────────────────────────────────────────────────────────
TICK_RATE = 64          # CS2 matchmaking=64, Faceit=128 (auto-detected below)
FOV_HALF_DEG = 40       # ~80° total FOV cone for "actually saw the enemy"
LOOKBACK_TICKS = 192    # 3s lookback at 64 tick
LOOKBACK_STEP = 2       # sample every 2 ticks (~31ms resolution)
EYE_HEIGHT = 64.0       # standing eye offset in source units


# ── Helpers ────────────────────────────────────────────────────────────────────

def _angle_between_deg(pitch_a, yaw_a, pos_a, pos_b):
    """Angle (degrees) between player A's view direction and vector to pos_b."""
    dx = pos_b[0] - pos_a[0]
    dy = pos_b[1] - pos_a[1]
    dz = pos_b[2] - pos_a[2]
    dist = math.sqrt(dx * dx + dy * dy + dz * dz)
    if dist < 1.0:
        return 999.0
    tx, ty, tz = dx / dist, dy / dist, dz / dist
    pr = math.radians(pitch_a)
    yr = math.radians(yaw_a)
    vx = math.cos(pr) * math.cos(yr)
    vy = math.cos(pr) * math.sin(yr)
    vz = -math.sin(pr)
    dot = max(-1.0, min(1.0, vx * tx + vy * ty + vz * tz))
    return math.degrees(math.acos(dot))


def decompress_if_needed(file_path: str) -> str:
    """Decompress .dem.zst or .dem.gz to .dem if needed."""
    if file_path.endswith('.zst'):
        dem_path = file_path[:-4]
        if not os.path.exists(dem_path):
            dctx = zstandard.ZstdDecompressor()
            with open(file_path, 'rb') as fin, open(dem_path, 'wb') as fout:
                dctx.copy_stream(fin, fout)
        return dem_path
    if file_path.endswith('.gz'):
        dem_path = file_path[:-3]
        if not os.path.exists(dem_path):
            with gzip.open(file_path, 'rb') as fin, open(dem_path, 'wb') as fout:
                while True:
                    chunk = fin.read(8192)
                    if not chunk:
                        break
                    fout.write(chunk)
        return dem_path
    return file_path


def detect_tickrate(header):
    """Detect tickrate from demo header."""
    try:
        ticks = header.get("playback_ticks", 0)
        time = header.get("playback_time", 0)
        if ticks > 0 and time > 0:
            rate = round(ticks / time)
            if rate >= 100:
                return 128
    except Exception:
        pass
    return 64


# ── Round building ─────────────────────────────────────────────────────────────

def build_rounds(freeze_end_df, prestart_df, ended_df, kills_df, hurts_df, parser):
    """Build round boundaries with tick ranges."""
    freeze_ticks = sorted(freeze_end_df["tick"].tolist())
    ended_ticks = sorted(set(ended_df["tick"].tolist()))

    rounds = []
    for i, start_tick in enumerate(freeze_ticks):
        end_tick = None
        for et in ended_ticks:
            if et > start_tick:
                end_tick = et
                break
        if end_tick is None:
            end_tick = start_tick + 20000

        rounds.append({
            "round_num": i + 1,
            "start_tick": start_tick,
            "end_tick": end_tick,
        })

    if rounds:
        score_ticks = [r["end_tick"] - 1 for r in rounds]
        try:
            score_data = parser.parse_ticks(
                ["team_rounds_total", "team_num"],
                ticks=score_ticks
            )
            for i, r in enumerate(rounds):
                tick = score_ticks[i]
                tick_scores = score_data[score_data["tick"] == tick]
                ct_score = t_score = 0
                for _, row in tick_scores.iterrows():
                    if row["team_num"] == 3:
                        ct_score = max(ct_score, int(row["team_rounds_total"]))
                    elif row["team_num"] == 2:
                        t_score = max(t_score, int(row["team_rounds_total"]))
                r["ct_score"] = ct_score
                r["t_score"] = t_score
        except Exception:
            for r in rounds:
                r["ct_score"] = r["t_score"] = 0

    return rounds


# ── Player extraction ──────────────────────────────────────────────────────────

def extract_players(kills_df, hurts_df, fires_df, parser):
    """Extract unique players with team info."""
    players = {}
    for _, row in kills_df.iterrows():
        for prefix in [("attacker_steamid", "attacker_name"), ("user_steamid", "user_name")]:
            sid_col, name_col = prefix
            if pd.notna(row.get(sid_col)) and row[sid_col]:
                sid = str(row[sid_col])
                if sid not in players and sid != "0":
                    players[sid] = {"name": row[name_col], "steamid": sid}

    try:
        first_round_tick = 5000
        team_data = parser.parse_ticks(["team_num"], ticks=[first_round_tick])
        for _, row in team_data.iterrows():
            sid = str(row["steamid"])
            if sid in players:
                players[sid]["team"] = "CT" if row["team_num"] == 3 else "T"
    except Exception:
        for sid in players:
            players[sid]["team"] = "?"

    return players


# ── FOV-based engagement analysis ──────────────────────────────────────────────

def compute_engagements(parser, hurts_df, fires_df, rounds, players, tick_rate=64):
    """
    For each first-damage event per attacker-victim pair per round:
      1. Walk back in tick data to find when victim first entered attacker's FOV
      2. Find first weapon_fire after that moment
      3. Calculate: sight->fire (reaction), sight->damage (TTD), fire->damage
    """
    lookback = int(LOOKBACK_TICKS * tick_rate / 64)

    contacts = []
    for r in rounds:
        st, et = r["start_tick"], r["end_tick"]
        round_hurts = hurts_df[
            (hurts_df["tick"] >= st) & (hurts_df["tick"] <= et)
        ].sort_values("tick")

        seen_pairs = set()
        for _, h in round_hurts.iterrows():
            attacker = str(h.get("attacker_steamid", ""))
            victim = str(h.get("user_steamid", ""))
            if not attacker or attacker == "0" or attacker == victim:
                continue
            pair = (attacker, victim)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            contacts.append({
                "attacker": attacker,
                "victim": victim,
                "damage_tick": int(h["tick"]),
                "round_num": r["round_num"],
            })

    if not contacts:
        return {}

    all_ticks = set()
    for c in contacts:
        t = c["damage_tick"]
        for dt in range(0, lookback, LOOKBACK_STEP):
            all_ticks.add(max(0, t - dt))
    all_ticks = sorted(all_ticks)

    tick_data = parser.parse_ticks(
        ["X", "Y", "Z", "pitch", "yaw", "is_alive"],
        ticks=all_ticks,
    )

    player_ticks = defaultdict(dict)
    for _, row in tick_data.iterrows():
        sid = str(row["steamid"])
        t = int(row["tick"])
        player_ticks[sid][t] = (
            float(row["X"]), float(row["Y"]), float(row["Z"]),
            float(row["pitch"]), float(row["yaw"]),
            bool(row["is_alive"]),
        )

    fire_by_player = defaultdict(list)
    for _, f in fires_df.iterrows():
        sid = str(f.get("user_steamid", ""))
        w = str(f.get("weapon", ""))
        if sid and not any(k in w.lower() for k in [
            "knife", "bayonet", "nade", "flash", "smoke",
            "molotov", "incgrenade", "decoy", "c4"
        ]):
            fire_by_player[sid].append(int(f["tick"]))
    for sid in fire_by_player:
        fire_by_player[sid].sort()

    engagements = defaultdict(list)
    for c in contacts:
        attacker = c["attacker"]
        victim = c["victim"]
        dmg_tick = c["damage_tick"]

        atk_ticks = player_ticks.get(attacker, {})
        vic_ticks = player_ticks.get(victim, {})
        if not atk_ticks or not vic_ticks:
            continue

        first_in_fov_tick = None
        check_ticks = list(range(dmg_tick, max(0, dmg_tick - lookback), -LOOKBACK_STEP))

        for t in check_ticks:
            closest_t = t - (t % LOOKBACK_STEP)
            a = atk_ticks.get(closest_t) or atk_ticks.get(t)
            v = vic_ticks.get(closest_t) or vic_ticks.get(t)
            if not a or not v:
                continue
            if not a[5] or not v[5]:
                break

            pos_a = (a[0], a[1], a[2] + EYE_HEIGHT)
            pos_v = (v[0], v[1], v[2] + EYE_HEIGHT)
            angle = _angle_between_deg(a[3], a[4], pos_a, pos_v)

            if angle <= FOV_HALF_DEG:
                first_in_fov_tick = closest_t if closest_t in atk_ticks else t
            else:
                if first_in_fov_tick is not None:
                    break

        if first_in_fov_tick is None or first_in_fov_tick >= dmg_tick:
            continue

        sight_to_damage_ms = round(((dmg_tick - first_in_fov_tick) / tick_rate) * 1000)

        sight_to_fire_ms = None
        fire_to_damage_ms = None
        for ft in fire_by_player.get(attacker, []):
            if first_in_fov_tick <= ft <= dmg_tick:
                sight_to_fire_ms = round(((ft - first_in_fov_tick) / tick_rate) * 1000)
                fire_to_damage_ms = round(((dmg_tick - ft) / tick_rate) * 1000)
                break

        engagements[attacker].append({
            "round_num": c["round_num"],
            "victim": victim,
            "damage_tick": dmg_tick,
            "sight_tick": first_in_fov_tick,
            "sight_to_damage_ms": sight_to_damage_ms,
            "sight_to_fire_ms": sight_to_fire_ms,
            "fire_to_damage_ms": fire_to_damage_ms,
        })

    return dict(engagements)


# ── Anti-cheat suspicion scoring ───────────────────────────────────────────────

def compute_anticheat_metrics(kills_df, hurts_df, bullets_df, fires_df,
                              rounds, players, parser, dem_path, tick_rate=64):
    """Compute suspicious behavior indicators for each player."""
    anticheat = {}

    for steam_id, info in players.items():
        player_kills = kills_df[
            (kills_df["attacker_steamid"] == steam_id) &
            (kills_df["user_steamid"] != steam_id)
        ]

        # 1. Reaction time (damage-taken → retaliation)
        MIN_REACTION_TICKS = max(3, int(3 * tick_rate / 64))
        reaction_times = []
        for r in rounds:
            st, et = r["start_tick"], r["end_tick"]
            round_hurts_taken = hurts_df[
                (hurts_df["user_steamid"] == steam_id) &
                (hurts_df["tick"] >= st) & (hurts_df["tick"] <= et)
            ].sort_values("tick")

            seen_attackers = set()
            for _, hurt in round_hurts_taken.iterrows():
                attacker_sid = str(hurt.get("attacker_steamid", ""))
                if attacker_sid in seen_attackers:
                    continue
                hurt_tick = hurt["tick"]
                retaliation = hurts_df[
                    (hurts_df["attacker_steamid"] == steam_id) &
                    (hurts_df["user_steamid"] == attacker_sid) &
                    (hurts_df["tick"] > hurt_tick) &
                    (hurts_df["tick"] <= hurt_tick + int(256 * tick_rate / 64))
                ]
                if len(retaliation) > 0:
                    reaction_ticks = retaliation.iloc[0]["tick"] - hurt_tick
                    if reaction_ticks >= MIN_REACTION_TICKS:
                        reaction_ms = (reaction_ticks / tick_rate) * 1000
                        reaction_times.append(reaction_ms)
                        seen_attackers.add(attacker_sid)

        avg_reaction = float(np.mean(reaction_times)) if reaction_times else None
        min_reaction = float(np.min(reaction_times)) if reaction_times else None

        # 2. Time to damage (TTD) — first damage in round
        ttd_values = []
        for r in rounds:
            st, et = r["start_tick"], r["end_tick"]
            round_hurts = hurts_df[
                (hurts_df["attacker_steamid"] == steam_id) &
                (hurts_df["tick"] >= st) & (hurts_df["tick"] <= et)
            ].sort_values("tick")
            if len(round_hurts) > 0:
                first_dmg_tick = round_hurts.iloc[0]["tick"]
                ttd_ms = ((first_dmg_tick - st) / tick_rate) * 1000
                ttd_values.append(ttd_ms)

        avg_ttd = float(np.mean(ttd_values)) if ttd_values else None

        # 3. Headshot consistency
        hs_kills = player_kills[player_kills["headshot"] == True]
        hs_rate = len(hs_kills) / len(player_kills) * 100 if len(player_kills) > 0 else 0

        hs_per_round = []
        for r in rounds:
            rk = player_kills[
                (player_kills["tick"] >= r["start_tick"]) &
                (player_kills["tick"] <= r["end_tick"])
            ]
            if len(rk) > 0:
                hs_per_round.append(len(rk[rk["headshot"] == True]) / len(rk) * 100)
        hs_variance = float(np.var(hs_per_round)) if len(hs_per_round) > 1 else None

        # 4. Through-smoke kills
        smoke_kills = player_kills[player_kills["thrusmoke"] == True]
        smoke_kill_rate = len(smoke_kills) / len(player_kills) * 100 if len(player_kills) > 0 else 0

        # 5. Accuracy
        player_bullets = bullets_df[bullets_df["user_steamid"] == steam_id]
        player_hurts = hurts_df[
            (hurts_df["attacker_steamid"] == steam_id) &
            (~hurts_df["weapon"].str.contains(
                "knife|bayonet|hegrenade|flashbang|smokegrenade|molotov|incgrenade|decoy|inferno",
                case=False, na=False
            ))
        ]
        accuracy = (len(player_hurts) / len(player_bullets) * 100) if len(player_bullets) > 0 else 0

        # 6. Aim snap detection
        snap_scores = []
        try:
            kill_ticks = player_kills["tick"].tolist()
            if kill_ticks:
                analysis_ticks = []
                for kt in kill_ticks:
                    analysis_ticks.extend(range(max(0, kt - 8), kt + 2))
                analysis_ticks = sorted(set(analysis_ticks))

                if analysis_ticks:
                    angle_data = parser.parse_ticks(["pitch", "yaw"], ticks=analysis_ticks)
                    player_angles = angle_data[angle_data["steamid"] == steam_id].sort_values("tick")

                    for kt in kill_ticks:
                        pre_kill = player_angles[
                            (player_angles["tick"] >= kt - 8) &
                            (player_angles["tick"] <= kt)
                        ]
                        if len(pre_kill) >= 2:
                            pitches = pre_kill["pitch"].values
                            yaws = pre_kill["yaw"].values
                            max_delta = 0
                            for j in range(1, len(pitches)):
                                dp = abs(pitches[j] - pitches[j - 1])
                                dy = abs(yaws[j] - yaws[j - 1])
                                if dy > 180:
                                    dy = 360 - dy
                                delta = math.sqrt(dp ** 2 + dy ** 2)
                                max_delta = max(max_delta, delta)
                            snap_scores.append(max_delta)
        except Exception:
            pass

        avg_snap = float(np.mean(snap_scores)) if snap_scores else None
        max_snap = float(np.max(snap_scores)) if snap_scores else None

        # 7. Suspicion score (0-100)
        suspicion = 0
        flags = []

        if avg_reaction is not None and avg_reaction < 120:
            suspicion += 25
            flags.append(f"Inhuman avg reaction: {avg_reaction:.0f}ms")
        elif avg_reaction is not None and avg_reaction < 180:
            suspicion += 10
            flags.append(f"Very fast avg reaction: {avg_reaction:.0f}ms")

        if min_reaction is not None and min_reaction < 70:
            suspicion += 15
            flags.append(f"Suspicious min reaction: {min_reaction:.0f}ms")

        if hs_rate > 75 and len(player_kills) >= 8:
            suspicion += 25
            flags.append(f"Abnormal HS rate: {hs_rate:.0f}%")
        elif hs_rate > 60 and len(player_kills) >= 8:
            suspicion += 5
            flags.append(f"High HS rate: {hs_rate:.0f}% (could be skill)")

        if smoke_kill_rate > 20 and len(smoke_kills) >= 3:
            suspicion += 20
            flags.append(f"Suspicious smoke kills: {len(smoke_kills)} ({smoke_kill_rate:.0f}%)")

        if accuracy > 55 and len(player_bullets) >= 30:
            suspicion += 20
            flags.append(f"Abnormal accuracy: {accuracy:.0f}%")
        elif accuracy > 40 and len(player_bullets) >= 30:
            suspicion += 5
            flags.append(f"High accuracy: {accuracy:.0f}%")

        if max_snap is not None and max_snap > 60:
            suspicion += 15
            flags.append(f"Aim snap detected: {max_snap:.1f}\u00b0")

        if hs_variance is not None and hs_variance < 80 and hs_rate > 55 and len(player_kills) >= 8:
            suspicion += 10
            flags.append(f"Unnatural HS consistency (variance: {hs_variance:.0f})")

        suspicion = min(100, suspicion)

        anticheat[steam_id] = {
            "name": info["name"],
            "steamid": steam_id,
            "suspicion_score": suspicion,
            "flags": flags,
            "reaction_times": reaction_times[:50],
            "avg_reaction_ms": round(avg_reaction, 1) if avg_reaction else None,
            "min_reaction_ms": round(min_reaction, 1) if min_reaction else None,
            "ttd_values_ms": [round(t, 0) for t in ttd_values],
            "avg_ttd_ms": round(avg_ttd, 0) if avg_ttd else None,
            "hs_rate": round(hs_rate, 1),
            "hs_variance": round(hs_variance, 1) if hs_variance else None,
            "accuracy": round(accuracy, 1),
            "smoke_kills": len(smoke_kills),
            "smoke_kill_rate": round(smoke_kill_rate, 1),
            "snap_scores": [round(s, 1) for s in snap_scores[:50]],
            "avg_snap_angle": round(avg_snap, 1) if avg_snap else None,
            "max_snap_angle": round(max_snap, 1) if max_snap else None,
        }

    return anticheat


# ── Main entry point ───────────────────────────────────────────────────────────

def parse_demo_anticheat(file_path: str) -> dict:
    """Parse a CS2 demo and return anti-cheat focused analysis."""
    dem_path = decompress_if_needed(file_path)
    parser = DemoParser(dem_path)

    header = parser.parse_header()
    tick_rate = detect_tickrate(header)

    # Events needed for anti-cheat
    kills_df = parser.parse_event("player_death")
    hurts_df = parser.parse_event("player_hurt")
    fires_df = parser.parse_event("weapon_fire")
    bullets_df = parser.parse_event("fire_bullets")

    # Round boundaries
    round_freeze_end = parser.parse_event("round_freeze_end")
    round_prestart = parser.parse_event("round_prestart")
    round_ended = parser.parse_event("round_officially_ended")

    rounds = build_rounds(round_freeze_end, round_prestart, round_ended,
                          kills_df, hurts_df, parser)
    players = extract_players(kills_df, hurts_df, fires_df, parser)

    # FOV-based engagement analysis (sight-to-fire, the key metric)
    engagements = compute_engagements(parser, hurts_df, fires_df, rounds, players, tick_rate)

    # Anti-cheat suspicion scoring
    anticheat = compute_anticheat_metrics(kills_df, hurts_df, bullets_df, fires_df,
                                          rounds, players, parser, dem_path, tick_rate)

    # Enrich anticheat data with FOV engagement metrics
    for steam_id, ac in anticheat.items():
        player_engs = engagements.get(steam_id, [])
        stf = [e["sight_to_fire_ms"] for e in player_engs if e["sight_to_fire_ms"] is not None]
        std = [e["sight_to_damage_ms"] for e in player_engs if e["sight_to_damage_ms"] is not None]
        ftd = [e["fire_to_damage_ms"] for e in player_engs if e["fire_to_damage_ms"] is not None]

        ac["fov_sight_to_fire"] = stf[:50]
        ac["fov_avg_sight_to_fire"] = round(float(np.mean(stf))) if stf else None
        ac["fov_min_sight_to_fire"] = round(float(np.min(stf))) if stf else None
        ac["fov_avg_sight_to_damage"] = round(float(np.mean(std))) if std else None
        ac["fov_avg_fire_to_damage"] = round(float(np.mean(ftd))) if ftd else None
        ac["engagement_count"] = len(player_engs)

    # Minimal player stats for context
    basic_stats = {}
    for steam_id, info in players.items():
        pk = kills_df[
            (kills_df["attacker_steamid"] == steam_id) &
            (kills_df["user_steamid"] != steam_id)
        ]
        pd_ = kills_df[kills_df["user_steamid"] == steam_id]
        k, d = len(pk), len(pd_)
        basic_stats[steam_id] = {
            "name": info["name"],
            "team": info.get("team", "?"),
            "kills": int(k),
            "deaths": int(d),
            "kd": round(k / d, 2) if d > 0 else float(k),
        }

    return {
        "map": header.get("map_name", "unknown"),
        "tick_rate": tick_rate,
        "total_rounds": len(rounds),
        "players": basic_stats,
        "anticheat": anticheat,
    }
