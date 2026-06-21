import logging
from datetime import date

import pandas as pd
import streamlit as st

logger = logging.getLogger(__name__)

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


def _normalize_zone_value(zone_value):
    if pd.isna(zone_value):
        return None
    try:
        return int(zone_value)
    except (TypeError, ValueError):
        return None


@st.cache_data(ttl=300, show_spinner="Loading strike zone data...")
def load_pitch_location_data(player_id, start_date, end_date):
    try:
        from pybaseball import statcast_pitcher

        df = statcast_pitcher(start_date, end_date, int(player_id))
    except Exception as exc:
        logger.error("Statcast fetch failed for player_id=%s: %s", player_id, exc)
        return pd.DataFrame()

    if df is None or df.empty:
        return pd.DataFrame()

    required = {"zone"}
    if not required.issubset(df.columns):
        logger.error("Statcast data missing zone column for player_id=%s", player_id)
        return pd.DataFrame()

    result_df = df.dropna(subset=["zone"]).copy()
    if "game_type" in result_df.columns:
        result_df = result_df[result_df["game_type"] == "R"].copy()
    if "batter_stands" not in result_df.columns and "stand" in result_df.columns:
        result_df["batter_stands"] = result_df["stand"]

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
        from pybaseball import statcast_batter

        df = statcast_batter(start_date, end_date, int(batter_id))
    except Exception as exc:
        logger.error("Statcast fetch failed for batter_id=%s: %s", batter_id, exc)
        return pd.DataFrame()

    if df is None or df.empty:
        return pd.DataFrame()

    if "zone" not in df.columns:
        logger.error("Statcast data missing zone column for batter_id=%s", batter_id)
        return pd.DataFrame()

    result_df = df.dropna(subset=["zone"]).copy()
    if "game_type" in result_df.columns:
        result_df = result_df[result_df["game_type"] == "R"].copy()
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
    working_df = filtered_df.copy()
    if working_df.empty:
        return pd.DataFrame()

    pitch_col = "pitch_name" if "pitch_name" in working_df.columns else "pitch_type"
    if pitch_col not in working_df.columns:
        return pd.DataFrame()

    working_df[pitch_col] = working_df[pitch_col].astype(str).str.strip()
    working_df = working_df[(working_df[pitch_col] != "") & (working_df[pitch_col].str.lower() != "nan")].copy()
    if working_df.empty:
        return pd.DataFrame()

    if metric in {"Pitch %", "Takes", "Batted Balls", "Home Runs"}:
        metric_masks = {
            "Pitch %": pd.Series(True, index=working_df.index),
            "Takes": working_df["description"].astype(str).str.lower().isin({"called_strike", "ball", "ballinplay", "blocked_ball", "pitchout"}) if "description" in working_df.columns else pd.Series(False, index=working_df.index),
            "Batted Balls": working_df["events"].astype(str).str.lower().isin({"single", "double", "triple", "home_run", "field_out", "grounded_into_double_play", "force_out", "fielders_choice_out", "field_error", "double_play", "triple_play", "other_out", "sac_fly", "sac_fly_double_play", "fielders_choice"}) if "events" in working_df.columns else pd.Series(False, index=working_df.index),
            "Home Runs": working_df["events"].astype(str).str.lower().eq("home_run") if "events" in working_df.columns else pd.Series(False, index=working_df.index),
        }
        metric_mask = metric_masks.get(metric, pd.Series(False, index=working_df.index))
        if metric == "Pitch %":
            metric_df = working_df.copy()
        else:
            metric_df = working_df[metric_mask].copy()
    elif metric == "K%":
        if "events" not in working_df.columns:
            return pd.DataFrame()
        # Use plate appearances, not pitch rows, so zone K% behaves like Savant's pitch highlighter.
        working_df["_pa_key"] = _plate_appearance_key(working_df)
        k_pa_keys = set(working_df.loc[working_df["events"].astype(str).str.lower().eq("strikeout"), "_pa_key"].astype(str))
    else:
        return pd.DataFrame()

    zone_counts = {zone["zone_id"]: 0 for zone in ZONE_LAYOUT}
    zone_denominators = {zone["zone_id"]: 0 for zone in ZONE_LAYOUT}

    if metric == "K%":
        zone_pa_sets = {zone["zone_id"]: set() for zone in ZONE_LAYOUT}
        zone_k_pa_sets = {zone["zone_id"]: set() for zone in ZONE_LAYOUT}

        for zone_id, pa_key in zip(working_df["zone"].apply(_normalize_zone_value), working_df["_pa_key"].astype(str)):
            if zone_id in zone_pa_sets:
                zone_pa_sets[zone_id].add(pa_key)
                if pa_key in k_pa_keys:
                    zone_k_pa_sets[zone_id].add(pa_key)

        for zone in ZONE_LAYOUT:
            zone_id = zone["zone_id"]
            zone_denominators[zone_id] = len(zone_pa_sets[zone_id])
            zone_counts[zone_id] = len(zone_k_pa_sets[zone_id])
    else:
        if working_df.empty:
            return pd.DataFrame()

        zone_ids = metric_df["zone"].apply(_normalize_zone_value)
        for zone_id in zone_ids.dropna().astype(int):
            if zone_id in zone_counts:
                zone_counts[zone_id] += 1

        total = float(len(metric_df))

    rows = []
    for zone in ZONE_LAYOUT:
        zone_id = zone["zone_id"]
        count = zone_counts[zone_id]
        total_for_zone = zone_denominators[zone_id] if metric == "K%" else total
        rows.append(
            {
                **zone,
                "pitch_count": int(count),
                "pitch_pct": (count / total_for_zone * 100.0) if total_for_zone else 0.0,
            }
        )

    return pd.DataFrame(rows)


def _build_batter_metric_strike_zone_html(zone_df, outer_stats):
    return _build_strike_zone_html(zone_df, outer_stats)


def display_batter_metric_strike_zone(batter_id, pitch_type, pitcher_throws="All", metric="Pitch %"):
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

    zone_df = _build_metric_zone_dataframe(filtered_df, metric)
    if zone_df.empty:
        st.info("Strike zone data is unavailable for this batter right now.")
        return

    outer_stats = _aggregate_outer_quadrants(filtered_df if metric == "Pitch %" else filtered_df[filtered_df["zone"].apply(_normalize_zone_value).isin({11, 12, 13, 14})])
    html = _build_batter_metric_strike_zone_html(zone_df, outer_stats)
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


def _format_cell_text(count, pct):
    return f"{int(count)}<br>{pct:.1f}%"


def _aggregate_outer_quadrants(statcast_df, total_pitches=None):
    total_pitches = len(statcast_df) if total_pitches is None else total_pitches
    counts = {"tl": 0, "tr": 0, "bl": 0, "br": 0}

    if total_pitches > 0:
        zone_to_quad = {11: "tl", 12: "tr", 13: "bl", 14: "br"}
        zone_ids = statcast_df["zone"].apply(_normalize_zone_value)
        for zone_id in zone_ids.dropna().astype(int):
            key = zone_to_quad.get(zone_id)
            if key is not None:
                counts[key] += 1

    return {
        key: {
            "pitch_count": count,
            "pitch_pct": (count / total_pitches * 100.0) if total_pitches else 0.0,
        }
        for key, count in counts.items()
    }


def _build_strike_zone_html(zone_df, outer_stats):
    zone_lookup = {int(row["zone_id"]): row for _, row in zone_df.iterrows()}

    inner_cells = []
    for zone_id in range(1, 10):
        row = zone_lookup.get(zone_id)
        if row is not None:
            inner_cells.append(_format_cell_text(row["pitch_count"], row["pitch_pct"]))
        else:
            inner_cells.append("0<br>0.0%")

    inner_html = "".join(f'<div class="sz-cell">{text}</div>' for text in inner_cells)

    outer_html = {
        key: _format_cell_text(outer_stats[key]["pitch_count"], outer_stats[key]["pitch_pct"])
        for key in ("tl", "tr", "bl", "br")
    }

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
        background: #fff;
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
                background: #fff;
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
        background: #fff;
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
        background: #fff;
      }}
    </style>
    <div class="sz-chart-wrap">
      <div class="sz-outer">
        <div class="sz-cross-h"></div>
        <div class="sz-cross-v"></div>
        <div class="sz-quad sz-quad-tl">{outer_html["tl"]}</div>
        <div class="sz-quad sz-quad-tr">{outer_html["tr"]}</div>
        <div class="sz-quad sz-quad-bl">{outer_html["bl"]}</div>
        <div class="sz-quad sz-quad-br">{outer_html["br"]}</div>
        <div class="sz-inner">
          {inner_html}
        </div>
      </div>
    </div>
    """


def render_strike_zone_grid(zone_df, filtered_df, total_pitches=None):
    outer_stats = _aggregate_outer_quadrants(filtered_df, total_pitches=total_pitches)
    return _build_strike_zone_html(zone_df, outer_stats)


def display_strike_zone(player_id, pitch_type, batter_stands="All Batters"):
    season_year = date.today().year
    start_date = f"{season_year}-03-01"
    end_date = date.today().isoformat()

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

    zone_df = aggregate_to_zones(filtered_df)
    html = render_strike_zone_grid(zone_df, filtered_df)
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
