import logging
import threading
from datetime import date
from pathlib import Path
from time import perf_counter

import pandas as pd
import streamlit as st

import performance_profile

logger = logging.getLogger(__name__)
_PITCHER_LOCATION_SESSION_CACHE = {}
_BATTER_LOCATION_SESSION_CACHE = {}
_PITCHER_STATCAST_SESSION_CACHE = {}
_BATTER_STATCAST_SESSION_CACHE = {}
_LOCATION_SESSION_CACHE_LOCK = threading.Lock()

GRID_CENTER_Z = 2.75

ZONE_LAYOUT = [
    {"zone_id": 1, "x_min": -2.5, "x_max": -0.8, "y_min": 3.5, "y_max": 4.5},
    {"zone_id": 2, "x_min": -0.8, "x_max": 0.8, "y_min": 3.5, "y_max": 4.5},
    {"zone_id": 3, "x_min": 0.8, "x_max": 2.5, "y_min": 3.5, "y_max": 4.5},
    {"zone_id": 4, "x_min": -2.5, "x_max": -0.8, "y_min": 2.2, "y_max": 3.5},
    {"zone_id": 5, "x_min": -0.8, "x_max": 0.8, "y_min": 2.2, "y_max": 3.5},
    {"zone_id": 6, "x_min": 0.8, "x_max": 2.5, "y_min": 2.2, "y_max": 3.5},
    {"zone_id": 7, "x_min": -2.5, "x_max": -0.8, "y_min": 1.0, "y_max": 2.2},
    {"zone_id": 8, "x_min": -0.8, "x_max": 0.8, "y_min": 1.0, "y_max": 2.2},
    {"zone_id": 9, "x_min": 0.8, "x_max": 2.5, "y_min": 1.0, "y_max": 2.2},
]
DISPLAY_ZONE_IDS = set(range(1, 10)) | {11, 12, 13, 14}
OUTER_ZONE_TO_QUAD = {11: "tl", 12: "tr", 13: "bl", 14: "br"}
OUTER_QUAD_TO_ZONE = {"tl": 11, "tr": 12, "bl": 13, "br": 14}
PITCHER_STRIKE_ZONE_METRICS = ("Pitch %", "Whiff %", "PutAway %", "Hard Hit %", "xwOBA", "K %")
PITCHER_BASELINE_CSVS = {
    "Pitch %": "strike_zone_pitch_pct_qualified_pitcher_summary.csv",
    "Whiff %": "strike_zone_whiff_pct_qualified_pitcher_summary.csv",
    "PutAway %": "strike_zone_putaway_pct_qualified_pitcher_summary.csv",
    "Hard Hit %": "strike_zone_hard_hit_pct_qualified_pitcher_summary.csv",
    "xwOBA": "strike_zone_xwoba_qualified_pitcher_summary.csv",
    "K %": "strike_zone_k_pct_qualified_pitcher_summary.csv",
}


def _load_zone_metric_baselines_from_csv(csv_map):
    baselines = {}
    base_dir = Path(__file__).resolve().parent
    for metric, filename in csv_map.items():
        path = base_dir / filename
        if not path.exists():
            continue
        try:
            df = pd.read_csv(path)
        except Exception as exc:
            logger.warning("Could not load pitcher strike-zone baseline CSV %s: %s", filename, exc)
            continue

        zone_col = "zone_id" if "zone_id" in df.columns else "zone" if "zone" in df.columns else None
        if not zone_col or not {"mean", "std"}.issubset(df.columns):
            logger.warning("Pitcher strike-zone baseline CSV %s is missing zone/mean/std columns.", filename)
            continue

        metric_baselines = {}
        for _, row in df.iterrows():
            zone_id = _normalize_zone_value(row.get(zone_col))
            if zone_id not in DISPLAY_ZONE_IDS:
                continue
            try:
                metric_baselines[int(zone_id)] = {
                    "mean": float(row["mean"]),
                    "std": float(row["std"]),
                }
            except (TypeError, ValueError):
                continue
        if metric_baselines:
            baselines[metric] = metric_baselines
    return baselines

ZONE_METRIC_BASELINES = {
    "Pitch %": {
        1: {"mean": 4.2779, "std": 0.8585},
        2: {"mean": 5.3092, "std": 0.7895},
        3: {"mean": 3.7112, "std": 0.8559},
        4: {"mean": 5.5823, "std": 1.0416},
        5: {"mean": 7.0652, "std": 0.7984},
        6: {"mean": 5.5636, "std": 1.1518},
        7: {"mean": 4.5870, "std": 1.1427},
        8: {"mean": 6.1730, "std": 0.9133},
        9: {"mean": 5.0530, "std": 1.1568},
        11: {"mean": 12.1429, "std": 2.8654},
        12: {"mean": 9.0247, "std": 2.0795},
        13: {"mean": 13.3472, "std": 4.0073},
        14: {"mean": 18.1630, "std": 4.8096},
    },
    "Takes": {
        1: {"mean": 3.1255, "std": 1.2231},
        2: {"mean": 2.7442, "std": 0.9246},
        3: {"mean": 2.3795, "std": 1.0527},
        4: {"mean": 3.6736, "std": 1.2547},
        5: {"mean": 3.3983, "std": 1.0041},
        6: {"mean": 3.4505, "std": 1.3047},
        7: {"mean": 3.6606, "std": 1.2806},
        8: {"mean": 3.8391, "std": 1.0091},
        9: {"mean": 3.8620, "std": 1.3424},
        11: {"mean": 17.2139, "std": 5.5458},
        12: {"mean": 11.7143, "std": 3.6310},
        13: {"mean": 17.0010, "std": 5.5371},
        14: {"mean": 23.9375, "std": 7.1954},
    },
    "K%": {
        1: {"mean": 5.5204, "std": 1.7875},
        2: {"mean": 6.0979, "std": 1.6064},
        3: {"mean": 4.7019, "std": 1.6501},
        4: {"mean": 6.0604, "std": 1.9266},
        5: {"mean": 6.8022, "std": 1.5241},
        6: {"mean": 6.0997, "std": 1.9501},
        7: {"mean": 5.5673, "std": 1.7130},
        8: {"mean": 6.6721, "std": 1.7558},
        9: {"mean": 6.1279, "std": 1.9968},
        11: {"mean": 10.3376, "std": 2.4670},
        12: {"mean": 8.8234, "std": 2.1951},
        13: {"mean": 12.0321, "std": 3.3459},
        14: {"mean": 15.1571, "std": 3.5670},
    },
    "Batted Balls": {
        1: {"mean": 5.0899, "std": 2.1125},
        2: {"mean": 7.7471, "std": 2.1674},
        3: {"mean": 5.2480, "std": 1.7200},
        4: {"mean": 9.8704, "std": 2.6059},
        5: {"mean": 14.7277, "std": 3.0861},
        6: {"mean": 10.0027, "std": 2.5381},
        7: {"mean": 6.8784, "std": 2.8785},
        8: {"mean": 11.5446, "std": 2.7842},
        9: {"mean": 7.2948, "std": 2.8192},
        11: {"mean": 4.4725, "std": 2.7998},
        12: {"mean": 4.2144, "std": 1.8860},
        13: {"mean": 6.3057, "std": 3.6421},
        14: {"mean": 6.6039, "std": 4.1059},
    },
    "Home Runs": {
        1: {"mean": 5.0810, "std": 7.5697},
        2: {"mean": 12.5537, "std": 11.3195},
        3: {"mean": 5.5799, "std": 8.4324},
        4: {"mean": 10.4396, "std": 12.1445},
        5: {"mean": 20.7431, "std": 13.4867},
        6: {"mean": 12.0796, "std": 13.9507},
        7: {"mean": 4.9090, "std": 7.7784},
        8: {"mean": 11.8285, "std": 11.4899},
        9: {"mean": 5.7744, "std": 7.8927},
        11: {"mean": 2.9176, "std": 6.0067},
        12: {"mean": 2.3630, "std": 4.9780},
        13: {"mean": 1.8373, "std": 4.4268},
        14: {"mean": 2.5946, "std": 6.3904},
    },
}

PITCHER_ZONE_METRIC_BASELINES = {}

ZONE_Z_SCORE_BACKGROUND_COLORS = {
    "red": "#e62727",
    "orange": "#FFD60A",
    "green": "#73e31e",
    "blue": "#1cb8e8",
}
HEATMAP_SCALE_LEAGUE = "Vs. League Average"
HEATMAP_SCALE_SELF = "Vs. Self"


def _normalize_zone_value(zone_value):
    if pd.isna(zone_value):
        return None
    try:
        return int(zone_value)
    except (TypeError, ValueError):
        return None


PITCHER_ZONE_METRIC_BASELINES = _load_zone_metric_baselines_from_csv(PITCHER_BASELINE_CSVS)


def _location_cache_key(player_id, start_date, end_date):
    return (int(player_id), str(start_date), str(end_date))


def _get_cached_location_df(cache, key):
    with _LOCATION_SESSION_CACHE_LOCK:
        cached = cache.get(key)
    if cached is None:
        return None
    return cached.copy()


def _store_cached_location_df(cache, key, df):
    with _LOCATION_SESSION_CACHE_LOCK:
        cache[key] = df.copy()
    return df


def load_pitcher_statcast_data(player_id, start_date, end_date):
    cache_key = _location_cache_key(player_id, start_date, end_date)
    with _LOCATION_SESSION_CACHE_LOCK:
        cached = _PITCHER_STATCAST_SESSION_CACHE.get(cache_key)
        if cached is not None:
            performance_profile.record_request("savant", f"statcast_pitcher:{cache_key}", cache_status="hit")
            return cached.copy()

        from pybaseball import statcast_pitcher

        started_at = perf_counter()
        df = statcast_pitcher(start_date, end_date, int(player_id))
        performance_profile.record_request(
            "savant",
            f"statcast_pitcher:{cache_key}",
            elapsed_seconds=perf_counter() - started_at,
            cache_status="miss",
        )
        if df is None:
            df = pd.DataFrame()
        _PITCHER_STATCAST_SESSION_CACHE[cache_key] = df.copy()
        return df


def load_batter_statcast_data(batter_id, start_date, end_date):
    cache_key = _location_cache_key(batter_id, start_date, end_date)
    with _LOCATION_SESSION_CACHE_LOCK:
        cached = _BATTER_STATCAST_SESSION_CACHE.get(cache_key)
        if cached is not None:
            performance_profile.record_request("savant", f"statcast_batter:{cache_key}", cache_status="hit")
            return cached.copy()

        from pybaseball import statcast_batter

        started_at = perf_counter()
        df = statcast_batter(start_date, end_date, int(batter_id))
        performance_profile.record_request(
            "savant",
            f"statcast_batter:{cache_key}",
            elapsed_seconds=perf_counter() - started_at,
            cache_status="miss",
        )
        if df is None:
            df = pd.DataFrame()
        _BATTER_STATCAST_SESSION_CACHE[cache_key] = df.copy()
        return df


@st.cache_data(ttl=300, show_spinner="Loading strike zone data...")
def load_pitch_location_data(player_id, start_date, end_date):
    try:
        cache_key = _location_cache_key(player_id, start_date, end_date)
    except (TypeError, ValueError):
        cache_key = None

    if cache_key is not None:
        cached_df = _get_cached_location_df(_PITCHER_LOCATION_SESSION_CACHE, cache_key)
        if cached_df is not None:
            return cached_df

    try:
        df = load_pitcher_statcast_data(player_id, start_date, end_date)
    except Exception as exc:
        logger.error("Statcast fetch failed for player_id=%s: %s", player_id, exc)
        return pd.DataFrame()

    if df is None or df.empty:
        empty_df = pd.DataFrame()
        if cache_key is not None:
            return _store_cached_location_df(_PITCHER_LOCATION_SESSION_CACHE, cache_key, empty_df)
        return empty_df

    required = {"zone"}
    if not required.issubset(df.columns):
        logger.error("Statcast data missing zone column for player_id=%s", player_id)
        return pd.DataFrame()

    result_df = df.dropna(subset=["zone"]).copy()
    if "game_type" in result_df.columns:
        result_df = result_df[result_df["game_type"] == "R"].copy()
    if "batter_stands" not in result_df.columns and "stand" in result_df.columns:
        result_df["batter_stands"] = result_df["stand"]

    if cache_key is not None:
        return _store_cached_location_df(_PITCHER_LOCATION_SESSION_CACHE, cache_key, result_df)
    return result_df


def filter_by_pitch_type(df, pitch_type):
    if df.empty or not pitch_type or pitch_type == "All Pitches":
        return df

    pitch_col = "pitch_name" if "pitch_name" in df.columns else "pitch_type"
    if pitch_col not in df.columns:
        return pd.DataFrame()

    normalized = pitch_type.strip().lower()
    return df[df[pitch_col].astype(str).str.lower() == normalized].copy()


def filter_by_batter_stands(df, batter_stands):
    if df.empty or not batter_stands or batter_stands == "All Batters":
        return df

    if "batter_stands" not in df.columns:
        return pd.DataFrame()

    stand_map = {"RHB": "R", "LHB": "L"}
    target_stand = stand_map.get(batter_stands)
    if not target_stand:
        return df

    return df[df["batter_stands"].astype(str).str.upper() == target_stand].copy()


@st.cache_data(ttl=300, show_spinner="Loading strike zone data...")
def load_batter_pitch_location_data(batter_id, start_date, end_date):
    try:
        cache_key = _location_cache_key(batter_id, start_date, end_date)
    except (TypeError, ValueError):
        cache_key = None

    if cache_key is not None:
        cached_df = _get_cached_location_df(_BATTER_LOCATION_SESSION_CACHE, cache_key)
        if cached_df is not None:
            return cached_df

    try:
        df = load_batter_statcast_data(batter_id, start_date, end_date)
    except Exception as exc:
        logger.error("Statcast fetch failed for batter_id=%s: %s", batter_id, exc)
        return pd.DataFrame()

    if df is None or df.empty:
        empty_df = pd.DataFrame()
        if cache_key is not None:
            return _store_cached_location_df(_BATTER_LOCATION_SESSION_CACHE, cache_key, empty_df)
        return empty_df

    if "zone" not in df.columns:
        logger.error("Statcast data missing zone column for batter_id=%s", batter_id)
        return pd.DataFrame()

    result_df = df.dropna(subset=["zone"]).copy()
    if "game_type" in result_df.columns:
        result_df = result_df[result_df["game_type"] == "R"].copy()
    if cache_key is not None:
        return _store_cached_location_df(_BATTER_LOCATION_SESSION_CACHE, cache_key, result_df)
    return result_df


def filter_by_pitcher_throws(df, pitcher_throws):
    if df.empty or not pitcher_throws or pitcher_throws == "All":
        return df

    throws_col = "p_throws" if "p_throws" in df.columns else "pitcher_throws"
    if throws_col not in df.columns:
        return pd.DataFrame()

    target = "R" if pitcher_throws == "RHP" else "L" if pitcher_throws == "LHP" else ""
    if not target:
        return df

    return df[df[throws_col].astype(str).str.upper() == target].copy()


def _is_swing_description(description_value):
    value = str(description_value or "").strip().lower()
    return value in {
        "swinging_strike",
        "swinging_strike_blocked",
        "foul",
        "foul_tip",
        "hit_into_play",
        "hit_into_play_no_out",
        "hit_into_play_score",
        "foul_bunt",
        "missed_bunt",
        "swinging_pitchout",
    }


def _is_take_description(description_value):
    return not _is_swing_description(description_value) and not str(description_value or "").strip().lower().startswith("hit_into_play")


def _batter_metric_mask(df, metric):
    if df.empty:
        return pd.Series(dtype=bool)

    metric_name = (metric or "Pitch %").strip().lower()
    events = df["events"].astype(str).str.lower() if "events" in df.columns else pd.Series("", index=df.index)
    descriptions = df["description"].astype(str).str.lower() if "description" in df.columns else pd.Series("", index=df.index)

    if metric_name == "pitch %":
        return pd.Series(True, index=df.index)

    if metric_name == "takes":
        return descriptions.apply(_is_take_description)

    if metric_name == "batted balls":
        return descriptions.str.startswith("hit_into_play") | events.isin(
            {
                "single",
                "double",
                "triple",
                "home_run",
                "field_out",
                "force_out",
                "fielders_choice",
                "fielders_choice_out",
                "grounded_into_double_play",
                "double_play",
                "triple_play",
                "field_error",
                "other_out",
                "sac_fly",
                "sac_fly_double_play",
                "sac_bunt",
                "sac_bunt_double_play",
            }
        )

    if metric_name == "k%":
        return events.str.startswith("strikeout") | descriptions.str.contains("strikeout", na=False)

    if metric_name == "home runs":
        return events == "home_run"

    return pd.Series(True, index=df.index)


def _metric_label(metric):
    metric_name = (metric or "Pitch %").strip()
    return metric_name if metric_name in {"Pitch %", "Takes", "Batted Balls", "K%", "Home Runs"} else "Pitch %"


def _pitcher_metric_label(metric):
    normalized = str(metric or "Pitch %").strip().lower().replace("_", " ").replace("-", " ")
    normalized = " ".join(normalized.split())
    metric_map = {
        "pitch %": "Pitch %",
        "pitch%": "Pitch %",
        "whiff %": "Whiff %",
        "whiff%": "Whiff %",
        "putaway %": "PutAway %",
        "putaway%": "PutAway %",
        "hard hit %": "Hard Hit %",
        "hardhit %": "Hard Hit %",
        "hardhit%": "Hard Hit %",
        "xwoba": "xwOBA",
        "k %": "K %",
        "k%": "K %",
    }
    return metric_map.get(normalized, "Pitch %")


def _clean_pitcher_metric_dataframe(filtered_df):
    if filtered_df.empty or "zone" not in filtered_df.columns:
        return pd.DataFrame()

    working_df = filtered_df.copy()
    pitch_col = "pitch_name" if "pitch_name" in working_df.columns else "pitch_type"
    if pitch_col in working_df.columns:
        working_df[pitch_col] = working_df[pitch_col].astype(str).str.strip()
        working_df = working_df[(working_df[pitch_col] != "") & (working_df[pitch_col].str.lower() != "nan")].copy()

    working_df["_zone_id"] = working_df["zone"].apply(_normalize_zone_value)
    return working_df[working_df["_zone_id"].isin(DISPLAY_ZONE_IDS)].copy()


def _events_series(df):
    if "events" not in df.columns:
        return pd.Series("", index=df.index)
    return df["events"].fillna("").astype(str).str.strip().str.lower()


def _description_series(df):
    if "description" not in df.columns:
        return pd.Series("", index=df.index)
    return df["description"].fillna("").astype(str).str.strip().str.lower()


def _pitcher_metric_unavailable_reason(df, metric):
    metric = _pitcher_metric_label(metric)
    required_columns = {
        "Pitch %": {"zone"},
        "Whiff %": {"zone", "description"},
        "PutAway %": {"zone", "strikes", "events"},
        "Hard Hit %": {"zone", "launch_speed"},
        "xwOBA": {"zone", "estimated_woba_using_speedangle"},
        "K %": {"zone", "events"},
    }.get(metric, {"zone"})

    missing = sorted(col for col in required_columns if col not in df.columns)
    if missing:
        return f"{metric} is unavailable because Statcast did not include: {', '.join(missing)}."
    return ""


def _safe_pct(numerator, denominator):
    return (float(numerator) / float(denominator) * 100.0) if denominator else 0.0


def _pitcher_metric_zone_value(metric, zone_df, total_display_pitches):
    metric = _pitcher_metric_label(metric)
    if zone_df.empty:
        return 0, 0.0

    if metric == "Pitch %":
        count = len(zone_df)
        return count, _safe_pct(count, total_display_pitches)

    if metric == "Whiff %":
        descriptions = _description_series(zone_df)
        swing_mask = descriptions.apply(_is_swing_description)
        whiff_mask = descriptions.isin({"swinging_strike", "swinging_strike_blocked", "missed_bunt"})
        numerator = int(whiff_mask.sum())
        denominator = int(swing_mask.sum())
        return numerator, _safe_pct(numerator, denominator)

    if metric == "PutAway %":
        strikes = pd.to_numeric(zone_df["strikes"], errors="coerce") if "strikes" in zone_df.columns else pd.Series(dtype=float)
        events = _events_series(zone_df)
        denominator = int((strikes == 2).sum()) if not strikes.empty else 0
        numerator = int(events.str.startswith("strikeout", na=False).sum())
        return numerator, _safe_pct(numerator, denominator)

    if metric == "Hard Hit %":
        launch_speed = pd.to_numeric(zone_df["launch_speed"], errors="coerce") if "launch_speed" in zone_df.columns else pd.Series(dtype=float)
        denominator = int(launch_speed.notna().sum()) if not launch_speed.empty else 0
        numerator = int((launch_speed >= 95).sum()) if not launch_speed.empty else 0
        return numerator, _safe_pct(numerator, denominator)

    if metric == "xwOBA":
        xwoba = (
            pd.to_numeric(zone_df["estimated_woba_using_speedangle"], errors="coerce")
            if "estimated_woba_using_speedangle" in zone_df.columns
            else pd.Series(dtype=float)
        )
        values = xwoba.dropna()
        return int(len(values)), float(values.mean()) if not values.empty else 0.0

    if metric == "K %":
        events = _events_series(zone_df)
        terminal_events = events[(events != "") & (events != "nan")]
        denominator = int(len(terminal_events))
        numerator = int(events.str.startswith("strikeout", na=False).sum())
        return numerator, _safe_pct(numerator, denominator)

    return len(zone_df), 0.0


def _build_pitcher_metric_zone_outputs(filtered_df, metric):
    metric = _pitcher_metric_label(metric)
    metric_df = _clean_pitcher_metric_dataframe(filtered_df)
    pitch_denominator = len(filtered_df) if metric == "Pitch %" else len(metric_df)

    zone_rows = []
    for zone in ZONE_LAYOUT:
        zone_subset = metric_df[metric_df["_zone_id"] == zone["zone_id"]] if not metric_df.empty else pd.DataFrame()
        count, value = _pitcher_metric_zone_value(metric, zone_subset, pitch_denominator)
        zone_rows.append(
            {
                **zone,
                "pitch_count": int(count),
                "pitch_pct": float(value),
            }
        )

    outer_stats = {}
    for key, zone_id in OUTER_QUAD_TO_ZONE.items():
        zone_subset = metric_df[metric_df["_zone_id"] == zone_id] if not metric_df.empty else pd.DataFrame()
        count, value = _pitcher_metric_zone_value(metric, zone_subset, pitch_denominator)
        outer_stats[key] = {
            "pitch_count": int(count),
            "pitch_pct": float(value),
        }

    return pd.DataFrame(zone_rows), outer_stats, pitch_denominator


def _clean_batter_metric_dataframe(filtered_df):
    working_df = filtered_df.copy()
    if working_df.empty:
        return pd.DataFrame()

    pitch_col = "pitch_name" if "pitch_name" in working_df.columns else "pitch_type"
    if pitch_col not in working_df.columns:
        return pd.DataFrame()

    working_df[pitch_col] = working_df[pitch_col].astype(str).str.strip()
    return working_df[(working_df[pitch_col] != "") & (working_df[pitch_col].str.lower() != "nan")].copy()


def _build_batter_metric_dataframe(filtered_df, metric):
    working_df = _clean_batter_metric_dataframe(filtered_df)
    if working_df.empty:
        return pd.DataFrame()

    metric = _metric_label(metric)
    if metric == "Pitch %":
        return working_df
    if metric in {"Takes", "Batted Balls", "Home Runs"}:
        metric_mask = _batter_metric_mask(working_df, metric)
        return working_df[metric_mask].copy() if not metric_mask.empty else working_df.iloc[0:0].copy()
    return working_df.iloc[0:0].copy()


def _filter_display_zone_dataframe(df):
    if df.empty:
        return df.copy()

    zone_ids = df["zone"].apply(_normalize_zone_value)
    return df[zone_ids.isin(DISPLAY_ZONE_IDS)].copy()


def _build_distribution_zone_outputs(filtered_df, metric):
    metric_df = _filter_display_zone_dataframe(_build_batter_metric_dataframe(filtered_df, metric))
    denominator = len(metric_df)

    zone_counts = {zone["zone_id"]: 0 for zone in ZONE_LAYOUT}
    outer_counts = {"tl": 0, "tr": 0, "bl": 0, "br": 0}
    outer_zone_to_quad = {11: "tl", 12: "tr", 13: "bl", 14: "br"}

    zone_ids = metric_df["zone"].apply(_normalize_zone_value) if not metric_df.empty else pd.Series(dtype=object)
    for zone_id in zone_ids.dropna().astype(int):
        if zone_id in zone_counts:
            zone_counts[zone_id] += 1
        else:
            key = outer_zone_to_quad.get(zone_id)
            if key is not None:
                outer_counts[key] += 1

    zone_rows = []
    for zone in ZONE_LAYOUT:
        count = zone_counts[zone["zone_id"]]
        zone_rows.append(
            {
                **zone,
                "pitch_count": int(count),
                "pitch_pct": (count / denominator * 100.0) if denominator else 0.0,
            }
        )

    outer_stats = {
        key: {
            "pitch_count": int(count),
            "pitch_pct": (count / denominator * 100.0) if denominator else 0.0,
        }
        for key, count in outer_counts.items()
    }

    return pd.DataFrame(zone_rows), outer_stats, denominator


def _build_k_distribution_zone_outputs(filtered_df):
    working_df = _clean_batter_metric_dataframe(filtered_df)
    if working_df.empty or "events" not in working_df.columns:
        outer_stats = {
            key: {"pitch_count": 0, "pitch_pct": 0.0}
            for key in ("tl", "tr", "bl", "br")
        }
        return pd.DataFrame(), outer_stats, 0

    working_df["_pa_key"] = _plate_appearance_key(working_df)
    k_pa_keys = set(working_df.loc[working_df["events"].astype(str).str.lower().eq("strikeout"), "_pa_key"].astype(str))
    k_df = working_df[working_df["_pa_key"].astype(str).isin(k_pa_keys)].copy()
    k_df = _filter_display_zone_dataframe(k_df)

    zone_counts = {zone["zone_id"]: 0 for zone in ZONE_LAYOUT}
    outer_counts = {"tl": 0, "tr": 0, "bl": 0, "br": 0}
    outer_zone_to_quad = {11: "tl", 12: "tr", 13: "bl", 14: "br"}

    if not k_df.empty:
        k_df["_zone_id"] = k_df["zone"].apply(_normalize_zone_value)
        touched_zones = k_df[["_pa_key", "_zone_id"]].dropna().drop_duplicates()
        for zone_id in touched_zones["_zone_id"].astype(int):
            if zone_id in zone_counts:
                zone_counts[zone_id] += 1
            else:
                key = outer_zone_to_quad.get(zone_id)
                if key is not None:
                    outer_counts[key] += 1

    denominator = sum(zone_counts.values()) + sum(outer_counts.values())

    zone_rows = []
    for zone in ZONE_LAYOUT:
        count = zone_counts[zone["zone_id"]]
        zone_rows.append(
            {
                **zone,
                "pitch_count": int(count),
                "pitch_pct": (count / denominator * 100.0) if denominator else 0.0,
            }
        )

    outer_stats = {
        key: {
            "pitch_count": int(count),
            "pitch_pct": (count / denominator * 100.0) if denominator else 0.0,
        }
        for key, count in outer_counts.items()
    }

    return pd.DataFrame(zone_rows), outer_stats, denominator


def _plate_appearance_key(df):
    if {"game_pk", "at_bat_number"}.issubset(df.columns):
        return (
            df["game_pk"].astype(str)
            + "_"
            + pd.to_numeric(df["at_bat_number"], errors="coerce").fillna(-1).astype(int).astype(str)
        )
    return df.index.astype(str)


def get_batter_pitch_type_options(batter_id):
    season_year = date.today().year
    start_date = f"{season_year}-03-01"
    end_date = date.today().isoformat()
    raw_df = load_batter_pitch_location_data(batter_id, start_date, end_date)
    if raw_df.empty:
        return ["All Pitches"]

    pitch_col = "pitch_name" if "pitch_name" in raw_df.columns else "pitch_type"
    if pitch_col not in raw_df.columns:
        return ["All Pitches"]

    options = [
        str(val).strip()
        for val in raw_df[pitch_col].dropna().astype(str).unique().tolist()
        if str(val).strip()
    ]
    options_sorted = sorted(set(options))
    return ["All Pitches", *options_sorted]


def _build_metric_zone_dataframe(filtered_df, metric):
    working_df = _clean_batter_metric_dataframe(filtered_df)
    if working_df.empty:
        return pd.DataFrame()

    if metric in {"Pitch %", "Takes", "Batted Balls", "Home Runs"}:
        zone_df, _, _ = _build_distribution_zone_outputs(working_df, metric)
        return zone_df
    elif metric == "K%":
        zone_df, _, _ = _build_k_distribution_zone_outputs(working_df)
        return zone_df
    return pd.DataFrame()


def _build_batter_metric_strike_zone_html(
    zone_df,
    outer_stats,
    metric=None,
    heatmap_scale=HEATMAP_SCALE_LEAGUE,
    **_kwargs,
):
    return _build_strike_zone_html(zone_df, outer_stats, metric=metric, heatmap_scale=heatmap_scale)


def display_batter_metric_strike_zone(
    batter_id,
    pitch_type,
    pitcher_throws="All",
    metric="Pitch %",
    heatmap_scale=HEATMAP_SCALE_LEAGUE,
):
    season_year = date.today().year
    start_date = f"{season_year}-03-01"
    end_date = date.today().isoformat()

    try:
        raw_df = load_batter_pitch_location_data(batter_id, start_date, end_date)
        filtered_df = filter_by_pitch_type(raw_df, pitch_type)
        filtered_df = filter_by_pitcher_throws(filtered_df, pitcher_throws)
    except Exception as exc:
        logger.error("Strike zone processing failed for batter_id=%s: %s", batter_id, exc)
        st.info("Strike zone data is unavailable for this batter right now.")
        return

    if filtered_df.empty:
        st.info("Strike zone data is unavailable for this batter right now.")
        return

    if metric == "K%":
        zone_df, outer_stats, _ = _build_k_distribution_zone_outputs(filtered_df)
        if zone_df.empty:
            st.info("Strike zone data is unavailable for this batter right now.")
            return
    else:
        zone_df, outer_stats, _ = _build_distribution_zone_outputs(filtered_df, metric)
    html = _build_batter_metric_strike_zone_html(zone_df, outer_stats, metric=metric, heatmap_scale=heatmap_scale)
    st.markdown(html, unsafe_allow_html=True)


def aggregate_to_zones(statcast_df, total_pitches=None):
    zone_rows = []
    total_pitches = len(statcast_df) if total_pitches is None else total_pitches

    zone_counts = {zone["zone_id"]: 0 for zone in ZONE_LAYOUT}
    if total_pitches > 0:
        zone_ids = statcast_df["zone"].apply(_normalize_zone_value)
        for zone_id in zone_ids.dropna().astype(int):
            if zone_id in zone_counts:
                zone_counts[zone_id] += 1

    for zone in ZONE_LAYOUT:
        count = zone_counts[zone["zone_id"]]
        pitch_pct = (count / total_pitches * 100.0) if total_pitches else 0.0
        zone_rows.append(
            {
                **zone,
                "pitch_count": count,
                "pitch_pct": pitch_pct,
            }
        )

    return pd.DataFrame(zone_rows)


def _zone_background_color(metric, zone_id, pct, baselines=None):
    metric_baselines = ZONE_METRIC_BASELINES if baselines is None else baselines
    baseline = metric_baselines.get(metric, {}).get(zone_id)
    if not baseline:
        return ""

    std = baseline.get("std", 0)
    if not std:
        return ""

    z_score = (float(pct) - baseline["mean"]) / std
    if z_score < -0.75:
        return ZONE_Z_SCORE_BACKGROUND_COLORS["red"]
    if z_score < 0.75:
        return ZONE_Z_SCORE_BACKGROUND_COLORS["orange"]
    if z_score < 1.50:
        return ZONE_Z_SCORE_BACKGROUND_COLORS["green"]
    return ZONE_Z_SCORE_BACKGROUND_COLORS["blue"]


def _format_cell_text(count, pct, metric=None):
    if _pitcher_metric_label(metric) == "xwOBA" or metric == "xwOBA":
        return f"{int(count)}<br>{pct:.3f}"
    return f"{int(count)}<br>{pct:.1f}%"


def _build_self_heatmap_color_map(zone_df, outer_stats):
    values = []
    zone_lookup = {int(row["zone_id"]): row for _, row in zone_df.iterrows()}
    for zone_id in range(1, 10):
        row = zone_lookup.get(zone_id)
        pct = float(row["pitch_pct"]) if row is not None else 0.0
        values.append((zone_id, pct))

    outer_zone_ids = {"tl": 11, "tr": 12, "bl": 13, "br": 14}
    for key, zone_id in outer_zone_ids.items():
        values.append((zone_id, float(outer_stats[key]["pitch_pct"])))

    if not values:
        return {}

    color_keys = ("red", "orange", "green", "blue")
    color_map = {}
    for rank, (zone_id, _) in enumerate(sorted(values, key=lambda item: (item[1], item[0]))):
        bucket = min(int(rank * len(color_keys) / len(values)), len(color_keys) - 1)
        color_map[zone_id] = ZONE_Z_SCORE_BACKGROUND_COLORS[color_keys[bucket]]
    return color_map


def _zone_background_style(
    metric,
    zone_id,
    pct,
    heatmap_scale=HEATMAP_SCALE_LEAGUE,
    self_color_map=None,
    baselines=None,
):
    if heatmap_scale == HEATMAP_SCALE_SELF:
        color = (self_color_map or {}).get(zone_id, "")
    else:
        color = _zone_background_color(metric, zone_id, pct, baselines=baselines)
    return f' style="--sz-bg:{color}; background-color:{color} !important;"' if color else ""


def _aggregate_outer_quadrants(statcast_df, total_pitches):
    total_pitches = 0 if total_pitches is None else total_pitches
    counts = {"tl": 0, "tr": 0, "bl": 0, "br": 0}

    if total_pitches > 0:
        zone_ids = statcast_df["zone"].apply(_normalize_zone_value)
        for zone_id in zone_ids.dropna().astype(int):
            key = OUTER_ZONE_TO_QUAD.get(zone_id)
            if key is not None:
                counts[key] += 1

    return {
        key: {
            "pitch_count": count,
            "pitch_pct": (count / total_pitches * 100.0) if total_pitches else 0.0,
        }
        for key, count in counts.items()
    }


def _build_strike_zone_html(
    zone_df,
    outer_stats,
    metric=None,
    heatmap_scale=HEATMAP_SCALE_LEAGUE,
    baselines=None,
):
    zone_lookup = {int(row["zone_id"]): row for _, row in zone_df.iterrows()}
    self_color_map = _build_self_heatmap_color_map(zone_df, outer_stats) if heatmap_scale == HEATMAP_SCALE_SELF else None

    inner_cells = []
    for zone_id in range(1, 10):
        row = zone_lookup.get(zone_id)
        if row is not None:
            cell_text = _format_cell_text(row["pitch_count"], row["pitch_pct"], metric=metric)
            cell_style = _zone_background_style(
                metric,
                zone_id,
                row["pitch_pct"],
                heatmap_scale=heatmap_scale,
                self_color_map=self_color_map,
                baselines=baselines,
            )
        else:
            cell_text = _format_cell_text(0, 0.0, metric=metric)
            cell_style = _zone_background_style(
                metric,
                zone_id,
                0.0,
                heatmap_scale=heatmap_scale,
                self_color_map=self_color_map,
                baselines=baselines,
            )
        inner_cells.append(f'<div class="sz-cell"{cell_style}>{cell_text}</div>')

    inner_html = "".join(inner_cells)

    outer_html = {
        key: {
            "text": _format_cell_text(outer_stats[key]["pitch_count"], outer_stats[key]["pitch_pct"], metric=metric),
            "style": _zone_background_style(
                metric,
                OUTER_QUAD_TO_ZONE[key],
                outer_stats[key]["pitch_pct"],
                heatmap_scale=heatmap_scale,
                self_color_map=self_color_map,
                baselines=baselines,
            ),
        }
        for key in ("tl", "tr", "bl", "br")
    }
    outer_bg_html = "".join(
        f'<div class="sz-quad-bg sz-quad-bg-{key}"{outer_html[key]["style"]}></div>'
        for key in ("tl", "tr", "bl", "br")
    )

    return f"""
    <style>
      .sz-chart-wrap {{
        display: flex;
        justify-content: center;
                margin: 8px 0;
      }}
      .sz-outer {{
        position: relative;
        width: 100%;
                max-width: 620px;
        aspect-ratio: 1;
        border: 2px solid #000;
        background-color: var(--sz-bg, #fff) !important;
        box-sizing: border-box;
      }}
      .sz-cross-h,
      .sz-cross-v {{
        position: absolute;
        background: #000;
        z-index: 1;
      }}
      .sz-cross-h {{
        top: 50%;
        left: 0;
        width: 100%;
        height: 2px;
        transform: translateY(-50%);
      }}
      .sz-cross-v {{
        left: 50%;
        top: 0;
        height: 100%;
        width: 2px;
        transform: translateX(-50%);
      }}
            .sz-quad-bg {{
                position: absolute;
                width: 50%;
                height: 50%;
                z-index: 0;
                background-color: var(--sz-bg, #fff) !important;
            }}
            .sz-quad-bg-tl {{ top: 0; left: 0; }}
            .sz-quad-bg-tr {{ top: 0; left: 50%; }}
            .sz-quad-bg-bl {{ top: 50%; left: 0; }}
            .sz-quad-bg-br {{ top: 50%; left: 50%; }}
            .sz-quad {{
                position: absolute;
                z-index: 3;
                display: flex;
                align-items: center;
                justify-content: center;
                text-align: center;
                font-size: 14px;
                font-weight: 600;
                color: #111;
                line-height: 1.25;
                width: auto;
                height: auto;
                padding: 2px 4px;
                background-color: var(--sz-bg, #fff) !important;
                transform: translate(-50%, -50%);
            }}
            .sz-quad-tl {{ top: 14%; left: 14%; }}
            .sz-quad-tr {{ top: 14%; left: 86%; }}
            .sz-quad-bl {{ top: 86%; left: 14%; }}
            .sz-quad-br {{ top: 86%; left: 86%; }}
      .sz-inner {{
        position: absolute;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        width: 58%;
        height: 58%;
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        grid-template-rows: repeat(3, 1fr);
        border: 3px solid #000;
        background-color: var(--sz-bg, #fff) !important;
        box-sizing: border-box;
        z-index: 2;
      }}
      .sz-cell {{
        border: 2px solid #000;
        display: flex;
        align-items: center;
        justify-content: center;
        text-align: center;
        font-size: 14px;
        font-weight: 600;
        color: #111;
        line-height: 1.35;
        box-sizing: border-box;
        background-color: var(--sz-bg, #fff) !important;
      }}
    </style>
    <div class="sz-chart-wrap">
      <div class="sz-outer">
        {outer_bg_html}
        <div class="sz-cross-h"></div>
        <div class="sz-cross-v"></div>
        <div class="sz-quad sz-quad-tl"{outer_html["tl"]["style"]}>{outer_html["tl"]["text"]}</div>
        <div class="sz-quad sz-quad-tr"{outer_html["tr"]["style"]}>{outer_html["tr"]["text"]}</div>
        <div class="sz-quad sz-quad-bl"{outer_html["bl"]["style"]}>{outer_html["bl"]["text"]}</div>
        <div class="sz-quad sz-quad-br"{outer_html["br"]["style"]}>{outer_html["br"]["text"]}</div>
        <div class="sz-inner">
          {inner_html}
        </div>
      </div>
    </div>
    """


def render_strike_zone_grid(zone_df, filtered_df, total_pitches=None):
    total_pitches = len(filtered_df) if total_pitches is None else total_pitches
    outer_stats = _aggregate_outer_quadrants(filtered_df, total_pitches=total_pitches)
    return _build_strike_zone_html(zone_df, outer_stats)


def display_strike_zone(
    player_id,
    pitch_type,
    batter_stands="All Batters",
    metric="Pitch %",
    heatmap_scale=HEATMAP_SCALE_LEAGUE,
):
    season_year = date.today().year
    start_date = f"{season_year}-03-01"
    end_date = date.today().isoformat()
    metric = _pitcher_metric_label(metric)

    try:
        raw_df = load_pitch_location_data(player_id, start_date, end_date)
        filtered_df = filter_by_pitch_type(raw_df, pitch_type)
        filtered_df = filter_by_batter_stands(filtered_df, batter_stands)
    except Exception as exc:
        logger.error("Strike zone processing failed for player_id=%s: %s", player_id, exc)
        st.info("Strike zone data is unavailable for this pitcher right now.")
        return

    if filtered_df.empty:
        st.info("Strike zone data is unavailable for this pitcher right now.")
        return

    unavailable_reason = _pitcher_metric_unavailable_reason(filtered_df, metric)
    if unavailable_reason:
        st.info(unavailable_reason)
        return

    zone_df, outer_stats, _ = _build_pitcher_metric_zone_outputs(filtered_df, metric)
    html = _build_strike_zone_html(
        zone_df,
        outer_stats,
        metric=metric,
        heatmap_scale=heatmap_scale,
        baselines=PITCHER_ZONE_METRIC_BASELINES,
    )
    st.markdown(html, unsafe_allow_html=True)


def display_batter_strike_zone(batter_id, pitch_type, pitcher_throws="All", metric="Pitch %"):
    season_year = date.today().year
    start_date = f"{season_year}-03-01"
    end_date = date.today().isoformat()

    try:
        raw_df = load_batter_pitch_location_data(batter_id, start_date, end_date)
        filtered_df = filter_by_pitch_type(raw_df, pitch_type)
        filtered_df = filter_by_pitcher_throws(filtered_df, pitcher_throws)
    except Exception as exc:
        logger.error("Strike zone processing failed for batter_id=%s: %s", batter_id, exc)
        st.info("Strike zone data is unavailable for this batter right now.")
        return

    if filtered_df.empty:
        st.info("Strike zone data is unavailable for this batter right now.")
        return

    metric_mask = _batter_metric_mask(filtered_df, metric)
    metric_df = filtered_df[metric_mask].copy() if not metric_mask.empty else filtered_df.iloc[0:0].copy()

    total_pitches = len(filtered_df)
    zone_df = aggregate_to_zones(metric_df, total_pitches=total_pitches)
    html = render_strike_zone_grid(zone_df, metric_df, total_pitches=total_pitches)
    st.markdown(html, unsafe_allow_html=True)
