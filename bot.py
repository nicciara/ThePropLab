import os
import asyncio
from datetime import date
from time import perf_counter
from typing import Any

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

from matchup_engine import get_matchup_data
import performance_profile

# Load the .env file as the source of truth for bot startup flags.
load_dotenv(dotenv_path=".env", override=True)

TOKEN = os.getenv("DISCORD_TOKEN")
DISCORD_CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID")
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
    analysis = candidate.get("home_run_analysis") or {}
    family_reads = _analysis_family_reads(analysis)
    important_labels = {"primary", "major"}

    primary_power = 0
    primary_contact = 0
    primary_actual = 0
    secondary_power = 0
    secondary_contact = 0
    low_usage_support = 0
    swing_miss_concerns = 0
    all_concerns = len(analysis.get("concerns", []) or []) if isinstance(analysis, dict) else 0
    top_usage = 0.0

    for family_read in family_reads:
        importance = _family_importance_label(family_read)
        usage = _family_usage(family_read)
        top_usage = max(top_usage, usage)

        expected_strength = _evidence_read(family_read, "expected_power") == "strength"
        contact_strength = _evidence_read(family_read, "quality_of_contact") == "strength"
        actual_strength = _evidence_read(family_read, "actual_production") == "strength"
        swing_concern = _evidence_read(family_read, "swing_and_miss_risk") == "concern"

        if importance in important_labels:
            primary_power += int(expected_strength)
            primary_contact += int(contact_strength)
            primary_actual += int(actual_strength)
            swing_miss_concerns += int(swing_concern)
        elif importance == "secondary":
            secondary_power += int(expected_strength)
            secondary_contact += int(contact_strength)
            swing_miss_concerns += int(swing_concern)
        elif expected_strength or contact_strength or actual_strength:
            low_usage_support += 1

    details = analysis.get("details", {}) if isinstance(analysis, dict) else {}
    strike_zone = details.get("strike_zone_overlap", {}) if isinstance(details, dict) else {}
    zone_available = bool(strike_zone.get("top_batter_home_run_zones")) if isinstance(strike_zone, dict) else False
    walk_risk = analysis.get("walk_risk", {}) if isinstance(analysis, dict) else {}
    walk_risk_level = str(walk_risk.get("level", "") if isinstance(walk_risk, dict) else "").lower()
    walk_risk_penalty = {"high": 2, "moderate": 1}.get(walk_risk_level, 0)
    batter_order = candidate.get("batting_order") or 99

    # This tuple is only an ordering key, not a score. It compares existing
    # evidence in baseball-priority order: heavily used pitch families first,
    # then contact/power indicators, then swing/miss and walk-risk flags.
    # Nothing is posted as a numeric confidence value.
    return (
        int(bool(analysis)),
        primary_power,
        primary_contact,
        primary_actual,
        secondary_power,
        secondary_contact,
        int(zone_available),
        low_usage_support,
        top_usage,
        -swing_miss_concerns,
        -walk_risk_penalty,
        -all_concerns,
        -int(batter_order) if str(batter_order).isdigit() else -99,
    )


def _candidate_reasons(candidate: dict[str, Any]) -> tuple[list[str], list[str]]:
    analysis = candidate.get("home_run_analysis") or {}
    family_reads = _analysis_family_reads(analysis)
    strengths = []
    concerns = []

    for family_read in family_reads:
        importance = _family_importance_label(family_read)
        if importance not in {"primary", "major", "secondary"}:
            continue

        label = family_read.get("pitch_type") or family_read.get("pitch_family")
        usage = _family_usage(family_read)
        evidence_bits = []
        for evidence_key in ("expected_power", "quality_of_contact", "actual_production"):
            if _evidence_read(family_read, evidence_key) == "strength":
                text = _evidence_text(family_read, evidence_key)
                if text:
                    evidence_bits.append(text)
        if evidence_bits:
            strengths.append(f"{label} ({usage:.1f}%): {' '.join(evidence_bits)}")

        if _evidence_read(family_read, "swing_and_miss_risk") == "concern":
            text = _evidence_text(family_read, "swing_and_miss_risk")
            concerns.append(f"{label} ({usage:.1f}%): {text}")

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
    parts = [_usage_phrase(family_read)]
    for evidence_key in ("quality_of_contact", "expected_power", "actual_production"):
        text = _evidence_text(family_read, evidence_key)
        if text and _evidence_read(family_read, evidence_key) in {"strength", "neutral", "concern"}:
            parts.append(text)
    return _join_sentences(parts)


def _swing_miss_sentence(family_read: dict[str, Any]) -> str:
    text = _evidence_text(family_read, "swing_and_miss_risk")
    if not text:
        return ""
    label = family_read.get("pitch_type") or family_read.get("pitch_family") or "This pitch family"
    text = text[0].lower() + text[1:] if text else text
    return _sentence(f"Against {label}, {text}")


def build_home_run_reasoning(home_run_analysis: dict[str, Any]) -> dict[str, Any]:
    family_reads = _analysis_family_reads(home_run_analysis)
    details = home_run_analysis.get("details", {}) if isinstance(home_run_analysis, dict) else {}
    strike_zone = details.get("strike_zone_overlap", {}) if isinstance(details, dict) else {}

    primary_reads = [
        family_read
        for family_read in family_reads
        if _family_importance_label(family_read) in {"primary", "major", "secondary"}
    ]
    primary_reads = sorted(primary_reads, key=_family_usage, reverse=True)

    family_sentences = []
    swing_concerns = []
    for family_read in primary_reads:
        family_sentence = _family_evidence_sentence(family_read)
        if family_sentence:
            family_sentences.append(family_sentence)
        if _evidence_read(family_read, "swing_and_miss_risk") == "concern":
            swing_sentence = _swing_miss_sentence(family_read)
            if swing_sentence:
                swing_concerns.append(swing_sentence)

    zone_sentence = ""
    if isinstance(strike_zone, dict):
        overlap_read = strike_zone.get("overlap_read")
        if overlap_read:
            zone_sentence = _sentence(overlap_read)

    walk_risk_sentence = ""
    if isinstance(walk_risk, dict):
        walk_level = str(walk_risk.get("level", "")).strip()
        walk_reasons = walk_risk.get("reasoning", []) or []
        if walk_level in {"Moderate", "High"} and walk_reasons:
            walk_risk_sentence = _sentence(f"{walk_level} walk risk: {walk_reasons[0]}")

    supporting = []
    if isinstance(home_run_analysis, dict) and home_run_analysis.get("summary"):
        supporting.append(_sentence(home_run_analysis.get("summary")))

    short_bullets = []
    if family_sentences:
        short_bullets.append(family_sentences[0])
    if zone_sentence:
        short_bullets.append(zone_sentence)
    if swing_concerns:
        short_bullets.append(swing_concerns[0])
    if walk_risk_sentence and len(short_bullets) < 3:
        short_bullets.append(walk_risk_sentence)
    if not short_bullets and supporting:
        short_bullets.append(supporting[0])

    paragraph_parts = []
    if family_sentences:
        paragraph_parts.extend(family_sentences[:2])
    if zone_sentence:
        paragraph_parts.append(zone_sentence)
    if swing_concerns:
        paragraph_parts.append(swing_concerns[0])
    if walk_risk_sentence:
        paragraph_parts.append(walk_risk_sentence)
    if not paragraph_parts and supporting:
        paragraph_parts.extend(supporting[:1])

    detailed_lines = []
    if family_sentences:
        detailed_lines.append("Pitch-family evidence:")
        detailed_lines.extend(f"- {sentence}" for sentence in family_sentences)
    if zone_sentence:
        detailed_lines.append(f"Strike-zone overlap: {zone_sentence}")
    if swing_concerns:
        detailed_lines.append("Swing-and-miss concerns:")
        detailed_lines.extend(f"- {sentence}" for sentence in swing_concerns)
    if walk_risk_sentence:
        detailed_lines.append(f"Walk risk: {walk_risk_sentence}")
    if supporting:
        detailed_lines.append("Supporting summary:")
        detailed_lines.extend(f"- {sentence}" for sentence in supporting)

    return {
        "short": short_bullets[:3],
        "medium": " ".join(paragraph_parts),
        "detailed": "\n".join(detailed_lines),
    }


def rank_home_run_candidates(lineup_payload: dict[str, Any], limit: int | None = None) -> list[dict[str, Any]]:
    candidates = []
    for batter in lineup_payload.get("batters", []) or []:
        analysis = batter.get("home_run_analysis")
        if not analysis:
            continue

        strengths, concerns = _candidate_reasons(batter)
        candidates.append(
            {
                "batter_id": batter.get("batter_id"),
                "batter_name": batter.get("batter_name"),
                "batting_order": batter.get("batting_order"),
                "position": batter.get("position"),
                "home_run_analysis": analysis,
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
                "home_run_analysis": candidate.get("home_run_analysis"),
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
    ready_count = sum(1 for batter in batters if batter.get("home_run_analysis"))
    error_count = sum(1 for batter in batters if batter.get("error"))
    pitcher_hand = pitcher.get("hand")
    pitcher_hand_text = f"({pitcher_hand})" if pitcher_hand else ""

    return (
        "**Confirmed lineup processed**\n"
        f"{game.get('away_team')} @ {game.get('home_team')} - {game.get('game_time_et')}\n"
        f"Lineup: {lineup.get('team')} ({len(batters)} batters)\n"
        f"Opposing SP: {pitcher.get('name')} {pitcher_hand_text}\n"
        f"Home run analyses ready: {ready_count}\n"
        f"Warnings/errors: {error_count}\n"
        "Payload stored in LINEUP_MATCHUP_RESULTS for ranking/posting."
    )


def _top_candidates_text(payload: dict[str, Any], limit: int | None = None) -> str:
    with performance_profile.timed("Ranking", profile=payload.get("_performance_profile")):
        ranked = rank_home_run_candidates(payload, limit=limit or TOP_HR_CANDIDATES_COUNT)
    if not ranked:
        return _lineup_message(payload)

    lines = [_lineup_message(payload), "", "Top home run candidates:"]
    for candidate in ranked:
        reasoning = build_home_run_reasoning(candidate.get("home_run_analysis") or {})
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

    if metric in {"Hard Hit%", "Whiff%", "PutAway%"}:
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
            _embed_importance_rank(family_read),
            _family_usage(family_read),
            _embed_strength_count(family_read),
        ),
        reverse=True,
    )[:2]


def _embed_biggest_risk(family_reads: list[dict[str, Any]]) -> dict[str, Any] | None:
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


def _build_candidate_embed_description(candidate: dict[str, Any]) -> str:
    analysis = candidate.get("home_run_analysis") or {}
    family_reads = _analysis_family_reads(analysis)
    pitch_matches = _analysis_pitch_matches(analysis)
    medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(candidate.get("rank"), f"#{candidate.get('rank')}")
    lines = [
        f"{medal} {candidate.get('batter_name')}",
        "",
        EMBED_SEPARATOR,
        "",
        "🎯 Pitcher Arsenal",
        _embed_arsenal_line(family_reads),
        "",
        EMBED_SEPARATOR,
        "",
        "🔥 Biggest Edges",
    ]

    edges = _embed_biggest_edges(family_reads)
    if edges:
        for family_read in edges:
            label = _embed_pitch_label(family_read)
            usage = _family_usage(family_read)
            pitch_match = _pitch_match_for_family(family_read, pitch_matches)
            lines.extend(
                [
                    "",
                    f"🟢 {label} ({usage:.1f}%)",
                    *_embed_metric_lines(family_read, ("SLG", "wOBA", "BA", "Hard Hit%"), pitch_match=pitch_match),
                ]
            )
    else:
        lines.append("No clear pitch-family edge in the existing analysis.")

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
                *_embed_metric_lines(risk, ("Whiff%", "PutAway%")),
            ]
        )

    walk_risk_lines = _embed_walk_risk_lines(analysis.get("walk_risk"))
    if walk_risk_lines:
        lines.extend(["", *walk_risk_lines])

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
            text=f"{game.get('game_time_et')} • Ranked from existing home_run_analysis evidence only. No confidence score."
        )
    else:
        embed.set_footer(text="Ranked from existing home_run_analysis evidence only. No confidence score.")

    if not ranked:
        embed.description = "The lineup was confirmed, but no home run analyses were available."
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
    if not DISCORD_CHANNEL_ID:
        with performance_profile.timed("Discord embed", profile=profile):
            text = _top_candidates_text(payload)
        with performance_profile.timed("Discord send", profile=profile):
            print(text)
        if profile is not None:
            print(performance_profile.format_report(profile))
        return True

    try:
        channel_id = int(DISCORD_CHANNEL_ID)
    except ValueError:
        print("Lineup monitor warning: DISCORD_CHANNEL_ID is not a valid integer.")
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

    if not DISCORD_CHANNEL_ID:
        print("TEST_MODE: DISCORD_CHANNEL_ID is not configured. Exact embed text:")
        print_started_at = perf_counter()
        print(_embed_terminal_text(embed))
        _log_test_timing(test_started_at, "Terminal print", print_started_at)
        return

    try:
        channel_id = int(DISCORD_CHANNEL_ID)
    except ValueError:
        print("TEST_MODE warning: DISCORD_CHANNEL_ID is not a valid integer. Exact embed text:")
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
    print("🚀 HR Bot is online!")
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
