import logging
import time
import json
import io
import html
import altair as alt
import streamlit as st
import pandas as pd
import requests
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import quote_plus

import strike_zone

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
PLAYER_API_CALLS = 0
LINEUP_MIN_HEIGHT = 220
GAME_LOG_PROPS = [
    "Hits",
    "Runs",
    "RBI",
    "H+R+RBI",
    "Total Bases",
    "Home Runs",
    "Walks",
    "Strikeouts",
    "Plate Appearances",
    "Stolen Bases",
    "Singles",
    "Doubles",
    "Triples",
    "1st Inning Hits + Runs + RBIs",
]
GAME_LOG_SAMPLE_RANGES = ("L5", "L10", "L15", "2026")
GAME_LOG_HIT_EVENT_LABELS = {
    "single": "Single",
    "double": "Double",
    "triple": "Triple",
    "home_run": "Home Run",
}
GAME_LOG_PROP_COLUMNS = {
    "Hits": "hits",
    "Runs": "runs",
    "RBI": "rbi",
    "H+R+RBI": "hrrrbi",
    "Total Bases": "total_bases",
    "Home Runs": "home_runs",
    "Walks": "walks",
    "Strikeouts": "strikeouts",
    "Plate Appearances": "plate_appearances",
    "Stolen Bases": "stolen_bases",
    "Singles": "singles",
    "Doubles": "doubles",
    "Triples": "triples",
    "1st Inning Hits + Runs + RBIs": "first_inning_hrrrbi",
}
SPORTSBOOK_BADGE_ASSETS = {
    "prizepicks": "app/static/badges/prizepicks.png",
}
MODIFIER_BADGE_ASSETS = {
    "goblin": "app/static/badges/goblin.png",
    "demon": "app/static/badges/demon.png",
}
PRIZEPICKS_MLB_LEAGUE_ID = 2
PRIZEPICKS_MLBLIVE_LEAGUE_ID = 231
PRIZEPICKS_MLB_LEAGUES = (
    ("MLB", PRIZEPICKS_MLB_LEAGUE_ID),
    ("MLBLIVE", PRIZEPICKS_MLBLIVE_LEAGUE_ID),
)
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
        --dash-page-bg:linear-gradient(180deg,#f7faff 0%, #f3f7ff 100%);
        --dash-card-bg:#ffffff;
        --dash-text:#0b1220;
        --dash-muted:#475569;
        --dash-control-bg:#ffffff;
        --dash-control-text:#111827;
        --dash-control-border:#cbd5e1;
        --dash-surface:#edf4ff;
        --dash-surface-2:#e3eeff;
        --dash-border:#5f7598;
        --dash-shadow:0 10px 24px rgba(15,23,42,0.18);
        --dash-title:#0f172a;
        --dash-label:#1f2d42;
        --dash-value:#0b1220;
        --dash-accent:#0057d8;
    }
    @media (prefers-color-scheme: dark){
        :root{
            --dash-page-bg:linear-gradient(180deg,#07111f 0%, #0b1526 100%);
            --dash-card-bg:#0f1b2d;
            --dash-text:#e5edf8;
            --dash-muted:#b7c4d8;
            --dash-border:#4f6688;
            --dash-control-bg:#111c2e;
            --dash-control-text:#f8fafc;
            --dash-control-border:#5f7598;
            --dash-surface:#102033;
            --dash-surface-2:#16283f;
            --dash-shadow:0 10px 24px rgba(0,0,0,0.34);
            --dash-title:#f8fafc;
            --dash-label:#cbd5e1;
            --dash-value:#f1f5f9;
            --dash-accent:#7dd3fc;
        }
    }
    section[data-testid="stMain"] .block-container{padding-bottom:1rem}
    section[data-testid="stMain"]{background:var(--dash-page-bg);color:var(--dash-text)}
    section[data-testid="stMain"] [data-testid="stVerticalBlock"]{gap:0.5rem}
    section[data-testid="stMain"] [data-testid="stHorizontalBlock"]{gap:0.75rem}
    section[data-testid="stMain"] h1,section[data-testid="stMain"] h2,section[data-testid="stMain"] h3{margin-top:0.2rem;margin-bottom:0.45rem}
    section[data-testid="stMain"] p{margin-top:0.2rem;margin-bottom:0.3rem}
    section[data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"]{
        border:2px solid var(--dash-border)!important;
        border-radius:16px!important;
        background:var(--dash-card-bg)!important;
        box-shadow:var(--dash-shadow)!important;
        color:var(--dash-text)!important;
    }
    .game-card{padding:10px 14px 20px 14px;box-sizing:border-box}
    .game-card .lineup-area{padding:8px 6px}
    /* Style Streamlit buttons used as inline pitcher links to look like normal hyperlinks (scoped to game cards) */
    .game-card .stButton>button{background:none;border:none;padding:0;color:var(--dash-value);text-decoration:none;cursor:pointer;font-size:inherit;font-weight:650}
    .game-card .stButton>button:hover{color:var(--dash-accent);text-decoration:underline}
    .nav-name-link{color:var(--dash-value)!important;text-decoration:none!important;font-weight:650;cursor:pointer}
    .nav-name-link:hover{color:var(--dash-accent)!important;text-decoration:underline!important}
    div[data-testid="stSegmentedControl"] div[role="radiogroup"]{overflow-x:auto;flex-wrap:nowrap}
    div[data-testid="stSegmentedControl"] label{white-space:pre-line;line-height:1.2}
    .st-key-prop_tab_row{
        max-width:100%;
        overflow-x:auto;
        overflow-y:hidden;
    }
    .st-key-prop_tab_row [data-testid="stHorizontalBlock"]{
        width:max-content;
        min-width:100%;
        max-width:none;
        overflow-x:auto;
        overflow-y:hidden;
        padding:2px 6px 8px 6px;
        margin:0 0 4px 0;
        scroll-behavior:smooth;
        -webkit-overflow-scrolling:touch;
        scrollbar-width:thin;
        scrollbar-color:var(--dash-control-border) transparent;
        flex-wrap:nowrap!important;
        gap:8px;
    }
    .st-key-prop_tab_row [data-testid="stHorizontalBlock"]>div{
        flex:0 0 auto!important;
        width:auto!important;
        min-width:max-content!important;
    }
    .st-key-prop_tab_row [data-testid="stHorizontalBlock"]::-webkit-scrollbar{
        height:6px;
    }
    .st-key-prop_tab_row [data-testid="stHorizontalBlock"]::-webkit-scrollbar-track{
        background:transparent;
    }
    .st-key-prop_tab_row [data-testid="stHorizontalBlock"]::-webkit-scrollbar-thumb{
        background:var(--dash-control-border);
        border-radius:999px;
    }
    .st-key-prop_tab_row .stButton{
        flex:0 0 auto;
    }
    .st-key-prop_tab_row .stButton>button{
        min-height:34px;
        padding:7px 14px;
        border:1px solid var(--dash-control-border);
        border-radius:999px;
        background:var(--dash-control-bg);
        color:var(--dash-control-text)!important;
        font-size:14px;
        font-weight:700;
        line-height:1;
        text-decoration:none!important;
        box-shadow:0 1px 2px rgba(15,23,42,0.05);
        cursor:pointer;
        white-space:nowrap;
    }
    .st-key-prop_tab_row .stButton>button p{
        margin:0;
        white-space:nowrap;
    }
    .st-key-prop_tab_row .stButton>button:hover{
        border-color:var(--dash-accent);
        color:var(--dash-control-text)!important;
    }
    .st-key-prop_tab_row .stButton>button[kind="primary"]{
        border-color:var(--dash-accent);
        background:var(--dash-surface-2);
        color:var(--dash-title)!important;
        box-shadow:0 0 0 2px rgba(0,87,216,0.12);
    }
    .st-key-game_log_range_tiles [data-testid="stHorizontalBlock"]{overflow-x:auto;flex-wrap:nowrap;gap:0.65rem}
    .st-key-game_log_range_tiles .stButton>button{
        min-width:132px;
        min-height:88px;
        padding:10px 14px;
        border-radius:13px;
        border:1px solid #273449;
        background:#07111f;
        color:#e5edf8;
        box-shadow:0 8px 18px rgba(15,23,42,0.22);
        white-space:pre-line;
        line-height:1.22;
        font-size:15px;
        font-weight:800;
    }
    .st-key-game_log_range_tiles .stButton>button p{margin:0;white-space:pre-line;line-height:1.22}
    .st-key-game_log_range_tiles .stButton>button:hover{
        border-color:#7dd3fc;
        background:#0b1b31;
        color:#ffffff;
    }
    .st-key-game_log_range_tiles .stButton>button[kind="primary"]{
        border:2px solid #38bdf8;
        background:#102a47;
        box-shadow:0 0 0 2px rgba(56,189,248,0.22),0 10px 20px rgba(15,23,42,0.28);
        color:#ffffff;
    }
    .line-badge{display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:6px 12px;border:1px solid var(--dash-control-border);border-radius:999px;min-width:120px;background:var(--dash-card-bg);box-shadow:0 1px 2px rgba(15,23,42,0.04);white-space:nowrap}
    .line-value{font-weight:700;font-size:22px;color:var(--dash-title);line-height:1}
    .book-badge,.boost-badge{display:inline-flex;align-items:center;justify-content:center;line-height:1;white-space:nowrap}
    .badge-img{display:block;object-fit:contain;flex:0 0 auto}
    .book-badge-img{height:23px;width:auto;max-width:34px;transform:translateY(-1.5px)}
    .modifier-badge-img{height:26px;width:auto;max-width:30px}
    .line-badge-wrap{display:flex;align-items:center;justify-content:center}
    .alt-line-row{display:flex;align-items:center;gap:8px;margin:4px 0}
    .prop-control-spacer{height:4px}
    .dash-card{
        border:2px solid var(--dash-border);
        border-radius:16px;
        background:var(--dash-card-bg);
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
    section[data-testid="stMain"] [data-testid="stWidgetLabel"] label,
    section[data-testid="stMain"] [data-testid="stWidgetLabel"] p{
        color:var(--dash-text)!important;
    }
    section[data-testid="stMain"] [data-baseweb="select"]{
        filter:none!important;
        zoom:1!important;
    }
    section[data-testid="stMain"] [data-baseweb="select"] > div{
        background-color:var(--dash-control-bg)!important;
        border-color:var(--dash-control-border)!important;
        color:var(--dash-control-text)!important;
    }
    section[data-testid="stMain"] [data-baseweb="select"] div,
    section[data-testid="stMain"] [data-baseweb="select"] span{
        filter:none!important;
        font-weight:400!important;
        color:var(--dash-control-text)!important;
        line-height:1.35!important;
        text-rendering:auto;
        -webkit-font-smoothing:auto;
    }
    section[data-testid="stMain"] [data-baseweb="select"] input{
        color:var(--dash-control-text)!important;
    }
    section[data-testid="stMain"] [data-baseweb="select"] input::placeholder{
        color:var(--dash-muted)!important;
        opacity:1!important;
    }
    section[data-testid="stMain"] [data-baseweb="select"] svg{
        filter:none!important;
        color:var(--dash-control-text)!important;
        fill:var(--dash-control-text)!important;
    }
    div[data-baseweb="popover"] [role="listbox"],
    div[data-baseweb="popover"] ul,
    div[data-baseweb="menu"]{
        background-color:var(--dash-control-bg)!important;
        color:var(--dash-control-text)!important;
        border-color:var(--dash-control-border)!important;
    }
    div[data-baseweb="popover"] [role="option"],
    div[data-baseweb="popover"] li,
    div[data-baseweb="menu"] li{
        background-color:var(--dash-control-bg)!important;
        color:var(--dash-control-text)!important;
    }
    div[data-baseweb="popover"] [role="option"] *,
    div[data-baseweb="popover"] li *,
    div[data-baseweb="menu"] li *{
        color:var(--dash-control-text)!important;
    }
    div[data-baseweb="popover"] [role="option"]:hover,
    div[data-baseweb="popover"] li:hover,
    div[data-baseweb="menu"] li:hover,
    div[data-baseweb="popover"] [aria-selected="true"]{
        background-color:var(--dash-surface-2)!important;
        color:var(--dash-control-text)!important;
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


def badge_image_html(asset_path, alt_text, wrapper_class, image_class):
    if not asset_path:
        return ""
    return (
        f'<span class="{html.escape(wrapper_class)}">'
        f'<img class="badge-img {html.escape(image_class)}" '
        f'src="{html.escape(asset_path, quote=True)}" '
        f'alt="{html.escape(alt_text, quote=True)}" loading="lazy" decoding="async" />'
        '</span>'
    )


def render_line_badge(line_value, odds_type="", show_book_badge=True):
    try:
        line_text = f"{float(line_value):.1f}"
    except (TypeError, ValueError):
        line_text = str(line_value)

    normalized_odds_type = normalize_name(odds_type)
    boost_html = ""
    if show_book_badge and normalized_odds_type == "goblin":
        boost_html = badge_image_html(MODIFIER_BADGE_ASSETS.get("goblin"), "Goblin", "boost-badge", "modifier-badge-img")
    elif show_book_badge and normalized_odds_type == "demon":
        boost_html = badge_image_html(MODIFIER_BADGE_ASSETS.get("demon"), "Demon", "boost-badge", "modifier-badge-img")
    book_badge_html = (
        badge_image_html(SPORTSBOOK_BADGE_ASSETS.get("prizepicks"), "PrizePicks", "book-badge", "book-badge-img")
        if show_book_badge
        else ""
    )

    return (
        '<div class="line-badge">'
        f'<span class="line-value">{html.escape(line_text)}</span>'
        f'{book_badge_html}'
        f'{boost_html}'
        '</div>'
    )


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
        "hrrbi": "hrrrbi",
        "hrrbis": "hrrrbi",
        "hrrrbi": "hrrrbi",
        "hitsrunsrbis": "hrrrbi",
        "hitsrunsrbi": "hrrrbi",
        "1stinnhrr": "firstinninghrrrbi",
        "1stinninghrr": "firstinninghrrrbi",
        "1stinninghrrbi": "firstinninghrrrbi",
        "1stinninghrrbis": "firstinninghrrrbi",
        "1stinninghrrrbi": "firstinninghrrrbi",
        "1stinnhitsrunsrbis": "firstinninghrrrbi",
        "1stinnhitsrunsrbi": "firstinninghrrrbi",
        "1stinninghitsrunsrbis": "firstinninghrrrbi",
        "1stinninghitsrunsrbi": "firstinninghrrrbi",
        "firstinninghrr": "firstinninghrrrbi",
        "firstinninghrrbi": "firstinninghrrrbi",
        "firstinninghrrbis": "firstinninghrrrbi",
        "firstinninghrrrbi": "firstinninghrrrbi",
        "firstinninghitsrunsrbis": "firstinninghrrrbi",
        "firstinninghitsrunsrbi": "firstinninghrrrbi",
        "totalbases": "totalbases",
        "tb": "totalbases",
        "homeruns": "homeruns",
        "walks": "walks",
        "strikeouts": "strikeouts",
        "hitterks": "strikeouts",
        "sb": "stolenbases",
        "stolenbase": "stolenbases",
        "stolenbases": "stolenbases",
    }
    return aliases.get(compact, compact)


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
        "boost odds_type": _projection_value(record, "odds_type", "oddsType", default=""),
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


@st.cache_data(ttl=300)
def load_prizepicks_mlb_projections(debug_version=2):
    headers = {
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://app.prizepicks.com",
        "Referer": "https://app.prizepicks.com/",
        "User-Agent": "Mozilla/5.0",
    }
    parsed = []
    seen_projection_ids = set()
    league_counts = {}
    first_inning_counts = {}

    for league_label, league_id in PRIZEPICKS_MLB_LEAGUES:
        params = {
            "league_id": league_id,
            "per_page": 10000,
        }
        try:
            response = requests.get(PRIZEPICKS_PROJECTIONS_URL, params=params, headers=headers, timeout=20)
            print(f"PrizePicks {league_label} request URL:", response.url)
            print(f"PrizePicks {league_label} HTTP status:", response.status_code)
            logger.warning("PrizePicks %s request URL: %s", league_label, response.url)
            logger.warning("PrizePicks %s HTTP status: %s", league_label, response.status_code)
            response.raise_for_status()
            payload = response.json()
            data_len = len(payload.get("data", [])) if isinstance(payload, dict) else 0
            print(f"PrizePicks {league_label} response data length:", data_len)
            logger.warning("PrizePicks %s response data length: %s", league_label, data_len)
        except Exception as exc:
            print(f"PrizePicks {league_label} projections request failed:", repr(exc))
            logger.warning("PrizePicks %s projections request failed: %s", league_label, exc)
            continue

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

        league_counts[league_label] = 0
        first_inning_counts[league_label] = 0
        for projection in payload.get("data", []):
            if not isinstance(projection, dict):
                continue
            projection_id = str(projection.get("id") or "")
            if projection_id and projection_id in seen_projection_ids:
                continue
            if projection_id:
                seen_projection_ids.add(projection_id)

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

            stat_display_name = attributes.get("stat_display_name")
            if _prop_match_key(stat_display_name) == "firstinninghrrrbi":
                first_inning_counts[league_label] += 1

            parsed_projection = {
                "id": projection.get("id"),
                "type": projection.get("type"),
                "source": "PrizePicks",
                "source_league": league_label,
                "source_league_id": league_id,
                "attributes": attributes,
                "relationships": relationships,
                "new_player": player,
                "score": score,
                "raw_projection": projection,
                "stat_display_name": stat_display_name,
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
            league_counts[league_label] += 1

    print("PrizePicks parsed projection count:", len(parsed))
    print("PrizePicks parsed projection counts by league:", league_counts)
    print("PrizePicks first-inning HRR counts by league:", first_inning_counts)
    logger.warning("PrizePicks parsed projection count: %s", len(parsed))
    logger.warning("PrizePicks parsed projection counts by league: %s", league_counts)
    logger.warning("PrizePicks first-inning HRR counts by league: %s", first_inning_counts)
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


def run_value_style_color_hex(level):
    style = RUN_VALUE_STYLE_COLORS.get(level, "")
    for part in style.split(";"):
        key, _, value = part.partition(":")
        if key.strip() == "color":
            return value.strip()
    return "#111"


def run_value_title_with_legend_html():
    legend_rows = [
        ("elite", "Elite"),
        ("good", "Good"),
        ("average", "Average"),
        ("bad", "Poor"),
    ]
    legend_html = "".join(
        "<span style='display:inline-flex; align-items:center; gap:5px; white-space:nowrap;'>"
        f"<span style='display:inline-block; width:10px; height:10px; border-radius:2px; background:{run_value_style_color_hex(level)};'></span>"
        f"<span>{label}</span>"
        "</span>"
        for level, label in legend_rows
    )
    return (
        "<div style='display:flex; align-items:center; justify-content:space-between; gap:16px; flex-wrap:wrap; margin-bottom:10px;'>"
        "<div class='section-title-strong' style='margin-bottom:0;'>Run Value by Pitch Type</div>"
        f"<div style='display:flex; align-items:center; gap:14px; flex-wrap:wrap; color:var(--dash-text); font-size:12px; font-weight:700;'>{legend_html}</div>"
        "</div>"
    )


def canonical_run_value_metric(metric):
    normalized = str(metric or "").strip().lower().replace(" ", "").replace("_", "")
    metric_map = {
        "ba": "BA",
        "xba": "xBA",
        "slg": "SLG",
        "xslg": "xSLG",
        "woba": "wOBA",
        "xwoba": "xwOBA",
        "hardhit%": "Hard Hit%",
        "hardhitpct": "Hard Hit%",
        "hardhitpercent": "Hard Hit%",
        "whiff%": "Whiff%",
        "whiffpct": "Whiff%",
        "whiffpercent": "Whiff%",
        "k%": "K%",
        "kpct": "K%",
        "kpercent": "K%",
        "putaway%": "PutAway%",
        "putawaypct": "PutAway%",
        "putawaypercent": "PutAway%",
    }
    return metric_map.get(normalized, "")


def run_value_threshold_style(value, metric):
    metric = canonical_run_value_metric(metric)
    if not metric:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if pd.isna(number):
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
        if number < 18:
            return RUN_VALUE_STYLE_COLORS["elite"]
        if number < 22:
            return RUN_VALUE_STYLE_COLORS["good"]
        if number < 26:
            return RUN_VALUE_STYLE_COLORS["average"]
        return RUN_VALUE_STYLE_COLORS["bad"]
    if metric == "K%":
        if number < 15:
            return RUN_VALUE_STYLE_COLORS["elite"]
        if number < 20:
            return RUN_VALUE_STYLE_COLORS["good"]
        if number < 24:
            return RUN_VALUE_STYLE_COLORS["average"]
        return RUN_VALUE_STYLE_COLORS["bad"]
    if metric == "PutAway%":
        if number < 15:
            return RUN_VALUE_STYLE_COLORS["elite"]
        if number < 18:
            return RUN_VALUE_STYLE_COLORS["good"]
        if number < 23:
            return RUN_VALUE_STYLE_COLORS["average"]
        return RUN_VALUE_STYLE_COLORS["bad"]
    return ""


def style_run_value_table(df):
    styled = df.style.map(pitch_type_cell_style, subset=["Pitch Type"])
    for column in df.columns:
        metric = canonical_run_value_metric(column)
        if metric:
            styled = styled.map(lambda value, metric=metric: run_value_threshold_style(value, metric), subset=[column])
    return styled


def _int_like(value, default=0):
    try:
        if pd.isna(value):
            return default
    except TypeError:
        pass
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


@st.cache_data(ttl=86400, show_spinner=False)
def load_batter_first_inning_hrrrbi_by_game(batter_id, season_year):
    if not batter_id or not season_year:
        return {}

    try:
        season_year = int(season_year)
    except (TypeError, ValueError):
        return {}

    try:
        selected_batter_id = int(float(batter_id))
    except (TypeError, ValueError):
        return {}

    season_log = load_batter_prop_game_log(batter_id, season_year=season_year, include_first_inning=False)
    if season_log.empty or "game_pk" not in season_log.columns:
        return {}

    hit_events = {"single", "double", "triple", "home_run"}
    first_inning_by_game = {}
    game_pks = [
        normalize_game_pk(game_pk)
        for game_pk in season_log["game_pk"].tolist()
        if normalize_game_pk(game_pk)
    ]

    for game_key in sorted(set(game_pks)):
        url = f"https://statsapi.mlb.com/api/v1.1/game/{game_key}/feed/live"
        try:
            feed = requests.get(url, timeout=20).json()
        except Exception as exc:
            logger.warning("First-inning game feed fetch failed for game_pk=%s batter_id=%s: %s", game_key, batter_id, exc)
            first_inning_by_game[game_key] = 0
            continue

        plays = feed.get("liveData", {}).get("plays", {}).get("allPlays", [])
        hits = 0
        runs = 0
        rbis = 0
        for play in plays:
            about = play.get("about", {}) if isinstance(play, dict) else {}
            if _int_like(about.get("inning")) != 1:
                continue

            matchup = play.get("matchup", {}) if isinstance(play.get("matchup"), dict) else {}
            batter = matchup.get("batter", {}) if isinstance(matchup.get("batter"), dict) else {}
            result = play.get("result", {}) if isinstance(play.get("result"), dict) else {}
            batter_matches = _int_like(batter.get("id"), default=-1) == selected_batter_id
            event_type = str(result.get("eventType") or "").lower().strip()
            if batter_matches:
                if event_type in hit_events:
                    hits += 1
                rbis += _int_like(result.get("rbi"), default=0)

            for runner in play.get("runners", []) or []:
                details = runner.get("details", {}) if isinstance(runner, dict) else {}
                runner_record = details.get("runner", {}) if isinstance(details.get("runner"), dict) else {}
                movement = runner.get("movement", {}) if isinstance(runner, dict) else {}
                if _int_like(runner_record.get("id"), default=-1) == selected_batter_id and str(movement.get("end") or "").lower() == "score":
                    runs += 1

        first_inning_by_game[game_key] = hits + runs + rbis

    return first_inning_by_game


@st.cache_data(ttl=1800, show_spinner=False)
def load_batter_prop_game_log(batter_id, season_year=2026, include_first_inning=False):
    if not batter_id:
        return pd.DataFrame()

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
        opponent_name = opponent.get("name") or opponent.get("teamName") or opponent_label
        raw_is_home = split.get("isHome", False)
        is_home = raw_is_home if isinstance(raw_is_home, bool) else str(raw_is_home).lower() == "true"
        prefix = "" if is_home else "@"
        game = split.get("game", {}) or {}
        hits = _int_stat(stat, "hits")
        runs = _int_stat(stat, "runs")
        rbi = _int_stat(stat, "rbi")
        doubles = _int_stat(stat, "doubles")
        triples = _int_stat(stat, "triples")
        home_runs = _int_stat(stat, "homeRuns")
        rows.append(
            {
                "game_pk": game.get("gamePk") or game.get("id") or "",
                "season": int(season_year),
                "game_date": game_date,
                "opponent": f"{prefix}{opponent_label}" if opponent_label else "",
                "opponent_team_id": opponent.get("id", ""),
                "opponent_name": opponent_name,
                "opponent_abbrev": opponent.get("abbreviation") or "",
                "hits": hits,
                "runs": runs,
                "rbi": rbi,
                "hrrrbi": hits + runs + rbi,
                "total_bases": _int_stat(stat, "totalBases"),
                "home_runs": home_runs,
                "walks": _int_stat(stat, "baseOnBalls"),
                "strikeouts": _int_stat(stat, "strikeOuts"),
                "plate_appearances": _int_stat(stat, "plateAppearances"),
                "stolen_bases": _int_stat(stat, "stolenBases"),
                "singles": max(hits - doubles - triples - home_runs, 0),
                "doubles": doubles,
                "triples": triples,
            }
        )

    if not rows:
        return pd.DataFrame()

    game_log = pd.DataFrame(rows).sort_values("game_date").reset_index(drop=True)
    if include_first_inning:
        first_inning_values = load_batter_first_inning_hrrrbi_by_game(batter_id, season_year)
        game_log["first_inning_hrrrbi"] = game_log["game_pk"].apply(
            lambda game_pk: int(first_inning_values.get(normalize_game_pk(game_pk), 0))
        )
    game_log["label"] = game_log.apply(
        lambda row: f"{row['game_date'].strftime('%m/%d')} {row['opponent']}".strip(),
        axis=1,
    )
    return game_log


@st.cache_data(ttl=86400, show_spinner=False)
def load_batter_prop_game_log_seasons(batter_id):
    if not batter_id:
        return []

    url = f"https://statsapi.mlb.com/api/v1/people/{batter_id}/stats"
    params = {"stats": "yearByYear", "group": "hitting", "sportIds": 1}
    try:
        data = requests.get(url, params=params, timeout=20).json()
    except Exception as exc:
        logger.warning("MLB batter year-by-year request failed for %s: %s", batter_id, exc)
        return [date.today().year]

    seasons = []
    current_year = date.today().year
    splits = data.get("stats", [{}])[0].get("splits", []) if data.get("stats") else []
    for split in splits:
        try:
            season = int(split.get("season"))
        except (TypeError, ValueError):
            continue
        if season <= current_year:
            seasons.append(season)

    return sorted(set(seasons))


@st.cache_data(ttl=86400, show_spinner=False)
def load_batter_prop_all_game_logs(batter_id, include_first_inning=False):
    seasons = load_batter_prop_game_log_seasons(batter_id)
    if not seasons:
        seasons = [date.today().year]

    frames = []
    for season in seasons:
        season_df = load_batter_prop_game_log(batter_id, season_year=season, include_first_inning=include_first_inning)
        if not season_df.empty:
            frames.append(season_df)

    if not frames:
        return pd.DataFrame()

    all_logs = pd.concat(frames, ignore_index=True).sort_values("game_date").reset_index(drop=True)
    if "game_pk" in all_logs.columns:
        has_game_pk = all_logs["game_pk"].astype(str).str.strip() != ""
        logs_with_game_pk = all_logs[has_game_pk].drop_duplicates(subset=["game_pk", "game_date"], keep="last")
        logs_without_game_pk = all_logs[~has_game_pk]
        all_logs = pd.concat([logs_without_game_pk, logs_with_game_pk], ignore_index=True)
        all_logs = all_logs.sort_values("game_date").reset_index(drop=True)
    return all_logs.reset_index(drop=True)


def normalize_game_pk(value):
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    if str(value).strip() == "":
        return ""
    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        return str(value).strip()


def savant_batter_detail_params(batter_id, start_date, end_date):
    return {
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


@st.cache_data(ttl=86400, show_spinner=False)
def load_batter_hit_details_by_game(batter_id, season_year):
    if not batter_id or not season_year:
        return {}

    try:
        season_year = int(season_year)
    except (TypeError, ValueError):
        return {}

    start_date = f"{season_year}-03-01"
    end_date = date.today().isoformat() if season_year == date.today().year else f"{season_year}-12-01"
    url = "https://baseballsavant.mlb.com/statcast_search/csv"
    params = savant_batter_detail_params(batter_id, start_date, end_date)

    try:
        response = requests.get(url, params=params, timeout=45)
    except Exception as exc:
        logger.warning("Batter hit detail fetch failed for batter_id=%s season=%s: %s", batter_id, season_year, exc)
        return {}

    if response.status_code != 200:
        logger.warning("Batter hit detail request failed for batter_id=%s season=%s status=%s", batter_id, season_year, response.status_code)
        return {}

    try:
        raw_df = pd.read_csv(io.StringIO(response.text), low_memory=False)
    except Exception as exc:
        logger.warning("Failed parsing batter hit detail CSV for batter_id=%s season=%s: %s", batter_id, season_year, exc)
        return {}

    required_columns = {"game_pk", "events", "pitcher"}
    if raw_df.empty or not required_columns.issubset(raw_df.columns):
        return {}

    working_df = raw_df.copy()
    if "game_year" in working_df.columns:
        working_df = working_df[pd.to_numeric(working_df["game_year"], errors="coerce") == season_year].copy()
    if working_df.empty:
        return {}

    working_df["_event_norm"] = working_df["events"].astype(str).str.lower().str.strip()
    hit_df = working_df[working_df["_event_norm"].isin(GAME_LOG_HIT_EVENT_LABELS)].copy()
    if hit_df.empty:
        return {}

    pitcher_ids = pd.to_numeric(hit_df["pitcher"], errors="coerce").dropna().astype(int).unique().tolist()
    pitcher_info = get_players_info(tuple(pitcher_ids)) if pitcher_ids else {}

    sort_columns = [column for column in ("game_date", "at_bat_number", "pitch_number") if column in hit_df.columns]
    if sort_columns:
        hit_df = hit_df.sort_values(sort_columns)

    details_by_game = {}
    for _, row in hit_df.iterrows():
        game_key = normalize_game_pk(row.get("game_pk"))
        if not game_key:
            continue

        event_label = GAME_LOG_HIT_EVENT_LABELS.get(str(row.get("_event_norm", "")).lower().strip())
        if not event_label:
            continue

        pitcher_id = row.get("pitcher")
        try:
            pitcher_id_int = int(float(pitcher_id))
        except (TypeError, ValueError):
            pitcher_id_int = None

        pitcher_record = pitcher_info.get(pitcher_id_int, {}) if pitcher_id_int is not None else {}
        pitcher_name = pitcher_record.get("fullName")
        if not pitcher_name and pitcher_id_int is not None:
            pitcher_name = f"Pitcher ID {pitcher_id_int}"
        if not pitcher_name:
            pitcher_name = "Unknown Pitcher"

        hand_code = normalize_hand_code(row.get("p_throws", "")) if "p_throws" in hit_df.columns else ""
        if not hand_code:
            hand_code = normalize_hand_code(pitcher_record.get("pitchHand", ""))
        hand_label = format_pitcher_hand(hand_code) if hand_code else "N/A"
        details_by_game.setdefault(game_key, []).append(f"{event_label} vs {pitcher_name} ({hand_label})")

    return details_by_game


@st.cache_data(ttl=86400, show_spinner=False)
def load_batter_hit_details_by_game_for_seasons(batter_id, seasons):
    details_by_game = {}
    for season in sorted({int(season) for season in seasons if season}):
        season_details = load_batter_hit_details_by_game(batter_id, season)
        for game_key, details in season_details.items():
            details_by_game.setdefault(game_key, []).extend(details)
    return details_by_game


@st.cache_data(ttl=86400, show_spinner=False)
def load_game_starting_pitchers(game_pk):
    game_key = normalize_game_pk(game_pk)
    if not game_key:
        return {}

    url = f"https://statsapi.mlb.com/api/v1.1/game/{game_key}/feed/live"
    try:
        data = requests.get(url, timeout=20).json()
    except Exception as exc:
        logger.warning("Game starter feed request failed for game_pk=%s: %s", game_key, exc)
        return {}

    boxscore = data.get("liveData", {}).get("boxscore", {}).get("teams", {})
    starters = {}
    starter_ids = []
    for side in ("away", "home"):
        team = boxscore.get(side, {}) or {}
        players = team.get("players", {}) or {}
        pitcher_ids = team.get("pitchers", []) or []
        starter_id = None
        starter_name = ""
        for pitcher_id in pitcher_ids:
            player = players.get(f"ID{pitcher_id}", {}) or {}
            pitching_stats = player.get("stats", {}).get("pitching", {}) or {}
            try:
                games_started = int(pitching_stats.get("gamesStarted", 0) or 0)
            except (TypeError, ValueError):
                games_started = 0
            if games_started > 0:
                starter_id = pitcher_id
                starter_name = player.get("person", {}).get("fullName", "")
                break

        if not starter_id:
            probable = data.get("gameData", {}).get("probablePitchers", {}).get(side, {}) or {}
            starter_id = probable.get("id")
            starter_name = probable.get("fullName", "")

        try:
            starter_id_int = int(starter_id) if starter_id else None
        except (TypeError, ValueError):
            starter_id_int = None
        if starter_id_int:
            starter_ids.append(starter_id_int)

        starters[side] = {
            "team_id": str(team.get("team", {}).get("id") or "").strip(),
            "team_name": team.get("team", {}).get("name", ""),
            "pitcher_id": starter_id_int,
            "pitcher_name": starter_name or "N/A",
            "pitcher_hand": "",
        }

    pitcher_info = get_players_info(tuple(starter_ids)) if starter_ids else {}
    for side, starter in starters.items():
        pitcher_id = starter.get("pitcher_id")
        if pitcher_id and pitcher_info.get(pitcher_id):
            starter["pitcher_name"] = pitcher_info[pitcher_id].get("fullName") or starter.get("pitcher_name") or "N/A"
            starter["pitcher_hand"] = format_pitcher_hand(normalize_hand_code(pitcher_info[pitcher_id].get("pitchHand", "")))
        if not starter.get("pitcher_name"):
            starter["pitcher_name"] = "N/A"

    return starters


def game_log_starting_pitcher_tooltips(row):
    starters = load_game_starting_pitchers(row.get("game_pk"))
    if not starters:
        return "N/A", "N/A"

    opponent_id = str(row.get("opponent_team_id") or "").strip()
    away_id = str(starters.get("away", {}).get("team_id") or "").strip()
    home_id = str(starters.get("home", {}).get("team_id") or "").strip()

    if opponent_id and opponent_id == away_id:
        opponent_side = "away"
        player_side = "home"
    elif opponent_id and opponent_id == home_id:
        opponent_side = "home"
        player_side = "away"
    else:
        opponent_prefix = str(row.get("opponent", "")).strip()
        opponent_side = "home" if opponent_prefix.startswith("@") else "away"
        player_side = "home" if opponent_side == "away" else "away"

    def _format_starter(side):
        starter = starters.get(side, {}) or {}
        name = starter.get("pitcher_name") or "N/A"
        hand = starter.get("pitcher_hand") or ""
        return f"{name} ({hand})" if name != "N/A" and hand else name

    return _format_starter(player_side), _format_starter(opponent_side)


def add_game_log_static_tooltip_columns(game_log_df, batter_id, enrich=False):
    if game_log_df.empty:
        return game_log_df.copy()

    enriched_df = game_log_df.copy()
    enriched_df["tooltip_date"] = enriched_df["game_date"].apply(game_log_full_date_label)
    enriched_df["tooltip_game"] = enriched_df.apply(game_log_matchup_tooltip, axis=1)
    if "hits" in enriched_df.columns:
        enriched_df["tooltip_hits"] = pd.to_numeric(enriched_df["hits"], errors="coerce").fillna(0).astype(int)
    else:
        enriched_df["tooltip_hits"] = 0

    if not enrich:
        enriched_df["tooltip_player_sp"] = "N/A"
        enriched_df["tooltip_opponent_sp"] = "N/A"
        enriched_df["tooltip_hit_details"] = enriched_df.apply(game_log_hit_details_tooltip, axis=1)
        return enriched_df

    starter_map = {}
    if "game_pk" in enriched_df.columns:
        for game_key in sorted({normalize_game_pk(value) for value in enriched_df["game_pk"]}):
            if game_key:
                starter_map[game_key] = load_game_starting_pitchers(game_key)

    def _starter_tooltips_from_map(row):
        game_key = normalize_game_pk(row.get("game_pk"))
        starters = starter_map.get(game_key, {})
        if not starters:
            return "N/A", "N/A"

        opponent_id = str(row.get("opponent_team_id") or "").strip()
        away_id = str(starters.get("away", {}).get("team_id") or "").strip()
        home_id = str(starters.get("home", {}).get("team_id") or "").strip()

        if opponent_id and opponent_id == away_id:
            opponent_side = "away"
            player_side = "home"
        elif opponent_id and opponent_id == home_id:
            opponent_side = "home"
            player_side = "away"
        else:
            opponent_prefix = str(row.get("opponent", "")).strip()
            opponent_side = "home" if opponent_prefix.startswith("@") else "away"
            player_side = "home" if opponent_side == "away" else "away"

        def _format_starter(side):
            starter = starters.get(side, {}) or {}
            name = starter.get("pitcher_name") or "N/A"
            hand = starter.get("pitcher_hand") or ""
            return f"{name} ({hand})" if name != "N/A" and hand else name

        return _format_starter(player_side), _format_starter(opponent_side)

    starter_tooltips = enriched_df.apply(_starter_tooltips_from_map, axis=1)
    enriched_df["tooltip_player_sp"] = starter_tooltips.apply(lambda value: value[0])
    enriched_df["tooltip_opponent_sp"] = starter_tooltips.apply(lambda value: value[1])

    rows_with_hits = enriched_df[enriched_df["tooltip_hits"] > 0]
    if rows_with_hits.empty:
        hit_details_by_game = {}
    else:
        if "season" in rows_with_hits.columns:
            hit_detail_seasons = pd.to_numeric(rows_with_hits["season"], errors="coerce").dropna().astype(int).unique().tolist()
        else:
            hit_detail_seasons = rows_with_hits["game_date"].dt.year.dropna().astype(int).unique().tolist()
        hit_details_by_game = load_batter_hit_details_by_game_for_seasons(batter_id, tuple(hit_detail_seasons))

    enriched_df["tooltip_hit_details"] = enriched_df.apply(
        lambda row: game_log_hit_details_tooltip(row, hit_details_by_game=hit_details_by_game),
        axis=1,
    )
    return enriched_df


def display_batter_metric_strike_zone_fixed(
    batter_id,
    pitch_type,
    pitcher_throws="All",
    metric="Pitch %",
    heatmap_scale=strike_zone.HEATMAP_SCALE_LEAGUE,
):
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
    if metric == "K%":
        zone_df, outer_stats, k_denominator = strike_zone._build_k_distribution_zone_outputs(filtered_df)
        if zone_df.empty:
            st.info("Strike zone data is unavailable for this batter right now.")
            return
    else:
        zone_df, outer_stats, shared_denominator = strike_zone._build_distribution_zone_outputs(filtered_df, metric)

    html = strike_zone._build_batter_metric_strike_zone_html(
        zone_df,
        outer_stats,
        metric=metric,
        heatmap_scale=heatmap_scale,
    )
    st.markdown(html, unsafe_allow_html=True)
    inner_percent_sum = float(zone_df["pitch_pct"].sum()) if "pitch_pct" in zone_df.columns else 0.0
    outer_percent_sum = sum(float(outer_stats[key]["pitch_pct"]) for key in ("tl", "tr", "bl", "br"))
    total_percent_sum = inner_percent_sum + outer_percent_sum
    if metric == "K%":
        st.caption(
            f"inner_sum={inner_percent_sum:.1f} "
            f"outer_sum={outer_percent_sum:.1f} "
            f"total_sum={total_percent_sum:.1f} "
            f"denominator_used={k_denominator}"
        )
    else:
        st.caption(
            f"inner_sum={inner_percent_sum:.1f} "
            f"outer_sum={outer_percent_sum:.1f} "
            f"total_sum={total_percent_sum:.1f} "
            f"inner_denominator={shared_denominator} "
            f"outer_denominator_used={shared_denominator}"
        )


strike_zone.display_batter_metric_strike_zone = display_batter_metric_strike_zone_fixed


def batter_heatmap_legend_html(heatmap_scale):
    colors = strike_zone.ZONE_Z_SCORE_BACKGROUND_COLORS
    if heatmap_scale == strike_zone.HEATMAP_SCALE_SELF:
        title = "HEATMAP KEY (Vs. Self)"
        rows = [
            ("blue", "Most frequent zones for this hitter"),
            ("green", "Above this hitter's normal zone frequency"),
            ("orange", "Below this hitter's normal zone frequency"),
            ("red", "Least frequent zones for this hitter"),
        ]
        note = "Compared only to this hitter's own 13-zone distribution."
    else:
        title = "HEATMAP KEY (Vs. League Average)"
        rows = [
            ("blue", "Elite / Much higher than league average"),
            ("green", "Above average"),
            ("orange", "Around average"),
            ("red", "Below average"),
        ]
        note = "Compared to qualified MLB hitters for the selected metric and zone."

    row_html = "".join(
        "<div style='display:flex; align-items:center; gap:7px; margin:3px 0;'>"
        f"<span style='display:inline-block; width:11px; height:11px; border:1px solid var(--dash-text); background:{colors[color_key]}; flex:0 0 auto;'></span>"
        f"<span>{label}</span>"
        "</div>"
        for color_key, label in rows
    )
    return (
        "<div style='border:1px solid var(--dash-control-border); border-radius:6px; padding:7px 8px; margin:8px 0 8px 0; "
        "font-size:11.5px; line-height:1.25; color:var(--dash-text); background:var(--dash-card-bg);'>"
        f"<div style='font-weight:800; font-size:11px; letter-spacing:0.02em; margin-bottom:5px;'>{title}</div>"
        f"{row_html}"
        f"<div style='font-size:10.5px; color:var(--dash-muted); margin-top:5px;'>{note}</div>"
        "</div>"
    )


def pitcher_heatmap_legend_html(heatmap_scale):
    colors = strike_zone.ZONE_Z_SCORE_BACKGROUND_COLORS
    if heatmap_scale == strike_zone.HEATMAP_SCALE_SELF:
        title = "HEATMAP KEY (Vs. Self)"
        rows = [
            ("blue", "Most frequent / highest zones for this pitcher"),
            ("green", "Above this pitcher's normal zone value"),
            ("orange", "Below this pitcher's normal zone value"),
            ("red", "Lowest zones for this pitcher"),
        ]
        note = "Compared only to this pitcher's own 13-zone distribution."
    else:
        title = "HEATMAP KEY (Vs. League Average)"
        rows = [
            ("blue", "Elite / Much higher than pitcher league average"),
            ("green", "Above average"),
            ("orange", "Around average"),
            ("red", "Below average"),
        ]
        note = "Compared to qualified MLB pitchers for the selected metric and zone."

    row_html = "".join(
        "<div style='display:flex; align-items:center; gap:7px; margin:3px 0;'>"
        f"<span style='display:inline-block; width:11px; height:11px; border:1px solid var(--dash-text); background:{colors[color_key]}; flex:0 0 auto;'></span>"
        f"<span>{label}</span>"
        "</div>"
        for color_key, label in rows
    )
    return (
        "<div style='border:1px solid var(--dash-control-border); border-radius:6px; padding:7px 8px; margin:8px 0 8px 0; "
        "font-size:11.5px; line-height:1.25; color:var(--dash-text); background:var(--dash-card-bg);'>"
        f"<div style='font-weight:800; font-size:11px; letter-spacing:0.02em; margin-bottom:5px;'>{title}</div>"
        f"{row_html}"
        f"<div style='font-size:10.5px; color:var(--dash-muted); margin-top:5px;'>{note}</div>"
        "</div>"
    )


def game_log_sample_dataframe(game_log_df, sample_label):
    if sample_label in {"L5", "L10", "L15"}:
        return game_log_df.tail(int(sample_label[1:])).copy()
    return game_log_df.copy()


def prop_hit_rate_summary_for_df(sample_df, prop_column, selected_prop_line, empty_hit_rate_text="--", empty_avg_text="--"):
    if sample_df.empty or prop_column not in sample_df.columns:
        return {
            "hit_rate_text": empty_hit_rate_text,
            "avg_text": empty_avg_text,
            "indicator": "",
            "games": 0,
        }

    values = pd.to_numeric(sample_df[prop_column], errors="coerce").dropna()
    if values.empty:
        return {
            "hit_rate_text": empty_hit_rate_text,
            "avg_text": empty_avg_text,
            "indicator": "",
            "games": 0,
        }

    hit_rate = float((values >= selected_prop_line).mean() * 100.0)
    avg_value = float(values.mean())
    if hit_rate >= 60:
        indicator = "🟢"
    elif hit_rate >= 45:
        indicator = "🟠"
    else:
        indicator = "🔴"

    return {
        "hit_rate_text": f"{hit_rate:.0f}%",
        "avg_text": f"{avg_value:.2f}",
        "indicator": indicator,
        "games": int(len(values)),
    }


def prop_hit_rate_sample_summary(game_log_df, prop_column, selected_prop_line, sample_label, opponent_context=None):
    sample_df = game_log_sample_dataframe(game_log_df, sample_label)
    if opponent_context:
        sample_df = filter_game_logs_vs_opponent(sample_df, opponent_context)
    return prop_hit_rate_summary_for_df(sample_df, prop_column, selected_prop_line)


def prop_h2h_summary(game_log_df, prop_column, selected_prop_line, opponent_context):
    h2h_df = filter_game_logs_vs_opponent(game_log_df, opponent_context)
    return prop_hit_rate_summary_for_df(h2h_df, prop_column, selected_prop_line, empty_hit_rate_text="N/A", empty_avg_text="—")


def strip_game_log_opponent_prefix(value):
    return str(value or "").strip().lstrip("@").strip()


def filter_game_logs_vs_opponent(game_log_df, opponent_context):
    if game_log_df.empty or not opponent_context:
        return game_log_df.iloc[0:0].copy()

    opponent_id = str(opponent_context.get("id") or "").strip()
    if opponent_id and "opponent_team_id" in game_log_df.columns:
        opponent_ids = game_log_df["opponent_team_id"].astype(str).str.strip()
        return game_log_df[opponent_ids == opponent_id].copy()

    opponent_keys = {
        normalize_name(opponent_context.get("name", "")),
        normalize_name(opponent_context.get("abbr", "")),
    }
    opponent_keys.discard("")
    if not opponent_keys:
        return game_log_df.iloc[0:0].copy()

    candidate_columns = [column for column in ("opponent_name", "opponent_abbrev", "opponent") if column in game_log_df.columns]
    if not candidate_columns:
        return game_log_df.iloc[0:0].copy()

    mask = pd.Series(False, index=game_log_df.index)
    for column in candidate_columns:
        normalized_values = game_log_df[column].apply(lambda value: normalize_name(strip_game_log_opponent_prefix(value)))
        mask = mask | normalized_values.isin(opponent_keys)
    return game_log_df[mask].copy()


def prop_hit_rate_sample_summaries(game_log_df, prop_column, selected_prop_line, opponent_context=None):
    return {
        sample_label: prop_hit_rate_sample_summary(
            game_log_df,
            prop_column,
            selected_prop_line,
            sample_label,
            opponent_context=opponent_context,
        )
        for sample_label in GAME_LOG_SAMPLE_RANGES
    }


def prop_hit_rate_sample_label(sample_label, summaries):
    summary = summaries.get(sample_label, {})
    indicator = summary.get("indicator", "")
    hit_rate_text = summary.get("hit_rate_text", "--")
    avg_text = summary.get("avg_text", "--")
    hr_prefix = f"{indicator} HR" if indicator else "HR"
    return f"**{sample_label}**\n{hr_prefix} {hit_rate_text}\nAvg {avg_text}"


def prop_h2h_tile_label(summary):
    if not summary or summary.get("games", 0) <= 0:
        return "**H2H**\nN/A\nAvg —"
    indicator = summary.get("indicator", "")
    hit_rate_text = summary.get("hit_rate_text", "N/A")
    avg_text = summary.get("avg_text", "—")
    hr_prefix = f"{indicator} HR" if indicator else "HR"
    return f"**H2H**\n{hr_prefix} {hit_rate_text}\nAvg {avg_text}"


def set_selected_prop(prop):
    if prop in GAME_LOG_PROPS:
        st.session_state["selected_prop"] = prop
        sb = st.session_state.get("selected_batter", {}) or {}
        prop_column = GAME_LOG_PROP_COLUMNS.get(prop)
        line_value = ""
        if prop_column and sb.get("id"):
            line_key = f"batter_{prop_column}_line_{sb.get('id')}"
            if line_key not in st.session_state:
                st.session_state[line_key] = 0.5
            line_value = st.session_state.get(line_key, 0.5)
        _sync_batter_detail_query({"prop": prop, "line": line_value})


def adjust_game_log_line_value(line_key, delta):
    current_value = st.session_state.get(line_key, 0.5)
    try:
        current_value = float(current_value)
    except (TypeError, ValueError):
        current_value = 0.5
    st.session_state[line_key] = max(0.5, current_value + float(delta))
    _sync_batter_detail_query({
        "prop": st.session_state.get("selected_prop", "Hits"),
        "line": st.session_state[line_key],
    })


def set_game_log_line_value(line_key, value):
    try:
        st.session_state[line_key] = float(value)
        _sync_batter_detail_query({
            "prop": st.session_state.get("selected_prop", "Hits"),
            "line": st.session_state[line_key],
        })
    except (TypeError, ValueError):
        pass


def game_log_chart_axis_label(row, h2h_active=False, current_season=2026):
    game_date = row["game_date"]
    if h2h_active and int(game_date.year) < int(current_season):
        date_label = game_date.strftime("%m/%d/%y")
    elif h2h_active:
        date_label = game_date.strftime("%m/%d")
    else:
        date_label = f"{game_date.month}/{game_date.day}"
    opponent_label = row["opponent"] if row["opponent"] else ""
    return f"{date_label}\n{opponent_label}"


def game_log_full_date_label(game_date):
    return f"{game_date.strftime('%B')} {game_date.day}, {game_date.year}"


def game_log_matchup_tooltip(row):
    opponent_display = row.get("opponent_name") or strip_game_log_opponent_prefix(row.get("opponent", ""))
    if not opponent_display:
        opponent_display = "N/A"
    prefix = "@" if str(row.get("opponent", "")).strip().startswith("@") else "vs"
    return f"{prefix} {opponent_display}"


def game_log_hit_details_tooltip(row, hit_details_by_game=None):
    try:
        hits = int(row.get("hits", 0) or 0)
    except (TypeError, ValueError):
        hits = 0
    if hits <= 0:
        return "No hits recorded."
    game_key = normalize_game_pk(row.get("game_pk"))
    hit_details = (hit_details_by_game or {}).get(game_key, [])
    if hit_details:
        return "\n".join(hit_details)
    return "Hit event detail unavailable."


def selected_batter_opponent_context(sb, game_pk, lineup_context, lineup_side):
    context = {
        "id": str(sb.get("opponent_id") or "").strip(),
        "name": str(sb.get("opponent") or "").strip(),
        "abbr": "",
    }

    if lineup_side in {"away", "home"}:
        opponent_side = "home" if lineup_side == "away" else "away"
        context["id"] = context["id"] or str(lineup_context.get(f"{opponent_side}_team_id") or "").strip()
        context["name"] = context["name"] or str(lineup_context.get(f"{opponent_side}_team") or "").strip()
        context["abbr"] = str(lineup_context.get(f"{opponent_side}_abbrev") or "").strip()

    if context["id"] or context["name"]:
        return context

    if not game_pk:
        return context

    try:
        schedule_df = load_schedule(date.today())
    except Exception as exc:
        logger.warning("Unable to resolve H2H opponent from schedule for game_pk=%s: %s", game_pk, exc)
        return context

    if schedule_df.empty or "game_pk" not in schedule_df.columns:
        return context

    game_match = schedule_df[schedule_df["game_pk"].astype(str) == str(game_pk)]
    if game_match.empty:
        return context

    game = game_match.iloc[0].to_dict()
    batter_team_key = normalize_name(sb.get("team", ""))
    if batter_team_key and normalize_name(game.get("away_team", "")) == batter_team_key:
        return {
            "id": str(game.get("home_team_id") or "").strip(),
            "name": str(game.get("home_team") or "").strip(),
            "abbr": str(game.get("home_abbrev") or "").strip(),
        }
    if batter_team_key and normalize_name(game.get("home_team", "")) == batter_team_key:
        return {
            "id": str(game.get("away_team_id") or "").strip(),
            "name": str(game.get("away_team") or "").strip(),
            "abbr": str(game.get("away_abbrev") or "").strip(),
        }

    if sb.get("return_pitcher_side") == "away":
        return {
            "id": str(game.get("away_team_id") or "").strip(),
            "name": str(game.get("away_team") or "").strip(),
            "abbr": str(game.get("away_abbrev") or "").strip(),
        }
    if sb.get("return_pitcher_side") == "home":
        return {
            "id": str(game.get("home_team_id") or "").strip(),
            "name": str(game.get("home_team") or "").strip(),
            "abbr": str(game.get("home_abbrev") or "").strip(),
        }

    return context


def set_game_log_range_selection(range_key, h2h_key, sample_label):
    h2h_enabled = bool(st.session_state.get(h2h_key, False))
    if h2h_enabled and st.session_state.get(range_key) == sample_label:
        st.session_state[range_key] = None
    else:
        st.session_state[range_key] = sample_label
    _sync_batter_detail_query({
        "prop": st.session_state.get("selected_prop", "Hits"),
        "sample": st.session_state.get(range_key, "") or "",
        "h2h": "1" if st.session_state.get(h2h_key, False) else "",
    })


def toggle_game_log_h2h_selection(h2h_key, range_key):
    h2h_enabled = bool(st.session_state.get(h2h_key, False))
    st.session_state[h2h_key] = not h2h_enabled
    if h2h_enabled:
        if st.session_state.get(range_key) not in GAME_LOG_SAMPLE_RANGES:
            st.session_state[range_key] = "L10"
    else:
        st.session_state[range_key] = None
    _sync_batter_detail_query({
        "prop": st.session_state.get("selected_prop", "Hits"),
        "sample": st.session_state.get(range_key, "") or "",
        "h2h": "1" if st.session_state.get(h2h_key, False) else "",
    })


def render_batter_game_log_sample_section(batter_id, prop_column, selected_prop, selected_prop_line, current_opponent_context):
    include_first_inning = prop_column == "first_inning_hrrrbi"
    game_log_df = load_batter_prop_game_log(batter_id, include_first_inning=include_first_inning)
    range_key = f"batter_game_log_range_{batter_id}"
    h2h_key = f"batter_game_log_h2h_{batter_id}"
    tooltip_ready_key = f"batter_game_log_tooltip_ready_{batter_id}"
    requested_sample = _query_param_value("sample", "")
    if requested_sample in GAME_LOG_SAMPLE_RANGES:
        st.session_state[range_key] = requested_sample
    requested_h2h = _query_param_value("h2h", "")
    if str(requested_h2h).lower() in {"1", "true", "yes", "on"}:
        st.session_state[h2h_key] = True
    h2h_enabled = bool(st.session_state.get(h2h_key, False))
    if st.session_state.get(range_key) not in GAME_LOG_SAMPLE_RANGES and not h2h_enabled:
        st.session_state[range_key] = "L10"
    elif st.session_state.get(range_key) not in GAME_LOG_SAMPLE_RANGES:
        st.session_state[range_key] = None

    has_opponent_context = bool(current_opponent_context.get("id") or current_opponent_context.get("name"))
    summary_opponent_context = current_opponent_context if h2h_enabled else None
    sample_summaries = prop_hit_rate_sample_summaries(
        game_log_df,
        prop_column,
        selected_prop_line,
        opponent_context=summary_opponent_context,
    )
    active_sample_label = st.session_state.get(range_key)
    if h2h_enabled and active_sample_label in GAME_LOG_SAMPLE_RANGES:
        h2h_tile_df = filter_game_logs_vs_opponent(
            game_log_sample_dataframe(game_log_df, active_sample_label),
            current_opponent_context,
        )
    elif h2h_enabled:
        all_game_log_df = load_batter_prop_all_game_logs(batter_id, include_first_inning=include_first_inning) if has_opponent_context else pd.DataFrame()
        h2h_tile_df = filter_game_logs_vs_opponent(all_game_log_df, current_opponent_context) if has_opponent_context else pd.DataFrame()
    else:
        h2h_tile_df = filter_game_logs_vs_opponent(game_log_df, current_opponent_context) if has_opponent_context else pd.DataFrame()
    h2h_summary = prop_hit_rate_summary_for_df(
        h2h_tile_df,
        prop_column,
        selected_prop_line,
        empty_hit_rate_text="N/A",
        empty_avg_text="—",
    )
    st.markdown("<div class='prop-control-spacer'></div>", unsafe_allow_html=True)
    with st.container(key="game_log_range_tiles", horizontal=True, gap="small"):
        for sample_label in GAME_LOG_SAMPLE_RANGES:
            is_selected_sample = sample_label == st.session_state[range_key]
            st.button(
                prop_hit_rate_sample_label(sample_label, sample_summaries),
                key=f"{range_key}_{sample_label}",
                type="primary" if is_selected_sample else "secondary",
                on_click=set_game_log_range_selection,
                args=(range_key, h2h_key, sample_label),
            )
        st.button(
            prop_h2h_tile_label(h2h_summary),
            key=f"{h2h_key}_tile",
            type="primary" if h2h_enabled else "secondary",
            on_click=toggle_game_log_h2h_selection,
            args=(h2h_key, range_key),
        )
    game_log_range = st.session_state[range_key]
    if h2h_enabled:
        if game_log_range in GAME_LOG_SAMPLE_RANGES:
            display_log_df = filter_game_logs_vs_opponent(
                game_log_sample_dataframe(game_log_df, game_log_range),
                current_opponent_context,
            )
        else:
            all_game_log_df = load_batter_prop_all_game_logs(batter_id, include_first_inning=include_first_inning) if has_opponent_context else pd.DataFrame()
            display_log_df = filter_game_logs_vs_opponent(all_game_log_df, current_opponent_context) if has_opponent_context else pd.DataFrame()
    else:
        display_log_df = game_log_sample_dataframe(game_log_df, game_log_range)

    if display_log_df.empty:
        if h2h_enabled:
            st.info("No previous games vs today's opponent.")
        else:
            st.info("Game log data is unavailable for this batter right now.")
        return

    tooltip_enrichment_allowed = bool(st.session_state.get(tooltip_ready_key, False))
    should_enrich_tooltips = tooltip_enrichment_allowed and (
        h2h_enabled or game_log_range in {"L5", "L10", "L15"}
    )
    display_log_df = add_game_log_static_tooltip_columns(
        display_log_df,
        batter_id,
        enrich=should_enrich_tooltips,
    )
    st.session_state[tooltip_ready_key] = True

    display_log_df["prop_value"] = pd.to_numeric(display_log_df[prop_column], errors="coerce").fillna(0)
    display_log_df["result_color"] = display_log_df["prop_value"].apply(
        lambda value: "#16a34a" if value >= selected_prop_line else "#dc2626"
    )
    display_log_df["bar_value"] = display_log_df["prop_value"].apply(lambda value: 0.12 if value == 0 else value)
    display_log_df["label_y"] = display_log_df["bar_value"].apply(lambda value: value + 0.22)
    display_log_df["chart_label"] = display_log_df.apply(
        lambda row: game_log_chart_axis_label(row, h2h_active=h2h_enabled),
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
                alt.Tooltip("tooltip_date:N", title="Full Date"),
                alt.Tooltip("tooltip_game:N", title="Game"),
                alt.Tooltip("tooltip_player_sp:N", title="Player Team SP"),
                alt.Tooltip("tooltip_opponent_sp:N", title="Opponent SP"),
                alt.Tooltip("tooltip_hits:Q", title="Hits", format=".0f"),
                alt.Tooltip("tooltip_hit_details:N", title="Hit Details"),
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


@st.fragment
def render_batter_prop_game_log_section(batter_id, batter_name, current_opponent_context):
    if st.session_state.get("selected_prop") not in GAME_LOG_PROPS:
        st.session_state["selected_prop"] = "Hits"

    selected_prop = st.session_state.get("selected_prop", "Hits")
    with st.container(key="prop_tab_row", horizontal=True, gap="small"):
        for prop in GAME_LOG_PROPS:
            prop_key = GAME_LOG_PROP_COLUMNS[prop].replace("_", "-")
            st.button(
                prop,
                key=f"batter_prop_tab_{batter_id}_{prop_key}",
                type="primary" if prop == selected_prop else "secondary",
                on_click=set_selected_prop,
                args=(prop,),
            )

    selected_prop = st.session_state.get("selected_prop", "Hits")
    if selected_prop not in GAME_LOG_PROPS:
        selected_prop = "Hits"

    prop_column = GAME_LOG_PROP_COLUMNS[selected_prop]
    prop_slug = prop_column.replace("_", "-")
    include_first_inning = prop_column == "first_inning_hrrrbi"
    game_log_df = load_batter_prop_game_log(batter_id, include_first_inning=include_first_inning)
    if prop_column not in game_log_df.columns:
        st.info("Data unavailable for this prop.")
        return

    line_key = f"batter_{prop_column}_line_{batter_id}"
    if line_key not in st.session_state:
        st.session_state[line_key] = 0.5
    requested_line_value = _query_param_value("line", "")
    if requested_line_value not in {"", None}:
        try:
            st.session_state[line_key] = float(requested_line_value)
        except (TypeError, ValueError):
            pass
    _ensure_query_params(_selected_batter_query_params({
        "prop": selected_prop,
        "line": st.session_state[line_key],
    }))

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
    has_exact_prizepicks_line = isinstance(selected_projection_line, dict)

    st.markdown("<div class='prop-control-spacer'></div>", unsafe_allow_html=True)
    line_cols = st.columns([0.34, 1.65, 0.34, 4.2])
    with line_cols[0]:
        st.button(
            "-",
            key=f"batter_{prop_slug}_line_minus_{batter_id}",
            on_click=adjust_game_log_line_value,
            args=(line_key, -1.0),
        )
    with line_cols[1]:
        selected_odds_type = (
            _projection_value(selected_projection_line, "odds_type", "oddsType", default="")
            if has_exact_prizepicks_line
            else ""
        )
        st.markdown(
            f"<div class='line-badge-wrap'>{render_line_badge(st.session_state[line_key], selected_odds_type, show_book_badge=has_exact_prizepicks_line)}</div>",
            unsafe_allow_html=True,
        )
    with line_cols[2]:
        st.button(
            "+",
            key=f"batter_{prop_slug}_line_plus_{batter_id}",
            on_click=adjust_game_log_line_value,
            args=(line_key, 1.0),
        )

    if projection_lines:
        with st.expander("Alt lines", expanded=False):
            for idx, projection_line in enumerate(projection_lines):
                projection_line_value = _projection_line_value(projection_line)
                projection_odds_type = _projection_value(projection_line, "odds_type", "oddsType", default="")
                st.markdown(
                    f"<div class='alt-line-row'>{render_line_badge(projection_line_value, projection_odds_type)}</div>",
                    unsafe_allow_html=True,
                )
                st.button(
                    "Use",
                    key=f"batter_{prop_slug}_alt_line_{batter_id}_{idx}",
                    on_click=set_game_log_line_value,
                    args=(line_key, projection_line_value),
                )

    selected_prop_line = float(st.session_state[line_key])
    render_batter_game_log_sample_section(
        batter_id,
        prop_column,
        selected_prop,
        selected_prop_line,
        current_opponent_context,
    )


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


def _set_query_params(params):
    cleaned = {str(key): str(value) for key, value in params.items() if value not in {None, ""}}
    try:
        st.query_params.clear()
        for key, value in cleaned.items():
            st.query_params[key] = value
    except Exception as exc:
        logger.debug("Unable to update query params: %s", exc)


def _query_params_need_update(params):
    try:
        current = st.query_params
        for key, value in params.items():
            if value in {None, ""}:
                continue
            current_value = current.get(str(key), "")
            if isinstance(current_value, list):
                current_value = current_value[0] if current_value else ""
            if str(current_value) != str(value):
                return True
    except Exception:
        return False
    return False


def _ensure_query_params(params):
    if _query_params_need_update(params):
        _set_query_params(params)


def _selected_batter_query_params(extra=None):
    sb = st.session_state.get("selected_batter", {}) or {}
    if not sb.get("id"):
        return {}
    params = {
        "view": "batter_detail",
        "batter_id": sb.get("id", ""),
        "batter_name": sb.get("name", ""),
        "batter_hand": sb.get("hand", ""),
        "team": sb.get("team", ""),
        "team_id": sb.get("team_id", ""),
        "opponent": sb.get("opponent", ""),
        "opponent_id": sb.get("opponent_id", ""),
        "return_pitcher_id": sb.get("return_pitcher_id", ""),
        "return_game_pk": sb.get("return_game_pk", ""),
        "return_pitcher_side": sb.get("return_pitcher_side", ""),
        "return_pitcher_name": sb.get("return_pitcher_name", ""),
        "return_pitcher_hand": sb.get("return_pitcher_hand", ""),
        "date": st.session_state.get("selected_date", eastern_today()).isoformat(),
    }
    selected_prop = st.session_state.get("selected_prop", "")
    if selected_prop in GAME_LOG_PROPS:
        params["prop"] = selected_prop
        prop_column = GAME_LOG_PROP_COLUMNS.get(selected_prop)
        if prop_column:
            line_key = f"batter_{prop_column}_line_{sb.get('id')}"
            if line_key in st.session_state:
                params["line"] = st.session_state.get(line_key)
    range_key = f"batter_game_log_range_{sb.get('id')}"
    h2h_key = f"batter_game_log_h2h_{sb.get('id')}"
    if st.session_state.get(range_key):
        params["sample"] = st.session_state.get(range_key)
    if st.session_state.get(h2h_key):
        params["h2h"] = "1"
    if extra:
        params.update(extra)
    return params


def _sync_batter_detail_query(extra=None):
    params = _selected_batter_query_params(extra=extra)
    if params:
        _set_query_params(params)


def _set_pitcher_detail_query(pitcher, game_pk):
    if not pitcher or not game_pk:
        return
    _set_query_params({
        "view": "pitcher_detail",
        "pitcher_id": pitcher.get("id", ""),
        "pitcher_name": pitcher.get("name", ""),
        "pitcher_hand": pitcher.get("hand", ""),
        "pitcher_side": pitcher.get("side", ""),
        "game_pk": game_pk,
        "date": st.session_state.get("selected_date", eastern_today()).isoformat(),
    })


def _build_batter_detail_href(
    batter_id,
    batter_name="",
    batter_hand="",
    team="",
    team_id="",
    opponent="",
    opponent_id="",
    return_pitcher_id="",
    return_game_pk="",
    return_pitcher_side="",
    return_pitcher_name="",
    return_pitcher_hand="",
    prop="",
    line="",
    sample="",
    h2h="",
):
    params = [("view", "batter_detail"), ("batter_id", str(batter_id))]
    if batter_name:
        params.append(("batter_name", str(batter_name)))
    if batter_hand:
        params.append(("batter_hand", str(batter_hand)))
    if team:
        params.append(("team", str(team)))
    if team_id:
        params.append(("team_id", str(team_id)))
    if opponent:
        params.append(("opponent", str(opponent)))
    if opponent_id:
        params.append(("opponent_id", str(opponent_id)))
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
    selected_date_value = st.session_state.get("selected_date")
    if selected_date_value:
        params.append(("date", selected_date_value.isoformat()))
    if prop:
        params.append(("prop", str(prop)))
    if line not in {None, ""}:
        params.append(("line", str(line)))
    if sample:
        params.append(("sample", str(sample)))
    if h2h:
        params.append(("h2h", str(h2h)))
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


def calculate_batter_overall_contact_stats(working_df):
    if working_df.empty:
        return {}
    if {"game_pk", "at_bat_number"}.issubset(working_df.columns):
        working_df["_pa_key"] = (
            working_df["game_pk"].astype(str)
            + "_"
            + pd.to_numeric(working_df["at_bat_number"], errors="coerce").fillna(-1).astype(int).astype(str)
        )
    else:
        working_df["_pa_key"] = working_df.index.astype(str)

    event_series = working_df["events"].astype(str).str.lower() if "events" in working_df.columns else pd.Series("", index=working_df.index)
    desc_series = working_df["description"].astype(str).str.lower() if "description" in working_df.columns else pd.Series("", index=working_df.index)

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

    pa = int(working_df["_pa_key"].nunique())
    ab = int(event_series.isin(ab_events).sum())
    hits = int(event_series.isin(hit_values.keys()).sum())
    total_bases = int(event_series.map(hit_values).fillna(0).sum())
    swings = int(desc_series.isin(swing_descriptions).sum())
    whiffs = int(desc_series.isin(whiff_descriptions).sum())
    strikeouts = int((event_series == "strikeout").sum())

    woba_values = pd.to_numeric(working_df.get("woba_value"), errors="coerce") if "woba_value" in working_df.columns else pd.Series(dtype=float)
    woba_denom = pd.to_numeric(working_df.get("woba_denom"), errors="coerce") if "woba_denom" in working_df.columns else pd.Series(dtype=float)
    denom_sum = float(woba_denom.fillna(0).sum()) if not woba_denom.empty else 0.0

    return {
        "BA": (hits / ab) if ab else None,
        "SLG": (total_bases / ab) if ab else None,
        "wOBA": (float(woba_values.fillna(0).sum()) / denom_sum) if denom_sum > 0 else None,
        "Whiff%": (float(whiffs) / float(swings) * 100.0) if swings else None,
        "K%": (float(strikeouts) / float(pa) * 100.0) if pa else None,
    }


@st.cache_data(ttl=1800, show_spinner=False)
def load_savant_batter_season_summary_stats(season_year):
    url = "https://baseballsavant.mlb.com/leaderboard/custom"
    params = {
        "year": str(season_year),
        "type": "batter",
        "min": "0",
    }
    fetch_start = time.perf_counter()
    try:
        response = requests.get(url, params=params, timeout=45)
    except Exception as exc:
        logger.warning("Savant batter summary fetch failed for season=%s: %s", season_year, exc)
        return {}

    if response.status_code != 200:
        logger.warning("Savant batter summary request failed for season=%s status=%s", season_year, response.status_code)
        return {}

    text = response.text
    marker = "var data = "
    idx = text.find(marker)
    if idx == -1:
        logger.warning("Savant batter summary data marker missing for season=%s", season_year)
        return {}

    start = text.find("[", idx)
    if start == -1:
        return {}

    depth = 0
    end = None
    for pos, char in enumerate(text[start:], start=start):
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                end = pos + 1
                break
    if end is None:
        return {}

    try:
        rows = json.loads(text[start:end])
    except Exception as exc:
        logger.warning("Failed parsing Savant batter summary for season=%s: %s", season_year, exc)
        return {}

    def _summary_number(value):
        try:
            if value in {None, ""}:
                return None
            return float(str(value).replace("%", ""))
        except (TypeError, ValueError):
            return None

    stats_by_batter = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            batter_key = str(int(float(row.get("player_id"))))
        except (TypeError, ValueError):
            continue
        stats_by_batter[batter_key] = {
            "BA": _summary_number(row.get("batting_avg")),
            "SLG": _summary_number(row.get("slg_percent")),
            "wOBA": _summary_number(row.get("woba")),
            "Whiff%": _summary_number(row.get("whiff_percent")),
            "K%": _summary_number(row.get("k_percent")),
        }

    logger.debug(
        "Savant batter summary loaded %s batters in %.2fs",
        len(stats_by_batter),
        time.perf_counter() - fetch_start,
    )
    return stats_by_batter


@st.cache_data(ttl=1800, show_spinner=False)
def load_batter_overall_contact_stats_for_lineup(batter_ids):
    sanitized_ids = []
    for batter_id in batter_ids or ():
        try:
            sanitized_ids.append(int(float(batter_id)))
        except (TypeError, ValueError):
            continue
    sanitized_ids = tuple(sorted(set(sanitized_ids)))
    if not sanitized_ids:
        return {}

    season_year = 2026
    all_stats = load_savant_batter_season_summary_stats(season_year)
    return {
        str(batter_id): all_stats.get(str(batter_id), {})
        for batter_id in sanitized_ids
        if all_stats.get(str(batter_id))
    }


def load_batter_overall_contact_stats(batter_id):
    try:
        batter_key = str(int(float(batter_id)))
    except (TypeError, ValueError):
        return {}
    return load_batter_overall_contact_stats_for_lineup((batter_key,)).get(batter_key, {})


requested_view = _query_param_value("view")
requested_batter_id = _query_param_value("batter_id")
if requested_view == "batter_detail" and requested_batter_id:
    st.session_state["selected_batter"] = {
        "name": _query_param_value("batter_name", "Batter Detail"),
        "id": requested_batter_id,
        "hand": _query_param_value("batter_hand", ""),
        "team": _query_param_value("team", ""),
        "team_id": _query_param_value("team_id", ""),
        "opponent": _query_param_value("opponent", ""),
        "opponent_id": _query_param_value("opponent_id", ""),
        "return_pitcher_id": _query_param_value("return_pitcher_id", ""),
        "return_game_pk": _query_param_value("return_game_pk", ""),
        "return_pitcher_side": _query_param_value("return_pitcher_side", ""),
        "return_pitcher_name": _query_param_value("return_pitcher_name", ""),
        "return_pitcher_hand": _query_param_value("return_pitcher_hand", ""),
    }
    requested_prop = _query_param_value("prop", "")
    if requested_prop in GAME_LOG_PROPS:
        st.session_state["selected_prop"] = requested_prop

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

requested_date_value = _query_param_value("date", "")
requested_date = pd.to_datetime(requested_date_value, errors="coerce") if requested_date_value else pd.NaT
if "selected_date" not in st.session_state:
    st.session_state["selected_date"] = requested_date.date() if pd.notna(requested_date) else eastern_today()
elif pd.notna(requested_date) and st.session_state.get("selected_date") != requested_date.date():
    st.session_state["selected_date"] = requested_date.date()
    st.session_state.pop("games", None)
if "calendar_date" not in st.session_state:
    st.session_state["calendar_date"] = st.session_state["selected_date"]
elif pd.notna(requested_date) and st.session_state.get("calendar_date") != requested_date.date():
    st.session_state["calendar_date"] = requested_date.date()


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
            "fullName": person.get("fullName", ""),
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
            "away_team_id": game.get("away_team_id", "") if game is not None else "",
            "home_team_id": game.get("home_team_id", "") if game is not None else "",
            "away_abbrev": game.get("away_abbrev", "") if game is not None else "",
            "home_abbrev": game.get("home_abbrev", "") if game is not None else "",
        }
    return lineups_by_game.get(game_key, {})


def lineup_status_html(lineup):
    if not lineup:
        return ""
    if any(player.get("is_projected") for player in lineup):
        return "<div style='margin:0 0 8px 0; padding:6px 8px; border:1px solid #dc2626; border-radius:6px; background:#fef2f2; color:#b91c1c; font-weight:800;'>⚠ Projected lineup — not confirmed</div>"
    return "<div style='margin:0 0 8px 0; padding:6px 8px; border:1px solid #16a34a; border-radius:6px; background:#f0fdf4; color:#15803d; font-weight:800;'>🟢 Confirmed MLB Lineup</div>"


def render_lineup_table(lineup, current_batter_id="", current_batter_name="", link_context=None, load_stats=True):
    if not lineup:
        return "<div style='font-size:13px; color:#92400e; font-weight:700;'>Lineup not available.</div>"

    def _format_lineup_decimal(value):
        try:
            if value is None or pd.isna(value):
                return "—"
            return f"{float(value):.3f}"
        except (TypeError, ValueError):
            return "—"

    def _format_lineup_pct(value):
        try:
            if value is None or pd.isna(value):
                return "—"
            return f"{float(value):.1f}%"
        except (TypeError, ValueError):
            return "—"

    grid_columns = "44px minmax(170px,1fr) 54px 54px 58px 58px 62px 68px 58px"
    current_name_key = normalize_name(current_batter_name)
    stats_by_player = {}
    if load_stats:
        lineup_player_ids = []
        for player in lineup:
            try:
                lineup_player_ids.append(int(float(player.get("player_id"))))
            except (TypeError, ValueError):
                continue
        stats_key = tuple(sorted(set(lineup_player_ids)))
        stats_by_player = load_batter_overall_contact_stats_for_lineup(stats_key)
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
                team_id=link_context.get("team_id", ""),
                opponent=link_context.get("opponent", ""),
                opponent_id=link_context.get("opponent_id", ""),
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

        try:
            player_stats_key = str(int(float(player_id)))
        except (TypeError, ValueError):
            player_stats_key = ""
        lineup_stats = stats_by_player.get(player_stats_key, {})
        rows.append(
            f"<div style='min-width:690px; display:grid; grid-template-columns:{grid_columns}; align-items:center; border-top:1px solid #e5e7eb; "
            f"{row_style}'>"
            f"<div style='padding:6px 10px;'>{player.get('number', '')}</div>"
            f"<div style='padding:6px 10px;'>{batter_cell_html}</div>"
            f"<div style='padding:6px 10px;'>{html.escape(str(player.get('handedness', '')))}</div>"
            f"<div style='padding:6px 10px;'>{html.escape(str(player.get('position', '')))}</div>"
            f"<div style='padding:6px 8px; text-align:right;'>{_format_lineup_decimal(lineup_stats.get('BA'))}</div>"
            f"<div style='padding:6px 8px; text-align:right;'>{_format_lineup_decimal(lineup_stats.get('SLG'))}</div>"
            f"<div style='padding:6px 8px; text-align:right;'>{_format_lineup_decimal(lineup_stats.get('wOBA'))}</div>"
            f"<div style='padding:6px 8px; text-align:right;'>{_format_lineup_pct(lineup_stats.get('Whiff%'))}</div>"
            f"<div style='padding:6px 8px; text-align:right;'>{_format_lineup_pct(lineup_stats.get('K%'))}</div>"
            "</div>"
        )

    return (
        f"{lineup_status_html(lineup)}"
        "<div style='overflow-x:auto; width:100%;'>"
        f"<div style='min-width:690px; display:grid; grid-template-columns:{grid_columns}; align-items:end; font-size:12px; color:#6b7280; font-weight:700;'>"
        "<div style='padding:0 10px 6px 10px;'>#</div>"
        "<div style='padding:0 10px 6px 10px;'>Batter</div>"
        "<div style='padding:0 10px 6px 10px;'>Hand</div>"
        "<div style='padding:0 10px 6px 10px;'>Pos</div>"
        "<div style='padding:0 8px 6px 8px; text-align:right;'>BA</div>"
        "<div style='padding:0 8px 6px 8px; text-align:right;'>SLG</div>"
        "<div style='padding:0 8px 6px 8px; text-align:right;'>wOBA</div>"
        "<div style='padding:0 8px 6px 8px; text-align:right;'>Whiff%</div>"
        "<div style='padding:0 8px 6px 8px; text-align:right;'>K%</div>"
        "</div>"
        f"{''.join(rows)}"
        "</div>"
    )


if st.session_state.get("selected_batter"):
    sb = st.session_state.get("selected_batter", {})
    has_return_pitcher = bool(sb.get("return_pitcher_id") and sb.get("return_game_pk"))
    back_label = "← Back to Pitcher" if has_return_pitcher else "← Back to Slate"
    if st.button(back_label):
        st.session_state.pop("selected_batter", None)
        if has_return_pitcher:
            _set_query_params({
                "view": "pitcher_detail",
                "pitcher_id": sb.get("return_pitcher_id", ""),
                "game_pk": sb.get("return_game_pk", ""),
                "pitcher_side": sb.get("return_pitcher_side", ""),
                "pitcher_name": sb.get("return_pitcher_name", ""),
                "pitcher_hand": sb.get("return_pitcher_hand", ""),
                "date": st.session_state.get("selected_date", eastern_today()).isoformat(),
            })
        else:
            try:
                _set_query_params({"date": st.session_state.get("selected_date", eastern_today()).isoformat()})
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
    current_opponent_context = selected_batter_opponent_context(sb, game_pk, lineup_context, lineup_side)

    with st.container(border=True):
        render_batter_prop_game_log_section(batter_id, batter_name, current_opponent_context)

    with st.container(border=True):
        st.markdown(
            run_value_title_with_legend_html(),
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
            selected_heatmap_scale = st.selectbox(
                "Heatmap Scale",
                [strike_zone.HEATMAP_SCALE_LEAGUE, strike_zone.HEATMAP_SCALE_SELF],
                index=0,
                key=f"batter_strike_zone_heatmap_scale_{batter_id}",
            )
            st.markdown(
                batter_heatmap_legend_html(selected_heatmap_scale),
                unsafe_allow_html=True,
            )
            if selected_metric == "K%":
                st.markdown(
                    "<div style='color:#b91c1c; font-size:12.5px; font-weight:600; line-height:1.35; text-align:left; margin:6px 0 0 0; padding:0 0 12px 12px;'>Note: K% shows the zone-touch distribution for plate appearances that ended in a strikeout.</div>",
                    unsafe_allow_html=True,
                )
        with batter_strike_zone_cols[1]:
            strike_zone.display_batter_metric_strike_zone(
                batter_id,
                selected_pitch_type,
                selected_pitcher_throws,
                selected_metric,
                selected_heatmap_scale,
            )

    with st.container(border=True):
        lineup_team = lineup_context.get(f"{lineup_side}_team", sb.get("team", "")) if lineup_side else sb.get("team", "")
        lineup_opponent = lineup_context.get("home_team", "") if lineup_side == "away" else lineup_context.get("away_team", "")
        lineup_team_id = lineup_context.get(f"{lineup_side}_team_id", sb.get("team_id", "")) if lineup_side else sb.get("team_id", "")
        lineup_opponent_side = "home" if lineup_side == "away" else "away"
        lineup_opponent_id = lineup_context.get(f"{lineup_opponent_side}_team_id", sb.get("opponent_id", "")) if lineup_side else sb.get("opponent_id", "")
        batter_lineup_link_context = {
            "team": lineup_team,
            "team_id": lineup_team_id,
            "opponent": lineup_opponent or sb.get("opponent", ""),
            "opponent_id": lineup_opponent_id,
            "return_pitcher_id": sb.get("return_pitcher_id", ""),
            "return_game_pk": game_pk,
            "return_pitcher_side": sb.get("return_pitcher_side", ""),
            "return_pitcher_name": sb.get("return_pitcher_name", ""),
            "return_pitcher_hand": sb.get("return_pitcher_hand", ""),
        }
        st.markdown(
            "<div class='section-title-strong'>Team Lineup Context</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            render_lineup_table(
                team_lineup,
                current_batter_id=batter_id,
                current_batter_name=batter_name,
                link_context=batter_lineup_link_context,
            ),
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
    _ensure_query_params({
        "view": "pitcher_detail",
        "pitcher_id": sp.get("id", ""),
        "pitcher_name": sp.get("name", ""),
        "pitcher_hand": sp.get("hand", ""),
        "pitcher_side": sp.get("side", ""),
        "game_pk": gp,
        "date": st.session_state.get("selected_date", eastern_today()).isoformat(),
    })
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
                _set_query_params({"date": st.session_state.get("selected_date", eastern_today()).isoformat()})
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
                selected_pitcher_metric = st.selectbox(
                    "Metric",
                    list(strike_zone.PITCHER_STRIKE_ZONE_METRICS),
                    index=0,
                    key=f"strike_zone_metric_{pid}",
                )
                selected_pitcher_heatmap_scale = st.selectbox(
                    "Heatmap Scale",
                    [strike_zone.HEATMAP_SCALE_LEAGUE, strike_zone.HEATMAP_SCALE_SELF],
                    index=0,
                    key=f"strike_zone_heatmap_scale_{pid}",
                )
                st.markdown(
                    pitcher_heatmap_legend_html(selected_pitcher_heatmap_scale),
                    unsafe_allow_html=True,
                )
            with strike_zone_cols[1]:
                strike_zone.display_strike_zone(
                    pid,
                    selected_pitch_type,
                    selected_batter_stands,
                    selected_pitcher_metric,
                    selected_pitcher_heatmap_scale,
                )

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
                            "team_id": game.get("away_team_id", ""),
                            "opponent": game.get("home_team", ""),
                            "opponent_id": game.get("home_team_id", ""),
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
                            "team_id": game.get("home_team_id", ""),
                            "opponent": game.get("away_team", ""),
                            "opponent_id": game.get("away_team_id", ""),
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


def set_homepage_date(new_date):
    if new_date == st.session_state.get("selected_date") and "games" in st.session_state:
        return
    st.session_state["selected_date"] = new_date
    st.session_state["calendar_date"] = new_date
    st.session_state["games"] = load_schedule(new_date)
    _set_query_params({"date": new_date.isoformat()})


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
                            selected_pitcher = {
                                'name': game.get('away_pitcher'),
                                'id': game.get('away_pitcher_id'),
                                'hand': game.get('away_pitcher_hand'),
                                'side': 'away'
                            }
                            st.session_state['selected_pitcher'] = selected_pitcher
                            st.session_state['selected_game'] = game['game_pk']
                            _set_pitcher_detail_query(selected_pitcher, game['game_pk'])
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
                                        team_id=game.get("away_team_id", ""),
                                        opponent=game.get("home_team", ""),
                                        opponent_id=game.get("home_team_id", ""),
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
                            selected_pitcher = {
                                'name': game.get('home_pitcher'),
                                'id': game.get('home_pitcher_id'),
                                'hand': game.get('home_pitcher_hand'),
                                'side': 'home'
                            }
                            st.session_state['selected_pitcher'] = selected_pitcher
                            st.session_state['selected_game'] = game['game_pk']
                            _set_pitcher_detail_query(selected_pitcher, game['game_pk'])
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
                                        team_id=game.get("home_team_id", ""),
                                        opponent=game.get("away_team", ""),
                                        opponent_id=game.get("away_team_id", ""),
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
