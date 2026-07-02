import argparse
import sys
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import app
from props_cache import SCHEMA_VERSION, props_summary_cache_path, write_json_atomic


SKIPPED_STAGE_1_PROPS = {
    "1st Inning Hits + Runs + RBIs": "first-inning props are deferred in Stage 1",
}
CACHE_TIMEZONE = "America/New_York"


def _team_lookup_keys(value):
    normalized = app.normalize_name(value)
    if not normalized:
        return set()
    aliases = {
        "ari": {"az"},
        "az": {"ari"},
        "chw": {"cws"},
        "cws": {"chw"},
        "kcr": {"kc"},
        "kc": {"kcr"},
        "sfg": {"sf"},
        "sf": {"sfg"},
        "tbr": {"tb"},
        "tb": {"tbr"},
        "wsh": {"was"},
        "was": {"wsh"},
    }
    return {normalized, *aliases.get(normalized, set())}


def _props_line_match_key(value):
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return str(value or "").strip()


def _projection_identity_match_key(record, player_name):
    projection_player_id = app._projection_player_id(record)
    if projection_player_id:
        return f"id:{projection_player_id}"
    return f"name:{app.normalize_name(player_name)}"


def _projection_line_type(record):
    odds_type = app.normalize_name(app._projection_value(record, "odds_type", "oddsType", default=""))
    if odds_type == "goblin":
        return "Goblin"
    if odds_type == "demon":
        return "Demon"
    return "PP Reg Line"


def _source_badges(exact_projection_lines):
    badges = ["prizepicks"] if exact_projection_lines else []
    seen = set(badges)
    for projection_line in exact_projection_lines or []:
        odds_type = app.normalize_name(app._projection_value(projection_line, "odds_type", "oddsType", default=""))
        if odds_type in {"goblin", "demon"} and odds_type not in seen:
            badges.append(odds_type)
            seen.add(odds_type)
    return badges


def _line_types(exact_projection_lines):
    labels = []
    seen = set()
    for projection_line in exact_projection_lines or []:
        label = _projection_line_type(projection_line)
        if label not in seen:
            labels.append(label)
            seen.add(label)
    return labels


def _status_from_projection_matches(exact_projection_lines):
    labels = _line_types(exact_projection_lines)
    return f"PrizePicks • {'/'.join(labels)}" if labels else "PrizePicks"


def _homepage_prop_match_key(prop):
    if prop in app.PITCHER_GAME_LOG_PROPS:
        return app.pitcher_prizepicks_prop_match_key(prop)
    return app._prop_match_key(prop)


def _homepage_team_context_lookup(games_df):
    team_lookup = {}
    if games_df is None or (isinstance(games_df, pd.DataFrame) and games_df.empty):
        return team_lookup
    for _, game in games_df.iterrows():
        for side in ("away", "home"):
            team_id = game.get(f"{side}_team_id", "")
            if not team_id:
                continue
            opponent_side = "home" if side == "away" else "away"
            context = {
                "team": game.get(f"{side}_team", ""),
                "team_abbr": game.get(f"{side}_abbrev", ""),
                "team_id": team_id,
                "opponent": game.get(f"{opponent_side}_team", ""),
                "opponent_id": game.get(f"{opponent_side}_team_id", ""),
                "opponent_abbr": game.get(f"{opponent_side}_abbrev", ""),
                "game_pk": game.get("game_pk", ""),
                "game_time": game.get("game_time_et", ""),
                "side": side,
                "game": game,
            }
            for value in (game.get(f"{side}_team", ""), game.get(f"{side}_abbrev", "")):
                for key in _team_lookup_keys(value):
                    team_lookup[key] = context
    return team_lookup


def _homepage_pitcher_context_lookup(games_df):
    pitcher_lookup = {}
    if games_df is None or (isinstance(games_df, pd.DataFrame) and games_df.empty):
        return pitcher_lookup
    for _, game in games_df.iterrows():
        for side in ("away", "home"):
            pitcher_id = str(game.get(f"{side}_pitcher_id") or "").strip()
            pitcher_name = str(game.get(f"{side}_pitcher") or "").strip()
            if not pitcher_id and not pitcher_name:
                continue
            opponent_side = "home" if side == "away" else "away"
            context = {
                "team": game.get(f"{side}_team", ""),
                "team_abbr": game.get(f"{side}_abbrev", ""),
                "team_id": game.get(f"{side}_team_id", ""),
                "opponent": game.get(f"{opponent_side}_team", ""),
                "opponent_id": game.get(f"{opponent_side}_team_id", ""),
                "opponent_abbr": game.get(f"{opponent_side}_abbrev", ""),
                "game_pk": game.get("game_pk", ""),
                "game_time": game.get("game_time_et", ""),
                "side": side,
                "hand": game.get(f"{side}_pitcher_hand", ""),
                "player_id": pitcher_id,
                "player": pitcher_name,
                "game": game,
            }
            if pitcher_id:
                pitcher_lookup[f"id:{pitcher_id}"] = context
            pitcher_name_key = app.normalize_name(pitcher_name)
            if pitcher_name_key and pitcher_name_key != "tbd":
                pitcher_lookup[f"name:{pitcher_name_key}"] = context
    return pitcher_lookup


def _projection_looks_like_pitcher(record, player_name, pitcher_context_lookup):
    projection_player_id = app._projection_player_id(record)
    if projection_player_id and pitcher_context_lookup.get(f"id:{projection_player_id}"):
        return True
    return bool(pitcher_context_lookup.get(f"name:{app.normalize_name(player_name)}"))


def _projection_homepage_prop(record, candidate_props, pitcher_context_lookup):
    player_name = str(record.get("player") or app._projection_player_name(record) or "").strip()
    stat_type = record.get("stat_display_name") or app._projection_stat_type(record)
    pitcher_like = _projection_looks_like_pitcher(record, player_name, pitcher_context_lookup)
    pitcher_matches = [
        prop for prop in candidate_props
        if prop in app.PITCHER_GAME_LOG_PROPS
        and app.pitcher_prizepicks_prop_match_key(stat_type) == app.pitcher_prizepicks_prop_match_key(prop)
    ]
    batter_matches = [
        prop for prop in candidate_props
        if prop not in app.PITCHER_GAME_LOG_PROPS
        and app._prop_match_key(stat_type) == app._prop_match_key(prop)
    ]
    if pitcher_like and pitcher_matches:
        return pitcher_matches[0]
    if not pitcher_like and batter_matches:
        return batter_matches[0]
    if pitcher_matches:
        return pitcher_matches[0]
    if batter_matches:
        return batter_matches[0]
    return ""


def _lineup_fallback_info(player_name, team_context, lineup_fallback_cache):
    game_pk = team_context.get("game_pk", "") if team_context else ""
    if not player_name or not game_pk:
        return {}
    if game_pk not in lineup_fallback_cache:
        lineup_fallback_cache[game_pk] = app.get_game_lineups(game_pk, team_context.get("game") if team_context else None)
    lineup_context = lineup_fallback_cache.get(game_pk, {}) or {}
    player_key = app.normalize_name(player_name)
    for side in ("away", "home"):
        for player in lineup_context.get(side, []) or []:
            if app.normalize_name(player.get("name", "")) == player_key:
                opponent_side = "home" if side == "away" else "away"
                return {
                    "player_id": player.get("player_id", ""),
                    "hand": player.get("handedness", ""),
                    "team": lineup_context.get(f"{side}_team", team_context.get("team", "")),
                    "team_id": lineup_context.get(f"{side}_team_id", team_context.get("team_id", "")),
                    "opponent": lineup_context.get(f"{opponent_side}_team", team_context.get("opponent", "")),
                    "opponent_id": lineup_context.get(f"{opponent_side}_team_id", team_context.get("opponent_id", "")),
                    "game_pk": game_pk,
                    "game_time": team_context.get("game_time", ""),
                }
    return {}


def _enrich_props_card_identity(row, player_id_cache, lineup_fallback_cache):
    player_name = row.get("player", "")
    player_type = row.get("player_type") or "batter"
    row_prop = row.get("prop") or ""
    team_id = row.get("team_id", "")
    team_context = row.get("team_context", {}) or {}
    player_id = row.get("projection_player_id", "")
    hand = row.get("hand", "")
    team = row.get("team", "")
    opponent = row.get("opponent", "")
    opponent_id = row.get("opponent_id", "")
    game_pk = row.get("game_pk", "")
    game_time = row.get("game_time", "")
    side = row.get("side", "")

    if not player_id:
        player_cache_key = (app.normalize_name(player_name), str(team_id or ""))
        if player_cache_key not in player_id_cache:
            player_id_cache[player_cache_key] = app.resolve_player_id_from_team_roster(player_name, team_id)
        player_id = player_id_cache[player_cache_key]

    if player_type == "batter" and not player_id:
        lineup_info = _lineup_fallback_info(player_name, team_context, lineup_fallback_cache)
        player_id = lineup_info.get("player_id", "")
        hand = lineup_info.get("hand", "")
        team = lineup_info.get("team") or team
        team_id = lineup_info.get("team_id") or team_id
        opponent = lineup_info.get("opponent") or opponent
        opponent_id = lineup_info.get("opponent_id") or opponent_id
        game_pk = lineup_info.get("game_pk") or game_pk
        game_time = lineup_info.get("game_time") or game_time

    if player_type == "pitcher" and player_id and not hand:
        try:
            pitcher_info = app.get_players_info((int(float(player_id)),))
            hand = app.format_pitcher_hand(app.normalize_hand_code(pitcher_info.get(int(float(player_id)), {}).get("pitchHand", "")))
        except (TypeError, ValueError):
            hand = hand or ""

    image_url = app.mlb_player_headshot_url(player_id) or row.get("projection_image_url", "")

    detail_href = ""
    if player_type == "pitcher":
        detail_href = app._build_pitcher_detail_href(
            player_id,
            pitcher_name=player_name,
            pitcher_hand=hand,
            pitcher_side=side,
            game_pk=game_pk,
            prop=row_prop,
            line=row.get("line"),
        )
    elif player_id:
        detail_href = app._build_batter_detail_href(
            player_id,
            batter_name=player_name,
            batter_hand=hand,
            team=team,
            team_id=team_id,
            opponent=opponent,
            opponent_id=opponent_id,
            return_game_pk=game_pk,
            prop=row_prop,
            line=row.get("line"),
        )

    row.update({
        "href": detail_href,
        "team": team,
        "team_id": team_id,
        "opponent": opponent,
        "opponent_id": opponent_id,
        "hand": hand,
        "player_id": player_id,
        "image_url": image_url,
        "game_pk": game_pk,
        "game_time": game_time,
        "side": side,
    })
    return row


def _props_stat_cache_key(row):
    player_type = row.get("player_type") or "batter"
    if player_type == "pitcher":
        prop_column = app.PITCHER_GAME_LOG_PROP_COLUMNS.get(row.get("prop"))
    else:
        prop_column = app.GAME_LOG_PROP_COLUMNS.get(row.get("prop"))
    player_id = row.get("player_id")
    if not player_id or not prop_column:
        return None
    try:
        selected_prop_line = float(row.get("line"))
    except (TypeError, ValueError):
        return None
    return (
        player_type,
        str(player_id),
        prop_column,
        selected_prop_line,
        str(row.get("opponent_id") or "").strip(),
        app.normalize_name(row.get("opponent", "")),
    )


def _blank_stat_value(display="--"):
    return {"value": None, "display": display}


def _blank_stat_values():
    return {
        "L5": _blank_stat_value(),
        "L10": _blank_stat_value(),
        "L15": _blank_stat_value(),
        "H2H": _blank_stat_value("N/A"),
        "AVG": _blank_stat_value(),
        "SZN": _blank_stat_value(),
    }


def _summary_from_values(values, selected_prop_line, prop_column, empty_hit_rate_text="--", empty_avg_text="--"):
    if values.empty:
        return {
            "hit_rate_value": None,
            "hit_rate_display": empty_hit_rate_text,
            "avg_value": None,
            "avg_display": empty_avg_text,
            "games": 0,
        }
    hit_rate = float((values >= selected_prop_line).mean() * 100.0)
    avg_value = float(values.mean())
    return {
        "hit_rate_value": hit_rate,
        "hit_rate_display": f"{hit_rate:.0f}%",
        "avg_value": avg_value,
        "avg_display": app.prop_average_text(avg_value, prop_column),
        "games": int(len(values)),
    }


def _numeric_sample_values(game_log_df, prop_column, sample_label):
    sample_df = app.game_log_sample_dataframe(game_log_df, sample_label)
    if sample_df.empty or prop_column not in sample_df.columns:
        return pd.Series(dtype="float64")
    return pd.to_numeric(sample_df[prop_column], errors="coerce").dropna()


def _build_props_stat_summary_cache(rows):
    stat_summary_cache = {}
    rows_by_game_log_key = {}
    skipped_first_inning = 0
    for row in rows:
        cache_key = _props_stat_cache_key(row)
        if not cache_key:
            continue
        player_type, player_id, prop_column, _, _, _ = cache_key
        include_first_inning = player_type == "batter" and prop_column == "first_inning_hrrrbi"
        if include_first_inning:
            skipped_first_inning += 1
            stat_summary_cache[cache_key] = _blank_stat_values()
            continue
        rows_by_game_log_key.setdefault((player_type, player_id, include_first_inning), []).append((row, cache_key))

    for (player_type, player_id, include_first_inning), player_rows in rows_by_game_log_key.items():
        if player_type == "pitcher":
            game_log_df = app.load_pitcher_prop_game_log(player_id)
        else:
            game_log_df = app.load_batter_prop_game_log(
                player_id,
                include_first_inning=include_first_inning,
            )
        if game_log_df.empty:
            for _, cache_key in player_rows:
                stat_summary_cache[cache_key] = _blank_stat_values()
            continue

        rows_by_prop = {}
        for row, cache_key in player_rows:
            prop_column = cache_key[2]
            rows_by_prop.setdefault(prop_column, []).append((row, cache_key))

        for prop_column, prop_rows in rows_by_prop.items():
            if prop_column not in game_log_df.columns:
                for _, cache_key in prop_rows:
                    stat_summary_cache[cache_key] = _blank_stat_values()
                continue

            sample_values = {
                sample_label: _numeric_sample_values(game_log_df, prop_column, sample_label)
                for sample_label in ("L5", "L10", "L15", "2026")
            }
            h2h_values_cache = {}
            for row, cache_key in prop_rows:
                _, _, _, selected_prop_line, opponent_id, opponent_name_key = cache_key
                stat_values = _blank_stat_values()

                for sample_label in ("L5", "L10", "L15"):
                    summary = _summary_from_values(sample_values[sample_label], selected_prop_line, prop_column)
                    stat_values[sample_label] = {
                        "value": summary["hit_rate_value"],
                        "display": summary["hit_rate_display"],
                    }

                season_summary = _summary_from_values(sample_values["2026"], selected_prop_line, prop_column)
                stat_values["AVG"] = {
                    "value": season_summary["avg_value"],
                    "display": season_summary["avg_display"],
                }
                stat_values["SZN"] = {
                    "value": season_summary["hit_rate_value"],
                    "display": season_summary["hit_rate_display"],
                }

                if opponent_id or opponent_name_key:
                    h2h_cache_key = (opponent_id, opponent_name_key)
                    if h2h_cache_key not in h2h_values_cache:
                        opponent_context = {
                            "id": opponent_id,
                            "name": str(row.get("opponent") or "").strip(),
                            "abbr": "",
                        }
                        h2h_df = app.filter_game_logs_vs_opponent(game_log_df, opponent_context)
                        if h2h_df.empty or prop_column not in h2h_df.columns:
                            h2h_values_cache[h2h_cache_key] = pd.Series(dtype="float64")
                        else:
                            h2h_values_cache[h2h_cache_key] = pd.to_numeric(
                                h2h_df[prop_column],
                                errors="coerce",
                            ).dropna()
                    h2h_summary = _summary_from_values(
                        h2h_values_cache[h2h_cache_key],
                        selected_prop_line,
                        prop_column,
                        empty_hit_rate_text="N/A",
                        empty_avg_text="-",
                    )
                    if h2h_summary["games"] > 0:
                        stat_values["H2H"] = {
                            "value": h2h_summary["hit_rate_value"],
                            "display": h2h_summary["hit_rate_display"],
                        }

                stat_summary_cache[cache_key] = stat_values

    return stat_summary_cache, skipped_first_inning


def _props_card_stat_values(row, stat_summary_cache):
    cache_key = _props_stat_cache_key(row)
    if not cache_key:
        return _blank_stat_values()
    return stat_summary_cache.get(cache_key, _blank_stat_values())


def _matchup_label(row):
    team_abbr = row.get("team_abbr") or row.get("team") or ""
    opponent_abbr = row.get("opponent_abbr") or row.get("opponent") or ""
    side = row.get("side")
    if side == "away" and team_abbr and opponent_abbr:
        return f"{team_abbr} @ {opponent_abbr}"
    if side == "home" and team_abbr and opponent_abbr:
        return f"{opponent_abbr} @ {team_abbr}"
    if team_abbr and opponent_abbr:
        return f"{team_abbr} vs {opponent_abbr}"
    return ""


def _record_from_row(row, stat_values):
    prop_column = (
        app.PITCHER_GAME_LOG_PROP_COLUMNS.get(row.get("prop"))
        if row.get("player_type") == "pitcher"
        else app.GAME_LOG_PROP_COLUMNS.get(row.get("prop"))
    )
    exact_projection_lines = row.get("exact_projection_lines") or []
    line_types = _line_types(exact_projection_lines)
    line_key = _props_line_match_key(row.get("line"))
    return {
        "record_id": "|".join([
            str(row.get("player_id") or row.get("projection_player_id") or app.normalize_name(row.get("player"))),
            _homepage_prop_match_key(row.get("prop")),
            line_key,
        ]),
        "player": {
            "id": str(row.get("player_id") or ""),
            "projection_player_id": str(row.get("projection_player_id") or ""),
            "name": row.get("player") or "",
            "type": row.get("player_type") or "batter",
            "hand": row.get("hand") or "",
            "side": row.get("side") or "",
            "headshot_url": row.get("image_url") or "",
        },
        "game": {
            "game_pk": str(row.get("game_pk") or ""),
            "matchup": _matchup_label(row),
            "game_time": row.get("game_time") or "",
            "team": row.get("team") or "",
            "team_id": str(row.get("team_id") or ""),
            "team_abbr": row.get("team_abbr") or "",
            "opponent": row.get("opponent") or "",
            "opponent_id": str(row.get("opponent_id") or ""),
            "opponent_abbr": row.get("opponent_abbr") or "",
            "side": row.get("side") or "",
        },
        "prop": {
            "label": row.get("prop") or "",
            "stat_column": prop_column or "",
            "line": row.get("line"),
            "line_key": line_key,
            "line_types": line_types,
            "source_badges": _source_badges(exact_projection_lines),
            "status": row.get("status") or _status_from_projection_matches(exact_projection_lines),
        },
        "routing": {
            "detail_type": row.get("player_type") or "batter",
            "href": row.get("href") or "",
        },
        "stats": stat_values,
    }


def _build_candidate_rows(projections, games):
    team_context_lookup = _homepage_team_context_lookup(games)
    pitcher_context_lookup = _homepage_pitcher_context_lookup(games)
    candidate_props = [
        prop for prop in [*app.GAME_LOG_PROPS, *app.PITCHER_GAME_LOG_PROPS]
        if prop not in SKIPPED_STAGE_1_PROPS
    ]
    selected_prop_projection_records = []
    skipped_records = {}

    for record in projections:
        if not isinstance(record, dict):
            skipped_records["invalid_projection"] = skipped_records.get("invalid_projection", 0) + 1
            continue
        stat_type = record.get("stat_display_name") or app._projection_stat_type(record)
        if app._prop_match_key(stat_type) == "firstinninghrrrbi":
            skipped_records[SKIPPED_STAGE_1_PROPS["1st Inning Hits + Runs + RBIs"]] = (
                skipped_records.get(SKIPPED_STAGE_1_PROPS["1st Inning Hits + Runs + RBIs"], 0) + 1
            )
            continue
        record_prop = _projection_homepage_prop(record, candidate_props, pitcher_context_lookup)
        if not record_prop:
            skipped_records["unsupported prop or unmatched player type"] = skipped_records.get("unsupported prop or unmatched player type", 0) + 1
            continue
        selected_prop_projection_records.append((record, record_prop))

    records_by_exact_key = {}
    for record, record_prop in selected_prop_projection_records:
        player_name = str(record.get("player") or app._projection_player_name(record) or "").strip()
        line_value = app._projection_line_value(record)
        record_prop_key = _homepage_prop_match_key(record_prop)
        exact_key = (
            _projection_identity_match_key(record, player_name),
            record_prop_key,
            _props_line_match_key(line_value),
        )
        records_by_exact_key.setdefault(exact_key, []).append(record)

    rows = []
    seen = set()
    for record, record_prop in selected_prop_projection_records:
        player_name = str(record.get("player") or app._projection_player_name(record) or "").strip()
        if not player_name:
            skipped_records["missing player name"] = skipped_records.get("missing player name", 0) + 1
            continue
        line_value = app._projection_line_value(record)
        record_prop_key = _homepage_prop_match_key(record_prop)
        exact_key = (
            _projection_identity_match_key(record, player_name),
            record_prop_key,
            _props_line_match_key(line_value),
        )
        if exact_key in seen:
            continue
        seen.add(exact_key)

        exact_projection_lines = records_by_exact_key.get(exact_key, [record])
        preferred_line = app.preferred_projection_line(exact_projection_lines) or record
        odds_type = app._projection_value(preferred_line, "odds_type", "oddsType", default="")
        projection_player_id = app._projection_player_id(record)
        pitcher_context = {}
        selected_is_pitcher_prop = record_prop in app.PITCHER_GAME_LOG_PROPS
        if selected_is_pitcher_prop:
            if projection_player_id:
                pitcher_context = pitcher_context_lookup.get(f"id:{projection_player_id}", {})
            if not pitcher_context:
                pitcher_context = pitcher_context_lookup.get(f"name:{app.normalize_name(player_name)}", {})

        projection_team = app._projection_value(record, "team", default="")
        team_context = pitcher_context if selected_is_pitcher_prop else {}
        for key in _team_lookup_keys(projection_team):
            team_context = team_context or team_context_lookup.get(key, {})
            if team_context:
                break

        rows.append({
            "player": player_name,
            "href": "",
            "team": team_context.get("team") or projection_team,
            "team_abbr": team_context.get("team_abbr", ""),
            "team_id": team_context.get("team_id", ""),
            "opponent": team_context.get("opponent") or app._projection_value(record, "description", default=""),
            "opponent_id": team_context.get("opponent_id", ""),
            "opponent_abbr": team_context.get("opponent_abbr", ""),
            "hand": team_context.get("hand", "") if selected_is_pitcher_prop else "",
            "player_id": "",
            "projection_player_id": projection_player_id or team_context.get("player_id", ""),
            "projection_image_url": app._projection_value(record, "image_url", "imageUrl", default=""),
            "team_context": team_context,
            "game_pk": team_context.get("game_pk", ""),
            "side": team_context.get("side", ""),
            "player_type": "pitcher" if selected_is_pitcher_prop else "batter",
            "prop": record_prop,
            "line": line_value,
            "odds_type": odds_type,
            "exact_projection_lines": exact_projection_lines,
            "status": _status_from_projection_matches(exact_projection_lines),
            "image_url": app._projection_value(record, "image_url", "imageUrl", default=""),
            "game_time": team_context.get("game_time", ""),
        })

    duplicate_exact_keys_merged = sum(max(len(lines) - 1, 0) for lines in records_by_exact_key.values())
    return rows, skipped_records, duplicate_exact_keys_merged


def build_props_summary_cache(cache_date):
    started_at = time.perf_counter()
    games = app.load_schedule(cache_date)
    projections = app.load_prizepicks_mlb_projections()
    rows, skipped_records, duplicate_exact_keys_merged = _build_candidate_rows(projections, games)

    player_id_cache = {}
    lineup_fallback_cache = {}
    enriched_rows = [
        _enrich_props_card_identity(dict(row), player_id_cache, lineup_fallback_cache)
        for row in rows
    ]
    missing_player_ids = sum(1 for row in enriched_rows if not row.get("player_id"))
    stat_summary_cache, skipped_first_inning_summaries = _build_props_stat_summary_cache(enriched_rows)

    records = [
        _record_from_row(row, _props_card_stat_values(row, stat_summary_cache))
        for row in enriched_rows
    ]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "date": cache_date.isoformat(),
        "generated_at": datetime.now(ZoneInfo(CACHE_TIMEZONE)).isoformat(),
        "timezone": CACHE_TIMEZONE,
        "sources": {
            "prizepicks_leagues": [label for label, _ in app.PRIZEPICKS_MLB_LEAGUES],
            "schedule_date": cache_date.isoformat(),
            "skipped_stage_1_props": SKIPPED_STAGE_1_PROPS,
        },
        "records": records,
    }
    build_duration = time.perf_counter() - started_at
    summary = {
        "date": cache_date.isoformat(),
        "records_written": len(records),
        "skipped_records": skipped_records,
        "missing_player_ids": missing_player_ids,
        "duplicate_exact_keys_merged": duplicate_exact_keys_merged,
        "skipped_first_inning_summaries": skipped_first_inning_summaries,
        "build_duration_seconds": round(build_duration, 2),
    }
    return payload, summary


def parse_args():
    parser = argparse.ArgumentParser(description="Build a daily homepage Props summary cache JSON file.")
    parser.add_argument("--date", required=True, help="Slate date in YYYY-MM-DD format.")
    parser.add_argument("--cache-dir", default=str(REPO_ROOT / "data" / "cache"), help="Output cache directory.")
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        cache_date = date.fromisoformat(args.date)
    except ValueError as exc:
        raise SystemExit(f"Invalid --date value {args.date!r}; expected YYYY-MM-DD.") from exc

    payload, summary = build_props_summary_cache(cache_date)
    output_path = props_summary_cache_path(cache_date.isoformat(), args.cache_dir)
    write_json_atomic(output_path, payload)
    summary["output_path"] = str(output_path)

    print("Props summary cache build complete")
    for key, value in summary.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
