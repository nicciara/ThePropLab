import logging
import time
import json
import io
import html
import base64
import altair as alt
import streamlit as st
import pandas as pd
import requests
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.parse import quote_plus

import strike_zone

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
PLAYER_API_CALLS = 0
LINEUP_MIN_HEIGHT = 220
GAME_LOG_PROPS = ["Hits", "Runs", "RBI", "H+R+RBI", "Total Bases", "Home Runs", "Walks", "Strikeouts"]
GAME_LOG_PROP_COLUMNS = {
    "Hits": "hits",
    "Runs": "runs",
    "RBI": "rbi",
    "H+R+RBI": "hrrrbi",
    "Total Bases": "total_bases",
    "Home Runs": "home_runs",
    "Walks": "walks",
    "Strikeouts": "strikeouts",
}
PRIZEPICKS_MLB_LEAGUE_ID = 2
PRIZEPICKS_PROJECTIONS_URL = "https://api.prizepicks.com/projections"
PROJECTION_STATE_KEYS = (
    "selected_projection",
    "selected_batter_projection",
    "projection_data",
    "prizepicks_projection",
    "prizepicks_projections",
    "prop_projections",
)

st.set_page_config(page_title="🧪 The Prop Lab", layout="wide")

# Header: single-line title with sport selector (MLB, NBA, NFL, NHL, WNBA)
# Single header row with two columns: title (left) and dropdown (right)
header_left, header_right = st.columns([9, 1])
with header_left:
    st.markdown(
        "<div style='font-size:20px; font-weight:700; text-align:left; margin:0; padding-left:0;'>🧪 The Prop Lab |</div>",
        unsafe_allow_html=True,
    )
with header_right:
    sport = st.selectbox("", ["MLB", "NBA", "NFL", "NHL", "WNBA"], index=0, key="selected_sport")

# If a non-MLB sport is selected, show a simple coming-soon placeholder and stop further MLB-specific rendering.
if sport != "MLB":
    st.markdown(
        f"<div style='display:flex; align-items:center; justify-content:center; height:200px;'><div style='text-align:center; font-size:20px; color:#374151; font-weight:600;'>{sport} coming soon — check back later.</div></div>",
        unsafe_allow_html=True,
    )
    st.stop()

st.markdown(
    """
    <style>
    :root{
        --dash-surface:#edf4ff;
        --dash-surface-2:#e3eeff;
        --dash-border:#5f7598;
        --dash-shadow:0 10px 24px rgba(15,23,42,0.18);
        --dash-title:#0f172a;
        --dash-label:#1f2d42;
        --dash-value:#0b1220;
        --dash-accent:#0057d8;
    }
    section[data-testid="stMain"] .block-container{padding-bottom:1rem}
    section[data-testid="stMain"]{background:linear-gradient(180deg,#f7faff 0%, #f3f7ff 100%)}
    section[data-testid="stMain"] [data-testid="stVerticalBlock"]{gap:0.5rem}
    section[data-testid="stMain"] [data-testid="stHorizontalBlock"]{gap:0.75rem}
    section[data-testid="stMain"] h1,section[data-testid="stMain"] h2,section[data-testid="stMain"] h3{margin-top:0.2rem;margin-bottom:0.45rem}
    section[data-testid="stMain"] p{margin-top:0.2rem;margin-bottom:0.3rem}
    section[data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"]{
        border:2px solid var(--dash-border)!important;
        border-radius:16px!important;
        background:#ffffff!important;
        box-shadow:var(--dash-shadow)!important;
    }
    .game-card{padding:10px 14px 20px 14px;box-sizing:border-box}
    .game-card .lineup-area{padding:8px 6px}
    /* Style Streamlit buttons used as inline pitcher links to look like normal hyperlinks (scoped to game cards) */
    .game-card .stButton>button{background:none;border:none;padding:0;color:var(--dash-value);text-decoration:none;cursor:pointer;font-size:inherit;font-weight:650}
    .game-card .stButton>button:hover{color:var(--dash-accent);text-decoration:underline}
    .nav-name-link{color:var(--dash-value)!important;text-decoration:none!important;font-weight:650;cursor:pointer}
    .nav-name-link:hover{color:var(--dash-accent)!important;text-decoration:underline!important}
    div[data-testid="stSegmentedControl"] div[role="radiogroup"]{overflow-x:auto;flex-wrap:nowrap}
    div[data-testid="stSegmentedControl"] label{white-space:nowrap}
    .prop-line-value{display:flex;align-items:center;justify-content:center;min-height:38px;border:1px solid #dbe3ef;border-radius:999px;background:#f8fafc;color:var(--dash-title);font-weight:900;font-size:17px;box-shadow:0 1px 2px rgba(15,23,42,0.04)}
    .prop-line-detail{display:flex;align-items:center;justify-content:center;gap:7px;min-height:38px;border:1px solid #dbe3ef;border-radius:999px;background:#f8fafc;color:var(--dash-title);font-weight:850;font-size:13px;box-shadow:0 1px 2px rgba(15,23,42,0.04);white-space:nowrap}
    .prop-line-main{font-size:17px;font-weight:900}
    .prop-source-logo{height:24px;width:auto;max-width:96px;object-fit:contain;vertical-align:middle;display:inline-block}
    .prop-boost-img{height:24px;width:24px;object-fit:contain;vertical-align:middle;display:inline-block}
    .prop-alt-row{display:flex;align-items:center;gap:7px;padding:5px 8px;margin:3px 0;border:1px solid #e5e7eb;border-radius:999px;background:#fff;font-size:12px;font-weight:750;color:var(--dash-value);white-space:nowrap}
    .prop-control-spacer{height:4px}
    .dash-card{
        border:2px solid var(--dash-border);
        border-radius:16px;
        background:#ffffff;
        box-shadow:var(--dash-shadow);
        padding:14px 16px;
        position:relative;
        overflow:hidden;
    }
    .dash-card:before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--dash-accent)}
    .dash-card-title{font-weight:900;font-size:21px;line-height:1.15;color:var(--dash-title);margin-bottom:12px}
    .dash-grid{display:grid;grid-template-columns:1fr auto;row-gap:8px;column-gap:14px;font-size:13px}
    .dash-grid-compact{display:grid;grid-template-columns:126px auto;column-gap:8px;row-gap:7px;font-size:12px;line-height:1.25}
    .dash-label{font-weight:800;color:var(--dash-label);letter-spacing:0.015em;text-transform:uppercase;font-size:11px}
    .dash-value{font-weight:800;color:var(--dash-value);font-size:14px}
    .dash-accent{font-weight:800;color:var(--dash-accent)}
    .section-title-strong{font-weight:900;font-size:24px;color:var(--dash-title);margin-bottom:10px;line-height:1.15;letter-spacing:0.01em}
    section[data-testid="stMain"] [data-baseweb="select"]{
        filter:none!important;
        zoom:1!important;
    }
    section[data-testid="stMain"] [data-baseweb="select"] div,
    section[data-testid="stMain"] [data-baseweb="select"] span{
        filter:none!important;
        font-weight:400!important;
        color:#111827!important;
        line-height:1.35!important;
        text-rendering:auto;
        -webkit-font-smoothing:auto;
    }
    section[data-testid="stMain"] [data-baseweb="select"] svg{
        filter:none!important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def _projection_value(record, *keys, default=""):
    if not isinstance(record, dict):
        return default
    search_records = [record]
    for nested_key in ("attributes", "data", "projection", "line", "relationships"):
        nested = record.get(nested_key)
        if isinstance(nested, dict):
            search_records.append(nested)

    for key in keys:
        for candidate in search_records:
            lowered = {str(candidate_key).lower(): value for candidate_key, value in candidate.items()}
            if key in candidate:
                value = candidate.get(key)
                if value not in {None, ""}:
                    return value
            value = lowered.get(str(key).lower())
            if value not in {None, ""}:
                return value
    return default


def _projection_truthy(record, *keys):
    value = _projection_value(record, *keys, default=False)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "y", "goblin", "demon"}


@st.cache_data
def local_asset_data_uri(relative_path):
    path = Path(relative_path)
    if not path.exists():
        return ""
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def local_asset_img(relative_path, css_class, alt):
    src = local_asset_data_uri(relative_path)
    if not src:
        return ""
    return f"<img class='{css_class}' src='{src}' alt='{html.escape(alt, quote=True)}' />"


def prizepicks_boost_indicator(record):
    if not isinstance(record, dict):
        return ""

    odds_type = normalize_name(_projection_value(record, "odds_type", "oddsType", default=""))
    if odds_type == "goblin":
        return local_asset_img("assets/goblin.png", "prop-boost-img", "Goblin")
    if odds_type == "demon":
        return local_asset_img("assets/demon.png", "prop-boost-img", "Demon")
    return ""


def _projection_line_value(record):
    value = _projection_value(
        record,
        "flash_sale_line_score", "flashSaleLineScore", "line", "line_score", "lineScore",
        "value", "statValue", "stat_value", "projection",
    )
    if value in {None, ""}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def _projection_stat_type(record):
    return normalize_name(_projection_value(record, "stat_display_name", "statDisplayName", "stat_type", "statType", "prop", "market", "name", default=""))


def _projection_player_id(record):
    value = _projection_value(record, "player_id", "playerId", "mlbam_id", "mlbamId", "batter_id", "batterId")
    return str(value or "")


def _projection_player_name(record):
    return str(_projection_value(record, "player", "player_name", "display_name", "displayName", "name", "full_name", "fullName", default="") or "")


def _projection_source_label(record):
    source = str(_projection_value(record, "source", "sportsbook", "book", "provider", default="PrizePicks") or "PrizePicks")
    return "PP" if normalize_name(source) == "prizepicks" else source


def _prop_match_key(value):
    normalized = normalize_name(value).replace("+", " ")
    compact = normalized.replace(" ", "")
    aliases = {
        "hits": "hits",
        "runs": "runs",
        "rbi": "rbi",
        "rbis": "rbi",
        "hrrrbi": "hrrrbi",
        "hitsrunsrbis": "hrrrbi",
        "hitsrunsrbi": "hrrrbi",
        "totalbases": "totalbases",
        "homeruns": "homeruns",
        "walks": "walks",
        "strikeouts": "strikeouts",
    }
    return aliases.get(compact, compact)


def _projection_meta_html(record):
    if not isinstance(record, dict):
        return ""
    source_html = local_asset_img("assets/prizepicks_logo.png", "prop-source-logo", "PrizePicks")
    indicator_html = prizepicks_boost_indicator(record)
    odds = _projection_value(record, "odds", "americanOdds", "american_odds", "price", default="")
    payout = _projection_value(record, "payout", "multiplier", "count", "entryCount", "entry_count", default="")
    odds_html = f"<span>{html.escape(str(odds))}</span>" if odds not in {None, ""} else ""
    payout_html = f"<span>{html.escape(str(payout))}</span>" if payout not in {None, ""} else ""
    return "".join(part for part in (source_html, indicator_html, odds_html, payout_html) if part)


def projection_debug_snapshot(record):
    interesting_keys = [
        "adjusted_odds", "adjustedOdds", "odds_type", "oddsType", "projection_type",
        "projectionType", "flash_sale_line_score", "flashSaleLineScore", "line_score",
        "lineScore", "payout", "rank", "description", "stat_type", "statType",
    ]
    attrs = record.get("attributes", {}) if isinstance(record, dict) else {}
    return {
        "line value": _projection_line_value(record),
        "sportsbook/source": _projection_source_label(record),
        "boost indicator html": prizepicks_boost_indicator(record),
        "player_id": _projection_player_id(record),
        "stat_type": _projection_stat_type(record),
        "interesting fields": {
            key: _projection_value(record, key, default="")
            for key in interesting_keys
            if _projection_value(record, key, default="") not in {None, ""}
        },
        "top-level keys": list(record.keys()) if isinstance(record, dict) else [],
        "attribute keys": list(attrs.keys()) if isinstance(attrs, dict) else [],
        "full attributes": attrs,
        "full projection object": record,
    }


def projection_debug_summary(record):
    return {
        "player": _projection_player_name(record),
        "team": _projection_value(record, "team", default=""),
        "stat_display_name": _projection_value(record, "stat_display_name", "statDisplayName", default=""),
        "line_score": _projection_value(record, "line_score", "lineScore", default=""),
        "description": _projection_value(record, "description", default=""),
        "adjusted_odds": _projection_value(record, "adjusted_odds", "adjustedOdds", default=""),
        "projection_type": _projection_value(record, "projection_type", "projectionType", default=""),
        "payout": _projection_value(record, "payout", "payout_multiplier", "payoutMultiplier", default=""),
        "rank": _projection_value(record, "rank", default=""),
    }


def _flatten_projection_records(value):
    if isinstance(value, list):
        for item in value:
            yield from _flatten_projection_records(item)
    elif isinstance(value, dict):
        if _projection_line_value(value) is not None:
            yield value
        for key in ("alt_lines", "altLines", "lines", "projections", "projection_lines", "projectionLines"):
            nested = value.get(key)
            if nested is not None:
                yield from _flatten_projection_records(nested)


def get_prop_projection_lines(batter_id, selected_prop, batter_name=""):
    selected_prop_key = _prop_match_key(selected_prop)
    selected_name_key = normalize_name(batter_name)
    lines = []
    for record in st.session_state.get("prizepicks_projections", []):
        if not isinstance(record, dict):
            continue
        player_name = normalize_name(record.get("player") or _projection_player_name(record))
        if selected_name_key and player_name != selected_name_key:
            continue
        stat_type = record.get("stat_display_name") or _projection_stat_type(record)
        if _prop_match_key(stat_type) != selected_prop_key:
            continue
        lines.append(record)
    return lines


def render_prizepicks_line_detail(line_value, projection_record=None):
    line_html = f"<span class='prop-line-main'>{float(line_value):.1f}</span>"
    meta_html = _projection_meta_html(projection_record)
    if not meta_html:
        return f"<div class='prop-line-value'>{line_html}</div>"
    return f"<div class='prop-line-detail'>{line_html}{meta_html}</div>"


@st.cache_data(ttl=300)
def load_prizepicks_mlb_projections(debug_version=2):
    headers = {
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://app.prizepicks.com",
        "Referer": "https://app.prizepicks.com/",
        "User-Agent": "Mozilla/5.0",
    }
    params = {
        "league_id": PRIZEPICKS_MLB_LEAGUE_ID,
        "per_page": 1000,
    }
    try:
        response = requests.get(PRIZEPICKS_PROJECTIONS_URL, params=params, headers=headers, timeout=20)
        print("PrizePicks request URL:", response.url)
        print("PrizePicks HTTP status:", response.status_code)
        logger.warning("PrizePicks request URL: %s", response.url)
        logger.warning("PrizePicks HTTP status: %s", response.status_code)
        response.raise_for_status()
        payload = response.json()
        data_len = len(payload.get("data", [])) if isinstance(payload, dict) else 0
        print("PrizePicks response data length:", data_len)
        logger.warning("PrizePicks response data length: %s", data_len)
    except Exception as exc:
        print("PrizePicks projections request failed:", repr(exc))
        logger.warning("PrizePicks projections request failed: %s", exc)
        return []

    included_by_type_id = {}
    for item in payload.get("included", []):
        if not isinstance(item, dict):
            continue
        item_type = item.get("type", "")
        item_id = str(item.get("id", ""))
        if item_type and item_id:
            included_by_type_id[(item_type, item_id)] = item

    def related_object(projection, relationship_name):
        rel_data = projection.get("relationships", {}).get(relationship_name, {}).get("data")
        if isinstance(rel_data, list):
            return [
                included_by_type_id.get((item.get("type", ""), str(item.get("id", ""))))
                for item in rel_data
                if isinstance(item, dict)
            ]
        if isinstance(rel_data, dict):
            return included_by_type_id.get((rel_data.get("type", ""), str(rel_data.get("id", ""))))
        return None

    parsed = []
    for projection in payload.get("data", []):
        if not isinstance(projection, dict):
            continue
        attributes = projection.get("attributes", {}) if isinstance(projection.get("attributes"), dict) else {}
        relationships = projection.get("relationships", {}) if isinstance(projection.get("relationships"), dict) else {}
        player = related_object(projection, "new_player") or related_object(projection, "player")
        score = related_object(projection, "score")
        player_attributes = player.get("attributes", {}) if isinstance(player, dict) and isinstance(player.get("attributes"), dict) else {}

        player_name = (
            player_attributes.get("display_name")
            or player_attributes.get("name")
            or player_attributes.get("full_name")
            or attributes.get("name")
        )

        parsed_projection = {
            "id": projection.get("id"),
            "type": projection.get("type"),
            "source": "PrizePicks",
            "attributes": attributes,
            "relationships": relationships,
            "new_player": player,
            "score": score,
            "raw_projection": projection,
            "stat_display_name": attributes.get("stat_display_name"),
            "description": attributes.get("description"),
            "line_score": attributes.get("line_score"),
            "flash_sale_line_score": attributes.get("flash_sale_line_score"),
            "adjusted_odds": attributes.get("adjusted_odds"),
            "projection_type": attributes.get("projection_type"),
            "odds_type": attributes.get("odds_type"),
            "payout": attributes.get("payout") or attributes.get("payout_multiplier"),
            "rank": attributes.get("rank"),
            "player": player_name,
            "player_name": player_name,
            "league": player_attributes.get("league"),
            "team": player_attributes.get("team"),
        }
        parsed.append(parsed_projection)

    print("PrizePicks parsed projection count:", len(parsed))
    logger.warning("PrizePicks parsed projection count: %s", len(parsed))
    return parsed

# (Pitcher view rendering via query params moved below helper function definitions)
def eastern_time(utc_time):
    if not utc_time:
        return "TBD"
    dt = datetime.fromisoformat(utc_time.replace("Z", "+00:00"))
    return dt.astimezone(ZoneInfo("America/New_York")).strftime("%I:%M %p ET").lstrip("0")


def eastern_today():
    return datetime.now(ZoneInfo("America/New_York")).date()


PITCH_TYPE_COLORS = {
    "4-seam fastball": "#dc2626",
    "four-seam fastball": "#dc2626",
    "fastball": "#dc2626",
    "sinker": "#f97316",
    "sweeper": "#c2410c",
    "slider": "#b45309",
    "changeup": "#15803d",
    "curveball": "#0f766e",
    "cutter": "#92400e",
    "split-finger": "#0f766e",
    "split finger": "#0f766e",
    "splitter": "#0f766e",
    "knuckle curve": "#7e22ce",
    "slurve": "#8b5cf6",
}


def pitch_type_color(pitch_name):
    normalized = str(pitch_name or "").strip().lower()
    if not normalized:
        return ""

    for key in ("4-seam fastball", "four-seam fastball", "knuckle curve", "split-finger", "split finger"):
        if key in normalized:
            return PITCH_TYPE_COLORS[key]

    for key, color in PITCH_TYPE_COLORS.items():
        if key in normalized:
            return color
    return ""


def pitch_type_text_html(pitch_name):
    color = pitch_type_color(pitch_name)
    escaped_name = html.escape(str(pitch_name or ""))
    if not color:
        return escaped_name
    return f"<span style='color:{color}; font-weight:700;'>{escaped_name}</span>"


def pitch_type_cell_style(value):
    color = pitch_type_color(value)
    return f"color:{color}; font-weight:700;" if color else ""


RUN_VALUE_STYLE_COLORS = {
    "bad": "color:#dc2626; font-weight:700;",
    "average": "color:#d97706; font-weight:700;",
    "good": "color:#16a34a; font-weight:700;",
    "elite": "color:#2563eb; font-weight:700;",
}


def run_value_threshold_style(value, metric):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""

    if metric in {"BA", "xBA"}:
        if number < 0.240:
            return RUN_VALUE_STYLE_COLORS["bad"]
        if number < 0.270:
            return RUN_VALUE_STYLE_COLORS["average"]
        if number < 0.300:
            return RUN_VALUE_STYLE_COLORS["good"]
        return RUN_VALUE_STYLE_COLORS["elite"]
    if metric in {"SLG", "xSLG"}:
        if number < 0.400:
            return RUN_VALUE_STYLE_COLORS["bad"]
        if number < 0.450:
            return RUN_VALUE_STYLE_COLORS["average"]
        if number < 0.500:
            return RUN_VALUE_STYLE_COLORS["good"]
        return RUN_VALUE_STYLE_COLORS["elite"]
    if metric in {"wOBA", "xwOBA"}:
        if number < 0.310:
            return RUN_VALUE_STYLE_COLORS["bad"]
        if number < 0.340:
            return RUN_VALUE_STYLE_COLORS["average"]
        if number < 0.380:
            return RUN_VALUE_STYLE_COLORS["good"]
        return RUN_VALUE_STYLE_COLORS["elite"]
    if metric == "Hard Hit%":
        if number < 38:
            return RUN_VALUE_STYLE_COLORS["bad"]
        if number < 45:
            return RUN_VALUE_STYLE_COLORS["average"]
        if number < 50:
            return RUN_VALUE_STYLE_COLORS["good"]
        return RUN_VALUE_STYLE_COLORS["elite"]
    if metric == "Whiff%":
        if number < 22:
            return RUN_VALUE_STYLE_COLORS["bad"]
        if number < 28:
            return RUN_VALUE_STYLE_COLORS["average"]
        if number < 35:
            return RUN_VALUE_STYLE_COLORS["good"]
        return RUN_VALUE_STYLE_COLORS["elite"]
    if metric == "K%":
        if number < 20:
            return RUN_VALUE_STYLE_COLORS["bad"]
        if number < 25:
            return RUN_VALUE_STYLE_COLORS["average"]
        if number < 30:
            return RUN_VALUE_STYLE_COLORS["good"]
        return RUN_VALUE_STYLE_COLORS["elite"]
    if metric == "PutAway%":
        if number < 18:
            return RUN_VALUE_STYLE_COLORS["bad"]
        if number < 25:
            return RUN_VALUE_STYLE_COLORS["average"]
        if number < 30:
            return RUN_VALUE_STYLE_COLORS["good"]
        return RUN_VALUE_STYLE_COLORS["elite"]
    return ""


def style_run_value_table(df):
    styled = df.style.map(pitch_type_cell_style, subset=["Pitch Type"])
    for column in ["BA", "SLG", "wOBA", "xBA", "xSLG", "xwOBA", "Hard Hit%", "Whiff%", "K%", "PutAway%"]:
        if column in df.columns:
            styled = styled.map(lambda value, metric=column: run_value_threshold_style(value, metric), subset=[column])
    return styled


@st.cache_data(ttl=1800)
def load_batter_prop_game_log(batter_id):
    if not batter_id:
        return pd.DataFrame()

    season_year = 2026
    url = f"https://statsapi.mlb.com/api/v1/people/{batter_id}/stats"
    params = {"stats": "gameLog", "group": "hitting", "season": season_year, "sportIds": 1}

    def _int_stat(stat, key):
        try:
            return int(stat.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0

    try:
        data = requests.get(url, params=params, timeout=20).json()
    except Exception as exc:
        logger.warning("MLB batter game log request failed for %s: %s", batter_id, exc)
        return pd.DataFrame()

    rows = []
    splits = data.get("stats", [{}])[0].get("splits", []) if data.get("stats") else []
    for split in splits:
        stat = split.get("stat", {})
        game_date = pd.to_datetime(split.get("date"), errors="coerce")
        if pd.isna(game_date):
            continue
        opponent = split.get("opponent", {}) or {}
        opponent_label = opponent.get("abbreviation") or opponent.get("teamName") or opponent.get("name", "")
        raw_is_home = split.get("isHome", False)
        is_home = raw_is_home if isinstance(raw_is_home, bool) else str(raw_is_home).lower() == "true"
        prefix = "" if is_home else "@"
        hits = _int_stat(stat, "hits")
        runs = _int_stat(stat, "runs")
        rbi = _int_stat(stat, "rbi")
        rows.append(
            {
                "game_date": game_date,
                "opponent": f"{prefix}{opponent_label}" if opponent_label else "",
                "hits": hits,
                "runs": runs,
                "rbi": rbi,
                "hrrrbi": hits + runs + rbi,
                "total_bases": _int_stat(stat, "totalBases"),
                "home_runs": _int_stat(stat, "homeRuns"),
                "walks": _int_stat(stat, "baseOnBalls"),
                "strikeouts": _int_stat(stat, "strikeOuts"),
            }
        )

    if not rows:
        return pd.DataFrame()

    game_log = pd.DataFrame(rows).sort_values("game_date").reset_index(drop=True)
    game_log["label"] = game_log.apply(
        lambda row: f"{row['game_date'].strftime('%m/%d')} {row['opponent']}".strip(),
        axis=1,
    )
    return game_log


def display_batter_metric_strike_zone_fixed(batter_id, pitch_type, pitcher_throws="All", metric="Pitch %"):
    season_year = date.today().year
    start_date = f"{season_year}-03-01"
    end_date = date.today().isoformat()

    try:
        raw_df = strike_zone.load_batter_pitch_location_data(batter_id, start_date, end_date)
        filtered_df = strike_zone.filter_by_pitch_type(raw_df, pitch_type)
        filtered_df = strike_zone.filter_by_pitcher_throws(filtered_df, pitcher_throws)
    except Exception as exc:
        logger.error("Strike zone processing failed for batter_id=%s: %s", batter_id, exc)
        st.info("Strike zone data is unavailable for this batter right now.")
        return

    if filtered_df.empty:
        st.info("Strike zone data is unavailable for this batter right now.")
        return

    metric = metric if metric in {"Pitch %", "Takes", "Batted Balls", "K%", "Home Runs"} else "Pitch %"
    zone_df = strike_zone._build_metric_zone_dataframe(filtered_df, metric)
    if zone_df.empty:
        st.info("Strike zone data is unavailable for this batter right now.")
        return

    if metric == "Pitch %":
        outer_df = filtered_df
        outer_total = None
    elif metric == "K%":
        working_df = filtered_df.copy()
        working_df["_pa_key"] = strike_zone._plate_appearance_key(working_df)
        k_pa_keys = set(working_df.loc[working_df["events"].astype(str).str.lower().eq("strikeout"), "_pa_key"].astype(str))
        zone_to_quad = {11: "tl", 12: "tr", 13: "bl", 14: "br"}
        zone_pa_sets = {key: set() for key in zone_to_quad.values()}
        zone_k_pa_sets = {key: set() for key in zone_to_quad.values()}
        for zone_id, pa_key in zip(working_df["zone"].apply(strike_zone._normalize_zone_value), working_df["_pa_key"].astype(str)):
            key = zone_to_quad.get(zone_id)
            if key is not None:
                zone_pa_sets[key].add(pa_key)
                if pa_key in k_pa_keys:
                    zone_k_pa_sets[key].add(pa_key)
        outer_stats = {
            key: {
                "pitch_count": len(zone_k_pa_sets[key]),
                "pitch_pct": (len(zone_k_pa_sets[key]) / len(zone_pa_sets[key]) * 100.0) if zone_pa_sets[key] else 0.0,
            }
            for key in ("tl", "tr", "bl", "br")
        }
    else:
        metric_mask = strike_zone._batter_metric_mask(filtered_df, metric)
        outer_df = filtered_df[metric_mask].copy() if not metric_mask.empty else filtered_df.iloc[0:0].copy()
        outer_total = None

    if metric != "K%":
        # Savant's 13-zone layout maps outer quadrants directly: 11=upper-left, 12=upper-right, 13=lower-left, 14=lower-right.
        outer_df = outer_df[outer_df["zone"].apply(strike_zone._normalize_zone_value).isin({11, 12, 13, 14})]
        outer_stats = strike_zone._aggregate_outer_quadrants(outer_df, total_pitches=outer_total)
    html = strike_zone._build_batter_metric_strike_zone_html(zone_df, outer_stats)
    st.markdown(html, unsafe_allow_html=True)


strike_zone.display_batter_metric_strike_zone = display_batter_metric_strike_zone_fixed


def normalize_hand_code(code):
    if code in {"L", "R"}:
        return code
    if code in {"S", "B"}:
        return "S"
    return ""


def format_pitcher_hand(code):
    if code == "L":
        return "LHP"
    if code == "R":
        return "RHP"
    return ""


def display_status(status):
    normalized = (status or "").strip().upper()
    if normalized in {"SCHEDULED", "PRE-GAME", "PRE GAME"}:
        return "SCHEDULED"
    if normalized == "WARMUP":
        return "WARM UPS"
    if normalized == "IN PROGRESS":
        return "IN PROGRESS"
    if normalized in {"FINAL", "GAME OVER"}:
        return "FINAL"
    return normalized


def status_color(status):
    display_text = display_status(status)
    if display_text == "SCHEDULED":
        return "#2563eb"
    if display_text == "WARM UPS":
        return "#fbbf24"
    if display_text == "IN PROGRESS":
        return "#f97316"
    if display_text == "FINAL":
        return "#dc2626"
    return "#111"


def _query_param_value(name, default=""):
    try:
        value = st.query_params.get(name, default)
    except Exception:
        return default
    if isinstance(value, list):
        return value[0] if value else default
    if value in {None, ""}:
        return default
    return value


def _build_batter_detail_href(
    batter_id,
    batter_name="",
    batter_hand="",
    team="",
    opponent="",
    return_pitcher_id="",
    return_game_pk="",
    return_pitcher_side="",
    return_pitcher_name="",
    return_pitcher_hand="",
):
    params = [("view", "batter_detail"), ("batter_id", str(batter_id))]
    if batter_name:
        params.append(("batter_name", str(batter_name)))
    if batter_hand:
        params.append(("batter_hand", str(batter_hand)))
    if team:
        params.append(("team", str(team)))
    if opponent:
        params.append(("opponent", str(opponent)))
    if return_pitcher_id:
        params.append(("return_pitcher_id", str(return_pitcher_id)))
    if return_game_pk:
        params.append(("return_game_pk", str(return_game_pk)))
    if return_pitcher_side:
        params.append(("return_pitcher_side", str(return_pitcher_side)))
    if return_pitcher_name:
        params.append(("return_pitcher_name", str(return_pitcher_name)))
    if return_pitcher_hand:
        params.append(("return_pitcher_hand", str(return_pitcher_hand)))
    return "?" + "&".join(f"{key}={quote_plus(value)}" for key, value in params)


@st.cache_data(ttl=1800)
def load_batter_run_value_pitch_type_table(batter_id):
    if not batter_id:
        return pd.DataFrame()

    season_year = 2026
    start_date = f"{season_year}-03-01"
    end_date = date.today().isoformat()

    url = "https://baseballsavant.mlb.com/statcast_search/csv"
    params = {
        "all": "true",
        "hfPT": "",
        "hfAB": "",
        "hfBBT": "",
        "hfPR": "",
        "hfZ": "",
        "stadium": "",
        "hfBBL": "",
        "hfNewZones": "",
        "hfGT": "R|PO|S|",
        "hfSea": "",
        "hfSit": "",
        "player_type": "batter",
        "hfOuts": "",
        "opponent": "",
        "pitcher_throws": "",
        "batter_stands": "",
        "hfSA": "",
        "game_date_gt": start_date,
        "game_date_lt": end_date,
        "batters_lookup[]": str(batter_id),
        "team": "",
        "position": "",
        "hfRO": "",
        "home_road": "",
        "hfFlag": "",
        "metric_1": "",
        "hfInn": "",
        "min_pitches": "0",
        "min_results": "0",
        "group_by": "name",
        "sort_col": "pitches",
        "player_event_sort": "h_launch_speed",
        "sort_order": "desc",
        "min_abs": "0",
        "type": "details",
    }

    try:
        response = requests.get(url, params=params, timeout=45)
    except Exception as exc:
        logger.error("Batter run value fetch failed for batter_id=%s: %s", batter_id, exc)
        return pd.DataFrame()

    if response.status_code != 200:
        logger.warning("Batter run value request failed for batter_id=%s status=%s", batter_id, response.status_code)
        return pd.DataFrame()

    try:
        raw_df = pd.read_csv(io.StringIO(response.text), low_memory=False)
    except Exception as exc:
        logger.error("Failed parsing batter run value CSV for batter_id=%s: %s", batter_id, exc)
        return pd.DataFrame()

    if raw_df.empty:
        return pd.DataFrame()

    if "game_year" in raw_df.columns:
        working_df = raw_df[pd.to_numeric(raw_df["game_year"], errors="coerce") == season_year].copy()
    else:
        working_df = raw_df.copy()

    if working_df.empty:
        return pd.DataFrame()

    pitch_col = "pitch_name" if "pitch_name" in working_df.columns else "pitch_type"
    if pitch_col not in working_df.columns:
        return pd.DataFrame()

    working_df[pitch_col] = working_df[pitch_col].astype(str).str.strip()
    working_df = working_df[(working_df[pitch_col] != "") & (working_df[pitch_col].str.lower() != "nan")].copy()
    if working_df.empty:
        return pd.DataFrame()

    total_pitches = len(working_df)

    if {"game_pk", "at_bat_number"}.issubset(working_df.columns):
        working_df["_pa_key"] = (
            working_df["game_pk"].astype(str) + "_" + pd.to_numeric(working_df["at_bat_number"], errors="coerce").fillna(-1).astype(int).astype(str)
        )
    else:
        working_df["_pa_key"] = working_df.index.astype(str)

    events = working_df["events"].astype(str).str.lower() if "events" in working_df.columns else pd.Series("", index=working_df.index)
    descriptions = (
        working_df["description"].astype(str).str.lower() if "description" in working_df.columns else pd.Series("", index=working_df.index)
    )

    working_df["_event_norm"] = events
    working_df["_desc_norm"] = descriptions

    ab_events = {
        "single", "double", "triple", "home_run", "strikeout", "field_out", "grounded_into_double_play",
        "force_out", "fielders_choice_out", "double_play", "triple_play", "field_error", "other_out",
        "sac_fly_double_play", "fielders_choice", "strikeout_double_play", "sac_bunt_double_play",
    }
    hit_values = {"single": 1, "double": 2, "triple": 3, "home_run": 4}
    whiff_descriptions = {"swinging_strike", "swinging_strike_blocked", "missed_bunt"}
    swing_descriptions = {
        "swinging_strike", "swinging_strike_blocked", "foul", "foul_tip", "hit_into_play", "hit_into_play_no_out",
        "hit_into_play_score", "foul_bunt", "missed_bunt", "swinging_pitchout",
    }

    def _safe_pct(num, den):
        return (float(num) / float(den) * 100.0) if den else None

    rows = []
    for pitch_name, grp in working_df.groupby(pitch_col):
        event_series = grp["_event_norm"]
        desc_series = grp["_desc_norm"]
        pitches = int(len(grp))
        pa = int(grp["_pa_key"].nunique())

        ab = int(event_series.isin(ab_events).sum())
        hits = int(event_series.isin(hit_values.keys()).sum())
        total_bases = int(event_series.map(hit_values).fillna(0).sum())

        ba = (hits / ab) if ab else None
        slg = (total_bases / ab) if ab else None

        woba_values = pd.to_numeric(grp.get("woba_value"), errors="coerce") if "woba_value" in grp.columns else pd.Series(dtype=float)
        woba_denom = pd.to_numeric(grp.get("woba_denom"), errors="coerce") if "woba_denom" in grp.columns else pd.Series(dtype=float)
        denom_sum = float(woba_denom.fillna(0).sum()) if not woba_denom.empty else 0.0
        woba = (float(woba_values.fillna(0).sum()) / denom_sum) if denom_sum > 0 else None

        swings = int(desc_series.isin(swing_descriptions).sum())
        whiffs = int(desc_series.isin(whiff_descriptions).sum())
        whiff_pct = _safe_pct(whiffs, swings)

        strikeouts = int((event_series == "strikeout").sum())
        k_pct = _safe_pct(strikeouts, pa)

        strikes_col = pd.to_numeric(grp.get("strikes"), errors="coerce") if "strikes" in grp.columns else pd.Series(dtype=float)
        two_strike_pitches = int((strikes_col == 2).sum()) if not strikes_col.empty else 0
        putaway_pct = _safe_pct(strikeouts, two_strike_pitches)

        xba_series = pd.to_numeric(grp.get("estimated_ba_using_speedangle"), errors="coerce") if "estimated_ba_using_speedangle" in grp.columns else pd.Series(dtype=float)
        xslg_series = pd.to_numeric(grp.get("estimated_slg_using_speedangle"), errors="coerce") if "estimated_slg_using_speedangle" in grp.columns else pd.Series(dtype=float)
        xwoba_series = pd.to_numeric(grp.get("estimated_woba_using_speedangle"), errors="coerce") if "estimated_woba_using_speedangle" in grp.columns else pd.Series(dtype=float)

        xba = float(xba_series.dropna().mean()) if not xba_series.dropna().empty else None
        xslg = float(xslg_series.dropna().mean()) if not xslg_series.dropna().empty else None
        xwoba = float(xwoba_series.dropna().mean()) if not xwoba_series.dropna().empty else None

        launch_speed = pd.to_numeric(grp.get("launch_speed"), errors="coerce") if "launch_speed" in grp.columns else pd.Series(dtype=float)
        bbe = int(launch_speed.notna().sum()) if not launch_speed.empty else 0
        hard_hit = int((launch_speed >= 95).sum()) if not launch_speed.empty else 0
        hard_hit_pct = _safe_pct(hard_hit, bbe)

        rows.append(
            {
                "Year": season_year,
                "Pitch Type": str(pitch_name),
                "Pitches": pitches,
                "%": _safe_pct(pitches, total_pitches),
                "PA": pa,
                "BA": ba,
                "SLG": slg,
                "wOBA": woba,
                "Whiff%": whiff_pct,
                "K%": k_pct,
                "PutAway%": putaway_pct,
                "xBA": xba,
                "xSLG": xslg,
                "xwOBA": xwoba,
                "Hard Hit%": hard_hit_pct,
            }
        )

    if not rows:
        return pd.DataFrame()

    table_df = pd.DataFrame(rows)
    table_df = table_df.sort_values(by="Pitches", ascending=False).reset_index(drop=True)

    for col in ["BA", "SLG", "wOBA", "xBA", "xSLG", "xwOBA"]:
        table_df[col] = table_df[col].round(3)
    for col in ["%", "Whiff%", "K%", "PutAway%", "Hard Hit%"]:
        table_df[col] = table_df[col].round(1)

    return table_df[
        [
            "Year", "Pitch Type", "Pitches", "%", "PA", "BA", "SLG", "wOBA",
            "Whiff%", "K%", "PutAway%", "xBA", "xSLG", "xwOBA", "Hard Hit%",
        ]
    ]


requested_view = _query_param_value("view")
requested_batter_id = _query_param_value("batter_id")
if requested_view == "batter_detail" and requested_batter_id:
    st.session_state["selected_batter"] = {
        "name": _query_param_value("batter_name", "Batter Detail"),
        "id": requested_batter_id,
        "hand": _query_param_value("batter_hand", ""),
        "team": _query_param_value("team", ""),
        "opponent": _query_param_value("opponent", ""),
        "return_pitcher_id": _query_param_value("return_pitcher_id", ""),
        "return_game_pk": _query_param_value("return_game_pk", ""),
        "return_pitcher_side": _query_param_value("return_pitcher_side", ""),
        "return_pitcher_name": _query_param_value("return_pitcher_name", ""),
        "return_pitcher_hand": _query_param_value("return_pitcher_hand", ""),
    }

requested_pitcher_id = _query_param_value("pitcher_id")
requested_game_pk = _query_param_value("game_pk")
if requested_view == "pitcher_detail" and requested_pitcher_id and requested_game_pk:
    st.session_state["selected_pitcher"] = {
        "name": _query_param_value("pitcher_name", ""),
        "id": requested_pitcher_id,
        "hand": _query_param_value("pitcher_hand", ""),
        "side": _query_param_value("pitcher_side", ""),
    }
    try:
        st.session_state["selected_game"] = int(str(requested_game_pk))
    except Exception:
        st.session_state["selected_game"] = requested_game_pk


@st.cache_data(ttl=43200)
def get_players_info(player_ids):
    global PLAYER_API_CALLS
    sanitized_ids = sorted({int(pid) for pid in player_ids if pid})
    if not sanitized_ids:
        return {}

    PLAYER_API_CALLS += 1
    logger.debug("Fetching handedness for player IDs: %s", sanitized_ids)
    url = "https://statsapi.mlb.com/api/v1/people"
    data = requests.get(url, params={"personIds": ",".join(str(pid) for pid in sanitized_ids)}).json()
    people = data.get("people", [])
    result = {}
    for person in people:
        pid = person.get("id")
        result[pid] = {
            "batSide": person.get("batSide", {}).get("code", ""),
            "pitchHand": person.get("pitchHand", {}).get("code", "")
        }
    return result


@st.cache_data(ttl=300)
def load_schedule(game_date):
    url = "https://statsapi.mlb.com/api/v1/schedule"
    params = {
        "sportId": 1,
        "date": game_date.strftime("%Y-%m-%d"),
        "hydrate": "probablePitcher,team,venue"
    }

    data = requests.get(url, params=params).json()
    games = []

    pitcher_ids = []
    for d in data.get("dates", []):
        for g in d.get("games", []):
            away = g["teams"]["away"]
            home = g["teams"]["home"]

            away_pitcher_id = away.get("probablePitcher", {}).get("id", "")
            home_pitcher_id = home.get("probablePitcher", {}).get("id", "")
            if away_pitcher_id:
                pitcher_ids.append(away_pitcher_id)
            if home_pitcher_id:
                pitcher_ids.append(home_pitcher_id)

            games.append({
                "game_pk": g.get("gamePk"),
                "away_team": away["team"]["name"],
                "home_team": home["team"]["name"],
                "away_abbrev": away["team"].get("abbreviation", ""),
                "home_abbrev": home["team"].get("abbreviation", ""),
                "away_team_id": away["team"].get("id", ""),
                "home_team_id": home["team"].get("id", ""),
                "away_pitcher": away.get("probablePitcher", {}).get("fullName", "TBD"),
                "home_pitcher": home.get("probablePitcher", {}).get("fullName", "TBD"),
                "away_pitcher_id": away_pitcher_id,
                "home_pitcher_id": home_pitcher_id,
                "venue": g.get("venue", {}).get("name", ""),
                "status": g.get("status", {}).get("detailedState", ""),
                "game_time_et": eastern_time(g.get("gameDate", "")),
                "game_dt": datetime.fromisoformat(g.get("gameDate", "").replace("Z", "+00:00")) if g.get("gameDate") else None
            })

    pitcher_info = get_players_info(tuple(pitcher_ids)) if pitcher_ids else {}
    for game in games:
        game["away_pitcher_hand"] = format_pitcher_hand(
            normalize_hand_code(pitcher_info.get(game["away_pitcher_id"], {}).get("pitchHand", ""))
        )
        game["home_pitcher_hand"] = format_pitcher_hand(
            normalize_hand_code(pitcher_info.get(game["home_pitcher_id"], {}).get("pitchHand", ""))
        )

    # Build DataFrame and sort so that FINAL games are placed at the end.
    df = pd.DataFrame(games)
    # Use the display_status helper to normalize statuses for ordering
    df["display_status"] = df["status"].apply(display_status)
    # Mark finals so they can be pushed to the bottom
    df["is_final"] = df["display_status"].apply(lambda s: s == "FINAL")

    # Map display statuses to explicit ranks for ordering within non-final games
    status_rank = {
        "WARM UPS": 1,
        "IN PROGRESS": 2,
        "SCHEDULED": 3,
        "FINAL": 4,
    }
    df["status_rank"] = df["display_status"].map(status_rank).fillna(99).astype(int)

    # Sort: non-final games first, ordered by status rank then game datetime;
    # final games (is_final=True) will be placed after non-final games, and
    # within the final group they remain sorted by datetime as well.
    df = df.sort_values(by=["is_final", "status_rank", "game_dt"], ascending=[True, True, True])

    # Keep the original column order but return sorted DataFrame
    return df.reset_index(drop=True)

@st.cache_data(ttl=1800)
def load_active_roster(team_id):
    if not team_id:
        return []
    url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/roster"
    data = requests.get(url, params={"rosterType": "active"}, timeout=15).json()
    return data.get("roster", [])


def normalize_name(name):
    return " ".join(str(name).lower().replace(".", "").split())


def build_roster_name_id_map(team_id):
    roster = load_active_roster(team_id)
    out = {}
    for row in roster:
        person = row.get("person", {})
        name = normalize_name(person.get("fullName", ""))
        pid = person.get("id")
        if name and pid:
            out[name] = pid
    return out


@st.cache_data(ttl=1800)
def load_fangraphs_projected_lineups():
    url = "https://www.fangraphs.com/api/roster-resource/lineup-tracker/data?season=2026"
    fangraphs_team_names = {
        1: "Los Angeles Angels",
        2: "Baltimore Orioles",
        3: "Boston Red Sox",
        4: "Chicago White Sox",
        5: "Cleveland Guardians",
        6: "Detroit Tigers",
        7: "Kansas City Royals",
        8: "Minnesota Twins",
        9: "New York Yankees",
        10: "Athletics",
        11: "Seattle Mariners",
        12: "Tampa Bay Rays",
        13: "Texas Rangers",
        14: "Toronto Blue Jays",
        15: "Arizona Diamondbacks",
        16: "Atlanta Braves",
        17: "Chicago Cubs",
        18: "Cincinnati Reds",
        19: "Colorado Rockies",
        20: "Miami Marlins",
        21: "Houston Astros",
        22: "Los Angeles Dodgers",
        23: "Milwaukee Brewers",
        24: "Washington Nationals",
        25: "New York Mets",
        26: "Philadelphia Phillies",
        27: "Pittsburgh Pirates",
        28: "St. Louis Cardinals",
        29: "San Diego Padres",
        30: "San Francisco Giants",
    }

    try:
        raw_lineups = requests.get(url, timeout=20).json()
    except Exception as exc:
        logger.warning("FanGraphs lineup fallback request failed: %s", exc)
        return {}

    if not isinstance(raw_lineups, list) or not raw_lineups:
        return {}

    lineups = {}
    for team_record in raw_lineups:
        if not isinstance(team_record, dict):
            continue

        team_name = fangraphs_team_names.get(team_record.get("teamId"))
        if not team_name:
            continue

        lineup_data = team_record.get("lineupData", {})
        lineup_tracker = lineup_data.get("lineupTracker", []) if isinstance(lineup_data, dict) else []
        if not isinstance(lineup_tracker, list):
            continue

        projected_players = []
        for lineup in lineup_tracker:
            data_players = lineup.get("dataPlayers", []) if isinstance(lineup, dict) else []
            projected_players = [
                player
                for player in data_players
                if isinstance(player, dict) and player.get("BO") and player.get("playerName")
            ]
            if projected_players:
                break

        if not projected_players:
            continue

        normalized_team = normalize_name(team_name)
        for player in sorted(projected_players, key=lambda row: row.get("BO") or 999):
            player_name = str(player.get("playerName", "")).strip()
            if not player_name:
                continue
            lineups.setdefault(normalized_team, []).append({"name": player_name, "position": ""})

    return lineups


def build_fangraphs_lineup_fallback(team_id, team_name):
    if not team_id or not team_name:
        return []

    fangraphs_lineups = load_fangraphs_projected_lineups()
    projected_players = fangraphs_lineups.get(normalize_name(team_name), [])
    if not projected_players:
        return []

    roster_map = build_roster_name_id_map(team_id)
    matched_ids = [
        roster_map.get(normalize_name(player.get("name", "")))
        for player in projected_players
        if roster_map.get(normalize_name(player.get("name", "")))
    ]
    player_info = get_players_info(tuple(matched_ids)) if matched_ids else {}

    lineup = []
    for i, player in enumerate(projected_players, start=1):
        player_name = player.get("name", "")
        player_id = roster_map.get(normalize_name(player_name))
        info = player_info.get(player_id, {}) if player_id else {}
        lineup.append(
            {
                "number": i,
                "player_id": player_id,
                "name": player_name,
                "handedness": normalize_hand_code(info.get("batSide", "")) if player_id else "",
                "position": player.get("position", ""),
                "is_projected": True,
            }
        )

    return lineup



@st.cache_data(ttl=300)
def load_lineups(game_pk):
    url = f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
    data = requests.get(url).json()

    boxscore = data.get("liveData", {}).get("boxscore", {}).get("teams", {})
    game_data_players = data.get("gameData", {}).get("players", {})

    def extract_player_codes(player_id):
        player_key = f"ID{player_id}"
        player = game_data_players.get(player_key, {})

        bat_side = normalize_hand_code(player.get("batSide", {}).get("code", ""))
        pitch_hand = normalize_hand_code(player.get("pitchHand", {}).get("code", ""))
        return bat_side, pitch_hand

    def team_lineup(side):
        team = boxscore.get(side, {})
        players = team.get("players", {})
        batting_order = team.get("battingOrder", [])
        team_id = team.get("team", {}).get("id")
        team_name = team.get("team", {}).get("name", "")

        if not batting_order:
            logger.warning("FanGraphs fallback triggered: team_id=%s team_name=%s", team_id, team_name)
            fallback_lineup = build_fangraphs_lineup_fallback(team_id, team_name)
            if fallback_lineup:
                return fallback_lineup

        lineup = []
        missing_ids = []
        player_codes = {}

        for player_id in batting_order:
            bat_side, pitch_hand = extract_player_codes(player_id)
            if bat_side or pitch_hand:
                player_codes[player_id] = (bat_side, pitch_hand)
            else:
                missing_ids.append(player_id)

        if missing_ids:
            fallback_info = get_players_info(tuple(missing_ids))
            for player_id in missing_ids:
                player_info = fallback_info.get(player_id, {})
                player_codes[player_id] = (
                    normalize_hand_code(player_info.get("batSide", "")),
                    normalize_hand_code(player_info.get("pitchHand", ""))
                )

        for i, player_id in enumerate(batting_order, start=1):
            key = f"ID{player_id}"
            p = players.get(key, {})
            person = p.get("person", {})
            handedness, _ = player_codes.get(player_id, ("", ""))

            lineup.append({
                "number": i,
                "player_id": player_id,
                "name": person.get("fullName", ""),
                "handedness": handedness,
                "position": p.get("position", {}).get("abbreviation", "")
            })

        return lineup

    return team_lineup("away"), team_lineup("home")


def get_game_lineups(game_pk, game=None):
    if not game_pk:
        return {}

    game_key = str(game_pk)
    lineups_by_game = st.session_state.setdefault("lineups_by_game", {})
    if game_key not in lineups_by_game:
        away_lineup, home_lineup = load_lineups(game_pk)
        lineups_by_game[game_key] = {
            "away": away_lineup,
            "home": home_lineup,
            "away_team": game.get("away_team", "") if game is not None else "",
            "home_team": game.get("home_team", "") if game is not None else "",
        }
    return lineups_by_game.get(game_key, {})


def lineup_status_html(lineup):
    if not lineup:
        return ""
    if any(player.get("is_projected") for player in lineup):
        return "<div style='margin:0 0 8px 0; padding:6px 8px; border:1px solid #dc2626; border-radius:6px; background:#fef2f2; color:#b91c1c; font-weight:800;'>⚠ Projected lineup — not confirmed</div>"
    return "<div style='margin:0 0 8px 0; padding:6px 8px; border:1px solid #16a34a; border-radius:6px; background:#f0fdf4; color:#15803d; font-weight:800;'>🟢 Confirmed MLB Lineup</div>"


def render_lineup_table(lineup, current_batter_id="", current_batter_name="", link_context=None):
    if not lineup:
        return "<div style='font-size:13px; color:#92400e; font-weight:700;'>Lineup not available.</div>"

    current_name_key = normalize_name(current_batter_name)
    rows = []
    for player in lineup:
        player_name = player.get("name", "")
        player_id = player.get("player_id")
        is_current = (
            bool(current_batter_id) and str(player_id or "") == str(current_batter_id)
        ) or (current_name_key and normalize_name(player_name) == current_name_key)
        row_style = "background:#dbeafe; border-left:4px solid #2563eb; font-weight:800;" if is_current else "border-left:4px solid transparent;"

        batter_cell_html = html.escape(str(player_name))
        if link_context and player_id:
            batter_href = _build_batter_detail_href(
                player_id,
                batter_name=player_name,
                batter_hand=player.get("handedness", ""),
                team=link_context.get("team", ""),
                opponent=link_context.get("opponent", ""),
                return_pitcher_id=link_context.get("return_pitcher_id", ""),
                return_game_pk=link_context.get("return_game_pk", ""),
                return_pitcher_side=link_context.get("return_pitcher_side", ""),
                return_pitcher_name=link_context.get("return_pitcher_name", ""),
                return_pitcher_hand=link_context.get("return_pitcher_hand", ""),
            )
            batter_cell_html = (
                f"<a class='nav-name-link' href='{html.escape(batter_href, quote=True)}' target='_self'>"
                f"{html.escape(str(player_name))}</a>"
            )

        rows.append(
            "<div style='display:grid; grid-template-columns:44px 1fr 64px 64px; align-items:center; border-top:1px solid #e5e7eb; "
            f"{row_style}'>"
            f"<div style='padding:6px 10px;'>{player.get('number', '')}</div>"
            f"<div style='padding:6px 10px;'>{batter_cell_html}</div>"
            f"<div style='padding:6px 10px;'>{html.escape(str(player.get('handedness', '')))}</div>"
            f"<div style='padding:6px 10px;'>{html.escape(str(player.get('position', '')))}</div>"
            "</div>"
        )

    return (
        f"{lineup_status_html(lineup)}"
        "<div style='display:grid; grid-template-columns:44px 1fr 64px 64px; align-items:end; font-size:12px; color:#6b7280; font-weight:700;'>"
        "<div style='padding:0 10px 6px 10px;'>#</div>"
        "<div style='padding:0 10px 6px 10px;'>Batter</div>"
        "<div style='padding:0 10px 6px 10px;'>Hand</div>"
        "<div style='padding:0 10px 6px 10px;'>Pos</div>"
        "</div>"
        f"{''.join(rows)}"
    )


if st.session_state.get("selected_batter"):
    sb = st.session_state.get("selected_batter", {})
    has_return_pitcher = bool(sb.get("return_pitcher_id") and sb.get("return_game_pk"))
    back_label = "← Back to Pitcher" if has_return_pitcher else "← Back to Slate"
    if st.button(back_label):
        st.session_state.pop("selected_batter", None)
        if has_return_pitcher:
            st.query_params.clear()
            st.query_params["view"] = "pitcher_detail"
            st.query_params["pitcher_id"] = str(sb.get("return_pitcher_id", ""))
            st.query_params["game_pk"] = str(sb.get("return_game_pk", ""))
            if sb.get("return_pitcher_side"):
                st.query_params["pitcher_side"] = str(sb.get("return_pitcher_side"))
            if sb.get("return_pitcher_name"):
                st.query_params["pitcher_name"] = str(sb.get("return_pitcher_name"))
            if sb.get("return_pitcher_hand"):
                st.query_params["pitcher_hand"] = str(sb.get("return_pitcher_hand"))
        else:
            try:
                st.query_params.clear()
            except Exception:
                pass
        st.rerun()

    batter_name = sb.get("name") or "Batter Detail"
    batter_hand = sb.get("hand", "")
    st.markdown(f"## {batter_name}{f' ({batter_hand})' if batter_hand else ''}")

    batter_id = sb.get("id", "")
    game_pk = sb.get("return_game_pk") or st.session_state.get("selected_game", "")
    lineup_context = get_game_lineups(game_pk) if game_pk else {}
    batter_team_key = normalize_name(sb.get("team", ""))
    lineup_side = ""
    if batter_team_key and normalize_name(lineup_context.get("away_team", "")) == batter_team_key:
        lineup_side = "away"
    elif batter_team_key and normalize_name(lineup_context.get("home_team", "")) == batter_team_key:
        lineup_side = "home"
    elif sb.get("return_pitcher_side") == "away":
        lineup_side = "home"
    elif sb.get("return_pitcher_side") == "home":
        lineup_side = "away"
    else:
        for candidate_side in ("away", "home"):
            for player in lineup_context.get(candidate_side, []):
                if str(player.get("player_id") or "") == str(batter_id or "") or normalize_name(player.get("name", "")) == normalize_name(batter_name):
                    lineup_side = candidate_side
                    break
            if lineup_side:
                break
    team_lineup = lineup_context.get(lineup_side, []) if lineup_side else []

    with st.container(border=True):
        if st.session_state.get("selected_prop") not in GAME_LOG_PROPS:
            st.session_state["selected_prop"] = "Hits"
        selected_prop = st.segmented_control(
            "Prop",
            GAME_LOG_PROPS,
            key="selected_prop",
            label_visibility="collapsed",
        )
        if selected_prop not in GAME_LOG_PROPS:
            selected_prop = "Hits"

        prop_column = GAME_LOG_PROP_COLUMNS[selected_prop]
        prop_slug = prop_column.replace("_", "-")
        line_key = f"batter_{prop_column}_line_{batter_id}"
        if line_key not in st.session_state:
            st.session_state[line_key] = 0.5
        st.session_state["prizepicks_projections"] = load_prizepicks_mlb_projections()
        projection_lines = get_prop_projection_lines(batter_id, selected_prop, batter_name)
        selected_line_value = float(st.session_state[line_key])
        selected_projection_line = None
        for projection_line in projection_lines:
            projection_line_value = _projection_line_value(projection_line)
            try:
                if float(projection_line_value) == selected_line_value:
                    selected_projection_line = projection_line
                    break
            except (TypeError, ValueError):
                continue
        st.markdown("<div class='prop-control-spacer'></div>", unsafe_allow_html=True)
        line_cols = st.columns([0.34, 0.62, 0.34, 5.2])
        with line_cols[0]:
            if st.button("-", key=f"batter_{prop_slug}_line_minus_{batter_id}"):
                st.session_state[line_key] = max(0.5, float(st.session_state[line_key]) - 1.0)
                st.rerun()
        with line_cols[1]:
            st.markdown(
                render_prizepicks_line_detail(st.session_state[line_key], selected_projection_line),
                unsafe_allow_html=True,
            )
        with line_cols[2]:
            if st.button("+", key=f"batter_{prop_slug}_line_plus_{batter_id}"):
                st.session_state[line_key] = float(st.session_state[line_key]) + 1.0
                st.rerun()
        if projection_lines:
            with st.expander("Alt lines", expanded=False):
                for idx, projection_line in enumerate(projection_lines):
                    projection_line_value = _projection_line_value(projection_line)
                    try:
                        display_line_value = f"{float(projection_line_value):.1f}"
                    except (TypeError, ValueError):
                        display_line_value = str(projection_line_value)
                    row_cols = st.columns([0.65, 4.8])
                    with row_cols[0]:
                        if st.button(display_line_value, key=f"batter_{prop_slug}_alt_line_{batter_id}_{idx}"):
                            try:
                                st.session_state[line_key] = float(projection_line_value)
                            except (TypeError, ValueError):
                                pass
                            st.rerun()
                    with row_cols[1]:
                        st.markdown(
                            f"<div class='prop-alt-row'>{_projection_meta_html(projection_line)}</div>",
                            unsafe_allow_html=True,
                        )
        st.markdown("<div class='prop-control-spacer'></div>", unsafe_allow_html=True)
        game_log_range = st.segmented_control(
            "Recent Range",
            ["L5", "L10", "L15", "2026"],
            default="L10",
            key=f"batter_game_log_range_{batter_id}",
            label_visibility="collapsed",
        )
        selected_prop_line = float(st.session_state[line_key])
        game_log_df = load_batter_prop_game_log(batter_id)
        if game_log_df.empty:
            st.info("Game log data is unavailable for this batter right now.")
        else:
            if game_log_range in {"L5", "L10", "L15"}:
                display_log_df = game_log_df.tail(int(game_log_range[1:])).copy()
            else:
                display_log_df = game_log_df.copy()
            display_log_df["prop_value"] = pd.to_numeric(display_log_df[prop_column], errors="coerce").fillna(0)
            display_log_df["result_color"] = display_log_df["prop_value"].apply(
                lambda value: "#16a34a" if value >= selected_prop_line else "#dc2626"
            )
            display_log_df["bar_value"] = display_log_df["prop_value"].apply(lambda value: 0.12 if value == 0 else value)
            display_log_df["label_y"] = display_log_df["bar_value"].apply(lambda value: value + 0.22)
            display_log_df["chart_label"] = display_log_df.apply(
                lambda row: f"{row['game_date'].month}/{row['game_date'].day}\n{row['opponent'] if row['opponent'] else ''}",
                axis=1,
            )
            max_value = max(float(display_log_df["prop_value"].max()), selected_prop_line, 1.0)
            if game_log_range == "L5":
                bar_size = 128
                x_step = 130
            elif game_log_range == "L10":
                bar_size = 74
                x_step = 76
            elif game_log_range == "L15":
                bar_size = 52
                x_step = 54
            else:
                bar_size = 11
                x_step = 12

            bars = (
                alt.Chart(display_log_df)
                .mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5, size=bar_size)
                .encode(
                    x=alt.X(
                        "chart_label:N",
                        sort=None,
                        title=None,
                        axis=alt.Axis(labelAngle=0, labelFontSize=11, labelColor="#475569", labelPadding=8, ticks=False, domain=False),
                        scale=alt.Scale(paddingInner=0.04, paddingOuter=0.03),
                    ),
                    y=alt.Y(
                        "bar_value:Q",
                        title=None,
                        scale=alt.Scale(domain=[0, max_value + 0.8], nice=False),
                        axis=alt.Axis(grid=True, gridColor="#e2e8f0", gridOpacity=0.7, tickColor="#e2e8f0", domain=False, titleColor="#475569", labelColor="#64748b"),
                    ),
                    color=alt.Color("result_color:N", scale=None, legend=None),
                    tooltip=[
                        alt.Tooltip("game_date:T", title="Date"),
                        alt.Tooltip("opponent:N", title="Opponent"),
                        alt.Tooltip("prop_value:Q", title=selected_prop, format=".0f"),
                    ],
                )
            )
            labels = (
                alt.Chart(display_log_df)
                .mark_text(dy=-8, fontWeight=700, fontSize=12, color="#0f172a")
                .encode(
                    x=alt.X("chart_label:N", sort=None),
                    y=alt.Y("label_y:Q"),
                    text=alt.Text("prop_value:Q", format=".0f"),
                )
            )
            line_df = pd.DataFrame({"line": [selected_prop_line]})
            line = alt.Chart(line_df).mark_rule(strokeDash=[6, 4], color="#334155", opacity=0.8).encode(y="line:Q")
            chart = (bars + labels + line).properties(height=230, width=alt.Step(x_step)).configure_view(stroke=None)
            st.altair_chart(chart, use_container_width=True)

    with st.container(border=True):
        st.markdown(
            "<div class='section-title-strong'>Run Value by Pitch Type</div>",
            unsafe_allow_html=True,
        )
        run_value_df = load_batter_run_value_pitch_type_table(batter_id)
        if run_value_df.empty:
            st.info("Run value by pitch type is unavailable for this batter right now.")
        else:
            st.dataframe(
                style_run_value_table(run_value_df),
                hide_index=True,
                use_container_width=True,
            )

    with st.container(border=True):
        st.markdown(
            "<div class='section-title-strong'>Strike Zone</div>",
            unsafe_allow_html=True,
        )
        batter_strike_zone_cols = st.columns([1.15, 4])
        with batter_strike_zone_cols[0]:
            pitch_type_options = strike_zone.get_batter_pitch_type_options(batter_id)
            # Streamlit selectbox options are plain text, so individual pitch names cannot be colored safely here.
            selected_pitch_type = st.selectbox(
                "Pitch Type",
                pitch_type_options,
                index=0,
                key=f"batter_strike_zone_pitch_type_{batter_id}",
            )
            selected_pitcher_throws = st.selectbox(
                "Pitcher Throws",
                ["All", "RHP", "LHP"],
                index=0,
                key=f"batter_strike_zone_pitcher_throws_{batter_id}",
            )
            selected_metric = st.selectbox(
                "Metric",
                ["Pitch %", "Takes", "Batted Balls", "K%", "Home Runs"],
                index=0,
                key=f"batter_strike_zone_metric_{batter_id}",
            )
            if selected_metric == "K%":
                st.markdown(
                    "<div style='color:#b91c1c; font-size:12.5px; font-weight:600; line-height:1.35; text-align:left; margin:6px 0 0 0; padding:0 0 12px 12px;'>Note: K% includes plate appearances that ended in a strikeout AND plate appearances that did not.</div>",
                    unsafe_allow_html=True,
                )
        with batter_strike_zone_cols[1]:
            strike_zone.display_batter_metric_strike_zone(batter_id, selected_pitch_type, selected_pitcher_throws, selected_metric)

    with st.container(border=True):
        lineup_team = lineup_context.get(f"{lineup_side}_team", sb.get("team", "")) if lineup_side else sb.get("team", "")
        lineup_opponent = lineup_context.get("home_team", "") if lineup_side == "away" else lineup_context.get("away_team", "")
        batter_lineup_link_context = {
            "team": lineup_team,
            "opponent": lineup_opponent or sb.get("opponent", ""),
            "return_pitcher_id": sb.get("return_pitcher_id", ""),
            "return_game_pk": game_pk,
            "return_pitcher_side": sb.get("return_pitcher_side", ""),
            "return_pitcher_name": sb.get("return_pitcher_name", ""),
            "return_pitcher_hand": sb.get("return_pitcher_hand", ""),
        }
        st.markdown(
            "<div class='section-title-strong'>Team Lineup Context</div>"
            f"{render_lineup_table(team_lineup, current_batter_id=batter_id, current_batter_name=batter_name, link_context=batter_lineup_link_context)}",
            unsafe_allow_html=True,
        )

    st.stop()


@st.cache_data(ttl=1800)
def load_pitcher_stats(player_id):
    if not player_id:
        return {}

    # MLB Stats API provides basic season values for pitchers via stats=season
    # If there is no data for the player, return an empty dict.
    stats_url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats"
    params = {
        "stats": "season",
        "season": str(date.today().year),
        "group": "pitching",
    }
    response = requests.get(stats_url, params=params, timeout=15)
    if response.status_code != 200:
        return {}
    payload = response.json()
    splits = payload.get("stats", [])
    if not splits:
        return {}

    raw_splits = splits[0].get("splits", [])
    if not raw_splits:
        return {}

    season_stat = raw_splits[0].get("stat", {})
    return {
        "era": season_stat.get("era"),
        "whip": season_stat.get("whip"),
        "k_percent": season_stat.get("strikeoutsPer9Inn") if season_stat.get("strikeoutsPer9Inn") is not None else season_stat.get("strikeoutWalkRatio"),
        "bb_percent": season_stat.get("walksPer9Inn"),
        "innings_pitched": season_stat.get("inningsPitched"),
        "hr_allowed": season_stat.get("homeRuns"),
    }


@st.cache_data(ttl=1800)
def load_savant_pitch_arsenal_data():
    year = str(date.today().year)
    url = f"https://baseballsavant.mlb.com/leaderboard/pitch-arsenal-stats?type=pitcher&year={year}"
    response = requests.get(url, timeout=20)
    if response.status_code != 200:
        return []

    text = response.text
    marker = "var leaderboardData = "
    idx = text.find(marker)
    if idx == -1:
        return []

    start = text.find("[", idx)
    if start == -1:
        return []

    depth = 1
    end = None
    for i, ch in enumerate(text[start + 1:], start=start + 1):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if end is None:
        return []

    block = text[start:end]
    try:
        return json.loads(block)
    except json.JSONDecodeError:
        return []


def _find_json_objects_for_player_page(text, marker):
    idx = 0
    while True:
        idx = text.find(marker, idx)
        if idx == -1:
            break
        start = text.rfind("{", 0, idx)
        if start == -1:
            idx += len(marker)
            continue

        depth = 0
        in_str = False
        escape = False
        end = None
        for i, ch in enumerate(text[start:], start=start):
            if ch == "\\" and not escape:
                escape = True
                continue
            if ch == '"' and not escape:
                in_str = not in_str
            escape = False
            if in_str:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break

        if end is None:
            break

        obj_text = text[start:end]
        try:
            yield json.loads(obj_text)
        except json.JSONDecodeError:
            pass

        idx = end


@st.cache_data(ttl=1800)
def get_savant_arsenal_for_player(player_id):
    year = str(date.today().year)
    url = f"https://baseballsavant.mlb.com/savant-player/{player_id}"
    response = requests.get(url, timeout=20)
    if response.status_code != 200:
        logger.warning("Pitch Arsenal N/A for player_id=%s season=%s: page request failed status=%s", player_id, year, response.status_code)
        return []

    text = response.text
    marker = '"pitch_type_name"'
    rows = []
    for obj in _find_json_objects_for_player_page(text, marker):
        if str(obj.get("pitcher_id")) != str(player_id):
            continue
        if str(obj.get("year")) != year:
            continue
        if not obj.get("pitch_type_name"):
            continue
        rows.append(obj)

    if not rows:
        logger.warning("Pitch Arsenal N/A for player_id=%s season=%s: no season pitch type rows found in player page", player_id, year)
    return rows


@st.cache_data(ttl=1800)
def load_savant_pitcher_data():
    # Load the Basebal Savant custom pitcher leaderboard page and parse inline JSON.
    url = "https://baseballsavant.mlb.com/leaderboard/custom?year=2026&type=pitcher"
    response = requests.get(url, timeout=20)
    if response.status_code != 200:
        return []

    text = response.text
    marker = "var data = "
    idx = text.find(marker)
    if idx == -1:
        return []

    start = idx + len(marker)
    depth = 0
    end = None
    for i, ch in enumerate(text[start:], start=start):
        if ch == "[":
            depth = 1
            break
    if depth == 0:
        return []

    for i, ch in enumerate(text[i + 1:], start=i + 1):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if end is None:
        return []

    block = text[start:end]
    try:
        return json.loads(block)
    except json.JSONDecodeError:
        return []


@st.cache_data(ttl=1800)
def get_savant_stats_for_player(player_id):
    all_data = load_savant_pitcher_data()
    for item in all_data:
        if item.get("player_id") == player_id:
            return item
    return {}


@st.cache_data(ttl=1800)
def load_regular_season_pitch_mix(player_id):
    if not player_id:
        return {"R": [], "L": [], "all": []}

    season_year = date.today().year
    start_date = f"{season_year}-03-01"
    end_date = date.today().isoformat()

    try:
        from pybaseball import statcast_pitcher

        df = statcast_pitcher(start_date, end_date, int(player_id))
    except Exception as exc:
        logger.error("Statcast pitch mix request failed for %s: %s", player_id, exc)
        return {"R": [], "L": [], "all": []}

    if df is None or df.empty:
        return {"R": [], "L": [], "all": []}

    regular_df = df.copy()
    if "game_type" in regular_df.columns:
        regular_df = regular_df[regular_df["game_type"] == "R"].copy()

    if regular_df.empty:
        return {"R": [], "L": [], "all": []}

    if "batter_stands" not in regular_df.columns and "stand" in regular_df.columns:
        regular_df["batter_stands"] = regular_df["stand"]

    pitch_col = "pitch_name" if "pitch_name" in regular_df.columns else "pitch_type"
    if pitch_col not in regular_df.columns:
        return {"R": [], "L": [], "all": []}

    working_df = regular_df.copy()
    working_df[pitch_col] = working_df[pitch_col].astype(str).str.strip()
    working_df = working_df[working_df[pitch_col] != ""]
    working_df = working_df[working_df[pitch_col].str.lower() != "nan"]

    def _build_mix_rows(frame):
        if frame.empty:
            return []

        counts = frame[pitch_col].value_counts()
        total = int(counts.sum())
        if total == 0:
            return []

        return [
            {
                "name": pitch_name,
                "count": int(count),
                "usage_pct": (float(count) / float(total)) * 100.0,
            }
            for pitch_name, count in counts.items()
        ]

    if "batter_stands" in working_df.columns:
        stands_series = working_df["batter_stands"].astype(str).str.upper()
        rhb_rows = _build_mix_rows(working_df[stands_series == "R"])
        lhb_rows = _build_mix_rows(working_df[stands_series == "L"])
    else:
        rhb_rows = []
        lhb_rows = []

    return {
        "R": rhb_rows,
        "L": lhb_rows,
        "all": _build_mix_rows(working_df),
    }

# Session-state based pitcher view (non-experimental)
if st.session_state.get("selected_pitcher"):
    sp = st.session_state.get("selected_pitcher")
    gp = st.session_state.get("selected_game")
    games_df = st.session_state.get("games")
    if games_df is None or (isinstance(games_df, pd.DataFrame) and games_df.empty):
        games_df = load_schedule(st.session_state.get("selected_date", eastern_today()))
    match = games_df[games_df["game_pk"] == gp]
    if match.empty:
        st.info("Game not found")
    else:
        game = match.iloc[0]
        lineup_context = get_game_lineups(game["game_pk"], game)
        away_lineup = lineup_context.get("away", [])
        home_lineup = lineup_context.get("home", [])
        side = sp.get("side")
        if side == "away":
            name = sp.get("name")
            pid = sp.get("id", "")
            hand = sp.get("hand", "")
            opponent_team = game.get("home_team", "")
            opponent_lineup = home_lineup
        else:
            name = sp.get("name")
            pid = sp.get("id", "")
            hand = sp.get("hand", "")
            opponent_team = game.get("away_team", "")
            opponent_lineup = away_lineup

        opponent_count = len(opponent_lineup) if opponent_lineup else 0
        rhb_count = sum(1 for p in opponent_lineup if p.get("handedness") == "R")
        lhb_count = sum(1 for p in opponent_lineup if p.get("handedness") == "L")
        switch_count = sum(1 for p in opponent_lineup if p.get("handedness") == "S")

        if st.button("← Back to Slate"):
            st.session_state.pop("selected_pitcher", None)
            st.session_state.pop("selected_game", None)
            try:
                st.query_params.clear()
            except Exception:
                pass
            st.rerun()

        st.markdown(f"## {name} {f'({hand})' if hand else ''}")
        st.markdown(f"{game.get('away_team')} @ {game.get('home_team')} • {game.get('game_time_et')}")

        try:
            mlb_stats = load_pitcher_stats(pid)
        except Exception as e:
            mlb_stats = {}
            logger.error("MLB stats request failed for %s: %s", pid, e)

        try:
            pitch_mix = load_regular_season_pitch_mix(pid)
        except Exception as e:
            pitch_mix = {"R": [], "L": [], "all": []}
            logger.error("Regular season pitch mix request failed for %s: %s", pid, e)

        def format_number(value, precision=2, suffix=""):
            if value is None or value == "":
                return "N/A"
            try:
                return f"{float(value):.{precision}f}{suffix}"
            except (TypeError, ValueError):
                return str(value)

        era_value = format_number(mlb_stats.get("era"))
        whip_value = format_number(mlb_stats.get("whip"))
        k_value = format_number(mlb_stats.get("k_percent"))
        bb_value = format_number(mlb_stats.get("bb_percent"))
        ip_value = format_number(mlb_stats.get("innings_pitched"), precision=1)
        hr_allowed_value = format_number(mlb_stats.get("hr_allowed"), precision=0)

        fastball_terms = ["4-seam fastball", "sinker", "cutter", "splitter"]
        breaking_terms = ["slider", "sweeper", "curveball", "knuckle curve", "slurve"]
        offspeed_terms = ["changeup", "forkball", "screwball"]

        actual_arsenal = pitch_mix.get("all", [])
        actual_arsenal_rhb = pitch_mix.get("R", [])
        actual_arsenal_lhb = pitch_mix.get("L", [])

        if actual_arsenal:
            primary_pitch = actual_arsenal[0]["name"]
            total_pitches = float(sum(row["count"] for row in actual_arsenal))
            fastball_count = 0.0
            breaking_count = 0.0
            offspeed_count = 0.0
            for row in actual_arsenal:
                pitch_name = str(row["name"]).lower()
                count = float(row["count"])
                if any(term in pitch_name for term in fastball_terms):
                    fastball_count += count
                elif any(term in pitch_name for term in breaking_terms):
                    breaking_count += count
                elif any(term in pitch_name for term in offspeed_terms):
                    offspeed_count += count

            fastball_value = format_number((fastball_count / total_pitches) * 100, precision=1, suffix="%")
            breaking_value = format_number((breaking_count / total_pitches) * 100, precision=1, suffix="%")
            offspeed_value = format_number((offspeed_count / total_pitches) * 100, precision=1, suffix="%")
        else:
            primary_pitch = "N/A"
            fastball_value = "N/A"
            breaking_value = "N/A"
            offspeed_value = "N/A"

        # --- Matchup Read (using already-loaded values; no new data fetching) ---
        try:
            def _parse_pct(s):
                if s is None:
                    return None
                try:
                    return float(str(s).replace('%', ''))
                except Exception:
                    return None

            fb_pct = _parse_pct(fastball_value)
            brk_pct = _parse_pct(breaking_value)
            off_pct = _parse_pct(offspeed_value)

            lean = None
            if fb_pct is not None or brk_pct is not None or off_pct is not None:
                # pick the largest available category
                choices = [(fb_pct or -1, 'fastball'), (brk_pct or -1, 'breaking'), (off_pct or -1, 'offspeed')]
                lean = max(choices, key=lambda x: x[0])[1]
        except Exception:
            lean = None

        if lean:
            arsenal_text = f"leans {lean} ({fastball_value} / {breaking_value} / {offspeed_value})"
        else:
            arsenal_text = f"{fastball_value} / {breaking_value} / {offspeed_value}"

        def _arsenal_table_html(rows):
            if rows:
                rows_html = "".join(
                    f"<span class='dash-label' style='text-transform:none; font-size:12px; letter-spacing:0;'>{pitch_type_text_html(row['name'])}</span><span class='dash-value dash-accent'>{row['usage_pct']:.1f}%</span>" for row in rows
                )
                return (
                    "<div class='dash-grid' style='grid-template-columns:1fr auto; row-gap:7px; column-gap:12px;'>"
                    "<span class='dash-label'>Pitch Name</span><span class='dash-label'>Usage %</span>"
                    f"{rows_html}"
                    "</div>"
                )
            else:
                return "<div style='font-size:13px; color:#475569; font-weight:700;'>No data</div>"

        stat_cols = st.columns(3)

        with stat_cols[0]:
            st.markdown(
                "<div class='dash-card'>"
                "<div class='dash-card-title'>2026 Season</div>"
                "<div class='dash-grid'>"
                f"<span class='dash-label'>ERA</span><span class='dash-value dash-accent'>{era_value}</span>"
                f"<span class='dash-label'>WHIP</span><span class='dash-value'>{whip_value}</span>"
                f"<span class='dash-label'>K%</span><span class='dash-value'>{k_value}</span>"
                f"<span class='dash-label'>BB%</span><span class='dash-value'>{bb_value}</span>"
                f"<span class='dash-label'>HR Allowed</span><span class='dash-value'>{hr_allowed_value}</span>"
                f"<span class='dash-label'>IP</span><span class='dash-value'>{ip_value}</span>"
                "</div></div>",
                unsafe_allow_html=True,
            )

        with stat_cols[1]:
            with st.container(border=True):
                st.markdown(
                    "<div class='section-title-strong'>Actual Pitch Arsenal</div>",
                    unsafe_allow_html=True,
                )
                selected_arsenal_split = st.segmented_control(
                    "Arsenal Split",
                    ["LHB", "Overall", "RHB"],
                    default="Overall",
                    key=f"arsenal_split_{pid}",
                    label_visibility="collapsed",
                )
                arsenal_rows = {
                    "LHB": actual_arsenal_lhb,
                    "Overall": actual_arsenal,
                    "RHB": actual_arsenal_rhb,
                }.get(selected_arsenal_split or "Overall", actual_arsenal)
                st.markdown(_arsenal_table_html(arsenal_rows), unsafe_allow_html=True)

        with stat_cols[2]:
            st.markdown(
                "<div class='dash-card'>"
                "<div class='dash-card-title'>Matchup Context</div>"
                "<div class='dash-grid'>"
                f"<span class='dash-label'>Opponent</span><span class='dash-value'>{opponent_team or 'N/A'}</span>"
                f"<span class='dash-label'>Opposing Batters</span><span class='dash-value'>{opponent_count or 'N/A'}</span>"
                f"<span class='dash-label'>RHB</span><span class='dash-value'>{rhb_count}</span>"
                f"<span class='dash-label'>LHB</span><span class='dash-value'>{lhb_count}</span>"
                f"<span class='dash-label'>Switch</span><span class='dash-value'>{switch_count}</span>"
                "</div></div>",
                unsafe_allow_html=True,
            )

        st.markdown(
            "<div class='dash-card' style='max-width:460px; margin-top:12px; margin-bottom:24px;'>"
            "<div class='dash-card-title'>Matchup Read</div>"
            "<div class='dash-grid-compact'>"
            f"<span class='dash-label'>Primary Pitch</span><span class='dash-value dash-accent'>{pitch_type_text_html(primary_pitch)}</span>"
            f"<span class='dash-label'>Arsenal</span><span class='dash-value'>{arsenal_text}</span>"
            f"<span class='dash-label'>Opposing Lineup</span><span class='dash-value'>{rhb_count} RHB / {lhb_count} LHB / {switch_count} switch</span>"
            "</div>"
            "</div>",
            unsafe_allow_html=True,
        )

        # Keep Matchup Read fully separated from Strike Zone without changing section order.
        st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

        pitch_type_options = ["All Pitches"]
        if actual_arsenal:
            pitch_type_options.extend(row["name"] for row in actual_arsenal)

        with st.container(border=True):
            st.markdown(
                "<div class='section-title-strong'>Strike Zone</div>",
                unsafe_allow_html=True,
            )
            strike_zone_cols = st.columns([1.15, 4])
            with strike_zone_cols[0]:
                # Streamlit selectbox options are plain text, so individual pitch names cannot be colored safely here.
                selected_pitch_type = st.selectbox(
                    "Pitch Type",
                    pitch_type_options,
                    index=0,
                    key=f"strike_zone_pitch_type_{pid}",
                )
                selected_batter_stands = st.selectbox(
                    "Batter Stands",
                    ["All Batters", "RHB", "LHB"],
                    index=0,
                    key=f"strike_zone_batter_stands_{pid}",
                )
            with strike_zone_cols[1]:
                strike_zone.display_strike_zone(pid, selected_pitch_type, selected_batter_stands)

        with st.container(border=True):
            st.markdown(
                "<div class='section-title-strong'>Game Lineups</div>",
                unsafe_allow_html=True,
            )
            lineup_cols = st.columns(2)
            with lineup_cols[0]:
                st.markdown(f"### {game.get('away_team', 'Away')}")
                st.markdown(
                    render_lineup_table(
                        away_lineup,
                        link_context={
                            "team": game.get("away_team", ""),
                            "opponent": game.get("home_team", ""),
                            "return_pitcher_id": pid,
                            "return_game_pk": gp,
                            "return_pitcher_side": side,
                            "return_pitcher_name": name,
                            "return_pitcher_hand": hand,
                        },
                    ),
                    unsafe_allow_html=True,
                )
            with lineup_cols[1]:
                st.markdown(f"### {game.get('home_team', 'Home')}")
                st.markdown(
                    render_lineup_table(
                        home_lineup,
                        link_context={
                            "team": game.get("home_team", ""),
                            "opponent": game.get("away_team", ""),
                            "return_pitcher_id": pid,
                            "return_game_pk": gp,
                            "return_pitcher_side": side,
                            "return_pitcher_name": name,
                            "return_pitcher_hand": hand,
                        },
                    ),
                    unsafe_allow_html=True,
                )

        st.stop()


# Pitcher view removed: query-param based navigation disabled to support older Streamlit versions


if "selected_date" not in st.session_state:
    st.session_state["selected_date"] = eastern_today()
if "calendar_date" not in st.session_state:
    st.session_state["calendar_date"] = st.session_state["selected_date"]


def set_homepage_date(new_date):
    if new_date == st.session_state.get("selected_date") and "games" in st.session_state:
        return
    st.session_state["selected_date"] = new_date
    st.session_state["calendar_date"] = new_date
    st.session_state["games"] = load_schedule(new_date)


def shift_homepage_date(days):
    set_homepage_date(st.session_state["selected_date"] + timedelta(days=days))


def set_homepage_today():
    set_homepage_date(eastern_today())


def set_homepage_calendar_date():
    set_homepage_date(st.session_state["calendar_date"])


if st.session_state["calendar_date"] != st.session_state["selected_date"]:
    st.session_state["calendar_date"] = st.session_state["selected_date"]

col1, col2, col3, col4 = st.columns([1, 4, 1, 1])
with col1:
    st.button("←", on_click=shift_homepage_date, args=(-1,))
with col2:
    formatted_date = st.session_state["selected_date"].strftime("%A, %B %d, %Y")
    st.markdown(
        f"<div style='text-align:center; font-size:20px; font-weight:600; margin: 8px 0;'>{formatted_date}</div>",
        unsafe_allow_html=True,
    )
with col3:
    st.button("→", on_click=shift_homepage_date, args=(1,))
with col4:
    st.button("Today", on_click=set_homepage_today)

with st.expander("Calendar", expanded=False):
    st.date_input(
        "Select date",
        key="calendar_date",
        on_change=set_homepage_calendar_date,
    )

if "games" not in st.session_state:
    st.session_state["games"] = load_schedule(st.session_state["selected_date"])

if "games" in st.session_state:
    PLAYER_API_CALLS = 0
    games = st.session_state["games"]
    st.success(f"Loaded {len(games)} games")
    logger.debug("Games loaded: %s", len(games))

    load_start = time.perf_counter()
    for i in range(0, len(games), 2):
        row_cols = st.columns(2)

        for col, (_, game) in zip(row_cols, games.iloc[i:i + 2].iterrows()):
            with col:
                with st.container(border=True):
                    st.markdown("<div class='game-card'>", unsafe_allow_html=True)
                    st.markdown(
                        f"<div style='display:flex; justify-content:center; align-items:center; gap:16px; margin-bottom:8px;'>"
                        f"<div style='width:48px; height:48px; display:flex; justify-content:center; align-items:center;'>"
                        f"<img src='https://www.mlbstatic.com/team-logos/{game['away_team_id']}.svg' alt='{game['away_abbrev']} logo' style='display:block; width:100%; height:100%; object-fit:contain;' />"
                        f"</div>"
                        f"<span style='font-size:1.1rem; font-weight:600; line-height:1; display:flex; align-items:center;'>@</span>"
                        f"<div style='width:48px; height:48px; display:flex; justify-content:center; align-items:center;'>"
                        f"<img src='https://www.mlbstatic.com/team-logos/{game['home_team_id']}.svg' alt='{game['home_abbrev']} logo' style='display:block; width:100%; height:100%; object-fit:contain;' />"
                        f"</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                    raw_status = game.get("status", "")
                    display_status_text = display_status(raw_status)
                    status_color_text = status_color(raw_status)
                    st.markdown(
                        f"<div style='text-align:center; margin-bottom:6px;'>"
                        f"<span style='font-weight:700; font-size:17px;'>🕒 {game['game_time_et']}</span>"
                        f"</div>"
                        f"<div style='text-align:center; font-size:13px; color:#555;'>"
                        f"{game['venue']} | "
                        f"<span style='color:{status_color_text}; font-weight:700;'>{display_status_text}</span>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

                    lineup_context = get_game_lineups(game["game_pk"], game)
                    away_lineup = lineup_context.get("away", [])
                    home_lineup = lineup_context.get("home", [])

                    away_col, home_col = st.columns(2)

                    with away_col:
                        st.markdown(f"### {game['away_team']}")
                        away_pitcher_label = f"Starting Pitcher:"
                        away_btn_key = f"away_pitch_{game['game_pk']}"
                        c_label, c_button, c_hand = st.columns([1, 3, 1])
                        c_label.markdown(away_pitcher_label)
                        # Render pitcher name as a link-styled button that opens pitcher detail
                        if c_button.button(game['away_pitcher'], key=away_btn_key):
                            st.session_state['selected_pitcher'] = {
                                'name': game.get('away_pitcher'),
                                'id': game.get('away_pitcher_id'),
                                'hand': game.get('away_pitcher_hand'),
                                'side': 'away'
                            }
                            st.session_state['selected_game'] = game['game_pk']
                            st.rerun()
                        away_hand_text = game.get('away_pitcher_hand')
                        c_hand.markdown(f"({away_hand_text})" if away_hand_text else "")
                        if not away_lineup:
                            st.markdown(
                                f"<div class='lineup-area' style='min-height:{LINEUP_MIN_HEIGHT}px; display:flex; flex-direction:column; align-items:flex-start; justify-content:flex-start; padding-top:6px; color:#92400e; font-weight:600;'>Lineup not posted yet.</div>",
                                unsafe_allow_html=True,
                            )
                        else:
                            away_lines = []
                            for player in away_lineup:
                                ph = f" ({player.get('handedness')})" if player.get('handedness') else ''
                                batter_name = player.get("name", "")
                                if player.get("player_id"):
                                    batter_href = _build_batter_detail_href(
                                        player.get("player_id"),
                                        batter_name=batter_name,
                                        batter_hand=player.get("handedness", ""),
                                        team=game.get("away_team", ""),
                                        opponent=game.get("home_team", ""),
                                        return_game_pk=game["game_pk"],
                                    )
                                    batter_name_html = (
                                        f"<a class='nav-name-link' href='{html.escape(batter_href, quote=True)}' target='_self'>"
                                        f"{html.escape(str(batter_name))}</a>"
                                    )
                                else:
                                    batter_name_html = html.escape(str(batter_name))
                                away_lines.append(f"<div style='line-height:1.4; margin:4px 0;'>{player.get('number','')}. {batter_name_html}{ph} {player.get('position','')}</div>")
                            away_lines_html = "".join(away_lines)
                            away_warning_html = (
                                "<div style='margin:0 0 8px 0; padding:6px 8px; border:1px solid #dc2626; border-radius:6px; background:#fef2f2; color:#b91c1c; font-weight:800;'>⚠ Projected lineup — not confirmed</div>"
                                if any(player.get("is_projected") for player in away_lineup)
                                else ""
                            )
                            away_confirmed_html = ""
                            if not away_warning_html:
                                away_confirmed_html = (
                                    "<div style='margin:0 0 8px 0; padding:6px 8px; border:1px solid #16a34a; border-radius:6px; background:#f0fdf4; color:#15803d; font-weight:800;'>"
                                    "🟢 Confirmed MLB Lineup"
                                    "</div>"
                                )
                            st.markdown(
                                f"<div class='lineup-area' style='min-height:{LINEUP_MIN_HEIGHT}px; display:flex; flex-direction:column; align-items:flex-start; justify-content:flex-start;'>{away_warning_html}{away_confirmed_html}{away_lines_html}</div>",
                                unsafe_allow_html=True,
                            )

                    with home_col:
                        st.markdown(f"### {game['home_team']}")
                        home_pitcher_label = f"Starting Pitcher:"
                        home_btn_key = f"home_pitch_{game['game_pk']}"
                        c_label_h, c_button_h, c_hand_h = st.columns([1, 3, 1])
                        c_label_h.markdown(home_pitcher_label)
                        # Render pitcher name as a link-styled button that opens pitcher detail
                        if c_button_h.button(game['home_pitcher'], key=home_btn_key):
                            st.session_state['selected_pitcher'] = {
                                'name': game.get('home_pitcher'),
                                'id': game.get('home_pitcher_id'),
                                'hand': game.get('home_pitcher_hand'),
                                'side': 'home'
                            }
                            st.session_state['selected_game'] = game['game_pk']
                            st.rerun()
                        home_hand_text = game.get('home_pitcher_hand')
                        c_hand_h.markdown(f"({home_hand_text})" if home_hand_text else "")

                        if not home_lineup:
                            st.markdown(
                                f"<div class='lineup-area' style='min-height:{LINEUP_MIN_HEIGHT}px; display:flex; flex-direction:column; align-items:flex-start; justify-content:flex-start; padding-top:6px; color:#92400e; font-weight:600;'>Lineup not posted yet.</div>",
                                unsafe_allow_html=True,
                            )
                        else:
                            home_lines = []
                            for player in home_lineup:
                                ph = f" ({player.get('handedness')})" if player.get('handedness') else ''
                                batter_name = player.get("name", "")
                                if player.get("player_id"):
                                    batter_href = _build_batter_detail_href(
                                        player.get("player_id"),
                                        batter_name=batter_name,
                                        batter_hand=player.get("handedness", ""),
                                        team=game.get("home_team", ""),
                                        opponent=game.get("away_team", ""),
                                        return_game_pk=game["game_pk"],
                                    )
                                    batter_name_html = (
                                        f"<a class='nav-name-link' href='{html.escape(batter_href, quote=True)}' target='_self'>"
                                        f"{html.escape(str(batter_name))}</a>"
                                    )
                                else:
                                    batter_name_html = html.escape(str(batter_name))
                                home_lines.append(f"<div style='line-height:1.4; margin:4px 0;'>{player.get('number','')}. {batter_name_html}{ph} {player.get('position','')}</div>")
                            home_lines_html = "".join(home_lines)
                            home_warning_html = (
                                "<div style='margin:0 0 8px 0; padding:6px 8px; border:1px solid #dc2626; border-radius:6px; background:#fef2f2; color:#b91c1c; font-weight:800;'>⚠ Projected lineup — not confirmed</div>"
                                if any(player.get("is_projected") for player in home_lineup)
                                else ""
                            )
                            home_confirmed_html = ""
                            if not home_warning_html:
                                home_confirmed_html = (
                                    "<div style='margin:0 0 8px 0; padding:6px 8px; border:1px solid #16a34a; border-radius:6px; background:#f0fdf4; color:#15803d; font-weight:800;'>"
                                    "🟢 Confirmed MLB Lineup"
                                    "</div>"
                                )
                            st.markdown(
                                f"<div class='lineup-area' style='min-height:{LINEUP_MIN_HEIGHT}px; display:flex; flex-direction:column; align-items:flex-start; justify-content:flex-start;'>{home_warning_html}{home_confirmed_html}{home_lines_html}</div>",
                                unsafe_allow_html=True,
                            )
                    st.markdown("</div>", unsafe_allow_html=True)
    load_time = time.perf_counter() - load_start
    logger.debug("Player API calls: %s", PLAYER_API_CALLS)
    logger.debug("Total load time: %.2fs", load_time)
    st.caption(f"Games loaded: {len(games)} | player API calls: {PLAYER_API_CALLS} | total load time: {load_time:.2f}s")
