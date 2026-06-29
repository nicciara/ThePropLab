"""
Diagnostic script for one matchup_engine.py matchup.

This script does not score, rank, or post anything. It only verifies that
get_matchup_data() can assemble raw data for one confirmed batter vs pitcher
matchup.
"""

from __future__ import annotations

import time
from datetime import date
from typing import Any

from pybaseball import analysis

try:
    from app import get_game_lineups, load_schedule
except Exception as exc:
    get_game_lineups = None
    load_schedule = None
    APP_IMPORT_ERROR = exc
else:
    APP_IMPORT_ERROR = None

from matchup_engine import get_matchup_data


def _elapsed(start_time: float) -> str:
    return f"{time.perf_counter() - start_time:.2f}s"


def _lineup_is_confirmed(lineup: list[dict[str, Any]] | None) -> bool:
    return bool(lineup) and not any(player.get("is_projected") for player in lineup)


def _has_data(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, dict):
        return bool(value)
    if isinstance(value, list):
        return bool(value)
    return bool(value)


def _print_section(label: str, loaded: bool, missing_label: str) -> None:
    if loaded:
        print(f"✓ {label}")
    else:
        print(f"Missing {missing_label}")


def _print_warnings(matchup: dict[str, Any]) -> None:
    for warning in matchup.get("errors", []) or []:
        print(f"WARNING: {warning}")
    for todo in matchup.get("todos", []) or []:
        print(f"WARNING: TODO: {todo}")


def main() -> int:
    total_start = time.perf_counter()

    if APP_IMPORT_ERROR is not None or load_schedule is None or get_game_lineups is None:
        print("Unable to import load_schedule() and get_game_lineups() from app.py.")
        print(
            "WARNING: app.py likely executed Streamlit/session_state code during import "
            f"instead of behaving like a pure library module. Original error: {APP_IMPORT_ERROR}"
        )
        return 1

    step_start = time.perf_counter()
    print("Loading today's schedule...")
    try:
        games = load_schedule(date.today())
    except Exception as exc:
        print(f"WARNING: load_schedule() failed after {_elapsed(step_start)}: {exc}")
        return 1
    print(f"Schedule loaded. ({_elapsed(step_start)})")

    if games is None or games.empty:
        print("No MLB games found for today.")
        print(f"Finished in {_elapsed(total_start)}.")
        return 0

    confirmed_game = None
    confirmed_lineups = None

    for _, game in games.iterrows():
        print()
        print("Checking game:")
        print(f"{game.get('away_team', 'Away')} @ {game.get('home_team', 'Home')}")

        step_start = time.perf_counter()
        try:
            lineup_context = get_game_lineups(game.get("game_pk"), game)
        except Exception as exc:
            print(f"WARNING: get_game_lineups() failed after {_elapsed(step_start)}: {exc}")
            continue
        print(f"Lineups checked. ({_elapsed(step_start)})")

        away_lineup = lineup_context.get("away", [])
        home_lineup = lineup_context.get("home", [])
        if _lineup_is_confirmed(away_lineup) and _lineup_is_confirmed(home_lineup):
            confirmed_game = game
            confirmed_lineups = lineup_context
            break

        print("Lineups are projected or unavailable. Continuing...")

    if confirmed_game is None or confirmed_lineups is None:
        print()
        print("No fully confirmed matchup found today.")
        print(f"Finished in {_elapsed(total_start)}.")
        return 0

    print()
    print("Confirmed lineup found.")

    away_lineup = confirmed_lineups.get("away", [])
    batter = away_lineup[0] if away_lineup else {}
    batter_id = batter.get("player_id")
    batter_name = batter.get("name") or f"Batter ID {batter_id}"

    pitcher_id = confirmed_game.get("home_pitcher_id", "")
    pitcher_name = confirmed_game.get("home_pitcher", "TBD")

    print()
    print("Batter:")
    print(batter_name)
    print()
    print("Pitcher:")
    print(pitcher_name)

    if not batter_id:
        print("WARNING: Leadoff batter has no player_id. Cannot test matchup.")
        return 1
    if not pitcher_id:
        print("WARNING: Home starting pitcher has no pitcher ID. Cannot test matchup.")
        return 1

    print()
    print("Loading matchup...")
    step_start = time.perf_counter()
    try:
        matchup = get_matchup_data(batter_id, pitcher_id)
    except Exception as exc:
        print(f"WARNING: get_matchup_data() failed after {_elapsed(step_start)}: {exc}")
        return 1
    print(f"Matchup loaded. ({_elapsed(step_start)})")
    print(matchup.keys())

    print()
    print("HOME RUN ANALYSIS")
    print("=" * 50)

    analysis = matchup.get("home_run_analysis")

    from pprint import pprint
    pprint(analysis)
    player_info_loaded = bool(
        matchup.get("batter_name")
        or matchup.get("pitcher_name")
        or matchup.get("batter_handedness")
        or matchup.get("pitcher_handedness")
    )
    _print_section("Player info", player_info_loaded, "player info")
    _print_section("Pitch mix", _has_data(matchup.get("pitch_mix")), "pitch mix")
    _print_section("Pitcher stats", _has_data(matchup.get("pitcher_season_stats")), "pitcher stats")
    _print_section(
        "Run value table",
        _has_data(matchup.get("batter_run_value_by_pitch_type")),
        "run value table",
    )
    _print_section(
        "Strike zone data",
        _has_data(matchup.get("batter_strike_zone_home_run_data")),
        "strike zone data",
    )
    _print_section("Batter game logs", _has_data(matchup.get("batter_game_log")), "batter game logs")
    _print_section("Contact stats", _has_data(matchup.get("batter_season_stats")), "contact stats")

    _print_warnings(matchup)

    print()
    print(f"Finished in {_elapsed(total_start)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
