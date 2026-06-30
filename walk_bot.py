import os
import asyncio
from datetime import date
from time import perf_counter
from typing import Any

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

import strike_zone
from matchup_engine import get_matchup_data, _pitch_name_key
import performance_profile

# Load the .env file as the source of truth for bot startup flags.
load_dotenv(dotenv_path=".env", override=True)

TOKEN = os.getenv("DISCORD_WALK_TOKEN")
DISCORD_WALK_CHANNEL_ID = os.getenv("DISCORD_WALK_CHANNEL_ID")
LINEUP_MONITOR_INTERVAL_SECONDS = 120
TOP_HR_CANDIDATES_COUNT = int(os.getenv("TOP_HR_CANDIDATES_COUNT", "3"))
TEST_MODE = os.getenv("TEST_MODE", "False").strip().lower() in {"1", "true", "yes", "on"}
print("TOKEN FOUND:", TOKEN is not None)
print("TEST_MODE:", TEST_MODE)

# Basic bot setup
intents = discord.Intents.default()

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

POSTED_GAME_KEYS: set[str] = set()
LINEUP_MATCHUP_RESULTS: list[dict[str, Any]] = []
CURRENT_MONITOR_DATE: date | None = None
APP_FUNCTIONS: dict[str, Any] | None = None
APP_IMPORT_ERROR: Exception | None = None


def _log_test_timing(started_at: float | None, label: str, step_started_at: float | None = None) -> None:
    if not TEST_MODE or started_at is None:
        return
    elapsed = perf_counter() - started_at
    if step_started_at is None:
        print(f"[{elapsed:.2f}s] {label}")
        return
    step_elapsed = perf_counter() - step_started_at
    print(f"[{elapsed:.2f}s] {label} (+{step_elapsed:.2f}s)")


def _load_app_functions() -> dict[str, Any]:
    global APP_FUNCTIONS, APP_IMPORT_ERROR
    if APP_FUNCTIONS is not None:
        return APP_FUNCTIONS
    if APP_IMPORT_ERROR is not None:
        raise APP_IMPORT_ERROR

    try:
        from app import get_game_lineups, load_schedule
    except Exception as exc:
        APP_IMPORT_ERROR = exc
        raise

    APP_FUNCTIONS = {
        "get_game_lineups": get_game_lineups,
        "load_schedule": load_schedule,
    }
    return APP_FUNCTIONS


def _lineup_is_confirmed(lineup: list[dict[str, Any]] | None) -> bool:
    return bool(lineup) and not any(player.get("is_projected") for player in lineup)


def _game_value(game: Any, key: str, default: Any = "") -> Any:
    try:
        value = game.get(key, default)
    except AttributeError:
        return default
    return default if value is None else value


def _lineup_key(game: Any, side: str) -> str:
    return f"{_game_value(game, 'game_pk')}:{side}"


def _game_key(game: Any) -> str:
    return str(_game_value(game, "game_pk"))


def _payload_game_key(payload: dict[str, Any]) -> str:
    game = payload.get("game", {}) if isinstance(payload, dict) else {}
    game_pk = game.get("game_pk") if isinstance(game, dict) else None
    return str(game_pk or payload.get("lineup_key") or "")


def _team_context(game: Any, side: str) -> dict[str, Any]:
    opponent_side = "home" if side == "away" else "away"
    return {
        "side": side,
        "team": _game_value(game, f"{side}_team"),
        "team_id": _game_value(game, f"{side}_team_id"),
        "opponent": _game_value(game, f"{opponent_side}_team"),
        "opponent_id": _game_value(game, f"{opponent_side}_team_id"),
    }


def _opposing_starting_pitcher(game: Any, batting_side: str) -> dict[str, Any]:
    pitcher_side = "home" if batting_side == "away" else "away"
    return {
        "side": pitcher_side,
        "id": _game_value(game, f"{pitcher_side}_pitcher_id"),
        "name": _game_value(game, f"{pitcher_side}_pitcher", "TBD"),
        "hand": _game_value(game, f"{pitcher_side}_pitcher_hand"),
    }


def _build_lineup_matchup_payload(game: Any, side: str, lineup: list[dict[str, Any]]) -> dict[str, Any]:
    pitcher = _opposing_starting_pitcher(game, side)
    team = _team_context(game, side)
    batters = []

    for player in lineup:
        batter_id = player.get("player_id")
        batter_payload = {
            "batting_order": player.get("number"),
            "batter_id": batter_id,
            "batter_name": player.get("name"),
            "batter_handedness": player.get("handedness"),
            "position": player.get("position"),
            "walk_analysis": None,
            "home_run_analysis": None,
            "matchup_data": None,
            "error": None,
        }

        if not batter_id:
            batter_payload["error"] = "No batter player_id available."
            batters.append(batter_payload)
            continue
        if not pitcher.get("id"):
            batter_payload["error"] = "No opposing starting pitcher ID available."
            batters.append(batter_payload)
            continue

        try:
            matchup_data = get_matchup_data(batter_id, pitcher["id"])
        except Exception as exc:
            batter_payload["error"] = f"get_matchup_data failed: {exc}"
        else:
            batter_payload["matchup_data"] = matchup_data
            batter_payload["home_run_analysis"] = matchup_data.get("home_run_analysis")
            with performance_profile.timed("Walk analysis"):
                batter_payload["walk_analysis"] = _build_walk_analysis(matchup_data)

        batters.append(batter_payload)

    payload = {
        "lineup_key": _lineup_key(game, side),
        "processed_at_date": date.today().isoformat(),
        "game": {
            "game_pk": _game_value(game, "game_pk"),
            "away_team": _game_value(game, "away_team"),
            "home_team": _game_value(game, "home_team"),
            "game_time_et": _game_value(game, "game_time_et"),
            "status": _game_value(game, "status"),
        },
        "lineup": {
            **team,
            "confirmed": True,
            "batting_order": lineup,
        },
        "opposing_starting_pitcher": pitcher,
        # Rank-ready raw analysis payload. No scoring or ranking is done here.
        "batters": batters,
    }
    profile = performance_profile.active_profile()
    if profile is not None:
        payload["_performance_profile"] = profile
    return payload


def _scan_confirmed_lineups_once() -> list[dict[str, Any]]:
    app_functions = _load_app_functions()
    load_schedule = app_functions["load_schedule"]
    get_game_lineups = app_functions["get_game_lineups"]

    scan_profile = performance_profile.start_profile("Lineup scan")
    schedule_started_at = perf_counter()
    try:
        games = load_schedule(date.today())
    finally:
        schedule_elapsed = perf_counter() - schedule_started_at
        performance_profile.record_timing("Load schedule", schedule_elapsed, profile=scan_profile)
        performance_profile.set_active_profile(None)
    if games is None or games.empty:
        return []

    newly_processed = []
    for _, game in games.iterrows():
        game_key = _game_key(game)
        if game_key in POSTED_GAME_KEYS:
            continue

        lineup_profile = performance_profile.start_profile("Lineup lookup")
        lineup_started_at = perf_counter()
        try:
            lineup_context = get_game_lineups(_game_value(game, "game_pk"), game)
        except Exception as exc:
            performance_profile.set_active_profile(None)
            print(f"Lineup monitor warning: get_game_lineups failed for game {_game_value(game, 'game_pk')}: {exc}")
            continue
        finally:
            lineup_elapsed = perf_counter() - lineup_started_at
            performance_profile.record_timing("Find lineup", lineup_elapsed, profile=lineup_profile)
            performance_profile.set_active_profile(None)

        for side in ("away", "home"):
            lineup = lineup_context.get(side, [])
            if not _lineup_is_confirmed(lineup):
                continue

            profile = performance_profile.start_profile(
                f"{_game_value(game, 'away_team')} @ {_game_value(game, 'home_team')}"
            )
            performance_profile.merge_profile_metrics(profile, scan_profile)
            performance_profile.merge_profile_metrics(profile, lineup_profile)
            try:
                payload = _build_lineup_matchup_payload(game, side, lineup)
            finally:
                performance_profile.set_active_profile(None)
            LINEUP_MATCHUP_RESULTS.append(payload)
            newly_processed.append(payload)
            break

    return newly_processed


def _build_single_batter_test_payload(game: Any, side: str, lineup: list[dict[str, Any]]) -> dict[str, Any]:
    pitcher = _opposing_starting_pitcher(game, side)
    team = _team_context(game, side)
    player = next((lineup_player for lineup_player in lineup if lineup_player.get("player_id")), lineup[0])
    batter_id = player.get("player_id")
    batter_payload = {
        "batting_order": player.get("number"),
        "batter_id": batter_id,
        "batter_name": player.get("name"),
        "batter_handedness": player.get("handedness"),
        "position": player.get("position"),
        "walk_analysis": None,
        "home_run_analysis": None,
        "matchup_data": None,
        "error": None,
    }

    if not batter_id:
        batter_payload["error"] = "No batter player_id available."
    elif not pitcher.get("id"):
        batter_payload["error"] = "No opposing starting pitcher ID available."
    else:
        try:
            matchup_data = get_matchup_data(batter_id, pitcher["id"])
        except Exception as exc:
            batter_payload["error"] = f"get_matchup_data failed: {exc}"
        else:
            batter_payload["matchup_data"] = matchup_data
            batter_payload["home_run_analysis"] = matchup_data.get("home_run_analysis")
            batter_payload["walk_analysis"] = _build_walk_analysis(matchup_data)

    return {
        "lineup_key": _lineup_key(game, side),
        "processed_at_date": date.today().isoformat(),
        "game": {
            "game_pk": _game_value(game, "game_pk"),
            "away_team": _game_value(game, "away_team"),
            "home_team": _game_value(game, "home_team"),
            "game_time_et": _game_value(game, "game_time_et"),
            "status": _game_value(game, "status"),
        },
        "lineup": {
            **team,
            "confirmed": _lineup_is_confirmed(lineup),
            "test_mode": True,
            "batting_order": [player],
        },
        "opposing_starting_pitcher": pitcher,
        "batters": [batter_payload],
    }


def _build_test_mode_payload(test_started_at: float | None = None) -> dict[str, Any] | None:
    app_functions_started_at = perf_counter()
    app_functions = _load_app_functions()
    _log_test_timing(test_started_at, "Load app functions", app_functions_started_at)
    load_schedule = app_functions["load_schedule"]
    get_game_lineups = app_functions["get_game_lineups"]

    step_started_at = perf_counter()
    games = load_schedule(date.today())
    _log_test_timing(test_started_at, "Load schedule", step_started_at)
    if games is None or games.empty:
        print("TEST_MODE: no games found for today.")
        return None

    find_lineup_started_at = perf_counter()
    for _, game in games.iterrows():
        try:
            lineup_context = get_game_lineups(_game_value(game, "game_pk"), game)
        except Exception as exc:
            print(f"TEST_MODE warning: get_game_lineups failed for game {_game_value(game, 'game_pk')}: {exc}")
            continue

        for side in ("away", "home"):
            lineup = lineup_context.get(side, [])
            if not lineup:
                continue

            pitcher = _opposing_starting_pitcher(game, side)
            if not pitcher.get("id"):
                continue

            player = next((lineup_player for lineup_player in lineup if lineup_player.get("player_id")), lineup[0])
            print(
                "TEST_MODE: using one batter from the first available lineup: "
                f"{_game_value(game, 'away_team')} @ {_game_value(game, 'home_team')} ({side}) - "
                f"{player.get('name', 'Unknown batter')}."
            )
            _log_test_timing(test_started_at, "Find lineup", find_lineup_started_at)
            matchup_started_at = perf_counter()
            payload = _build_single_batter_test_payload(game, side, lineup)
            _log_test_timing(test_started_at, "One batter matchup data", matchup_started_at)
            LINEUP_MATCHUP_RESULTS.append(payload)
            return payload

    _log_test_timing(test_started_at, "Find lineup", find_lineup_started_at)
    print("TEST_MODE: no lineup with an opposing starting pitcher was available.")
    return None


def _analysis_family_reads(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    details = analysis.get("details", {}) if isinstance(analysis, dict) else {}
    pitch_families = details.get("pitch_families", []) if isinstance(details, dict) else []
    if isinstance(pitch_families, list) and pitch_families:
        return pitch_families
    arsenal = details.get("arsenal_vs_batter_run_value", {}) if isinstance(details, dict) else {}
    reads = arsenal.get("usage_ordered_family_reads", []) if isinstance(arsenal, dict) else []
    return reads if isinstance(reads, list) else []


def _analysis_pitch_matches(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    details = analysis.get("details", {}) if isinstance(analysis, dict) else {}
    arsenal = details.get("arsenal_vs_batter_run_value", {}) if isinstance(details, dict) else {}
    matches = arsenal.get("pitch_matches", []) if isinstance(arsenal, dict) else []
    return matches if isinstance(matches, list) else []


def _pitch_match_for_family(
    family_read: dict[str, Any],
    pitch_matches: list[dict[str, Any]],
) -> dict[str, Any] | None:
    family = family_read.get("pitch_family")
    pitch_type = family_read.get("pitch_type")
    for pitch_match in pitch_matches:
        if pitch_match.get("pitch_family") == family:
            return pitch_match
        if pitch_match.get("pitch_type") == pitch_type:
            return pitch_match
    return None


def _to_float(value: Any) -> float | None:
    try:
        if value in ("", None):
            return None
        return float(str(value).replace("%", ""))
    except (TypeError, ValueError):
        return None


def _first_number(mapping: dict[str, Any], *keys: str) -> float | None:
    if not isinstance(mapping, dict):
        return None
    normalized = {str(key).lower().replace("_", "").replace(" ", ""): value for key, value in mapping.items()}
    for key in keys:
        value = normalized.get(key.lower().replace("_", "").replace(" ", ""))
        number = _to_float(value)
        if number is not None:
            return number
    return None


def _batter_walk_rate(matchup: dict[str, Any]) -> float | None:
    batter_stats = matchup.get("batter_season_stats") or {}
    direct_value = _first_number(batter_stats, "BB%", "BB Percent", "bb_percent", "walk_rate")
    if direct_value is not None:
        return direct_value

    game_log = matchup.get("batter_game_log") or []
    walks = 0.0
    plate_appearances = 0.0
    if isinstance(game_log, list):
        for row in game_log:
            if not isinstance(row, dict):
                continue
            walks += _to_float(row.get("walks")) or 0.0
            plate_appearances += _to_float(row.get("plate_appearances")) or 0.0
    return (walks / plate_appearances * 100.0) if plate_appearances else None


def _pitcher_walk_rate(matchup: dict[str, Any]) -> float | None:
    pitcher_stats = matchup.get("pitcher_season_stats") or {}
    return _first_number(pitcher_stats, "BB%", "BB Percent", "bb_percent", "walk_rate")


def _outside_zone_pct(zone_payload: dict[str, Any] | None) -> float | None:
    if not isinstance(zone_payload, dict):
        return None

    outside_pct = 0.0
    found_outer = False
    outer_stats = zone_payload.get("outer_stats") or {}
    if isinstance(outer_stats, dict):
        for stats in outer_stats.values():
            if not isinstance(stats, dict):
                continue
            pct = _to_float(stats.get("pitch_pct"))
            if pct is not None:
                outside_pct += pct
                found_outer = True

    if found_outer:
        return outside_pct

    outside_count = 0.0
    total_count = 0.0
    for row in zone_payload.get("zone_rows", []) or []:
        if not isinstance(row, dict):
            continue
        count = _to_float(row.get("pitch_count")) or 0.0
        total_count += count
        if str(row.get("zone_group", "")).lower() == "outer":
            outside_count += count
    return (outside_count / total_count * 100.0) if total_count else None


def _pitch_match_metric(pitch_match: dict[str, Any] | None, metric: str) -> float | None:
    if not isinstance(pitch_match, dict):
        return None
    weighted_metrics = pitch_match.get("weighted_metrics", {})
    weighted_metric = weighted_metrics.get(metric) if isinstance(weighted_metrics, dict) else None
    if isinstance(weighted_metric, dict):
        value = _to_float(weighted_metric.get("value"))
        if value is not None:
            return value

    rows_by_variant = pitch_match.get("batter_run_value_rows_by_variant", {})
    values = []
    if isinstance(rows_by_variant, dict):
        for rows in rows_by_variant.values():
            for row in rows or []:
                if not isinstance(row, dict):
                    continue
                value = _to_float(row.get(metric))
                if value is not None:
                    values.append(value)
    return (sum(values) / len(values)) if values else None


def _arsenal_family_reads_from_matches(pitch_matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    family_reads = []
    for pitch_match in pitch_matches:
        if not isinstance(pitch_match, dict):
            continue
        family_key = pitch_match.get("pitch_family")
        if not family_key:
            continue
        family_reads.append(
            {
                "pitch_family": family_key,
                "pitch_type": pitch_match.get("pitch_type"),
                "pitcher_usage_pct": pitch_match.get("pitcher_usage_pct"),
                "importance": pitch_match.get("importance"),
            }
        )
    return family_reads


def _merge_pitcher_arsenal_family_reads(
    family_reads: list[dict[str, Any]],
    pitch_matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}

    for arsenal_read in _arsenal_family_reads_from_matches(pitch_matches):
        family_key = arsenal_read.get("pitch_family")
        if family_key:
            merged[family_key] = dict(arsenal_read)

    for family_read in family_reads:
        if not isinstance(family_read, dict):
            continue
        family_key = family_read.get("pitch_family")
        if not family_key:
            continue
        existing = merged.get(family_key, {})
        combined = {**existing, **family_read}
        if family_read.get("pitcher_usage_pct") in (None, "") and existing.get("pitcher_usage_pct") is not None:
            combined["pitcher_usage_pct"] = existing.get("pitcher_usage_pct")
        if not family_read.get("importance") and existing.get("importance"):
            combined["importance"] = existing.get("importance")
        merged[family_key] = combined

    return sorted(merged.values(), key=_family_usage, reverse=True)


def _top_usage_family_reads(
    family_reads: list[dict[str, Any]],
    coverage_target: float = 90.0,
) -> tuple[list[dict[str, Any]], float | None]:
    sorted_reads = sorted(family_reads, key=_family_usage, reverse=True)
    total_usage = sum(_family_usage(read) for read in sorted_reads)
    if total_usage <= 0:
        return sorted_reads, None

    selected = []
    coverage = 0.0
    for family_read in sorted_reads:
        usage = _family_usage(family_read)
        if usage <= 0:
            continue
        selected.append(family_read)
        coverage += usage
        if coverage >= coverage_target:
            break
    return selected, coverage


def _batter_outside_discipline_by_pitch_family(
    batter_id: Any,
    pitcher_hand: str,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    season_year = date.today().year
    start_date = f"{season_year}-03-01"
    end_date = date.today().isoformat()
    missing = []

    try:
        raw_df = strike_zone.load_batter_pitch_location_data(batter_id, start_date, end_date)
    except Exception as exc:
        return {}, [f"Batter pitch-specific plate discipline unavailable: {exc}"]

    if raw_df is None or raw_df.empty:
        return {}, ["Batter pitch-specific plate discipline unavailable."]

    pitch_col = "pitch_name" if "pitch_name" in raw_df.columns else "pitch_type" if "pitch_type" in raw_df.columns else ""
    if not pitch_col:
        return {}, ["Batter pitch-specific plate discipline unavailable because pitch type is missing."]
    if "zone" not in raw_df.columns:
        return {}, ["Batter pitch-specific plate discipline unavailable because zone is missing."]

    working_df = raw_df.copy()
    if pitcher_hand in {"RHP", "LHP"}:
        try:
            working_df = strike_zone.filter_by_pitcher_throws(working_df, pitcher_hand)
        except Exception as exc:
            return {}, [f"Batter pitch-specific pitcher-hand filter failed: {exc}"]

    if working_df is None or working_df.empty:
        return {}, [f"Batter pitch-specific plate discipline unavailable for {pitcher_hand or 'all pitchers'}."]

    zone_ids = working_df["zone"].apply(strike_zone._normalize_zone_value)
    outside_df = working_df[zone_ids.isin(set(strike_zone.OUTER_ZONE_TO_QUAD))].copy()
    if outside_df.empty:
        return {}, ["Batter has no outside-zone pitch-specific discipline sample."]

    descriptions = outside_df["description"] if "description" in outside_df.columns else ["" for _ in range(len(outside_df))]
    outside_df["_is_take"] = [strike_zone._is_take_description(value) for value in descriptions]
    outside_df["_pitch_family"] = outside_df[pitch_col].apply(_pitch_name_key)
    outside_df = outside_df[outside_df["_pitch_family"] != ""].copy()
    if outside_df.empty:
        return {}, ["Batter outside-zone discipline sample has no usable pitch family names."]

    by_family = {}
    for family_key, group in outside_df.groupby("_pitch_family"):
        outside_pitch_count = int(len(group))
        outside_take_count = int(group["_is_take"].sum())
        outside_chase_count = outside_pitch_count - outside_take_count
        by_family[family_key] = {
            "pitch_family": family_key,
            "outside_pitch_count": outside_pitch_count,
            "outside_take_count": outside_take_count,
            "outside_chase_count": outside_chase_count,
            "outside_take_pct": (outside_take_count / outside_pitch_count * 100.0)
            if outside_pitch_count
            else None,
            "outside_chase_pct": (outside_chase_count / outside_pitch_count * 100.0)
            if outside_pitch_count
            else None,
        }

    return by_family, missing


def _weighted_average(rows: list[tuple[float | None, float]]) -> float | None:
    numerator = 0.0
    denominator = 0.0
    for value, weight in rows:
        if value is None or weight <= 0:
            continue
        numerator += value * weight
        denominator += weight
    return (numerator / denominator) if denominator else None


def _build_weighted_pitch_specific_discipline(
    matchup: dict[str, Any],
    family_reads: list[dict[str, Any]],
    pitch_matches: list[dict[str, Any]],
    by_pitch_family: dict[str, Any],
) -> dict[str, Any]:
    arsenal_reads = _merge_pitcher_arsenal_family_reads(family_reads, pitch_matches)
    selected_reads, arsenal_coverage_pct = _top_usage_family_reads(arsenal_reads)
    batter_family_discipline, missing = _batter_outside_discipline_by_pitch_family(
        matchup.get("batter_id"),
        str(matchup.get("pitcher_handedness") or ""),
    )

    family_profiles = []
    weighted_ooz_inputs = []
    weighted_take_inputs = []
    weighted_chase_inputs = []
    weighted_usage_with_discipline = 0.0

    for family_read in selected_reads:
        family_key = family_read.get("pitch_family")
        usage = _family_usage(family_read)
        family_zone = by_pitch_family.get(family_key, {}) if isinstance(by_pitch_family, dict) else {}
        pitcher_ooz_pct = _outside_zone_pct(family_zone)
        batter_discipline = batter_family_discipline.get(family_key, {})
        outside_take_pct = _to_float(batter_discipline.get("outside_take_pct"))
        outside_chase_pct = _to_float(batter_discipline.get("outside_chase_pct"))

        if pitcher_ooz_pct is not None:
            weighted_ooz_inputs.append((pitcher_ooz_pct, usage))
        if outside_take_pct is not None:
            weighted_take_inputs.append((outside_take_pct, usage))
            weighted_usage_with_discipline += usage
        if outside_chase_pct is not None:
            weighted_chase_inputs.append((outside_chase_pct, usage))

        family_profiles.append(
            {
                "pitch_family": family_key,
                "pitch_type": family_read.get("pitch_type"),
                "pitcher_usage_pct": family_read.get("pitcher_usage_pct"),
                "importance": family_read.get("importance"),
                "pitcher_outside_zone_pct": pitcher_ooz_pct,
                "batter_outside_take_pct": outside_take_pct,
                "batter_outside_chase_pct": outside_chase_pct,
                "outside_pitch_count": batter_discipline.get("outside_pitch_count"),
                "outside_take_count": batter_discipline.get("outside_take_count"),
                "outside_chase_count": batter_discipline.get("outside_chase_count"),
            }
        )

    weighted_pitcher_ooz_pct = _weighted_average(weighted_ooz_inputs)
    weighted_outside_take_pct = _weighted_average(weighted_take_inputs)
    weighted_chase_pct = _weighted_average(weighted_chase_inputs)

    edge_count = 0
    if weighted_pitcher_ooz_pct is not None and weighted_pitcher_ooz_pct >= 32:
        edge_count += 1
    if weighted_outside_take_pct is not None and weighted_outside_take_pct >= 55:
        edge_count += 1
    if weighted_chase_pct is not None and weighted_chase_pct <= 35:
        edge_count += 1

    return {
        "available": bool(family_profiles),
        "coverage_target_pct": 90.0,
        "arsenal_coverage_pct": arsenal_coverage_pct,
        "weighted_usage_with_discipline_pct": weighted_usage_with_discipline or None,
        "weighted_pitcher_ooz_pct": weighted_pitcher_ooz_pct,
        "weighted_outside_take_pct": weighted_outside_take_pct,
        "weighted_chase_pct": weighted_chase_pct,
        "edge_count": edge_count,
        "families": family_profiles,
        "missing_data": missing,
        "description": "Pitcher's primary arsenal versus this batter's handedness.",
    }


def _build_walk_analysis(matchup: dict[str, Any]) -> dict[str, Any]:
    home_run_analysis = matchup.get("home_run_analysis") or {}
    family_reads = _analysis_family_reads(home_run_analysis)
    pitch_matches = _analysis_pitch_matches(home_run_analysis)
    family_reads = _merge_pitcher_arsenal_family_reads(family_reads, pitch_matches)
    walk_risk = home_run_analysis.get("walk_risk") if isinstance(home_run_analysis, dict) else {}

    batter_bb_pct = _batter_walk_rate(matchup)
    pitcher_bb_pct = _pitcher_walk_rate(matchup)
    discipline = matchup.get("batter_plate_discipline_zone_data") or {}
    outside_take_pct = _to_float(discipline.get("outside_take_pct")) if isinstance(discipline, dict) else None
    chase_pct = (100.0 - outside_take_pct) if outside_take_pct is not None else None
    zone_swing_pct = _first_number(matchup.get("batter_season_stats") or {}, "Zone Swing%", "zone_swing_pct")

    pitcher_zone_data = matchup.get("pitcher_strike_zone_tendency_data") or {}
    overall_zone = pitcher_zone_data.get("overall") if isinstance(pitcher_zone_data, dict) else None
    pitcher_ooz_pct = _outside_zone_pct(overall_zone)
    by_pitch_family = pitcher_zone_data.get("by_pitch_family", {}) if isinstance(pitcher_zone_data, dict) else {}
    weighted_discipline = _build_weighted_pitch_specific_discipline(
        matchup,
        family_reads,
        pitch_matches,
        by_pitch_family,
    )
    discipline_by_family = {
        row.get("pitch_family"): row
        for row in weighted_discipline.get("families", [])
        if isinstance(row, dict) and row.get("pitch_family")
    }
    if discipline_by_family:
        evaluated_family_keys = set(discipline_by_family)
        family_reads = [
            family_read
            for family_read in family_reads
            if family_read.get("pitch_family") in evaluated_family_keys
        ]

    pitch_families = []
    strengths = []
    concerns = []
    missing_data = []

    if batter_bb_pct is None:
        missing_data.append("Batter BB% unavailable.")
    if pitcher_bb_pct is None:
        missing_data.append("Pitcher BB% unavailable.")
    if outside_take_pct is None:
        missing_data.append("Batter outside-zone take tendency unavailable.")
    if pitcher_ooz_pct is None:
        missing_data.append("Pitcher outside-zone tendency unavailable.")
    missing_data.extend(weighted_discipline.get("missing_data", []) or [])

    walk_level = str(walk_risk.get("level", "") if isinstance(walk_risk, dict) else "")
    walk_level_bonus = {"High": 2, "Moderate": 1, "Low": 0}.get(walk_level, 0)

    for family_read in family_reads:
        pitch_match = _pitch_match_for_family(family_read, pitch_matches)
        family_key = family_read.get("pitch_family")
        family_zone = by_pitch_family.get(family_key, {}) if isinstance(by_pitch_family, dict) else {}
        family_specific = discipline_by_family.get(family_key, {})
        family_ooz_pct = _to_float(family_specific.get("pitcher_outside_zone_pct"))
        if family_ooz_pct is None:
            family_ooz_pct = _outside_zone_pct(family_zone)
        family_take_pct = _to_float(family_specific.get("batter_outside_take_pct"))
        family_chase_pct = _to_float(family_specific.get("batter_outside_chase_pct"))

        hard_hit_pct = _pitch_match_metric(pitch_match, "Hard Hit%")
        slg = _pitch_match_metric(pitch_match, "SLG")
        woba = _pitch_match_metric(pitch_match, "wOBA")
        whiff_pct = _pitch_match_metric(pitch_match, "Whiff%")
        putaway_pct = _pitch_match_metric(pitch_match, "PutAway%")

        edge_reasons = []
        zone_edge_count = 0
        discipline_edge_count = 0
        pitcher_walk_edge_count = 0
        batter_walk_support_count = 0
        if family_ooz_pct is not None and family_ooz_pct >= 32:
            zone_edge_count += 1
            edge_reasons.append("pitcher works this family outside the zone")
        if family_take_pct is not None and family_take_pct >= 55:
            discipline_edge_count += 1
            edge_reasons.append("batter takes this family outside the zone")
        if family_chase_pct is not None and family_chase_pct <= 35:
            discipline_edge_count += 1
            edge_reasons.append("batter chase profile is controlled against this family")
        if pitcher_bb_pct is not None and pitcher_bb_pct >= 8:
            pitcher_walk_edge_count += 1
            edge_reasons.append("pitcher walk rate supports deep counts")
        if batter_bb_pct is not None and batter_bb_pct >= 8:
            batter_walk_support_count += 1

        contact_warning = (
            (hard_hit_pct is not None and hard_hit_pct >= 45)
            or (slg is not None and slg >= 0.500)
            or (woba is not None and woba >= 0.360)
        )
        if contact_warning:
            concerns.append(
                f"{family_read.get('pitch_type')} has strong contact indicators, which may reduce walk confidence."
            )

        pitch_family = {
            "pitch_family": family_key,
            "pitch_type": family_read.get("pitch_type"),
            "pitcher_usage_pct": family_read.get("pitcher_usage_pct"),
            "importance": family_read.get("importance"),
            "zone_edge_count": zone_edge_count,
            "discipline_edge_count": discipline_edge_count,
            "pitcher_walk_edge_count": pitcher_walk_edge_count,
            "batter_walk_support_count": batter_walk_support_count,
            "walk_edge_count": zone_edge_count + discipline_edge_count + pitcher_walk_edge_count,
            "edge_reasons": edge_reasons,
            "edge_metrics": {
                "OOZ%": family_ooz_pct,
                "Take%": family_take_pct,
                "Chase%": family_chase_pct,
                "Batter BB%": batter_bb_pct,
                "Pitcher BB%": pitcher_bb_pct,
                "Zone Swing%": zone_swing_pct,
                "Outside Pitches": family_specific.get("outside_pitch_count"),
            },
            "contact_warning": contact_warning,
            "contact_metrics": {
                "Hard Hit%": hard_hit_pct,
                "SLG": slg,
                "wOBA": woba,
            },
            "risk_metrics": {
                "Whiff%": whiff_pct,
                "PutAway%": putaway_pct,
            },
        }
        pitch_families.append(pitch_family)

        if pitch_family["walk_edge_count"]:
            strengths.append(
                f"{family_read.get('pitch_type')} ({_family_usage(family_read):.1f}%): {', '.join(edge_reasons)}."
            )

    summary_parts = []
    if batter_bb_pct is not None:
        summary_parts.append(f"batter BB% {batter_bb_pct:.1f}%")
    if pitcher_bb_pct is not None:
        summary_parts.append(f"pitcher BB% {pitcher_bb_pct:.1f}%")
    weighted_take_pct = _to_float(weighted_discipline.get("weighted_outside_take_pct"))
    weighted_chase_pct = _to_float(weighted_discipline.get("weighted_chase_pct"))
    coverage_pct = _to_float(weighted_discipline.get("arsenal_coverage_pct"))
    if weighted_take_pct is not None:
        summary_parts.append(f"weighted outside-zone take {weighted_take_pct:.1f}%")
    if weighted_chase_pct is not None:
        summary_parts.append(f"weighted chase {weighted_chase_pct:.1f}%")
    if coverage_pct is not None:
        summary_parts.append(f"arsenal coverage {coverage_pct:.1f}%")
    summary = "Walk profile built from existing matchup data"
    if summary_parts:
        summary = f"Walk profile: {', '.join(summary_parts)}."

    return {
        "summary": summary,
        "strengths": strengths,
        "concerns": concerns,
        "missing_data": missing_data,
        "details": {
            "pitch_families": pitch_families,
            "context": {
                "batter_bb_pct": batter_bb_pct,
                "pitcher_bb_pct": pitcher_bb_pct,
                "batter_take_pct": outside_take_pct,
                "batter_chase_pct": chase_pct,
                "batter_zone_swing_pct": zone_swing_pct,
                "pitcher_ooz_pct": pitcher_ooz_pct,
                "temporary_home_run_walk_risk_reused": bool(walk_risk),
                "walk_risk_level_bonus": walk_level_bonus,
            },
            "weighted_pitch_specific_discipline": weighted_discipline,
        },
        "walk_risk": walk_risk if isinstance(walk_risk, dict) else {},
        "note": "Phase 1 walk analysis uses existing matchup data; home_run_analysis.walk_risk is reused temporarily.",
    }


def _family_importance_label(family_read: dict[str, Any]) -> str:
    importance = family_read.get("importance", {})
    return str(importance.get("label", "") if isinstance(importance, dict) else "").lower()


def _family_usage(family_read: dict[str, Any]) -> float:
    try:
        return float(family_read.get("pitcher_usage_pct") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _evidence_read(family_read: dict[str, Any], evidence_key: str) -> str:
    evidence = family_read.get("evidence", {})
    item = evidence.get(evidence_key, {}) if isinstance(evidence, dict) else {}
    return str(item.get("read", "") if isinstance(item, dict) else "").lower()


def _evidence_text(family_read: dict[str, Any], evidence_key: str) -> str:
    evidence = family_read.get("evidence", {})
    item = evidence.get(evidence_key, {}) if isinstance(evidence, dict) else {}
    return str(item.get("text", "") if isinstance(item, dict) else "").strip()


def _candidate_rank_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
    analysis = candidate.get("walk_analysis") or {}
    family_reads = _analysis_family_reads(analysis)
    details = analysis.get("details", {}) if isinstance(analysis, dict) else {}
    context = details.get("context", {}) if isinstance(details, dict) else {}
    weighted_profile = (
        details.get("weighted_pitch_specific_discipline", {})
        if isinstance(details, dict)
        else {}
    )
    weighted_profile_available = bool(
        isinstance(weighted_profile, dict)
        and weighted_profile.get("available")
        and _to_float(weighted_profile.get("weighted_outside_take_pct")) is not None
    )
    weighted_edge_count = int(weighted_profile.get("edge_count") or 0) if isinstance(weighted_profile, dict) else 0
    weighted_ooz = _to_float(weighted_profile.get("weighted_pitcher_ooz_pct")) or 0.0
    weighted_take = _to_float(weighted_profile.get("weighted_outside_take_pct")) or 0.0
    weighted_chase = _to_float(weighted_profile.get("weighted_chase_pct")) or 100.0
    arsenal_coverage = _to_float(weighted_profile.get("arsenal_coverage_pct")) or 0.0

    primary_zone_edges = 0
    secondary_zone_edges = 0
    primary_discipline_edges = 0
    secondary_discipline_edges = 0
    primary_pitcher_walk_edges = 0
    secondary_pitcher_walk_edges = 0
    batter_walk_support = 0
    low_usage_support = 0
    contact_warnings = 0
    all_concerns = len(analysis.get("concerns", []) or []) if isinstance(analysis, dict) else 0
    top_usage = 0.0
    top_ooz = 0.0

    for family_read in family_reads:
        importance = _family_importance_label(family_read)
        usage = _family_usage(family_read)
        top_usage = max(top_usage, usage)
        edge_count = int(family_read.get("walk_edge_count") or 0)
        zone_edges = int(family_read.get("zone_edge_count") or 0)
        discipline_edges = int(family_read.get("discipline_edge_count") or 0)
        pitcher_walk_edges = int(family_read.get("pitcher_walk_edge_count") or 0)
        batter_walk_support += int(family_read.get("batter_walk_support_count") or 0)
        edge_metrics = family_read.get("edge_metrics", {}) if isinstance(family_read, dict) else {}
        family_ooz = _to_float(edge_metrics.get("OOZ%")) if isinstance(edge_metrics, dict) else None
        top_ooz = max(top_ooz, family_ooz or 0.0)
        contact_warnings += int(bool(family_read.get("contact_warning")))

        if importance in {"primary", "major"}:
            primary_zone_edges += zone_edges
            primary_discipline_edges += discipline_edges
            primary_pitcher_walk_edges += pitcher_walk_edges
        elif importance == "secondary":
            secondary_zone_edges += zone_edges
            secondary_discipline_edges += discipline_edges
            secondary_pitcher_walk_edges += pitcher_walk_edges
        elif edge_count:
            low_usage_support += edge_count

    walk_risk = analysis.get("walk_risk", {}) if isinstance(analysis, dict) else {}
    walk_risk_level = str(walk_risk.get("level", "") if isinstance(walk_risk, dict) else "").lower()
    walk_risk_bonus = {"high": 2, "moderate": 1}.get(walk_risk_level, 0)
    batter_order = candidate.get("batting_order") or 99

    return (
        int(bool(analysis)),
        int(weighted_profile_available),
        weighted_edge_count,
        weighted_ooz,
        arsenal_coverage,
        weighted_take,
        -weighted_chase,
        primary_zone_edges,
        secondary_zone_edges,
        top_ooz,
        top_usage,
        primary_discipline_edges,
        secondary_discipline_edges,
        _to_float(context.get("batter_take_pct")) or 0.0,
        -(_to_float(context.get("batter_chase_pct")) or 100.0),
        primary_pitcher_walk_edges,
        secondary_pitcher_walk_edges,
        _to_float(context.get("pitcher_bb_pct")) or 0.0,
        walk_risk_bonus,
        low_usage_support,
        batter_walk_support,
        _to_float(context.get("batter_bb_pct")) or 0.0,
        -contact_warnings,
        -all_concerns,
        -int(batter_order) if str(batter_order).isdigit() else -99,
    )


def _candidate_reasons(candidate: dict[str, Any]) -> tuple[list[str], list[str]]:
    analysis = candidate.get("walk_analysis") or {}
    strengths = list(analysis.get("strengths", []) or [])
    concerns = list(analysis.get("concerns", []) or [])
    if not strengths and analysis.get("summary"):
        strengths.append(str(analysis.get("summary")))
    return strengths[:2], concerns[:1]


def _sentence(text: str) -> str:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return ""
    return cleaned if cleaned.endswith((".", "!", "?")) else f"{cleaned}."


def _join_sentences(parts: list[str]) -> str:
    return " ".join(_sentence(part) for part in parts if str(part or "").strip())


def _usage_phrase(family_read: dict[str, Any]) -> str:
    label = family_read.get("pitch_type") or family_read.get("pitch_family") or "Pitch family"
    usage = _family_usage(family_read)
    importance = _family_importance_label(family_read)
    if usage:
        if importance in {"primary", "major"}:
            return f"{label} is a high-usage family at {usage:.1f}%"
        return f"{label} is part of the arsenal at {usage:.1f}%"
    return f"{label} is part of the arsenal"


def _family_evidence_sentence(family_read: dict[str, Any]) -> str:
    edge_reasons = family_read.get("edge_reasons", []) or []
    parts = [_usage_phrase(family_read)]
    if edge_reasons:
        parts.append(", ".join(edge_reasons))
    return _join_sentences(parts)


def _swing_miss_sentence(family_read: dict[str, Any]) -> str:
    return ""


def build_home_run_reasoning(walk_analysis: dict[str, Any]) -> dict[str, Any]:
    strengths = [_sentence(item) for item in (walk_analysis.get("strengths", []) or []) if item]
    concerns = [_sentence(item) for item in (walk_analysis.get("concerns", []) or []) if item]
    supporting = [_sentence(walk_analysis.get("summary"))] if walk_analysis.get("summary") else []
    short_bullets = (strengths[:2] + concerns[:1]) or supporting
    paragraph_parts = (strengths[:2] + concerns[:1]) or supporting
    detailed_lines = []
    if strengths:
        detailed_lines.append("Walk edges:")
        detailed_lines.extend(f"- {sentence}" for sentence in strengths)
    if concerns:
        detailed_lines.append("Walk concerns:")
        detailed_lines.extend(f"- {sentence}" for sentence in concerns)
    return {
        "short": short_bullets[:3],
        "medium": " ".join(paragraph_parts),
        "detailed": "\n".join(detailed_lines),
    }


def rank_home_run_candidates(lineup_payload: dict[str, Any], limit: int | None = None) -> list[dict[str, Any]]:
    candidates = []
    for batter in lineup_payload.get("batters", []) or []:
        analysis = batter.get("walk_analysis")
        if not analysis:
            continue

        strengths, concerns = _candidate_reasons(batter)
        candidates.append(
            {
                "batter_id": batter.get("batter_id"),
                "batter_name": batter.get("batter_name"),
                "batting_order": batter.get("batting_order"),
                "position": batter.get("position"),
                "walk_analysis": analysis,
                "ranking_basis": {
                    "strengths": strengths,
                    "concerns": concerns,
                    "summary": analysis.get("summary"),
                },
            }
        )

    ranked = sorted(
        candidates,
        key=lambda candidate: _candidate_rank_key(
            {
                **candidate,
                "walk_analysis": candidate.get("walk_analysis"),
            }
        ),
        reverse=True,
    )

    for idx, candidate in enumerate(ranked, start=1):
        candidate["rank"] = idx

    return ranked[:limit] if limit else ranked

def _lineup_message(payload: dict[str, Any]) -> str:
    game = payload.get("game", {})
    lineup = payload.get("lineup", {})
    pitcher = payload.get("opposing_starting_pitcher", {})
    batters = payload.get("batters", [])
    ready_count = sum(1 for batter in batters if batter.get("walk_analysis"))
    error_count = sum(1 for batter in batters if batter.get("error"))
    pitcher_hand = pitcher.get("hand")
    pitcher_hand_text = f"({pitcher_hand})" if pitcher_hand else ""

    return (
        "**Confirmed lineup processed**\n"
        f"{game.get('away_team')} @ {game.get('home_team')} - {game.get('game_time_et')}\n"
        f"Lineup: {lineup.get('team')} ({len(batters)} batters)\n"
        f"Opposing SP: {pitcher.get('name')} {pitcher_hand_text}\n"
        f"Walk analyses ready: {ready_count}\n"
        f"Warnings/errors: {error_count}\n"
        "Payload stored in LINEUP_MATCHUP_RESULTS for ranking/posting."
    )


def _top_candidates_text(payload: dict[str, Any], limit: int | None = None) -> str:
    with performance_profile.timed("Ranking", profile=payload.get("_performance_profile")):
        ranked = rank_home_run_candidates(payload, limit=limit or TOP_HR_CANDIDATES_COUNT)
    if not ranked:
        return _lineup_message(payload)

    lines = [_lineup_message(payload), "", "Top walk candidates:"]
    for candidate in ranked:
        reasoning = build_home_run_reasoning(candidate.get("walk_analysis") or {})
        reason_text = reasoning.get("medium") or candidate.get("ranking_basis", {}).get("summary", "Analysis available.")
        lines.append(f"{candidate['rank']}. {candidate.get('batter_name')} - {reason_text}")
    return "\n".join(lines)


EMBED_SEPARATOR = "━━━━━━━━━━━━━━━━━━"


def _embed_pitch_label(family_read: dict[str, Any]) -> str:
    return str(family_read.get("pitch_type") or family_read.get("pitch_family") or "Pitch").strip()


def _embed_pitch_abbreviation(label: str) -> str:
    normalized = label.lower()
    abbreviation_map = {
        "4-seam": "4S",
        "four-seam": "4S",
        "fastball": "FB",
        "sinker": "SI",
        "two-seam": "SI",
        "cutter": "CT",
        "slider": "SL",
        "sweeper": "SW",
        "curveball": "CB",
        "knuckle curve": "KC",
        "changeup": "CH",
        "splitter": "SP",
        "split-finger": "SP",
    }
    for token, abbreviation in abbreviation_map.items():
        if token in normalized:
            return abbreviation
    words = [word for word in label.replace("/", " ").replace("-", " ").split() if word]
    return "".join(word[0].upper() for word in words[:2]) or "P"


def _embed_stat_value(value: Any, metric: str) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)

    if metric in {"OOZ%", "Take%", "Chase%", "Batter BB%", "Pitcher BB%", "Zone Swing%", "Hard Hit%", "Whiff%", "PutAway%"}:
        return f"{number:.1f}%"
    return f"{number:.3f}".lstrip("0")


def _embed_raw_pitch_match_metric_value(pitch_match: dict[str, Any] | None, metric: str) -> Any:
    if not isinstance(pitch_match, dict):
        return None

    weighted_metrics = pitch_match.get("weighted_metrics", {})
    weighted_metric = weighted_metrics.get(metric) if isinstance(weighted_metrics, dict) else None
    if isinstance(weighted_metric, dict) and weighted_metric.get("value") is not None:
        return weighted_metric.get("value")

    components_source = weighted_metrics.get("SLG", {}) if isinstance(weighted_metrics, dict) else {}
    components = components_source.get("components", []) if isinstance(components_source, dict) else []
    weighted_values = []
    for component in components:
        if not isinstance(component, dict):
            continue
        rows = component.get("batter_rows", []) or []
        values = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                values.append(float(row.get(metric)))
            except (TypeError, ValueError):
                continue
        if values:
            weighted_values.append((sum(values) / len(values), component.get("weight")))

    if weighted_values and all(weight is not None for _, weight in weighted_values):
        return sum(value * float(weight) for value, weight in weighted_values)
    if weighted_values:
        return sum(value for value, _ in weighted_values) / len(weighted_values)

    rows_by_variant = pitch_match.get("batter_run_value_rows_by_variant", {})
    values = []
    if isinstance(rows_by_variant, dict):
        for rows in rows_by_variant.values():
            for row in rows or []:
                if not isinstance(row, dict):
                    continue
                try:
                    values.append(float(row.get(metric)))
                except (TypeError, ValueError):
                    continue
    return (sum(values) / len(values)) if values else None


def _embed_metric_value(
    family_read: dict[str, Any],
    metric: str,
    pitch_match: dict[str, Any] | None = None,
) -> Any:
    edge_metrics = family_read.get("edge_metrics", {}) if isinstance(family_read, dict) else {}
    if isinstance(edge_metrics, dict) and metric in edge_metrics:
        return edge_metrics.get(metric)

    contact_metrics = family_read.get("contact_metrics", {}) if isinstance(family_read, dict) else {}
    if isinstance(contact_metrics, dict) and metric in contact_metrics:
        return contact_metrics.get(metric)

    risk_metrics = family_read.get("risk_metrics", {}) if isinstance(family_read, dict) else {}
    if isinstance(risk_metrics, dict) and metric in risk_metrics:
        return risk_metrics.get(metric)

    evidence = family_read.get("evidence", {})
    if not isinstance(evidence, dict):
        return None

    if metric in {"BA", "wOBA"}:
        return _embed_raw_pitch_match_metric_value(pitch_match, metric)
    if metric in {"xSLG", "xwOBA"}:
        expected = evidence.get("expected_power", {})
        values = expected.get("values", {}) if isinstance(expected, dict) else {}
        return values.get(metric) if isinstance(values, dict) else None
    if metric == "Hard Hit%":
        contact = evidence.get("quality_of_contact", {})
        return contact.get("value") if isinstance(contact, dict) else None
    if metric == "SLG":
        raw_value = _embed_raw_pitch_match_metric_value(pitch_match, metric)
        if raw_value is not None:
            return raw_value
        actual = evidence.get("actual_production", {})
        return actual.get("value") if isinstance(actual, dict) else None
    if metric in {"Whiff%", "PutAway%"}:
        swing = evidence.get("swing_and_miss_risk", {})
        values = swing.get("values", {}) if isinstance(swing, dict) else {}
        return values.get(metric) if isinstance(values, dict) else None
    return None


def _embed_metric_lines(
    family_read: dict[str, Any],
    metrics: tuple[str, ...],
    limit: int = 2,
    pitch_match: dict[str, Any] | None = None,
) -> list[str]:
    labels = {
        "OOZ%": "OOZ",
        "Take%": "Take",
        "Chase%": "Chase",
        "Batter BB%": "Batter BB",
        "Pitcher BB%": "Pitcher BB",
        "Zone Swing%": "Zone Swing",
        "Hard Hit%": "Hard Hit",
        "Whiff%": "Whiff",
        "PutAway%": "PutAway",
    }
    lines = []
    for metric in metrics:
        value = _embed_stat_value(_embed_metric_value(family_read, metric, pitch_match), metric)
        if value:
            lines.append(f"{labels.get(metric, metric)} {value}")
        if len(lines) >= limit:
            break
    return lines


def _embed_strength_count(family_read: dict[str, Any]) -> int:
    if "walk_edge_count" in family_read:
        return int(family_read.get("walk_edge_count") or 0)
    return sum(
        1
        for evidence_key in ("expected_power", "quality_of_contact", "actual_production")
        if _evidence_read(family_read, evidence_key) == "strength"
    )


def _embed_importance_rank(family_read: dict[str, Any]) -> int:
    return {
        "primary": 4,
        "major": 3,
        "secondary": 2,
        "low": 1,
    }.get(_family_importance_label(family_read), 0)


def _embed_arsenal_line(family_reads: list[dict[str, Any]]) -> str:
    pieces = []
    for family_read in sorted(family_reads, key=_family_usage, reverse=True)[:3]:
        usage = _family_usage(family_read)
        if not usage:
            continue
        label = _embed_pitch_label(family_read)
        pieces.append(f"{_embed_pitch_abbreviation(label)} {usage:.1f}%")
    return " • ".join(pieces) or "Pitch mix unavailable"


def _embed_biggest_edges(family_reads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    edges = [
        family_read
        for family_read in family_reads
        if _embed_strength_count(family_read) > 0
    ]
    return sorted(
        edges,
        key=lambda family_read: (
            int(family_read.get("zone_edge_count") or 0),
            _embed_importance_rank(family_read),
            _family_usage(family_read),
            int(family_read.get("discipline_edge_count") or 0),
            int(family_read.get("pitcher_walk_edge_count") or 0),
            _embed_strength_count(family_read),
        ),
        reverse=True,
    )[:2]


def _embed_biggest_risk(family_reads: list[dict[str, Any]]) -> dict[str, Any] | None:
    contact_risks = [
        family_read
        for family_read in family_reads
        if family_read.get("contact_warning")
    ]
    if contact_risks:
        return sorted(
            contact_risks,
            key=lambda family_read: (
                _embed_importance_rank(family_read),
                _family_usage(family_read),
            ),
            reverse=True,
        )[0]

    risks = [
        family_read
        for family_read in family_reads
        if _evidence_read(family_read, "swing_and_miss_risk") == "concern"
    ]
    if not risks:
        return None
    return sorted(
        risks,
        key=lambda family_read: (
            _embed_importance_rank(family_read),
            _family_usage(family_read),
        ),
        reverse=True,
    )[0]


def _embed_walk_risk_lines(walk_risk: dict[str, Any]) -> list[str]:
    if not isinstance(walk_risk, dict) or not walk_risk:
        return []

    level = str(walk_risk.get("level") or "").strip()
    if not level:
        return []

    emoji = {
        "low": "🟢",
        "moderate": "🟡",
        "high": "🔴",
    }.get(level.lower(), "⚪")
    lines = [f"{emoji} {level} Walk Risk"]

    for reason in walk_risk.get("reasoning", []) or []:
        text = " ".join(str(reason or "").split())
        if not text or "overlap" in text.lower() or "%" in text:
            continue
        lines.append(text)
        if len(lines) >= 4:
            break

    return lines


def _weighted_profile(analysis: dict[str, Any]) -> dict[str, Any]:
    details = analysis.get("details", {}) if isinstance(analysis, dict) else {}
    return (
        details.get("weighted_pitch_specific_discipline", {})
        if isinstance(details, dict)
        else {}
    )


def _weighted_profile_families(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    profile = _weighted_profile(analysis)
    families = profile.get("families", []) if isinstance(profile, dict) else []
    return families if isinstance(families, list) else []


def _outside_pitch_name(family_key: Any, label: str) -> str:
    key = str(family_key or "").lower()
    label_lower = str(label or "").lower()
    if key in {"four_seam_fastball", "fastball"} or "fastball" in label_lower:
        return "fastballs"
    if key == "slider_sweeper" or "slider" in label_lower or "sweeper" in label_lower:
        return "sliders/sweepers" if "sweeper" in label_lower else "sliders"
    if key == "curveball" or "curve" in label_lower:
        return "curveballs"
    if key == "sinker" or "sinker" in label_lower or "two-seam" in label_lower:
        return "sinkers"
    if key == "changeup" or "change" in label_lower:
        return "changeups"
    if key == "cutter" or "cutter" in label_lower:
        return "cutters"
    if key == "splitter" or "split" in label_lower:
        return "splitters"
    clean = str(label or "pitches").split("/")[0].strip().lower()
    return f"{clean}s" if clean and not clean.endswith("s") else clean or "pitches"


def _count_text(numerator: Any, denominator: Any) -> str:
    try:
        num = int(float(numerator))
        den = int(float(denominator))
    except (TypeError, ValueError):
        return ""
    if den <= 0:
        return ""
    return f" ({num}/{den})"


def _embed_whole_pct(value: Any) -> str:
    number = _to_float(value)
    return f"{number:.0f}%" if number is not None else ""


def _embed_pitch_family_edge_lines(
    family_read: dict[str, Any],
    profile_family: dict[str, Any],
) -> list[str]:
    label = _embed_pitch_label(family_read) or str(profile_family.get("pitch_type") or "Pitch")
    usage = _family_usage(family_read) or (_to_float(profile_family.get("pitcher_usage_pct")) or 0.0)
    outside_name = _outside_pitch_name(profile_family.get("pitch_family") or family_read.get("pitch_family"), label)
    ooz = _embed_whole_pct(profile_family.get("pitcher_outside_zone_pct"))
    take = _embed_whole_pct(profile_family.get("batter_outside_take_pct"))
    take_counts = _count_text(
        profile_family.get("outside_take_count"),
        profile_family.get("outside_pitch_count"),
    )

    lines = ["", f"🔴 {label} ({usage:.1f}%)"]
    if ooz:
        lines.append(f"📍 Pitcher throws {ooz} of these outside the zone")
    if take:
        lines.append(f"✅ Batter takes {take} of those outside {outside_name}{take_counts}")
    return lines


def _embed_overall_matchup_lines(analysis: dict[str, Any]) -> list[str]:
    profile = _weighted_profile(analysis)
    if not isinstance(profile, dict) or not profile.get("available"):
        return []

    weighted_ooz = _embed_whole_pct(profile.get("weighted_pitcher_ooz_pct"))
    weighted_take = _embed_whole_pct(profile.get("weighted_outside_take_pct"))
    coverage = _embed_whole_pct(profile.get("arsenal_coverage_pct"))
    total_takes = 0
    total_outside = 0
    for family in _weighted_profile_families(analysis):
        take_count = _to_float(family.get("outside_take_count"))
        outside_count = _to_float(family.get("outside_pitch_count"))
        if take_count is not None:
            total_takes += int(take_count)
        if outside_count is not None:
            total_outside += int(outside_count)
    take_counts = _count_text(total_takes, total_outside)

    lines = ["", EMBED_SEPARATOR, "", f"‼️ Overall Matchup ({coverage or 'N/A'} Arsenal)"]
    if weighted_ooz:
        lines.extend(["", f"📍 Pitcher throws {weighted_ooz} of these pitches outside the zone"])
    if weighted_take:
        lines.append(f"🧪 Batter takes {weighted_take} of those outside pitches{take_counts}")
    return lines


def _build_candidate_embed_description(candidate: dict[str, Any]) -> str:
    analysis = candidate.get("walk_analysis") or {}
    family_reads = _analysis_family_reads(analysis)
    medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(candidate.get("rank"), f"#{candidate.get('rank')}")
    lines = [
        f"{medal} {candidate.get('batter_name')}",
        "",
        EMBED_SEPARATOR,
        "",
        "🔥 Biggest Edges",
    ]

    profile_families = _weighted_profile_families(analysis)
    family_reads_by_key = {
        family_read.get("pitch_family"): family_read
        for family_read in family_reads
        if isinstance(family_read, dict) and family_read.get("pitch_family")
    }
    if profile_families:
        for profile_family in profile_families:
            family_key = profile_family.get("pitch_family")
            family_read = family_reads_by_key.get(family_key, profile_family)
            lines.extend(_embed_pitch_family_edge_lines(family_read, profile_family))
    else:
        lines.append("No clear walk edge in the existing analysis.")

    lines.extend(_embed_overall_matchup_lines(analysis))

    risk = _embed_biggest_risk(family_reads)
    if risk:
        label = _embed_pitch_label(risk)
        usage = _family_usage(risk)
        lines.extend(
            [
                "",
                EMBED_SEPARATOR,
                "",
                "⚠️ Biggest Risk",
                "",
                f"🔴 {label} ({usage:.1f}%)",
                *_embed_metric_lines(risk, ("Hard Hit%", "SLG", "wOBA")),
                "Strong contact may reduce walk confidence.",
            ]
        )

    return "\n".join(lines)


def _build_top_candidates_embed(payload: dict[str, Any]) -> discord.Embed:
    game = payload.get("game", {})
    with performance_profile.timed("Ranking", profile=payload.get("_performance_profile")):
        ranked = rank_home_run_candidates(payload, limit=TOP_HR_CANDIDATES_COUNT)

    embed = discord.Embed(
        title=f"⚾ {game.get('away_team')} @ {game.get('home_team')}",
        color=discord.Color.orange(),
    )

    if game.get("game_time_et"):
        embed.set_footer(
            text=f"{game.get('game_time_et')} • Ranked from existing walk_analysis evidence only. No confidence score."
        )
    else:
        embed.set_footer(text="Ranked from existing walk_analysis evidence only. No confidence score.")

    if not ranked:
        embed.description = "The lineup was confirmed, but no walk analyses were available."
        return embed

    embed.description = _build_candidate_embed_description(ranked[0])
    return embed


def _embed_terminal_text(embed: discord.Embed) -> str:
    lines = []
    if embed.title:
        lines.append(str(embed.title))
    if embed.description:
        if lines:
            lines.append("")
        lines.append(str(embed.description))

    for field in embed.fields:
        if lines:
            lines.append("")
        lines.append(str(field.name))
        lines.append(str(field.value))

    footer_text = getattr(embed.footer, "text", None)
    if footer_text:
        if lines:
            lines.append("")
        lines.append(str(footer_text))

    return "\n".join(lines)


async def _send_lineup_message(payload: dict[str, Any]) -> bool:
    profile = payload.get("_performance_profile")
    if not DISCORD_WALK_CHANNEL_ID:
        with performance_profile.timed("Discord embed", profile=profile):
            text = _top_candidates_text(payload)
        with performance_profile.timed("Discord send", profile=profile):
            print(text)
        if profile is not None:
            print(performance_profile.format_report(profile))
        return True

    try:
        channel_id = int(DISCORD_WALK_CHANNEL_ID)
    except ValueError:
        print("Lineup monitor warning: DISCORD_WALK_CHANNEL_ID is not a valid integer.")
        with performance_profile.timed("Discord embed", profile=profile):
            text = _top_candidates_text(payload)
        with performance_profile.timed("Discord send", profile=profile):
            print(text)
        if profile is not None:
            print(performance_profile.format_report(profile))
        return True

    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except Exception as exc:
            print(f"Lineup monitor warning: could not fetch Discord channel {channel_id}: {exc}")
            with performance_profile.timed("Discord embed", profile=profile):
                text = _top_candidates_text(payload)
            with performance_profile.timed("Discord send", profile=profile):
                print(text)
            if profile is not None:
                print(performance_profile.format_report(profile))
            return True

    try:
        with performance_profile.timed("Discord embed", profile=profile):
            embed = _build_top_candidates_embed(payload)
        with performance_profile.timed("Discord send", profile=profile):
            await channel.send(embed=embed)
    except Exception as exc:
        print(f"Lineup monitor warning: could not send Discord embed: {exc}")
        return False
    if profile is not None:
        print(performance_profile.format_report(profile))
    return True


async def _send_test_mode_message(payload: dict[str, Any], test_started_at: float | None = None) -> None:
    embed_started_at = perf_counter()
    embed = _build_top_candidates_embed(payload)
    _log_test_timing(test_started_at, "Discord embed", embed_started_at)

    if not DISCORD_WALK_CHANNEL_ID:
        print("TEST_MODE: DISCORD_WALK_CHANNEL_ID is not configured. Exact embed text:")
        print_started_at = perf_counter()
        print(_embed_terminal_text(embed))
        _log_test_timing(test_started_at, "Terminal print", print_started_at)
        return

    try:
        channel_id = int(DISCORD_WALK_CHANNEL_ID)
    except ValueError:
        print("TEST_MODE warning: DISCORD_WALK_CHANNEL_ID is not a valid integer. Exact embed text:")
        print_started_at = perf_counter()
        print(_embed_terminal_text(embed))
        _log_test_timing(test_started_at, "Terminal print", print_started_at)
        return

    channel_started_at = perf_counter()
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except Exception as exc:
            print(f"TEST_MODE warning: could not fetch Discord channel {channel_id}: {exc}")
            print("Exact embed text:")
            print_started_at = perf_counter()
            print(_embed_terminal_text(embed))
            _log_test_timing(test_started_at, "Terminal print", print_started_at)
            return
    _log_test_timing(test_started_at, "Discord channel lookup", channel_started_at)

    post_started_at = perf_counter()
    await channel.send(embed=embed)
    _log_test_timing(test_started_at, "Discord post", post_started_at)
    print(f"TEST_MODE: posted test embed to Discord channel {channel_id}.")


@tasks.loop(seconds=LINEUP_MONITOR_INTERVAL_SECONDS)
async def monitor_confirmed_lineups():
    global CURRENT_MONITOR_DATE

    today = date.today()
    if CURRENT_MONITOR_DATE != today:
        CURRENT_MONITOR_DATE = today
        POSTED_GAME_KEYS.clear()
        LINEUP_MATCHUP_RESULTS.clear()
        print(f"Lineup monitor reset for {today.isoformat()}.")

    try:
        new_payloads = await asyncio.to_thread(_scan_confirmed_lineups_once)
    except Exception as exc:
        print(f"Lineup monitor warning: scan failed: {exc}")
        return

    for payload in new_payloads:
        game_key = _payload_game_key(payload)
        if game_key in POSTED_GAME_KEYS:
            continue
        if await _send_lineup_message(payload):
            POSTED_GAME_KEYS.add(game_key)


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    print("🚀 Walk Bot is online!")
    if TEST_MODE:
        test_started_at = perf_counter()
        print("TEST_MODE enabled: running one immediate end-to-end embed test.")
        try:
            payload = await asyncio.to_thread(_build_test_mode_payload, test_started_at)
        except Exception as exc:
            print(f"TEST_MODE failed while building matchup payload: {exc}")
            await bot.close()
            return

        if payload is None:
            await bot.close()
            return

        ranking_started_at = perf_counter()
        ranked = rank_home_run_candidates(payload, limit=TOP_HR_CANDIDATES_COUNT)
        _log_test_timing(test_started_at, "Ranking", ranking_started_at)
        print(f"TEST_MODE: ranking pipeline produced {len(ranked)} candidate(s).")
        await _send_test_mode_message(payload, test_started_at)
        await bot.close()
        return

    if not monitor_confirmed_lineups.is_running():
        monitor_confirmed_lineups.start()
        print(f"Lineup monitor started. Interval: {LINEUP_MONITOR_INTERVAL_SECONDS}s")

if TEST_MODE and not TOKEN:
    test_started_at = perf_counter()
    print("TEST_MODE: DISCORD_TOKEN is not configured. Building and printing the embed without connecting to Discord.")
    payload = _build_test_mode_payload(test_started_at)
    if payload is not None:
        ranking_started_at = perf_counter()
        ranked = rank_home_run_candidates(payload, limit=TOP_HR_CANDIDATES_COUNT)
        _log_test_timing(test_started_at, "Ranking", ranking_started_at)
        print(f"TEST_MODE: ranking pipeline produced {len(ranked)} candidate(s).")
        embed_started_at = perf_counter()
        embed = _build_top_candidates_embed(payload)
        _log_test_timing(test_started_at, "Discord embed", embed_started_at)
        print_started_at = perf_counter()
        print(_embed_terminal_text(embed))
        _log_test_timing(test_started_at, "Terminal print", print_started_at)
else:
    bot.run(TOKEN)
