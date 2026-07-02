import logging
import time
import json
import io
import html
import math
import os
import threading
import altair as alt
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import requests
import plotly.graph_objects as go
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.parse import quote_plus

import strike_zone
import performance_profile
from props_cache import load_props_summary_cache

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
logging.getLogger("urllib3").setLevel(logging.WARNING)
PLAYER_API_CALLS = 0
PLAYER_INFO_SESSION_CACHE = {}
PLAYER_INFO_SESSION_CACHE_LOCK = threading.Lock()
SAVANT_RESPONSE_SESSION_CACHE = {}
SAVANT_RESPONSE_SESSION_CACHE_LOCK = threading.Lock()
LINEUP_MIN_HEIGHT = 220
GAME_LOG_PROPS = [
    "Hits",
    "Runs",
    "RBI",
    "H+R+RBI",
    "Total Bases",
    "Batter Fantasy Score",
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
    "Fantasy Score": "fantasy_score",
    "Batter Fantasy Score": "fantasy_score",
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
PITCHER_GAME_LOG_PROPS = [
    "Pitcher Strikeouts",
    "Pitcher Fantasy Score",
    "Earned Runs",
    "Hits Allowed",
    "Walks Allowed",
    "Pitching Outs",
    "Pitches Thrown",
]
HOMEPAGE_PROP_OPTIONS = [*GAME_LOG_PROPS, *PITCHER_GAME_LOG_PROPS]
PROPS_LINE_TYPE_FILTER_OPTIONS = ("All", "PP Reg Line", "Goblin", "Demon")
PITCHER_GAME_LOG_PROP_COLUMNS = {
    "Pitcher Strikeouts": "strikeouts",
    "Pitcher Fantasy Score": "pitcher_fantasy_score",
    "Earned Runs": "earned_runs",
    "Hits Allowed": "hits_allowed",
    "Walks Allowed": "walks_allowed",
    "Pitching Outs": "pitching_outs",
    "Pitches Thrown": "pitches_thrown",
}
PITCHER_PRIZEPICKS_PROP_ALIASES = {
    "pitcherstrikeouts": "pitcherstrikeouts",
    "pitcherstrikeout": "pitcherstrikeouts",
    "pitcherks": "pitcherstrikeouts",
    "pitcherk": "pitcherstrikeouts",
    "strikeouts": "pitcherstrikeouts",
    "strikeout": "pitcherstrikeouts",
    "ks": "pitcherstrikeouts",
    "k": "pitcherstrikeouts",
    "pitcherfantasyscore": "pitcherfantasyscore",
    "pitcherfantasy": "pitcherfantasyscore",
    "pitcherfs": "pitcherfantasyscore",
    "pfs": "pitcherfantasyscore",
    "fantasyscorepitcher": "pitcherfantasyscore",
    "fantasypointspitcher": "pitcherfantasyscore",
    "earnedruns": "earnedrunsallowed",
    "earnedrun": "earnedrunsallowed",
    "earnedrunsallowed": "earnedrunsallowed",
    "earnedrunallowed": "earnedrunsallowed",
    "er": "earnedrunsallowed",
    "erallowed": "earnedrunsallowed",
    "era": "earnedrunsallowed",
    "hitsallowed": "hitsallowed",
    "hitallowed": "hitsallowed",
    "pitcherhitsallowed": "hitsallowed",
    "walksallowed": "walksallowed",
    "walkallowed": "walksallowed",
    "pitcherwalksallowed": "walksallowed",
    "bballowed": "walksallowed",
    "bb": "walksallowed",
    "baseonballsallowed": "walksallowed",
    "basesonballsallowed": "walksallowed",
    "pitchingouts": "pitchingouts",
    "pitchingout": "pitchingouts",
    "po": "pitchingouts",
    "outs": "pitchingouts",
    "outsrecorded": "pitchingouts",
    "outrecorded": "pitchingouts",
    "pitchesthrown": "pitchesthrown",
    "pitchesthrow": "pitchesthrown",
    "pitches": "pitchesthrown",
    "pitchcount": "pitchesthrown",
    "numberofpitches": "pitchesthrown",
}


def calculate_prizepicks_hitter_fantasy_score(
    singles,
    doubles,
    triples,
    home_runs,
    runs,
    rbi,
    walks,
    hit_by_pitch,
    stolen_bases,
):
    return (
        float(singles or 0) * 3
        + float(doubles or 0) * 5
        + float(triples or 0) * 8
        + float(home_runs or 0) * 10
        + float(runs or 0) * 2
        + float(rbi or 0) * 2
        + float(walks or 0) * 2
        + float(hit_by_pitch or 0) * 2
        + float(stolen_bases or 0) * 5
    )


def calculate_prizepicks_pitcher_fantasy_score(
    wins,
    earned_runs,
    strikeouts,
    pitching_outs,
    quality_start=None,
):
    if quality_start is None:
        quality_start = int(float(pitching_outs or 0) >= 18 and float(earned_runs or 0) <= 3)
    return (
        float(wins or 0) * 6
        + float(quality_start or 0) * 4
        - float(earned_runs or 0) * 3
        + float(strikeouts or 0) * 3
        + float(pitching_outs or 0)
    )


def prop_average_text(avg_value, prop_column):
    precision = 1 if prop_column in {"fantasy_score", "pitcher_fantasy_score"} else 2
    return f"{float(avg_value):.{precision}f}"


def prop_chart_value_format(prop_column):
    return ".1f" if prop_column in {"fantasy_score", "pitcher_fantasy_score"} else ".0f"


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
PROPS_AUTOLOAD_SENTINEL = components.declare_component(
    "props_autoload_sentinel",
    path=str(Path(__file__).parent / "components" / "props_autoload_sentinel"),
)


def _request_profile_key(url, params=None):
    if not params:
        return str(url)
    return f"{url}?{_freeze_request_params(params)}"


def _profiled_requests_get(url, *, service, params=None, timeout=None, **kwargs):
    started_at = time.perf_counter()
    try:
        if timeout is None:
            return requests.get(url, params=params, **kwargs)
        return requests.get(url, params=params, timeout=timeout, **kwargs)
    finally:
        performance_profile.record_request(
            service,
            _request_profile_key(url, params),
            elapsed_seconds=time.perf_counter() - started_at,
            cache_status="miss",
        )


def _render_page_header_and_styles():
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


def normalize_name(name):
    return " ".join(str(name).lower().replace(".", "").split())


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


def mlb_team_logo_url(team_id):
    team_id_text = str(team_id or "").strip()
    if not team_id_text:
        return ""
    return f"https://www.mlbstatic.com/team-logos/{team_id_text}.svg"


def title_with_team_logo_html(title_text, team_id="", logo_size=24, font_size_px=None, font_weight=800, color="inherit", margin_bottom_px=0):
    text = html.escape(str(title_text or ""))
    if not text:
        return ""

    font_size_style = f"font-size:{int(font_size_px)}px;" if font_size_px else ""
    logo_url = mlb_team_logo_url(team_id)
    logo_html = ""
    if logo_url:
        safe_logo_url = html.escape(logo_url, quote=True)
        logo_html = (
            "<img "
            f"src='{safe_logo_url}' alt='Team logo' "
            f"style='display:block; width:auto; height:{int(logo_size)}px; object-fit:contain; flex:0 0 auto;' "
            "loading='lazy' decoding='async' />"
        )

    return (
        "<div style='display:flex; align-items:center; gap:8px; line-height:1.2; "
        f"font-weight:{int(font_weight)}; color:{html.escape(str(color))}; margin-bottom:{int(margin_bottom_px)}px; {font_size_style}'>"
        f"{logo_html}<span>{text}</span>"
        "</div>"
    )


def short_weekday_with_period(date_value):
    try:
        parsed_date = pd.to_datetime(date_value).date()
    except Exception:
        return ""
    weekday_labels = {
        0: "Mon.",
        1: "Tue.",
        2: "Wed.",
        3: "Thu.",
        4: "Fri.",
        5: "Sat.",
        6: "Sun.",
    }
    return weekday_labels.get(parsed_date.weekday(), "")


def batter_header_matchup_subtitle(sb):
    game_pk = str(sb.get("return_game_pk") or st.session_state.get("selected_game", "") or "").strip()
    if not game_pk:
        return ""

    games_df = st.session_state.get("games")
    if games_df is None or (isinstance(games_df, pd.DataFrame) and games_df.empty):
        try:
            games_df = load_schedule(st.session_state.get("selected_date", eastern_today()))
        except Exception:
            games_df = pd.DataFrame()

    if not isinstance(games_df, pd.DataFrame) or games_df.empty or "game_pk" not in games_df.columns:
        return ""

    game_match = games_df[games_df["game_pk"].astype(str) == game_pk]
    if game_match.empty:
        return ""

    game = game_match.iloc[0]
    away_team = str(game.get("away_team", "") or "").strip()
    home_team = str(game.get("home_team", "") or "").strip()
    away_abbrev = str(game.get("away_abbrev", "") or away_team).strip()
    home_abbrev = str(game.get("home_abbrev", "") or home_team).strip()
    if not away_abbrev or not home_abbrev:
        return ""

    batter_team_id = str(sb.get("team_id", "") or "").strip()
    batter_team_name = normalize_name(sb.get("team", ""))
    away_team_id = str(game.get("away_team_id", "") or "").strip()
    home_team_id = str(game.get("home_team_id", "") or "").strip()

    batter_is_away = False
    batter_is_home = False
    if batter_team_id and away_team_id and batter_team_id == away_team_id:
        batter_is_away = True
    elif batter_team_id and home_team_id and batter_team_id == home_team_id:
        batter_is_home = True
    elif batter_team_name and normalize_name(away_team) == batter_team_name:
        batter_is_away = True
    elif batter_team_name and normalize_name(home_team) == batter_team_name:
        batter_is_home = True
    elif sb.get("return_pitcher_side") == "away":
        batter_is_home = True
    elif sb.get("return_pitcher_side") == "home":
        batter_is_away = True

    if batter_is_away:
        matchup_text = f"{away_abbrev} @ {home_abbrev}"
    elif batter_is_home:
        matchup_text = f"{home_abbrev} vs {away_abbrev}"
    else:
        return ""

    game_time_text = str(game.get("game_time_et", "") or sb.get("game_time", "") or "").strip()
    if not game_time_text or game_time_text.upper() == "TBD":
        return matchup_text

    weekday_text = short_weekday_with_period(st.session_state.get("selected_date", eastern_today()))
    if not weekday_text:
        return matchup_text
    return f"{matchup_text} | {weekday_text} {game_time_text}"


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
    value = _projection_value(
        record,
        "player_id", "playerId", "mlbam_id", "mlbamId",
        "batter_id", "batterId", "pitcher_id", "pitcherId",
    )
    return str(value or "")


def _projection_player_mlbam_id(player_attributes):
    if not isinstance(player_attributes, dict):
        return ""
    for key in ("mlbam_id", "mlbamId", "mlb_id", "mlbId", "batter_id", "batterId", "pitcher_id", "pitcherId"):
        value = player_attributes.get(key)
        if value not in {None, ""}:
            return str(value)
    return ""


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
        "fantasy": "fantasyscore",
        "fantasyscore": "fantasyscore",
        "batterfantasy": "fantasyscore",
        "batterfantasyscore": "fantasyscore",
        "batterfs": "fantasyscore",
        "fantasypoints": "fantasyscore",
        "fantasypts": "fantasyscore",
        "hitterfantasy": "fantasyscore",
        "hitterfantasyscore": "fantasyscore",
        "hitterfs": "fantasyscore",
        "hfs": "fantasyscore",
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


def pitcher_prizepicks_prop_match_key(value):
    normalized = normalize_name(value).replace("+", " ")
    compact = normalized.replace(" ", "")
    return PITCHER_PRIZEPICKS_PROP_ALIASES.get(compact, _prop_match_key(value))


def get_pitcher_prop_projection_lines(pitcher_id, selected_prop, pitcher_name=""):
    selected_prop_key = pitcher_prizepicks_prop_match_key(selected_prop)
    selected_pitcher_id = str(pitcher_id or "").strip()
    selected_name_key = normalize_name(pitcher_name)
    lines = []
    for record in st.session_state.get("prizepicks_projections", []):
        if not isinstance(record, dict):
            continue

        record_player_id = _projection_player_id(record)
        player_name = normalize_name(record.get("player") or _projection_player_name(record))
        if selected_pitcher_id and record_player_id:
            if record_player_id != selected_pitcher_id:
                continue
        elif selected_name_key:
            if player_name != selected_name_key:
                continue
        else:
            continue

        stat_type = record.get("stat_display_name") or _projection_stat_type(record)
        if pitcher_prizepicks_prop_match_key(stat_type) != selected_prop_key:
            continue
        lines.append(record)
    return lines


def projection_lines_matching_value(projection_lines, selected_line_value):
    exact_lines = []
    for projection_line in projection_lines:
        projection_line_value = _projection_line_value(projection_line)
        try:
            if float(projection_line_value) == float(selected_line_value):
                exact_lines.append(projection_line)
        except (TypeError, ValueError):
            continue
    return exact_lines


def preferred_projection_line(projection_lines):
    if not projection_lines:
        return None
    for projection_line in projection_lines:
        odds_type = normalize_name(_projection_value(projection_line, "odds_type", "oddsType", default=""))
        if odds_type not in {"goblin", "demon"}:
            return projection_line
    return projection_lines[0]


def render_line_badge_for_projection_matches(line_value, exact_projection_lines):
    if not exact_projection_lines:
        return render_line_badge(line_value, show_book_badge=False)

    try:
        line_text = f"{float(line_value):.1f}"
    except (TypeError, ValueError):
        line_text = str(line_value)

    modifier_html = []
    seen_modifiers = set()
    for projection_line in exact_projection_lines:
        odds_type = normalize_name(_projection_value(projection_line, "odds_type", "oddsType", default=""))
        if odds_type in seen_modifiers:
            continue
        if odds_type == "goblin":
            modifier_html.append(badge_image_html(MODIFIER_BADGE_ASSETS.get("goblin"), "Goblin", "boost-badge", "modifier-badge-img"))
            seen_modifiers.add(odds_type)
        elif odds_type == "demon":
            modifier_html.append(badge_image_html(MODIFIER_BADGE_ASSETS.get("demon"), "Demon", "boost-badge", "modifier-badge-img"))
            seen_modifiers.add(odds_type)

    return (
        '<div class="line-badge">'
        f'<span class="line-value">{html.escape(line_text)}</span>'
        f'{badge_image_html(SPORTSBOOK_BADGE_ASSETS.get("prizepicks"), "PrizePicks", "book-badge", "book-badge-img")}'
        f'{"".join(modifier_html)}'
        '</div>'
    )


def prop_label_from_query(value, default="Hits"):
    target_key = _prop_match_key(value)
    for prop in GAME_LOG_PROPS:
        if _prop_match_key(prop) == target_key:
            return prop
    return default


def pitcher_prop_label_from_query(value, default="Pitcher Strikeouts"):
    target_key = pitcher_prizepicks_prop_match_key(value)
    for prop in PITCHER_GAME_LOG_PROPS:
        if pitcher_prizepicks_prop_match_key(prop) == target_key:
            return prop
    return default


def homepage_prop_label_from_query(value, default="Hits"):
    batter_prop = prop_label_from_query(value, default="")
    if batter_prop:
        return batter_prop
    pitcher_prop = pitcher_prop_label_from_query(value, default="")
    if pitcher_prop:
        return pitcher_prop
    return default


def props_line_type_filter_label_from_query(value, default="All"):
    normalized = str(value or "").strip().lower()
    if normalized in {"standard", "pp reg line", "ppregline", "ppreg", "reg line", "regline"}:
        return "PP Reg Line"
    for option in PROPS_LINE_TYPE_FILTER_OPTIONS:
        if normalized == option.lower():
            return option
    return default


def game_log_prop_column(prop, default=None):
    resolved_prop = prop_label_from_query(prop, default="")
    if resolved_prop in GAME_LOG_PROP_COLUMNS:
        return GAME_LOG_PROP_COLUMNS[resolved_prop]
    return GAME_LOG_PROP_COLUMNS.get(prop, default)


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
    seen_projection_keys = set()
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
            player_mlbam_id = _projection_player_mlbam_id(player_attributes)
            line_value = _projection_line_value({"attributes": attributes})
            try:
                line_key = f"{float(line_value):.4f}"
            except (TypeError, ValueError):
                line_key = str(line_value or "").strip()
            dedupe_key = (
                player_mlbam_id or normalize_name(player_name),
                normalize_name(stat_display_name),
                line_key,
                normalize_name(attributes.get("odds_type") or "standard"),
            )
            if dedupe_key in seen_projection_keys:
                continue
            seen_projection_keys.add(dedupe_key)

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
                "player_id": player_mlbam_id,
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
    "average": "color:#ca8a04; font-weight:700;",
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


def compact_run_value_display_df(df):
    if df is None or df.empty:
        return pd.DataFrame()

    display_df = df.copy()
    if "%" in display_df.columns:
        display_df = display_df.drop(columns=["%"])
    return display_df


def compact_run_value_table_formatters(df):
    formatters = {}
    integer_columns = {"Year", "Pitches", "PA"}
    three_decimal_columns = {"BA", "SLG", "wOBA", "xBA", "xSLG", "xwOBA"}
    one_decimal_metric_keys = {"whiff%", "k%", "putaway%", "hard hit%"}

    for column in df.columns:
        if column in integer_columns:
            formatters[column] = lambda value: "—" if pd.isna(value) else f"{float(value):.0f}"
            continue
        if column in three_decimal_columns:
            formatters[column] = lambda value: "—" if pd.isna(value) else f"{float(value):.3f}"
            continue

        normalized_column = str(column).strip().lower()
        if normalized_column in one_decimal_metric_keys or "%" in str(column):
            formatters[column] = lambda value: "—" if pd.isna(value) else f"{float(value):.1f}"

    return formatters


def opposing_pitcher_arsenal_card_html(pitcher_name, arsenal_rows, team_id=""):
    title = html.escape(str(pitcher_name or "Opposing Pitcher Arsenal"))
    title_html = title_with_team_logo_html(
        pitcher_name or "Opposing Pitcher Arsenal",
        team_id=team_id,
        logo_size=22,
        font_size_px=21,
        font_weight=900,
        color="var(--dash-title)",
        margin_bottom_px=12,
    ) or f"<div class='dash-card-title'>{title}</div>"
    if not arsenal_rows:
        return (
            "<div class='dash-card'>"
            f"{title_html}"
            "<div style='font-size:13px; color:var(--dash-muted); font-weight:700;'>No arsenal data available.</div>"
            "</div>"
        )

    rows_html = []
    for row in arsenal_rows:
        pitch_name_html = pitch_type_text_html(row.get("name", ""))
        usage_text = f"{float(row.get('usage_pct', 0.0)):.1f}%"
        velocity = row.get("avg_velocity")
        velocity_text = f"{float(velocity):.1f}" if velocity not in {None, ""} and not pd.isna(velocity) else "—"
        count_text = f"{int(float(row.get('count', 0) or 0))}"
        rows_html.append(
            "<div style='display:grid; grid-template-columns:minmax(120px,1fr) 58px 52px 40px; gap:8px; align-items:center; "
            "padding:5px 0; border-top:1px solid rgba(148,163,184,0.22);'>"
            f"<div style='font-size:12px; font-weight:700; line-height:1.2;'>{pitch_name_html}</div>"
            f"<div style='font-size:12px; font-weight:800; text-align:right; color:var(--dash-accent);'>{usage_text}</div>"
            f"<div style='font-size:12px; font-weight:700; text-align:right; color:var(--dash-value);'>{velocity_text}</div>"
            f"<div style='font-size:12px; font-weight:700; text-align:right; color:var(--dash-value);'>{count_text}</div>"
            "</div>"
        )

    return (
        "<div class='dash-card'>"
        f"{title_html}"
        "<div style='display:grid; grid-template-columns:minmax(120px,1fr) 58px 52px 40px; gap:8px; align-items:end; "
        "font-size:11px; color:var(--dash-muted); font-weight:800; letter-spacing:0.02em; text-transform:uppercase; margin-bottom:2px;'>"
        "<div>Pitch Type</div><div style='text-align:right;'>Usage</div><div style='text-align:right;'>Velo</div><div style='text-align:right;'>Ct</div>"
        "</div>"
        f"{''.join(rows_html)}"
        "</div>"
    )


def format_pitcher_name_with_hand(pitcher_name, pitcher_hand=""):
    name = str(pitcher_name or "").strip()
    hand = str(pitcher_hand or "").strip()
    if name and hand:
        return f"{name} ({hand})"
    return name or "Opposing Pitcher Arsenal"


def format_batter_name_with_hand(batter_name, batter_hand=""):
    name = str(batter_name or "").strip()
    hand_code = normalize_hand_code(batter_hand)
    hand_label = {
        "L": "LHB",
        "R": "RHB",
        "S": "Switch",
    }.get(hand_code, "")
    if name and hand_label:
        return f"{name} ({hand_label})"
    return name or "Batter"


def default_opposing_pitcher_arsenal_split(batter_hand):
    normalized_hand = normalize_hand_code(batter_hand)
    if normalized_hand == "L":
        return "LHB"
    if normalized_hand == "R":
        return "RHB"
    return "Overall"


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
            feed = _profiled_requests_get(url, service="mlb", timeout=20).json()
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
        data = _profiled_requests_get(url, service="mlb", params=params, timeout=20).json()
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
        walks = _int_stat(stat, "baseOnBalls")
        hit_by_pitch = _int_stat(stat, "hitByPitch")
        stolen_bases = _int_stat(stat, "stolenBases")
        singles = max(hits - doubles - triples - home_runs, 0)
        fantasy_score = calculate_prizepicks_hitter_fantasy_score(
            singles,
            doubles,
            triples,
            home_runs,
            runs,
            rbi,
            walks,
            hit_by_pitch,
            stolen_bases,
        )
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
                "fantasy_score": fantasy_score,
                "home_runs": home_runs,
                "walks": walks,
                "hit_by_pitch": hit_by_pitch,
                "strikeouts": _int_stat(stat, "strikeOuts"),
                "plate_appearances": _int_stat(stat, "plateAppearances"),
                "stolen_bases": stolen_bases,
                "singles": singles,
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
        data = _profiled_requests_get(url, service="mlb", params=params, timeout=20).json()
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


def innings_pitched_to_outs(innings_pitched):
    value = str(innings_pitched or "0").strip()
    if not value:
        return 0

    if "." in value:
        whole_text, partial_text = value.split(".", 1)
    else:
        whole_text, partial_text = value, "0"

    try:
        whole_innings = int(float(whole_text or 0))
    except (TypeError, ValueError):
        whole_innings = 0

    partial_text = "".join(ch for ch in str(partial_text) if ch.isdigit())
    try:
        partial_outs = int(partial_text[:1] or 0)
    except (TypeError, ValueError):
        partial_outs = 0
    partial_outs = min(max(partial_outs, 0), 2)
    return whole_innings * 3 + partial_outs


@st.cache_data(ttl=1800, show_spinner=False)
def load_pitcher_prop_game_log(pitcher_id, season_year=2026):
    if not pitcher_id:
        return pd.DataFrame()

    url = f"https://statsapi.mlb.com/api/v1/people/{pitcher_id}/stats"
    params = {"stats": "gameLog", "group": "pitching", "season": season_year, "sportIds": 1}

    def _int_stat(stat, key):
        try:
            return int(stat.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0

    try:
        data = _profiled_requests_get(url, service="mlb", params=params, timeout=20).json()
    except Exception as exc:
        logger.warning("MLB pitcher game log request failed for %s: %s", pitcher_id, exc)
        return pd.DataFrame()

    rows = []
    splits = data.get("stats", [{}])[0].get("splits", []) if data.get("stats") else []
    for split in splits:
        stat = split.get("stat", {}) or {}
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
        innings_pitched = stat.get("inningsPitched", "0")
        strikeouts = _int_stat(stat, "strikeOuts")
        earned_runs = _int_stat(stat, "earnedRuns")
        pitching_outs = innings_pitched_to_outs(innings_pitched)
        wins = _int_stat(stat, "wins")
        quality_start = int(pitching_outs >= 18 and earned_runs <= 3)
        pitcher_fantasy_score = calculate_prizepicks_pitcher_fantasy_score(
            wins,
            earned_runs,
            strikeouts,
            pitching_outs,
            quality_start=quality_start,
        )
        rows.append(
            {
                "game_pk": game.get("gamePk") or game.get("id") or "",
                "season": int(season_year),
                "game_date": game_date,
                "opponent": f"{prefix}{opponent_label}" if opponent_label else "",
                "opponent_team_id": opponent.get("id", ""),
                "opponent_name": opponent_name,
                "opponent_abbrev": opponent.get("abbreviation") or "",
                "strikeouts": strikeouts,
                "pitcher_fantasy_score": pitcher_fantasy_score,
                "wins": wins,
                "quality_starts": quality_start,
                "earned_runs": earned_runs,
                "hits_allowed": _int_stat(stat, "hits"),
                "walks_allowed": _int_stat(stat, "baseOnBalls"),
                "innings_pitched": innings_pitched,
                "pitching_outs": pitching_outs,
                "pitches_thrown": _int_stat(stat, "numberOfPitches"),
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


@st.cache_data(ttl=86400, show_spinner=False)
def load_pitcher_prop_game_log_seasons(pitcher_id):
    if not pitcher_id:
        return []

    url = f"https://statsapi.mlb.com/api/v1/people/{pitcher_id}/stats"
    params = {"stats": "yearByYear", "group": "pitching", "sportIds": 1}
    try:
        data = _profiled_requests_get(url, service="mlb", params=params, timeout=20).json()
    except Exception as exc:
        logger.warning("MLB pitcher year-by-year request failed for %s: %s", pitcher_id, exc)
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
def load_pitcher_prop_all_game_logs(pitcher_id):
    seasons = load_pitcher_prop_game_log_seasons(pitcher_id)
    if not seasons:
        seasons = [date.today().year]

    frames = []
    for season in seasons:
        season_df = load_pitcher_prop_game_log(pitcher_id, season_year=season)
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


def _freeze_request_params(params):
    frozen = []
    for key, value in params.items():
        if isinstance(value, (list, tuple)):
            normalized_value = tuple(str(item) for item in value)
        else:
            normalized_value = str(value)
        frozen.append((str(key), normalized_value))
    return tuple(sorted(frozen))


def _get_cached_response_text(url, params, timeout=45):
    cache_key = (url, _freeze_request_params(params))
    with SAVANT_RESPONSE_SESSION_CACHE_LOCK:
        cached = SAVANT_RESPONSE_SESSION_CACHE.get(cache_key)
        if cached is not None:
            performance_profile.record_request("savant", cache_key, cache_status="hit")
            return cached
        started_at = time.perf_counter()
        response = requests.get(url, params=params, timeout=timeout)
        elapsed = time.perf_counter() - started_at
        performance_profile.record_request("savant", cache_key, elapsed_seconds=elapsed, cache_status="miss")
        cached_response = (response.status_code, response.text)
        SAVANT_RESPONSE_SESSION_CACHE[cache_key] = cached_response
        return cached_response


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
        status_code, response_text = _get_cached_response_text(url, params, timeout=45)
    except Exception as exc:
        logger.warning("Batter hit detail fetch failed for batter_id=%s season=%s: %s", batter_id, season_year, exc)
        return {}

    if status_code != 200:
        logger.warning("Batter hit detail request failed for batter_id=%s season=%s status=%s", batter_id, season_year, status_code)
        return {}

    try:
        raw_df = pd.read_csv(io.StringIO(response_text), low_memory=False)
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
        data = _profiled_requests_get(url, service="mlb", timeout=20).json()
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
        "avg_text": prop_average_text(avg_value, prop_column),
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


def toggle_batter_strike_zone_compare(compare_key):
    st.session_state[compare_key] = not bool(st.session_state.get(compare_key, False))


def toggle_pitcher_strike_zone_compare(compare_key):
    st.session_state[compare_key] = not bool(st.session_state.get(compare_key, False))


def selected_batter_comparison_pitcher_context(sb, game_pk, lineup_context, lineup_side):
    context = {
        "id": str(sb.get("return_pitcher_id") or "").strip(),
        "name": str(sb.get("return_pitcher_name") or "").strip(),
        "hand": str(sb.get("return_pitcher_hand") or "").strip(),
    }
    if context["id"] or context["name"]:
        return context

    if not game_pk:
        return context

    starters = load_game_starting_pitchers(game_pk)
    if not starters:
        return context

    opponent_side = ""
    if lineup_side in {"away", "home"}:
        opponent_side = "home" if lineup_side == "away" else "away"
    elif sb.get("return_pitcher_side") in {"away", "home"}:
        opponent_side = str(sb.get("return_pitcher_side"))
    else:
        batter_team_key = normalize_name(sb.get("team", ""))
        if batter_team_key and normalize_name(lineup_context.get("away_team", "")) == batter_team_key:
            opponent_side = "home"
        elif batter_team_key and normalize_name(lineup_context.get("home_team", "")) == batter_team_key:
            opponent_side = "away"

    if opponent_side not in {"away", "home"}:
        return context

    starter = starters.get(opponent_side, {}) or {}
    return {
        "id": str(starter.get("pitcher_id") or "").strip(),
        "name": str(starter.get("pitcher_name") or "").strip(),
        "hand": str(starter.get("pitcher_hand") or "").strip(),
    }


def batter_comparison_pitcher_stands(sb):
    batter_hand = normalize_hand_code(sb.get("hand", ""))
    if batter_hand == "R":
        return "RHB"
    if batter_hand == "L":
        return "LHB"
    return "All Batters"


def get_pitcher_compare_pitch_type_options(pitcher_id):
    if not pitcher_id:
        return ["All Pitches"]

    season_year = date.today().year
    start_date = f"{season_year}-03-01"
    end_date = date.today().isoformat()
    raw_df = strike_zone.load_pitch_location_data(pitcher_id, start_date, end_date)
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
    return ["All Pitches", *sorted(set(options))]


def get_batter_compare_pitcher_options(opponent_team_id, scheduled_pitcher):
    options = []
    seen_pitcher_ids = set()

    def _add_pitcher(pitcher_id, pitcher_name, pitcher_hand=""):
        pitcher_id = str(pitcher_id or "").strip()
        pitcher_name = str(pitcher_name or "").strip()
        pitcher_hand = str(pitcher_hand or "").strip()
        if not pitcher_id or not pitcher_name or pitcher_id in seen_pitcher_ids:
            return
        options.append({
            "id": pitcher_id,
            "name": pitcher_name,
            "hand": pitcher_hand,
        })
        seen_pitcher_ids.add(pitcher_id)

    scheduled_pitcher = scheduled_pitcher or {}
    _add_pitcher(
        scheduled_pitcher.get("id", ""),
        scheduled_pitcher.get("name", ""),
        scheduled_pitcher.get("hand", ""),
    )

    if not opponent_team_id:
        return options

    try:
        roster = load_active_roster(opponent_team_id)
    except Exception as exc:
        logger.warning("Unable to load opposing pitcher roster for team_id=%s: %s", opponent_team_id, exc)
        return options

    roster_pitchers = []
    pitcher_ids = []
    for row in roster or []:
        person = row.get("person", {}) or {}
        position = row.get("position", {}) or {}
        position_abbr = str(position.get("abbreviation") or "").strip().upper()
        position_name = normalize_name(position.get("name", ""))
        position_type = normalize_name(position.get("type", ""))
        if position_abbr != "P" and "pitcher" not in {position_name, position_type}:
            continue

        pitcher_id = str(person.get("id") or "").strip()
        pitcher_name = str(person.get("fullName") or "").strip()
        if not pitcher_id or not pitcher_name:
            continue
        roster_pitchers.append((pitcher_id, pitcher_name))
        try:
            pitcher_ids.append(int(float(pitcher_id)))
        except (TypeError, ValueError):
            continue

    pitcher_info = get_players_info(tuple(pitcher_ids)) if pitcher_ids else {}
    for pitcher_id, pitcher_name in sorted(roster_pitchers, key=lambda item: normalize_name(item[1])):
        try:
            pitcher_info_key = int(float(pitcher_id))
        except (TypeError, ValueError):
            pitcher_info_key = None
        hand_code = ""
        if pitcher_info_key is not None:
            hand_code = pitcher_info.get(pitcher_info_key, {}).get("pitchHand", "")
        pitcher_hand = format_pitcher_hand(normalize_hand_code(hand_code)) if hand_code else ""
        _add_pitcher(pitcher_id, pitcher_name, pitcher_hand)

    return options


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
    chart_value_format = prop_chart_value_format(prop_column)
    labels = (
        alt.Chart(display_log_df)
        .mark_text(dy=-8, fontWeight=700, fontSize=12, color="#0f172a")
        .encode(
            x=alt.X("chart_label:N", sort=None),
            y=alt.Y("label_y:Q"),
            text=alt.Text("prop_value:Q", format=chart_value_format),
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
            prop_key = game_log_prop_column(prop, default="").replace("_", "-")
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

    prop_column = game_log_prop_column(selected_prop)
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


def set_selected_pitcher_prop(prop):
    if prop in PITCHER_GAME_LOG_PROPS:
        st.session_state["selected_pitcher_prop"] = prop


def adjust_pitcher_game_log_line_value(line_key, delta):
    current_value = st.session_state.get(line_key, 0.5)
    try:
        current_value = float(current_value)
    except (TypeError, ValueError):
        current_value = 0.5
    st.session_state[line_key] = max(0.5, current_value + float(delta))


def set_pitcher_game_log_line_value(line_key, value):
    try:
        st.session_state[line_key] = float(value)
    except (TypeError, ValueError):
        pass


def set_pitcher_game_log_range_selection(range_key, h2h_key, sample_label):
    h2h_enabled = bool(st.session_state.get(h2h_key, False))
    if h2h_enabled and st.session_state.get(range_key) == sample_label:
        st.session_state[range_key] = None
    else:
        st.session_state[range_key] = sample_label


def toggle_pitcher_game_log_h2h_selection(h2h_key, range_key):
    h2h_enabled = bool(st.session_state.get(h2h_key, False))
    st.session_state[h2h_key] = not h2h_enabled
    if h2h_enabled:
        if st.session_state.get(range_key) not in GAME_LOG_SAMPLE_RANGES:
            st.session_state[range_key] = "L10"
    else:
        st.session_state[range_key] = None


def add_pitcher_game_log_tooltip_columns(game_log_df, selected_prop):
    if game_log_df.empty:
        return game_log_df.copy()

    enriched_df = game_log_df.copy()
    enriched_df["tooltip_date"] = enriched_df["game_date"].apply(game_log_full_date_label)
    enriched_df["tooltip_game"] = enriched_df.apply(game_log_matchup_tooltip, axis=1)
    enriched_df["tooltip_prop_label"] = selected_prop
    enriched_df["tooltip_prop_value"] = pd.to_numeric(enriched_df["prop_value"], errors="coerce").fillna(0)
    enriched_df["tooltip_ip"] = enriched_df.get("innings_pitched", "").astype(str) if "innings_pitched" in enriched_df.columns else ""
    return enriched_df


def render_pitcher_game_log_chart(display_log_df, prop_column, selected_prop, selected_prop_line, game_log_range, h2h_enabled):
    display_log_df = display_log_df.copy()
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
    display_log_df = add_pitcher_game_log_tooltip_columns(display_log_df, selected_prop)
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
                alt.Tooltip("tooltip_prop_value:Q", title=selected_prop, format=".0f"),
                alt.Tooltip("tooltip_ip:N", title="IP"),
            ],
        )
    )
    labels = (
        alt.Chart(display_log_df)
        .mark_text(dy=-8, fontWeight=700, fontSize=12, color="#0f172a")
        .encode(
            x=alt.X("chart_label:N", sort=None),
            y=alt.Y("label_y:Q"),
            text=alt.Text("prop_value:Q", format=prop_chart_value_format(prop_column)),
        )
    )
    line_df = pd.DataFrame({"line": [selected_prop_line]})
    line = alt.Chart(line_df).mark_rule(strokeDash=[6, 4], color="#334155", opacity=0.8).encode(y="line:Q")
    chart = (bars + labels + line).properties(height=230, width=alt.Step(x_step)).configure_view(stroke=None)
    st.altair_chart(chart, use_container_width=True)


def render_pitcher_game_log_sample_section(pitcher_id, prop_column, selected_prop, selected_prop_line, current_opponent_context):
    game_log_df = load_pitcher_prop_game_log(pitcher_id)
    range_key = f"pitcher_game_log_range_{pitcher_id}"
    h2h_key = f"pitcher_game_log_h2h_{pitcher_id}"
    h2h_enabled = bool(st.session_state.get(h2h_key, False))
    if st.session_state.get(range_key) not in GAME_LOG_SAMPLE_RANGES and not h2h_enabled:
        st.session_state[range_key] = "L10"
    elif st.session_state.get(range_key) not in GAME_LOG_SAMPLE_RANGES:
        st.session_state[range_key] = None

    has_opponent_context = bool(current_opponent_context.get("id") or current_opponent_context.get("name"))
    if h2h_enabled and not has_opponent_context:
        st.session_state[h2h_key] = False
        h2h_enabled = False
        if st.session_state.get(range_key) not in GAME_LOG_SAMPLE_RANGES:
            st.session_state[range_key] = "L10"
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
        all_game_log_df = load_pitcher_prop_all_game_logs(pitcher_id) if has_opponent_context else pd.DataFrame()
        h2h_tile_df = filter_game_logs_vs_opponent(all_game_log_df, current_opponent_context) if has_opponent_context else pd.DataFrame()
    else:
        h2h_tile_df = filter_game_logs_vs_opponent(game_log_df, current_opponent_context) if has_opponent_context else pd.DataFrame()
    h2h_summary = prop_hit_rate_summary_for_df(
        h2h_tile_df,
        prop_column,
        selected_prop_line,
        empty_hit_rate_text="N/A",
        empty_avg_text="-",
    )

    st.markdown("<div class='prop-control-spacer'></div>", unsafe_allow_html=True)
    with st.container(key="game_log_range_tiles", horizontal=True, gap="small"):
        for sample_label in GAME_LOG_SAMPLE_RANGES:
            is_selected_sample = sample_label == st.session_state[range_key]
            st.button(
                prop_hit_rate_sample_label(sample_label, sample_summaries),
                key=f"{range_key}_{sample_label}",
                type="primary" if is_selected_sample else "secondary",
                on_click=set_pitcher_game_log_range_selection,
                args=(range_key, h2h_key, sample_label),
            )
        if has_opponent_context:
            st.button(
                prop_h2h_tile_label(h2h_summary),
                key=f"{h2h_key}_tile",
                type="primary" if h2h_enabled else "secondary",
                on_click=toggle_pitcher_game_log_h2h_selection,
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
            all_game_log_df = load_pitcher_prop_all_game_logs(pitcher_id) if has_opponent_context else pd.DataFrame()
            display_log_df = filter_game_logs_vs_opponent(all_game_log_df, current_opponent_context) if has_opponent_context else pd.DataFrame()
    else:
        display_log_df = game_log_sample_dataframe(game_log_df, game_log_range)

    if display_log_df.empty:
        if h2h_enabled:
            st.info("No previous games vs today's opponent.")
        else:
            st.info("Game log data is unavailable for this pitcher right now.")
        return

    render_pitcher_game_log_chart(
        display_log_df,
        prop_column,
        selected_prop,
        selected_prop_line,
        game_log_range,
        h2h_enabled,
    )


@st.fragment
def render_pitcher_prop_game_log_section(pitcher_id, current_opponent_context, pitcher_name=""):
    if st.session_state.get("selected_pitcher_prop") not in PITCHER_GAME_LOG_PROPS:
        st.session_state["selected_pitcher_prop"] = "Pitcher Strikeouts"

    selected_prop = st.session_state.get("selected_pitcher_prop", "Pitcher Strikeouts")
    with st.container(key="prop_tab_row", horizontal=True, gap="small"):
        for prop in PITCHER_GAME_LOG_PROPS:
            prop_column_key = PITCHER_GAME_LOG_PROP_COLUMNS.get(prop, "").replace("_", "-")
            st.button(
                prop,
                key=f"pitcher_prop_tab_{pitcher_id}_{prop_column_key}",
                type="primary" if prop == selected_prop else "secondary",
                on_click=set_selected_pitcher_prop,
                args=(prop,),
            )

    selected_prop = st.session_state.get("selected_pitcher_prop", "Pitcher Strikeouts")
    if selected_prop not in PITCHER_GAME_LOG_PROPS:
        selected_prop = "Pitcher Strikeouts"

    prop_column = PITCHER_GAME_LOG_PROP_COLUMNS.get(selected_prop)
    prop_slug = prop_column.replace("_", "-")
    game_log_df = load_pitcher_prop_game_log(pitcher_id)
    if prop_column not in game_log_df.columns:
        st.info("Data unavailable for this prop.")
        return

    st.session_state["prizepicks_projections"] = load_prizepicks_mlb_projections()
    projection_lines = get_pitcher_prop_projection_lines(pitcher_id, selected_prop, pitcher_name)
    default_projection_line = preferred_projection_line(projection_lines)
    default_projection_line_value = _projection_line_value(default_projection_line) if default_projection_line else None

    line_key = f"pitcher_{prop_column}_line_{pitcher_id}"
    if line_key not in st.session_state:
        st.session_state[line_key] = default_projection_line_value if default_projection_line_value not in {None, ""} else 0.5

    selected_line_value = float(st.session_state[line_key])
    exact_projection_lines = projection_lines_matching_value(projection_lines, selected_line_value)

    st.markdown("<div class='prop-control-spacer'></div>", unsafe_allow_html=True)
    line_cols = st.columns([0.34, 1.65, 0.34, 4.2])
    with line_cols[0]:
        st.button(
            "-",
            key=f"pitcher_{prop_slug}_line_minus_{pitcher_id}",
            on_click=adjust_pitcher_game_log_line_value,
            args=(line_key, -1.0),
        )
    with line_cols[1]:
        st.markdown(
            f"<div class='line-badge-wrap'>{render_line_badge_for_projection_matches(st.session_state[line_key], exact_projection_lines)}</div>",
            unsafe_allow_html=True,
        )
    with line_cols[2]:
        st.button(
            "+",
            key=f"pitcher_{prop_slug}_line_plus_{pitcher_id}",
            on_click=adjust_pitcher_game_log_line_value,
            args=(line_key, 1.0),
        )

    if projection_lines:
        with st.expander("Alt lines", expanded=False):
            for idx, projection_line in enumerate(projection_lines):
                projection_line_value = _projection_line_value(projection_line)
                projection_exact_lines = projection_lines_matching_value(projection_lines, projection_line_value)
                st.markdown(
                    f"<div class='alt-line-row'>{render_line_badge_for_projection_matches(projection_line_value, projection_exact_lines)}</div>",
                    unsafe_allow_html=True,
                )
                st.button(
                    "Use",
                    key=f"pitcher_{prop_slug}_alt_line_{pitcher_id}_{idx}",
                    on_click=set_pitcher_game_log_line_value,
                    args=(line_key, projection_line_value),
                )

    selected_prop_line = float(st.session_state[line_key])
    render_pitcher_game_log_sample_section(
        pitcher_id,
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


def _build_pitcher_detail_href(
    pitcher_id,
    pitcher_name="",
    pitcher_hand="",
    pitcher_side="",
    game_pk="",
    prop="",
    line="",
):
    if not pitcher_id or not game_pk:
        return ""
    params = [("view", "pitcher_detail"), ("pitcher_id", str(pitcher_id)), ("game_pk", str(game_pk))]
    if pitcher_name:
        params.append(("pitcher_name", str(pitcher_name)))
    if pitcher_hand:
        params.append(("pitcher_hand", str(pitcher_hand)))
    if pitcher_side:
        params.append(("pitcher_side", str(pitcher_side)))
    selected_date_value = st.session_state.get("selected_date")
    if selected_date_value:
        params.append(("date", selected_date_value.isoformat()))
    if prop:
        params.append(("prop", str(prop)))
    if line not in {None, ""}:
        params.append(("line", str(line)))
    return "?" + "&".join(f"{key}={quote_plus(value)}" for key, value in params)


@st.cache_data(ttl=1800)
def load_batter_run_value_pitch_type_table(batter_id):
    if not batter_id:
        return pd.DataFrame()

    season_year = 2026
    start_date = f"{season_year}-03-01"
    end_date = date.today().isoformat()

    url = "https://baseballsavant.mlb.com/statcast_search/csv"
    params = savant_batter_detail_params(batter_id, start_date, end_date)

    try:
        status_code, response_text = _get_cached_response_text(url, params, timeout=45)
    except Exception as exc:
        logger.error("Batter run value fetch failed for batter_id=%s: %s", batter_id, exc)
        return pd.DataFrame()

    if status_code != 200:
        logger.warning("Batter run value request failed for batter_id=%s status=%s", batter_id, status_code)
        return pd.DataFrame()

    try:
        raw_df = pd.read_csv(io.StringIO(response_text), low_memory=False)
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
        response = _profiled_requests_get(url, service="savant", params=params, timeout=45)
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


def _initialize_page_state_from_query():
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
        requested_prop = prop_label_from_query(_query_param_value("prop", ""), default="")
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
        requested_pitcher_prop = pitcher_prop_label_from_query(_query_param_value("prop", ""), default="")
        if requested_pitcher_prop in PITCHER_GAME_LOG_PROPS:
            st.session_state["selected_pitcher_prop"] = requested_pitcher_prop
        try:
            st.session_state["selected_game"] = int(str(requested_game_pk))
        except Exception:
            st.session_state["selected_game"] = requested_game_pk

    requested_date_value = _query_param_value("date", "")
    requested_date = pd.to_datetime(requested_date_value, errors="coerce") if requested_date_value else pd.NaT
    requested_home_tab = str(_query_param_value("home_tab", "lineups")).strip().lower()
    if requested_home_tab == "slate":
        requested_home_tab = "lineups"
    if requested_home_tab not in {"lineups", "props"}:
        requested_home_tab = "lineups"
    if st.session_state.get("home_tab") != requested_home_tab:
        st.session_state["home_tab"] = requested_home_tab
    requested_home_prop = homepage_prop_label_from_query(_query_param_value("prop", "Hits"))
    if st.session_state.get("homepage_selected_prop") not in HOMEPAGE_PROP_OPTIONS:
        st.session_state["homepage_selected_prop"] = requested_home_prop
    elif requested_home_prop != st.session_state.get("homepage_selected_prop") and requested_home_tab == "props":
        st.session_state["homepage_selected_prop"] = requested_home_prop
    requested_line_type = props_line_type_filter_label_from_query(_query_param_value("line_type", "All"))
    if st.session_state.get("props_line_type_filter") not in PROPS_LINE_TYPE_FILTER_OPTIONS:
        st.session_state["props_line_type_filter"] = requested_line_type
    elif requested_line_type != st.session_state.get("props_line_type_filter") and requested_home_tab == "props":
        st.session_state["props_line_type_filter"] = requested_line_type
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

    with PLAYER_INFO_SESSION_CACHE_LOCK:
        missing_ids = [pid for pid in sanitized_ids if pid not in PLAYER_INFO_SESSION_CACHE]
        cached_ids = [pid for pid in sanitized_ids if pid in PLAYER_INFO_SESSION_CACHE]

    for pid in cached_ids:
        performance_profile.record_request("mlb", f"https://statsapi.mlb.com/api/v1/people:{pid}", cache_status="hit")

    if missing_ids:
        PLAYER_API_CALLS += 1
        logger.debug("Fetching handedness for player IDs: %s", missing_ids)
        url = "https://statsapi.mlb.com/api/v1/people"
        params = {"personIds": ",".join(str(pid) for pid in missing_ids)}
        data = _profiled_requests_get(url, service="mlb", params=params).json()
        people = data.get("people", [])
        fetched = {}
        for person in people:
            pid = person.get("id")
            fetched[pid] = {
                "fullName": person.get("fullName", ""),
                "batSide": person.get("batSide", {}).get("code", ""),
                "pitchHand": person.get("pitchHand", {}).get("code", "")
            }
        for pid in missing_ids:
            fetched.setdefault(pid, {})
        with PLAYER_INFO_SESSION_CACHE_LOCK:
            PLAYER_INFO_SESSION_CACHE.update(fetched)

    with PLAYER_INFO_SESSION_CACHE_LOCK:
        return {pid: PLAYER_INFO_SESSION_CACHE.get(pid, {}) for pid in sanitized_ids}


@st.cache_data(ttl=300)
def load_schedule(game_date):
    url = "https://statsapi.mlb.com/api/v1/schedule"
    params = {
        "sportId": 1,
        "date": game_date.strftime("%Y-%m-%d"),
        "hydrate": "probablePitcher,team,venue"
    }

    data = _profiled_requests_get(url, service="mlb", params=params).json()
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
    data = _profiled_requests_get(url, service="mlb", params={"rosterType": "active"}, timeout=15).json()
    return data.get("roster", [])


@st.cache_data(ttl=1800, show_spinner=False)
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


@st.cache_data(ttl=1800, show_spinner=False)
def resolve_player_id_from_team_roster(player_name, team_id):
    name_key = normalize_name(player_name)
    if not name_key or not team_id:
        return ""
    roster_map = build_roster_name_id_map(team_id)
    return str(roster_map.get(name_key) or "")


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
    data = _profiled_requests_get(url, service="mlb").json()

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

    def _lineup_stat_cell(value, metric, formatter):
        display_value = formatter(value)
        metric_style = run_value_threshold_style(value, metric) if display_value != "—" else ""
        return f"<div style='padding:6px 6px; text-align:center; white-space:nowrap; {metric_style}'>{display_value}</div>"

    grid_columns = "34px minmax(160px,1fr) 42px 42px 62px 62px 66px 78px 70px"
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
            f"<div style='padding:6px 8px;'>{player.get('number', '')}</div>"
            f"<div style='padding:6px 10px;'>{batter_cell_html}</div>"
            f"<div style='padding:6px 6px; text-align:center; white-space:nowrap;'>{html.escape(str(player.get('handedness', '')))}</div>"
            f"<div style='padding:6px 6px; text-align:center; white-space:nowrap;'>{html.escape(str(player.get('position', '')))}</div>"
            f"{_lineup_stat_cell(lineup_stats.get('BA'), 'BA', _format_lineup_decimal)}"
            f"{_lineup_stat_cell(lineup_stats.get('SLG'), 'SLG', _format_lineup_decimal)}"
            f"{_lineup_stat_cell(lineup_stats.get('wOBA'), 'wOBA', _format_lineup_decimal)}"
            f"{_lineup_stat_cell(lineup_stats.get('Whiff%'), 'Whiff%', _format_lineup_pct)}"
            f"{_lineup_stat_cell(lineup_stats.get('K%'), 'K%', _format_lineup_pct)}"
            "</div>"
        )

    return (
        f"{lineup_status_html(lineup)}"
        "<div style='overflow-x:auto; width:100%;'>"
        f"<div style='min-width:690px; display:grid; grid-template-columns:{grid_columns}; align-items:end; font-size:12px; color:#6b7280; font-weight:700;'>"
        "<div style='padding:0 8px 6px 8px;'>#</div>"
        "<div style='padding:0 10px 6px 10px;'>Batter</div>"
        "<div style='padding:0 6px 6px 6px; text-align:center; white-space:nowrap;'>Hand</div>"
        "<div style='padding:0 6px 6px 6px; text-align:center; white-space:nowrap;'>Pos</div>"
        "<div style='padding:0 6px 6px 6px; text-align:center; white-space:nowrap;'>BA</div>"
        "<div style='padding:0 6px 6px 6px; text-align:center; white-space:nowrap;'>SLG</div>"
        "<div style='padding:0 6px 6px 6px; text-align:center; white-space:nowrap;'>wOBA</div>"
        "<div style='padding:0 6px 6px 6px; text-align:center; white-space:nowrap;'>Whiff%</div>"
        "<div style='padding:0 6px 6px 6px; text-align:center; white-space:nowrap;'>K%</div>"
        "</div>"
        f"{''.join(rows)}"
        "</div>"
    )


def render_general_information(sb, batter_id, batter_name):
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
        run_value_pitcher = selected_batter_comparison_pitcher_context(sb, game_pk, lineup_context, lineup_side)
        run_value_cols = st.columns([3.2, 1.45])
        with run_value_cols[0]:
            st.markdown(
                run_value_title_with_legend_html(),
                unsafe_allow_html=True,
            )
            run_value_df = load_batter_run_value_pitch_type_table(batter_id)
            if run_value_df.empty:
                st.info("Run value by pitch type is unavailable for this batter right now.")
            else:
                display_run_value_df = compact_run_value_display_df(run_value_df)
                st.dataframe(
                    style_run_value_table(display_run_value_df).format(
                        compact_run_value_table_formatters(display_run_value_df)
                    ),
                    hide_index=True,
                    use_container_width=True,
                )
        with run_value_cols[1]:
            pitcher_id = run_value_pitcher.get("id", "")
            pitcher_name = run_value_pitcher.get("name", "") or "Opposing Pitcher Arsenal"
            pitcher_hand = run_value_pitcher.get("hand", "")
            opposing_pitcher_team_id = str(current_opponent_context.get("id") or "").strip()
            if pitcher_id:
                arsenal_split_key = f"batter_opposing_pitcher_arsenal_split_{batter_id}_{pitcher_id}"
                split_options = ["LHB", "Overall", "RHB"]
                default_split = default_opposing_pitcher_arsenal_split(sb.get("hand", ""))
                if st.session_state.get(arsenal_split_key) not in split_options:
                    st.session_state[arsenal_split_key] = default_split

                pitch_mix = load_regular_season_pitch_mix(pitcher_id)
                selected_arsenal_split = st.segmented_control(
                    "Opposing Pitcher Arsenal Split",
                    split_options,
                    default=st.session_state.get(arsenal_split_key, default_split),
                    key=arsenal_split_key,
                    label_visibility="collapsed",
                )
                opposing_arsenal_rows = {
                    "LHB": pitch_mix.get("L", []),
                    "Overall": pitch_mix.get("all", []),
                    "RHB": pitch_mix.get("R", []),
                }.get(selected_arsenal_split or default_split, pitch_mix.get("all", []))
                opposing_arsenal_rows = sorted(
                    opposing_arsenal_rows,
                    key=lambda row: float(row.get("usage_pct", 0.0)),
                    reverse=True,
                )
                st.markdown(
                    opposing_pitcher_arsenal_card_html(
                        format_pitcher_name_with_hand(pitcher_name, pitcher_hand),
                        opposing_arsenal_rows,
                        team_id=opposing_pitcher_team_id,
                    ),
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    "<div class='dash-card'>"
                    "<div class='dash-card-title'>Opposing Pitcher Arsenal</div>"
                    "<div style='font-size:13px; color:var(--dash-muted); font-weight:700;'>No opposing pitcher selected.</div>"
                    "</div>",
                    unsafe_allow_html=True,
                )

    with st.container(border=True):
        compare_key = f"batter_strike_zone_compare_{batter_id}"
        compare_enabled = bool(st.session_state.get(compare_key, False))
        comparison_pitcher = selected_batter_comparison_pitcher_context(sb, game_pk, lineup_context, lineup_side)

        strike_zone_header_cols = st.columns([5, 1.2])
        with strike_zone_header_cols[0]:
            st.markdown(
                "<div class='section-title-strong'>Strike Zone</div>",
                unsafe_allow_html=True,
            )
        with strike_zone_header_cols[1]:
            st.button(
                "Compare",
                key=f"{compare_key}_button",
                type="primary" if compare_enabled else "secondary",
                on_click=toggle_batter_strike_zone_compare,
                args=(compare_key,),
                use_container_width=True,
            )
        compare_pitcher_id = comparison_pitcher.get("id", "")
        compare_pitcher_name = comparison_pitcher.get("name", "")
        opposing_pitcher_team_id = str(current_opponent_context.get("id") or "").strip()
        pitcher_options = (
            get_batter_compare_pitcher_options(opposing_pitcher_team_id, comparison_pitcher)
            if compare_enabled else []
        )
        pitcher_option_lookup = {option["id"]: option for option in pitcher_options}
        pitcher_option_labels = {
            option["id"]: format_pitcher_name_with_hand(option.get("name", ""), option.get("hand", ""))
            for option in pitcher_options
        }
        pitcher_select_key = f"batter_compare_pitcher_id_{batter_id}"
        if compare_enabled and pitcher_options and st.session_state.get(pitcher_select_key) not in pitcher_option_lookup:
            scheduled_pitcher_id = str(comparison_pitcher.get("id") or "").strip()
            st.session_state[pitcher_select_key] = (
                scheduled_pitcher_id if scheduled_pitcher_id in pitcher_option_lookup else pitcher_options[0]["id"]
            )

        selected_compare_pitcher_id = st.session_state.get(pitcher_select_key, compare_pitcher_id) if compare_enabled else compare_pitcher_id
        selected_compare_pitcher = pitcher_option_lookup.get(selected_compare_pitcher_id, {})
        if selected_compare_pitcher:
            compare_pitcher_id = selected_compare_pitcher.get("id", "")
            compare_pitcher_name = selected_compare_pitcher.get("name", "")
            comparison_pitcher = selected_compare_pitcher
        pitcher_pitch_type_options = get_pitcher_compare_pitch_type_options(compare_pitcher_id)
        pitcher_pitch_type_key = f"batter_compare_pitcher_pitch_type_{batter_id}"
        if st.session_state.get(pitcher_pitch_type_key) not in pitcher_pitch_type_options:
            st.session_state[pitcher_pitch_type_key] = "All Pitches"

        pitcher_stands_key = f"batter_compare_pitcher_batter_stands_{batter_id}"
        if pitcher_stands_key not in st.session_state:
            st.session_state[pitcher_stands_key] = batter_comparison_pitcher_stands(sb)

        pitcher_metric_key = f"batter_compare_pitcher_metric_{batter_id}"
        if st.session_state.get(pitcher_metric_key) not in strike_zone.PITCHER_STRIKE_ZONE_METRICS:
            st.session_state[pitcher_metric_key] = "Pitch %"

        pitcher_heatmap_key = f"batter_compare_pitcher_heatmap_scale_{batter_id}"
        if st.session_state.get(pitcher_heatmap_key) not in {
            strike_zone.HEATMAP_SCALE_LEAGUE,
            strike_zone.HEATMAP_SCALE_SELF,
        }:
            st.session_state[pitcher_heatmap_key] = strike_zone.HEATMAP_SCALE_LEAGUE

        selected_pitcher_pitch_type = st.session_state.get(pitcher_pitch_type_key, "All Pitches")
        selected_pitcher_batter_stands = st.session_state.get(
            pitcher_stands_key,
            batter_comparison_pitcher_stands(sb),
        )
        selected_pitcher_metric = st.session_state.get(pitcher_metric_key, "Pitch %")
        selected_pitcher_heatmap_scale = st.session_state.get(
            pitcher_heatmap_key,
            strike_zone.HEATMAP_SCALE_LEAGUE,
        )
        batter_team_id = (
            str(lineup_context.get(f"{lineup_side}_team_id") or "").strip()
            if lineup_side else ""
        ) or str(sb.get("team_id") or "").strip()

        batter_strike_zone_cols = st.columns([1.15, 4, 4, 1.15] if compare_enabled else [1.15, 4])
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
            st.markdown(
                title_with_team_logo_html(
                    f"{format_batter_name_with_hand(batter_name, sb.get('hand', ''))} Location Tendencies",
                    team_id=batter_team_id,
                    logo_size=20,
                    font_size_px=14,
                    font_weight=700,
                    color="var(--dash-muted)",
                    margin_bottom_px=6,
                ),
                unsafe_allow_html=True,
            )
            if not compare_enabled:
                strike_zone.display_batter_metric_strike_zone(
                    batter_id,
                    selected_pitch_type,
                    selected_pitcher_throws,
                    selected_metric,
                    selected_heatmap_scale,
                )
            else:
                strike_zone.display_batter_metric_strike_zone(
                    batter_id,
                    selected_pitch_type,
                    selected_pitcher_throws,
                    selected_metric,
                    selected_heatmap_scale,
                )
        if compare_enabled:
            with batter_strike_zone_cols[2]:
                if compare_pitcher_id:
                    pitcher_label = format_pitcher_name_with_hand(compare_pitcher_name, comparison_pitcher.get("hand", ""))
                    st.markdown(
                        title_with_team_logo_html(
                            f"{pitcher_label} Location Tendencies",
                            team_id=opposing_pitcher_team_id,
                            logo_size=20,
                            font_size_px=14,
                            font_weight=700,
                            color="var(--dash-muted)",
                            margin_bottom_px=6,
                        ),
                        unsafe_allow_html=True,
                    )
                    strike_zone.display_strike_zone(
                        compare_pitcher_id,
                        selected_pitcher_pitch_type,
                        selected_pitcher_batter_stands,
                        selected_pitcher_metric,
                        selected_pitcher_heatmap_scale,
                    )
                else:
                    st.caption("Opposing Pitcher")
                    st.info("No pitcher selected for comparison.")
            with batter_strike_zone_cols[3]:
                if pitcher_options:
                    st.selectbox(
                        "Pitcher",
                        [option["id"] for option in pitcher_options],
                        key=pitcher_select_key,
                        format_func=lambda pitcher_id: pitcher_option_labels.get(pitcher_id, str(pitcher_id)),
                    )
                st.selectbox(
                    "Pitch Type",
                    pitcher_pitch_type_options,
                    key=pitcher_pitch_type_key,
                )
                st.selectbox(
                    "Batter Side",
                    ["All Batters", "RHB", "LHB"],
                    key=pitcher_stands_key,
                )
                st.selectbox(
                    "Metric",
                    list(strike_zone.PITCHER_STRIKE_ZONE_METRICS),
                    key=pitcher_metric_key,
                )
                st.selectbox(
                    "Heatmap Scale",
                    [strike_zone.HEATMAP_SCALE_LEAGUE, strike_zone.HEATMAP_SCALE_SELF],
                    key=pitcher_heatmap_key,
                )
                st.markdown(
                    pitcher_heatmap_legend_html(selected_pitcher_heatmap_scale),
                    unsafe_allow_html=True,
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


OUTFIELD_POSITIONS = ("7", "8", "9")
INFIELD_POSITIONS = ("3", "4", "5", "6")
DEFENSE_POSITION_GROUPS = {
    "outfield": {
        "positions": OUTFIELD_POSITIONS,
        "savant_pos": "of",
        "no_data_message": "No Outfield data available.",
    },
    "infield": {
        "positions": INFIELD_POSITIONS,
        "savant_pos": "if",
        "no_data_message": "No Infield data available.",
    },
}
DEFENSE_POSITION_LABEL_TO_ID = {"1B": "3", "2B": "4", "3B": "5", "SS": "6", "LF": "7", "CF": "8", "RF": "9"}
DEFENSE_POSITION_ID_TO_ARM_FIELD = {
    "3": "arm_1b",
    "4": "arm_2b",
    "5": "arm_3b",
    "6": "arm_ss",
    "7": "arm_lf",
    "8": "arm_cf",
    "9": "arm_rf",
}
OUTFIELD_RATING_THRESHOLDS = {
    "run_value": {"elite": 5.0, "good": 2.0, "average": -1.0},
    "oaa": {"elite": 5.0, "good": 2.0, "average": -1.0},
    "jump": {"elite": 1.5, "good": 0.5, "average": -0.5},
    "arm_strength": {"elite": 90.0, "good": 87.0, "average": 83.0},
    "sprint_speed": {"elite": 29.0, "good": 28.0, "average": 27.0},
    "success_rate": {"elite": 90.0, "good": 85.0, "average": 80.0},
    "success_rate_added": {"elite": 5.0, "good": 2.0, "average": -1.0},
}


def _savant_player_key(player_id):
    try:
        return str(int(float(player_id)))
    except (TypeError, ValueError):
        return ""


def _numeric_value(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    if str(value).strip() == "":
        return None
    try:
        return float(str(value).replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _format_outfield_value(value):
    number = _numeric_value(value)
    if number is None:
        return "N/A"
    if abs(number - round(number)) < 0.05:
        return str(int(round(number)))
    return f"{number:.1f}"


def defense_rating_level(value, threshold_key):
    number = _numeric_value(value)
    thresholds = OUTFIELD_RATING_THRESHOLDS.get(threshold_key)
    if number is None or not thresholds:
        return ""
    if number >= thresholds["elite"]:
        return "elite"
    if number >= thresholds["good"]:
        return "good"
    if number >= thresholds["average"]:
        return "average"
    return "bad"


def outfield_metric_rating(value, threshold_key):
    level = defense_rating_level(value, threshold_key)
    if not level:
        return "N/A"
    return {"elite": "Elite", "good": "Good", "average": "Average", "bad": "Bad"}[level]


def defense_rating_style(value, threshold_key):
    level = defense_rating_level(value, threshold_key)
    return RUN_VALUE_STYLE_COLORS.get(level, "")


def style_defense_rating_table(df):
    hidden_columns = [column for column in ("_RawValue", "_RatingKey") if column in df.columns]
    style_source = df[hidden_columns].copy() if hidden_columns else pd.DataFrame(index=df.index)
    visible_df = df.drop(columns=hidden_columns) if hidden_columns else df

    def cell_style(row, column_name):
        if column_name not in {"Value", "Rating"}:
            return ""
        if style_source.empty or row.name not in style_source.index:
            return ""
        return defense_rating_style(style_source.at[row.name, "_RawValue"], style_source.at[row.name, "_RatingKey"])

    return visible_df.style.apply(
        lambda row: [cell_style(row, column) for column in row.index],
        axis=1,
    )


def _savant_csv_dataframe(url, params, log_label):
    try:
        response = _profiled_requests_get(url, service="savant", params=params, timeout=45)
    except Exception as exc:
        logger.warning("%s request failed: %s", log_label, exc)
        return pd.DataFrame()
    if response.status_code != 200:
        logger.warning("%s request failed status=%s", log_label, response.status_code)
        return pd.DataFrame()
    try:
        return pd.read_csv(io.StringIO(response.text.lstrip("\ufeff")), low_memory=False)
    except Exception as exc:
        logger.warning("%s CSV parse failed: %s", log_label, exc)
        return pd.DataFrame()


def _savant_row_for_player(df, player_id, id_column):
    player_key = _savant_player_key(player_id)
    if df.empty or not player_key or id_column not in df.columns:
        return {}
    ids = pd.to_numeric(df[id_column], errors="coerce").astype("Int64").astype(str)
    matches = df[ids == player_key]
    if matches.empty:
        return {}
    return matches.iloc[0].to_dict()


def _normalize_defense_position(value):
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    text = str(value).strip().upper()
    if not text:
        return ""
    if text.endswith(".0"):
        text = text[:-2]
    return DEFENSE_POSITION_LABEL_TO_ID.get(text, text if text in DEFENSE_POSITION_ID_TO_ARM_FIELD else "")


def _defense_group_for_position(position_id):
    position_id = _normalize_defense_position(position_id)
    if position_id in OUTFIELD_POSITIONS:
        return "outfield"
    if position_id in INFIELD_POSITIONS:
        return "infield"
    return ""


@st.cache_data(ttl=1800, show_spinner=False)
def load_defense_oaa(season_year, position_group):
    group_config = DEFENSE_POSITION_GROUPS.get(position_group, DEFENSE_POSITION_GROUPS["outfield"])
    return _savant_csv_dataframe(
        "https://baseballsavant.mlb.com/leaderboard/outs_above_average",
        {
            "type": "Fielder",
            "startYear": str(season_year),
            "endYear": str(season_year),
            "split": "no",
            "team": "",
            "range": "year",
            "min": "q",
            "pos": group_config["savant_pos"],
            "roles": "",
            "viz": "show",
            "csv": "true",
        },
        f"{position_group.title()} OAA",
    )


def load_outfield_oaa(season_year):
    return load_defense_oaa(season_year, "outfield")


def load_infield_oaa(season_year):
    return load_defense_oaa(season_year, "infield")


@st.cache_data(ttl=1800, show_spinner=False)
def load_outfield_jump(season_year):
    return _savant_csv_dataframe(
        "https://baseballsavant.mlb.com/leaderboard/outfield_jump",
        {"year": str(season_year), "team": "", "min": "q", "csv": "true"},
        "Outfield jump",
    )


@st.cache_data(ttl=1800, show_spinner=False)
def load_defense_arm_strength(season_year, position_group):
    group_config = DEFENSE_POSITION_GROUPS.get(position_group, DEFENSE_POSITION_GROUPS["outfield"])
    return _savant_csv_dataframe(
        "https://baseballsavant.mlb.com/leaderboard/arm-strength",
        {"year": str(season_year), "minThrows": "100", "pos": group_config["savant_pos"], "team": "", "csv": "true"},
        f"{position_group.title()} arm strength",
    )


def load_outfield_arm_strength(season_year):
    return load_defense_arm_strength(season_year, "outfield")


def load_infield_arm_strength(season_year):
    return load_defense_arm_strength(season_year, "infield")


@st.cache_data(ttl=1800, show_spinner=False)
def load_defense_fielding_run_value(season_year):
    return _savant_csv_dataframe(
        "https://baseballsavant.mlb.com/leaderboard/fielding-run-value",
        {
            "type": "fielder",
            "seasonStart": str(season_year),
            "seasonEnd": str(season_year),
            "minInnings": "q",
            "csv": "true",
        },
        "Fielding run value",
    )


def load_outfield_fielding_run_value(season_year):
    return load_defense_fielding_run_value(season_year)


@st.cache_data(ttl=1800, show_spinner=False)
def load_outfield_sprint_speed(season_year):
    return _savant_csv_dataframe(
        "https://baseballsavant.mlb.com/leaderboard/sprint_speed",
        {"year": str(season_year), "position": "", "team": "", "min": "10", "csv": "true"},
        "Sprint speed",
    )


@st.cache_data(ttl=1800, show_spinner=False)
def load_defense_positioning(season_year, bat_side, position_group):
    group_config = DEFENSE_POSITION_GROUPS.get(position_group, DEFENSE_POSITION_GROUPS["outfield"])
    rows = []
    league_rows = []
    for position in group_config["positions"]:
        params = {
            "type": "player",
            "teamId": "",
            "firstBase": "0",
            "shift": "1",
            "batSide": bat_side,
            "season": str(season_year),
            "position": position,
            "attempts": "1",
        }
        try:
            response = _profiled_requests_get(
                "https://baseballsavant.mlb.com/visuals/position_data",
                service="savant",
                params=params,
                timeout=45,
            )
        except Exception as exc:
            logger.warning("%s positioning request failed bat_side=%s position=%s: %s", position_group.title(), bat_side, position, exc)
            continue
        if response.status_code != 200:
            logger.warning(
                "%s positioning request failed bat_side=%s position=%s status=%s",
                position_group.title(),
                bat_side,
                position,
                response.status_code,
            )
            continue
        try:
            payload = response.json()
        except Exception as exc:
            logger.warning("%s positioning JSON parse failed bat_side=%s position=%s: %s", position_group.title(), bat_side, position, exc)
            continue
        rows.extend(payload.get("positionData", []) or [])
        league_rows.extend(payload.get("leagueAvg", []) or [])
    return {"positionData": rows, "leagueAvg": league_rows}


def load_outfield_positioning(season_year, bat_side):
    return load_defense_positioning(season_year, bat_side, "outfield")


def load_infield_positioning(season_year, bat_side):
    return load_defense_positioning(season_year, bat_side, "infield")


def _weighted_positioning_values(rows, player_id):
    if isinstance(rows, dict):
        rows = rows.get("positionData", [])
    player_key = _savant_player_key(player_id)
    player_rows = [
        row for row in rows or []
        if _savant_player_key(row.get("fielder_id")) == player_key
    ]
    if not player_rows:
        return {}

    weighted_fields = {
        "Average Depth": "avg_norm_start_distance",
        "Average Angle": "avg_norm_start_angle",
        "Average X Position": "avg_norm_start_pos_x",
        "Average Y Position": "avg_norm_start_pos_y",
    }
    total_weight = 0.0
    totals = {label: 0.0 for label in weighted_fields}
    for row in player_rows:
        weight = _numeric_value(row.get("n")) or 0.0
        if weight <= 0:
            continue
        for label, field in weighted_fields.items():
            value = _numeric_value(row.get(field))
            if value is not None:
                totals[label] += value * weight
        total_weight += weight

    if total_weight <= 0:
        return {}
    return {label: totals[label] / total_weight for label in weighted_fields}


def _weighted_league_positioning_values(positioning_payload):
    league_rows = positioning_payload.get("leagueAvg", []) if isinstance(positioning_payload, dict) else []
    if not league_rows:
        return {}

    weighted_fields = {
        "Average Depth": "avg_norm_start_distance",
        "Average Angle": "avg_norm_start_angle",
        "Average X Position": "avg_norm_start_pos_x",
        "Average Y Position": "avg_norm_start_pos_y",
    }
    total_weight = 0.0
    totals = {label: 0.0 for label in weighted_fields}
    for row in league_rows:
        weight = _numeric_value(row.get("n")) or 0.0
        if weight <= 0:
            continue
        for label, field in weighted_fields.items():
            value = _numeric_value(row.get(field))
            if value is not None:
                totals[label] += value * weight
        total_weight += weight

    if total_weight <= 0:
        return {}
    return {label: totals[label] / total_weight for label in weighted_fields}


def _fielding_run_value_primary_position(row):
    best_position = ""
    best_outs = -1.0
    for position in INFIELD_POSITIONS + OUTFIELD_POSITIONS:
        outs = _numeric_value(row.get(f"outs_{position}"))
        if outs is not None and outs > best_outs:
            best_position = position
            best_outs = outs
    return best_position if best_outs > 0 else ""


def detect_player_defense_position(player_id):
    season_year = date.today().year
    for position_group in ("outfield", "infield"):
        oaa_row = _savant_row_for_player(load_defense_oaa(season_year, position_group), player_id, "player_id")
        position_id = _normalize_defense_position(oaa_row.get("primary_pos_formatted")) if oaa_row else ""
        if position_id and _defense_group_for_position(position_id) == position_group:
            return position_group, position_id

    fielding_run_value_row = _savant_row_for_player(load_defense_fielding_run_value(season_year), player_id, "id")
    position_id = _fielding_run_value_primary_position(fielding_run_value_row)
    position_group = _defense_group_for_position(position_id)
    if position_group:
        return position_group, position_id

    arm_row = _savant_row_for_player(load_outfield_arm_strength(season_year), player_id, "player_id")
    position_id = _normalize_defense_position(arm_row.get("primary_position"))
    position_group = _defense_group_for_position(position_id)
    if position_group:
        return position_group, position_id

    return "outfield", ""


def load_defense_player_metrics(player_id, position_group):
    season_year = date.today().year
    oaa_row = _savant_row_for_player(load_defense_oaa(season_year, position_group), player_id, "player_id")
    jump_row = _savant_row_for_player(load_outfield_jump(season_year), player_id, "resp_fielder_id") if position_group == "outfield" else {}
    arm_row = _savant_row_for_player(load_defense_arm_strength(season_year, position_group), player_id, "player_id")
    fielding_run_value_row = _savant_row_for_player(load_defense_fielding_run_value(season_year), player_id, "id")
    sprint_row = _savant_row_for_player(load_outfield_sprint_speed(season_year), player_id, "player_id")
    left_positioning = load_defense_positioning(season_year, "L", position_group)
    right_positioning = load_defense_positioning(season_year, "R", position_group)
    positioning = {
        "L": _weighted_positioning_values(left_positioning, player_id),
        "R": _weighted_positioning_values(right_positioning, player_id),
    }
    league_positioning = {
        "L": _weighted_league_positioning_values(left_positioning),
        "R": _weighted_league_positioning_values(right_positioning),
    }
    return {
        "oaa": oaa_row,
        "jump": jump_row,
        "arm": arm_row,
        "fielding_run_value": fielding_run_value_row,
        "sprint": sprint_row,
        "positioning": positioning,
        "league_positioning": league_positioning,
    }


def load_outfield_player_metrics(player_id):
    return load_defense_player_metrics(player_id, "outfield")


def _arm_strength_value(arm_row, primary_position, position_group):
    position_field = DEFENSE_POSITION_ID_TO_ARM_FIELD.get(_normalize_defense_position(primary_position), "")
    for field in (position_field, "arm_of" if position_group == "outfield" else "arm_inf", "arm_overall", "max_arm_strength"):
        if field and _numeric_value(arm_row.get(field)) is not None:
            return arm_row.get(field)
    return None


def _available_defensive_rows(primary_rows, fallback_rows=(), target_count=None):
    rows = []
    labels = set()
    for row in primary_rows:
        label, value, _rating_key = row
        if _numeric_value(value) is None:
            continue
        rows.append(row)
        labels.add(label)
    target_count = target_count or len(primary_rows)
    for row in fallback_rows:
        if len(rows) >= target_count:
            break
        label, value, _rating_key = row
        if label in labels or _numeric_value(value) is None:
            continue
        rows.append(row)
        labels.add(label)
    return rows


def _overall_defensive_rows(metrics, position_group, primary_position):
    oaa_row = metrics["oaa"]
    jump_row = metrics["jump"]
    arm_row = metrics["arm"]
    fielding_run_value_row = metrics["fielding_run_value"]
    sprint_row = metrics["sprint"]
    arm_strength = _arm_strength_value(arm_row, primary_position, position_group)

    if position_group == "infield":
        primary_rows = [
            ("Outs Above Average (OAA)", oaa_row.get("outs_above_average"), "oaa"),
            ("Fielding Runs Prevented", oaa_row.get("fielding_runs_prevented"), "run_value"),
            ("Fielding Run Value", fielding_run_value_row.get("total_runs"), "run_value"),
            ("Range Runs", fielding_run_value_row.get("range_runs"), "run_value"),
            ("Double Play Runs", fielding_run_value_row.get("dp_runs"), "run_value"),
            ("Arm Runs", fielding_run_value_row.get("arm_runs"), "run_value"),
            ("Arm Strength", arm_strength, "arm_strength"),
            ("Sprint Speed", sprint_row.get("sprint_speed"), "sprint_speed"),
        ]
        fallback_rows = [
            ("INF/OF Runs", fielding_run_value_row.get("inf_of_runs"), "run_value"),
            ("Success Rate Added", oaa_row.get("diff_success_rate_formatted"), "success_rate_added"),
            ("Actual Success Rate", oaa_row.get("actual_success_rate_formatted"), ""),
            ("Estimated Success Rate", oaa_row.get("adj_estimated_success_rate_formatted"), ""),
        ]
        return _available_defensive_rows(primary_rows, fallback_rows=fallback_rows, target_count=len(primary_rows))

    return [
        ("Outs Above Average (OAA)", oaa_row.get("outs_above_average"), "oaa"),
        ("Fielding Runs Prevented", oaa_row.get("fielding_runs_prevented"), "run_value"),
        ("Fielding Run Value", fielding_run_value_row.get("total_runs"), "run_value"),
        ("Jump", jump_row.get("rel_league_bootup_distance"), "jump"),
        ("Reaction", jump_row.get("rel_league_reaction_distance"), "jump"),
        ("Burst", jump_row.get("rel_league_burst_distance"), "jump"),
        ("Route", jump_row.get("rel_league_routing_distance"), "jump"),
        ("Arm Strength", arm_strength, "arm_strength"),
        ("Arm Runs", fielding_run_value_row.get("arm_runs"), "run_value"),
        ("Sprint Speed", sprint_row.get("sprint_speed"), "sprint_speed"),
    ]


def _outfield_metric_table(rows):
    signed_rating_keys = {"run_value", "oaa", "jump", "success_rate_added"}

    def display_value(value, rating_key):
        formatted = _format_outfield_value(value)
        number = _numeric_value(value)
        if formatted == "N/A" or rating_key not in signed_rating_keys or number is None or number <= 0:
            return formatted
        return f"+{formatted}"

    return pd.DataFrame(
        [
            {
                "Metric": label,
                "Value": display_value(value, rating_key),
                "Rating": outfield_metric_rating(value, rating_key),
                "_RawValue": value,
                "_RatingKey": rating_key,
            }
            for label, value, rating_key in rows
        ],
        columns=["Metric", "Value", "Rating", "_RawValue", "_RatingKey"],
    )


def _oaa_split_table(oaa_row):
    rows = [
        ("Overall OAA", oaa_row.get("outs_above_average"), "oaa"),
        ("OAA vs Right-Handed Batters", oaa_row.get("outs_above_average_rhh"), "oaa"),
        ("OAA vs Left-Handed Batters", oaa_row.get("outs_above_average_lhh"), "oaa"),
    ]
    return pd.DataFrame(
        [
            {
                "Split": label,
                "Value": f"+{_format_outfield_value(value)}" if (_numeric_value(value) or 0) > 0 else _format_outfield_value(value),
                "Rating": outfield_metric_rating(value, rating_key),
                "_RawValue": value,
                "_RatingKey": rating_key,
            }
            for label, value, rating_key in rows
            if _numeric_value(value) is not None
        ],
        columns=["Split", "Value", "Rating", "_RawValue", "_RatingKey"],
    )


def _last_name(name):
    text = str(name or "").strip()
    if not text:
        return "Player"
    if "," in text:
        return text.split(",", 1)[0].strip() or text
    return text.split()[-1]


def _positioning_field_figure(positioning_values, league_positioning_values, player_name):
    player_x = _numeric_value(positioning_values.get("Average X Position"))
    player_y = _numeric_value(positioning_values.get("Average Y Position"))
    if player_x is None or player_y is None:
        return None

    league_x = _numeric_value((league_positioning_values or {}).get("Average X Position"))
    league_y = _numeric_value((league_positioning_values or {}).get("Average Y Position"))
    player_color = run_value_style_color_hex("elite")
    league_color = "#64748b"
    grass_color = "#3d8f5a"
    dirt_color = "#c9985a"
    mound_color = "#b78349"
    line_color = "#ffffff"

    def shape_path(points, close=True):
        path = "M " + " L ".join(f"{x:.2f},{y:.2f}" for x, y in points)
        if close:
            path += " Z"
        return path

    def quadratic_curve(start, control, end, steps=96):
        points = []
        for step in range(steps):
            t = step / (steps - 1)
            inverse_t = 1 - t
            x_value = inverse_t**2 * start[0] + 2 * inverse_t * t * control[0] + t**2 * end[0]
            y_value = inverse_t**2 * start[1] + 2 * inverse_t * t * control[1] + t**2 * end[1]
            points.append((x_value, y_value))
        return points

    def diamond_points(x_value, y_value, radius):
        return [
            (x_value, y_value + radius),
            (x_value + radius, y_value),
            (x_value, y_value - radius),
            (x_value - radius, y_value),
        ]

    def scaled_vector(unit_vector, length):
        return (unit_vector[0] * length, unit_vector[1] * length)

    field_scale = 1.0
    base_distance = 90.0 * field_scale
    base_offset = base_distance / math.sqrt(2)
    foul_line_distance = 330.0 * field_scale
    center_field_distance = 400.0 * field_scale
    mound_distance = 60.5 * field_scale
    home_plate = (0, 0)
    first_base = (base_offset, base_offset)
    second_base = (0, base_offset * 2)
    third_base = (-base_offset, base_offset)
    base_points = [home_plate, first_base, second_base, third_base]
    right_foul_unit = (first_base[0] / base_distance, first_base[1] / base_distance)
    left_foul_unit = (third_base[0] / base_distance, third_base[1] / base_distance)
    right_foul_pole = scaled_vector(right_foul_unit, foul_line_distance)
    left_foul_pole = scaled_vector(left_foul_unit, foul_line_distance)
    fence_control_y = (center_field_distance * 2) - right_foul_pole[1]
    fence_points = quadratic_curve(left_foul_pole, (0, fence_control_y), right_foul_pole)
    grass_points = [home_plate, right_foul_pole] + list(reversed(fence_points)) + [left_foul_pole]
    infield_dirt_home_depth = 12.0 * field_scale
    infield_dirt_corner_extra = 18.0 * field_scale
    infield_dirt_second_extra = 25.0 * field_scale
    infield_dirt_points = [
        (0, -infield_dirt_home_depth),
        (first_base[0] + infield_dirt_corner_extra, first_base[1]),
        (0, second_base[1] + infield_dirt_second_extra),
        (third_base[0] - infield_dirt_corner_extra, third_base[1]),
    ]
    mound_radius = base_distance * 0.145
    mound_center = (0, mound_distance)
    base_marker_radius = base_distance * 0.055
    home_plate_points = [
        (0, -base_distance * 0.067),
        (base_distance * 0.067, -base_distance * 0.011),
        (base_distance * 0.044, base_distance * 0.078),
        (-base_distance * 0.044, base_distance * 0.078),
        (-base_distance * 0.067, -base_distance * 0.011),
    ]
    field_points = (
        grass_points
        + infield_dirt_points
        + home_plate_points
        + diamond_points(first_base[0], first_base[1], base_marker_radius)
        + diamond_points(second_base[0], second_base[1], base_marker_radius)
        + diamond_points(third_base[0], third_base[1], base_marker_radius)
        + [
            (mound_center[0] - mound_radius, mound_center[1] - mound_radius),
            (mound_center[0] + mound_radius, mound_center[1] + mound_radius),
        ]
    )
    field_x_min = min(x for x, _ in field_points)
    field_x_max = max(x for x, _ in field_points)
    field_y_min = min(y for _, y in field_points)
    field_y_max = max(y for _, y in field_points)

    def marker_label_point(x_value, y_value):
        candidates = [(24, 24), (-24, 24), (24, -24), (-24, -24), (0, 32), (0, -32)]
        best_point = None
        best_score = None
        for x_offset, y_offset in candidates:
            label_x = x_value + x_offset
            label_y = y_value + y_offset
            base_distance = min(
                ((label_x - base_x) ** 2 + (label_y - base_y) ** 2) ** 0.5
                for base_x, base_y in base_points
            )
            boundary_penalty = (
                max(0, field_x_min - label_x)
                + max(0, label_x - field_x_max)
                + max(0, field_y_min - label_y)
                + max(0, label_y - field_y_max)
            )
            score = base_distance - boundary_penalty * 2
            if best_score is None or score > best_score:
                best_score = score
                best_point = (label_x, label_y)
        return best_point

    player_label = _last_name(player_name)
    player_label_x, player_label_y = marker_label_point(player_x, player_y)
    plot_points = field_points + [(player_x, player_y), (player_label_x, player_label_y)]
    if league_x is not None and league_y is not None:
        plot_points.append((league_x, league_y))

    x_center = (field_x_min + field_x_max) / 2
    y_center = (field_y_min + field_y_max) / 2
    axis_padding = base_distance * 0.075
    half_width = max(abs(x - x_center) for x, _ in plot_points) + axis_padding
    half_height = max(abs(y - y_center) for _, y in plot_points) + axis_padding
    x_range = [x_center - half_width, x_center + half_width]
    y_range = [y_center - half_height, y_center + half_height]

    fig = go.Figure()
    fig.add_shape(
        type="path",
        path=shape_path(grass_points),
        line=dict(color="rgba(255,255,255,0)", width=0),
        fillcolor=grass_color,
        layer="below",
    )
    fig.add_shape(
        type="path",
        path=shape_path(infield_dirt_points),
        line=dict(color="rgba(255,255,255,0)", width=0),
        fillcolor=dirt_color,
        layer="below",
    )
    fig.add_shape(
        type="path",
        path=shape_path(base_points + [(0, 0)]),
        line=dict(color=line_color, width=2),
        fillcolor="rgba(0,0,0,0)",
        layer="above",
    )
    fig.add_shape(
        type="line",
        x0=0,
        y0=0,
        x1=right_foul_pole[0],
        y1=right_foul_pole[1],
        line=dict(color=line_color, width=2),
        layer="above",
    )
    fig.add_shape(
        type="line",
        x0=0,
        y0=0,
        x1=left_foul_pole[0],
        y1=left_foul_pole[1],
        line=dict(color=line_color, width=2),
        layer="above",
    )
    fig.add_shape(
        type="path",
        path=shape_path(fence_points, close=False),
        line=dict(color=line_color, width=4),
        layer="above",
    )
    fig.add_shape(
        type="circle",
        x0=mound_center[0] - mound_radius,
        y0=mound_center[1] - mound_radius,
        x1=mound_center[0] + mound_radius,
        y1=mound_center[1] + mound_radius,
        line=dict(color="rgba(255,255,255,0.45)", width=1),
        fillcolor=mound_color,
        layer="above",
    )
    for base_x, base_y in [first_base, second_base, third_base]:
        fig.add_shape(
            type="path",
            path=shape_path(diamond_points(base_x, base_y, base_marker_radius)),
            line=dict(color=line_color, width=1),
            fillcolor=line_color,
            layer="above",
        )
    fig.add_shape(
        type="path",
        path=shape_path(home_plate_points),
        line=dict(color=line_color, width=1),
        fillcolor=line_color,
        layer="above",
    )
    if league_x is not None and league_y is not None:
        fig.add_trace(
            go.Scatter(
                x=[league_x],
                y=[league_y],
                mode="markers",
                marker=dict(size=6, color=league_color, opacity=0.32),
                name="League Average",
                hovertemplate="League Avg<br>X: %{x:.1f}<br>Y: %{y:.1f}<extra></extra>",
            )
        )
    fig.add_trace(
        go.Scatter(
            x=[player_x],
            y=[player_y],
            mode="markers",
            marker=dict(size=14, color=player_color, line=dict(color=line_color, width=2)),
            name="Player",
            hovertemplate="Player<br>X: %{x:.1f}<br>Y: %{y:.1f}<extra></extra>",
        )
    )
    if player_label:
        for halo_x_offset, halo_y_offset in [(-1, 0), (1, 0), (0, -1), (0, 1), (-0.7, -0.7), (-0.7, 0.7), (0.7, -0.7), (0.7, 0.7)]:
            fig.add_annotation(
                x=player_label_x + halo_x_offset,
                y=player_label_y + halo_y_offset,
                text=html.escape(player_label),
                showarrow=False,
                font=dict(size=11, color=line_color),
                xanchor="center",
                yanchor="middle",
            )
        fig.add_annotation(
            x=player_label_x,
            y=player_label_y,
            text=html.escape(player_label),
            showarrow=False,
            font=dict(size=11, color=player_color),
            xanchor="center",
            yanchor="middle",
        )
    fig.update_xaxes(range=x_range, visible=False, scaleanchor="y", scaleratio=1)
    fig.update_yaxes(range=y_range, visible=False)
    fig.update_layout(
        height=270,
        margin=dict(l=0, r=0, t=4, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
    )
    return fig


def _render_positioning_card(title, positioning_values, league_positioning_values=None, player_name=""):
    with st.container(border=True):
        st.markdown(f"<div class='dash-card-title'>{html.escape(title)}</div>", unsafe_allow_html=True)
        if not positioning_values:
            st.caption("No positioning data available.")
            return
        field_figure = _positioning_field_figure(positioning_values, league_positioning_values, player_name)
        if field_figure is not None:
            st.plotly_chart(field_figure, use_container_width=True, config={"displayModeBar": False})
        rows = []
        for label in ("Average Depth", "Average Angle", "Average X Position", "Average Y Position"):
            rows.append(
                f"<span class='dash-label'>{html.escape(label)}</span>"
                f"<span class='dash-value'>{html.escape(_format_outfield_value(positioning_values.get(label)))}</span>"
            )
        st.markdown(f"<div class='dash-grid'>{''.join(rows)}</div>", unsafe_allow_html=True)


def render_outfield_information(batter_id, batter_name=""):
    position_group, primary_position = detect_player_defense_position(batter_id)
    metrics = load_defense_player_metrics(batter_id, position_group)
    oaa_row = metrics["oaa"]
    arm_row = metrics["arm"]
    fielding_run_value_row = metrics["fielding_run_value"]
    positioning = metrics["positioning"]
    league_positioning = metrics.get("league_positioning", {})
    group_config = DEFENSE_POSITION_GROUPS.get(position_group, DEFENSE_POSITION_GROUPS["outfield"])

    has_defense_data = any(
        [
            bool(oaa_row),
            bool(arm_row),
            bool(fielding_run_value_row),
            bool(positioning.get("L")),
            bool(positioning.get("R")),
        ]
    )
    if not has_defense_data:
        st.info(group_config["no_data_message"])
        return

    with st.container(border=True):
        st.markdown("<div class='section-title-strong'>Overall Defensive Metrics</div>", unsafe_allow_html=True)
        st.dataframe(
            style_defense_rating_table(_outfield_metric_table(_overall_defensive_rows(metrics, position_group, primary_position))),
            hide_index=True,
            use_container_width=True,
        )

    with st.container(border=True):
        st.markdown("<div class='section-title-strong'>OAA Splits</div>", unsafe_allow_html=True)
        split_df = _oaa_split_table(oaa_row)
        if split_df.empty:
            st.caption("No OAA split data available.")
        else:
            st.dataframe(
                style_defense_rating_table(split_df),
                hide_index=True,
                use_container_width=True,
            )

    st.markdown("<div class='section-title-strong'>Positioning</div>", unsafe_allow_html=True)
    left_col, right_col = st.columns(2)
    with left_col:
        _render_positioning_card("vs Left-Handed Batters", positioning.get("L"), league_positioning.get("L"), batter_name)
    with right_col:
        _render_positioning_card("vs Right-Handed Batters", positioning.get("R"), league_positioning.get("R"), batter_name)


def render_selected_batter_view():
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
        st.markdown(
            title_with_team_logo_html(
                f"{batter_name}{f' ({batter_hand})' if batter_hand else ''}",
                team_id=sb.get("team_id", ""),
                logo_size=26,
                font_size_px=30,
                font_weight=800,
                color="var(--dash-title)",
                margin_bottom_px=8,
            ),
            unsafe_allow_html=True,
        )
        matchup_subtitle = batter_header_matchup_subtitle(sb)
        if matchup_subtitle:
            st.markdown(
                (
                    "<div style='margin:-2px 0 10px 34px; font-size:13px; font-weight:600; "
                    "line-height:1.2; color:var(--dash-muted);'>"
                    f"{html.escape(matchup_subtitle)}"
                    "</div>"
                ),
                unsafe_allow_html=True,
            )

        batter_id = sb.get("id", "")
        batter_detail_view_key = f"batter_detail_view_{batter_id or 'unknown'}"
        previous_view_label = st.session_state.get(batter_detail_view_key)
        if previous_view_label == "General Information":
            st.session_state[batter_detail_view_key] = "Batting"
        elif previous_view_label == "Outfield":
            st.session_state[batter_detail_view_key] = "Fielding"
        elif previous_view_label not in {"Batting", "Fielding"}:
            st.session_state[batter_detail_view_key] = "Batting"
        selected_view = st.segmented_control(
            "Batter Detail View",
            ["Batting", "Fielding"],
            key=batter_detail_view_key,
            label_visibility="collapsed",
        )

        if selected_view == "Batting":
            render_general_information(sb, batter_id, batter_name)
        elif selected_view == "Fielding":
            render_outfield_information(batter_id, batter_name)

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
    response = _profiled_requests_get(stats_url, service="mlb", params=params, timeout=15)
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
        df = strike_zone.load_pitcher_statcast_data(player_id, start_date, end_date)
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

        rows = []
        for pitch_name, count in counts.items():
            pitch_frame = frame[frame[pitch_col] == pitch_name]
            avg_velocity = None
            if "release_speed" in pitch_frame.columns:
                velocity_values = pd.to_numeric(pitch_frame["release_speed"], errors="coerce").dropna()
                if not velocity_values.empty:
                    avg_velocity = float(velocity_values.mean())
            rows.append(
                {
                    "name": pitch_name,
                    "count": int(count),
                    "usage_pct": (float(count) / float(total)) * 100.0,
                    "avg_velocity": avg_velocity,
                }
            )
        return rows

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
def render_selected_pitcher_view():
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
                pitcher_team_id = str(game.get("away_team_id") or "").strip()
                opponent_team = game.get("home_team", "")
                opponent_context = {
                    "id": str(game.get("home_team_id") or "").strip(),
                    "name": str(game.get("home_team") or "").strip(),
                    "abbr": str(game.get("home_abbrev") or "").strip(),
                }
                opponent_lineup = home_lineup
            else:
                name = sp.get("name")
                pid = sp.get("id", "")
                hand = sp.get("hand", "")
                pitcher_team_id = str(game.get("home_team_id") or "").strip()
                opponent_team = game.get("away_team", "")
                opponent_context = {
                    "id": str(game.get("away_team_id") or "").strip(),
                    "name": str(game.get("away_team") or "").strip(),
                    "abbr": str(game.get("away_abbrev") or "").strip(),
                }
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

            st.markdown(
                title_with_team_logo_html(
                    format_pitcher_name_with_hand(name, hand),
                    team_id=pitcher_team_id,
                    logo_size=24,
                    font_size_px=28,
                    font_weight=800,
                    color="var(--dash-title)",
                    margin_bottom_px=4,
                ),
                unsafe_allow_html=True,
            )
            st.markdown(f"{game.get('away_team')} @ {game.get('home_team')} • {game.get('game_time_et')}")

            with st.container(border=True):
                render_pitcher_prop_game_log_section(pid, opponent_context, name)

            st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

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
                pitcher_compare_key = f"pitcher_strike_zone_compare_{pid}"
                pitcher_compare_enabled = bool(st.session_state.get(pitcher_compare_key, False))
                strike_zone_header_cols = st.columns([5, 1.2])
                with strike_zone_header_cols[0]:
                    st.markdown(
                        "<div class='section-title-strong'>Strike Zone</div>",
                        unsafe_allow_html=True,
                    )
                with strike_zone_header_cols[1]:
                    st.button(
                        "Compare",
                        key=f"{pitcher_compare_key}_button",
                        type="primary" if pitcher_compare_enabled else "secondary",
                        on_click=toggle_pitcher_strike_zone_compare,
                        args=(pitcher_compare_key,),
                        use_container_width=True,
                    )

                compare_batter_options = []
                compare_batter_labels = {}
                compare_batter_lookup = {}
                for player in opponent_lineup or []:
                    player_id = str(player.get("player_id") or "").strip()
                    player_name = str(player.get("name") or "").strip()
                    if not player_id or not player_name:
                        continue
                    batter_label = format_batter_name_with_hand(player_name, player.get("handedness", ""))
                    compare_batter_options.append(player_id)
                    compare_batter_labels[player_id] = batter_label
                    compare_batter_lookup[player_id] = player

                compare_batter_id_key = f"pitcher_compare_batter_id_{pid}"
                if compare_batter_options and st.session_state.get(compare_batter_id_key) not in compare_batter_options:
                    st.session_state[compare_batter_id_key] = compare_batter_options[0]

                selected_compare_batter_id = st.session_state.get(compare_batter_id_key, "")
                selected_compare_batter = compare_batter_lookup.get(selected_compare_batter_id, {})

                compare_batter_pitch_type_key = f"pitcher_compare_batter_pitch_type_{pid}"
                compare_batter_pitch_type_options = (
                    strike_zone.get_batter_pitch_type_options(selected_compare_batter_id)
                    if pitcher_compare_enabled and selected_compare_batter_id else ["All Pitches"]
                )
                if st.session_state.get(compare_batter_pitch_type_key) not in compare_batter_pitch_type_options:
                    st.session_state[compare_batter_pitch_type_key] = "All Pitches"

                compare_batter_pitcher_throws_key = f"pitcher_compare_batter_pitcher_throws_{pid}"
                if st.session_state.get(compare_batter_pitcher_throws_key) not in {"All", "RHP", "LHP"}:
                    st.session_state[compare_batter_pitcher_throws_key] = "All"

                compare_batter_metric_key = f"pitcher_compare_batter_metric_{pid}"
                compare_batter_metric_options = ["Pitch %", "Takes", "Batted Balls", "K%", "Home Runs"]
                if st.session_state.get(compare_batter_metric_key) not in compare_batter_metric_options:
                    st.session_state[compare_batter_metric_key] = "Pitch %"

                compare_batter_heatmap_key = f"pitcher_compare_batter_heatmap_scale_{pid}"
                if st.session_state.get(compare_batter_heatmap_key) not in {
                    strike_zone.HEATMAP_SCALE_LEAGUE,
                    strike_zone.HEATMAP_SCALE_SELF,
                }:
                    st.session_state[compare_batter_heatmap_key] = strike_zone.HEATMAP_SCALE_LEAGUE

                strike_zone_cols = st.columns([1.15, 4, 4, 1.15] if pitcher_compare_enabled else [1.15, 4])
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
                    if pitcher_compare_enabled:
                        st.markdown(
                            title_with_team_logo_html(
                                f"{format_pitcher_name_with_hand(name, hand)} Location Tendencies",
                                team_id=pitcher_team_id,
                                logo_size=20,
                                font_size_px=14,
                                font_weight=700,
                                color="var(--dash-muted)",
                                margin_bottom_px=6,
                            ),
                            unsafe_allow_html=True,
                        )
                    strike_zone.display_strike_zone(
                        pid,
                        selected_pitch_type,
                        selected_batter_stands,
                        selected_pitcher_metric,
                        selected_pitcher_heatmap_scale,
                    )
                if pitcher_compare_enabled:
                    with strike_zone_cols[2]:
                        if selected_compare_batter_id:
                            batter_title = format_batter_name_with_hand(
                                selected_compare_batter.get("name", ""),
                                selected_compare_batter.get("handedness", ""),
                            )
                            st.markdown(
                                title_with_team_logo_html(
                                    f"{batter_title} Location Tendencies",
                                    team_id=str(opponent_context.get("id") or "").strip(),
                                    logo_size=20,
                                    font_size_px=14,
                                    font_weight=700,
                                    color="var(--dash-muted)",
                                    margin_bottom_px=6,
                                ),
                                unsafe_allow_html=True,
                            )
                            strike_zone.display_batter_metric_strike_zone(
                                selected_compare_batter_id,
                                st.session_state.get(compare_batter_pitch_type_key, "All Pitches"),
                                st.session_state.get(compare_batter_pitcher_throws_key, "All"),
                                st.session_state.get(compare_batter_metric_key, "Pitch %"),
                                st.session_state.get(compare_batter_heatmap_key, strike_zone.HEATMAP_SCALE_LEAGUE),
                            )
                        else:
                            st.info("No opposing batters available for comparison.")
                    with strike_zone_cols[3]:
                        if compare_batter_options:
                            st.selectbox(
                                "Batter",
                                compare_batter_options,
                                key=compare_batter_id_key,
                                format_func=lambda player_id: compare_batter_labels.get(player_id, str(player_id)),
                            )
                            st.selectbox(
                                "Pitch Type",
                                compare_batter_pitch_type_options,
                                key=compare_batter_pitch_type_key,
                            )
                            selected_compare_batter_pitcher_throws = st.selectbox(
                                "Pitcher Throws",
                                ["All", "RHP", "LHP"],
                                key=compare_batter_pitcher_throws_key,
                            )
                            selected_compare_batter_metric = st.selectbox(
                                "Metric",
                                compare_batter_metric_options,
                                key=compare_batter_metric_key,
                            )
                            selected_compare_batter_heatmap_scale = st.selectbox(
                                "Heatmap Scale",
                                [strike_zone.HEATMAP_SCALE_LEAGUE, strike_zone.HEATMAP_SCALE_SELF],
                                key=compare_batter_heatmap_key,
                            )
                            st.markdown(
                                batter_heatmap_legend_html(selected_compare_batter_heatmap_scale),
                                unsafe_allow_html=True,
                            )
                            if selected_compare_batter_metric == "K%":
                                st.markdown(
                                    "<div style='color:#b91c1c; font-size:12.5px; font-weight:600; line-height:1.35; text-align:left; margin:6px 0 0 0; padding:0 0 12px 12px;'>Note: K% shows the zone-touch distribution for plate appearances that ended in a strikeout.</div>",
                                    unsafe_allow_html=True,
                                )
                        else:
                            st.info("No opposing batters available for comparison.")

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
    params = {
        "date": new_date.isoformat(),
        "home_tab": st.session_state.get("home_tab", "lineups"),
        "prop": st.session_state.get("homepage_selected_prop", "Hits") if st.session_state.get("home_tab") == "props" else "",
        "line_type": st.session_state.get("props_line_type_filter", "All") if st.session_state.get("home_tab") == "props" else "",
    }
    if st.session_state.get("home_tab") == "props":
        params = _with_props_cache_query_param(params)
    _set_query_params(params)


def shift_homepage_date(days):
    set_homepage_date(st.session_state["selected_date"] + timedelta(days=days))


def set_homepage_today():
    set_homepage_date(eastern_today())


def set_homepage_calendar_date():
    set_homepage_date(st.session_state["calendar_date"])


def set_homepage_tab():
    selected_label = st.session_state.get("homepage_tab_switch", "Lineups")
    selected_tab = "props" if selected_label == "Props" else "lineups"
    st.session_state["home_tab"] = selected_tab
    params = {
        "date": st.session_state.get("selected_date", eastern_today()).isoformat(),
        "home_tab": selected_tab,
        "prop": st.session_state.get("homepage_selected_prop", "Hits") if selected_tab == "props" else "",
        "line_type": st.session_state.get("props_line_type_filter", "All") if selected_tab == "props" else "",
    }
    if selected_tab == "props":
        params = _with_props_cache_query_param(params)
    _set_query_params(params)


def set_homepage_props_prop(prop):
    if prop not in HOMEPAGE_PROP_OPTIONS:
        return
    st.session_state["homepage_selected_prop"] = prop
    _set_query_params(_with_props_cache_query_param({
        "date": st.session_state.get("selected_date", eastern_today()).isoformat(),
        "home_tab": "props",
        "prop": prop,
        "line_type": st.session_state.get("props_line_type_filter", "All"),
    }))


def set_homepage_props_line_type():
    selected_line_type = props_line_type_filter_label_from_query(
        st.session_state.get("props_line_type_filter", "All"),
        default="All",
    )
    st.session_state["props_line_type_filter"] = selected_line_type
    _set_query_params(_with_props_cache_query_param({
        "date": st.session_state.get("selected_date", eastern_today()).isoformat(),
        "home_tab": "props",
        "prop": st.session_state.get("homepage_selected_prop", "Hits"),
        "line_type": selected_line_type,
    }))


@st.cache_data(ttl=86400, show_spinner=False)
def mlb_player_headshot_url(player_id):
    try:
        player_id = int(float(player_id))
    except (TypeError, ValueError):
        return ""
    return f"https://img.mlbstatic.com/mlb-photos/image/upload/w_160,q_auto:best/v1/people/{player_id}/headshot/67/current"


def homepage_slate_batter_map(games):
    batter_map = {}
    if games is None or (isinstance(games, pd.DataFrame) and games.empty):
        return batter_map
    for _, game in games.iterrows():
        lineup_context = get_game_lineups(game.get("game_pk"), game)
        side_meta = {
            "away": {
                "team": game.get("away_team", ""),
                "team_id": game.get("away_team_id", ""),
                "opponent": game.get("home_team", ""),
                "opponent_id": game.get("home_team_id", ""),
            },
            "home": {
                "team": game.get("home_team", ""),
                "team_id": game.get("home_team_id", ""),
                "opponent": game.get("away_team", ""),
                "opponent_id": game.get("away_team_id", ""),
            },
        }
        for side in ("away", "home"):
            for player in lineup_context.get(side, []) or []:
                player_name = player.get("name", "")
                player_key = normalize_name(player_name)
                if not player_key:
                    continue
                batter_map[player_key] = {
                    **side_meta[side],
                    "player_id": player.get("player_id", ""),
                    "name": player_name,
                    "hand": player.get("handedness", ""),
                    "game_pk": game.get("game_pk", ""),
                    "game_time": game.get("game_time_et", ""),
                }
    return batter_map


def _truthy_query_or_env(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _props_cache_mode():
    query_value = str(_query_param_value("props_cache", "") or "").strip().lower()
    if query_value in {"0", "false", "no", "off"}:
        return "force_live"
    if query_value in {"1", "true", "yes", "on"}:
        return "force_cache"
    if _truthy_query_or_env(os.environ.get("USE_PROPS_SUMMARY_CACHE", "")):
        return "force_cache"
    return "auto"


def _props_autoload_enabled():
    query_value = str(_query_param_value("props_autoload", "") or "").strip().lower()
    if query_value in {"0", "false", "no", "off"}:
        return False
    if query_value in {"1", "true", "yes", "on"}:
        return True
    return True


def _with_props_cache_query_param(params):
    updated = dict(params)
    query_value = str(_query_param_value("props_cache", "") or "").strip()
    if query_value in {"0", "1"}:
        updated["props_cache"] = query_value
    return updated


def _render_props_autoload_sentinel(props_loaded_card_limit_key, loaded_card_limit, props_card_batch_size, total_count, button_key_parts):
    if not _props_autoload_enabled() or loaded_card_limit >= total_count:
        return

    event = PROPS_AUTOLOAD_SENTINEL(
        limit=int(loaded_card_limit),
        total=int(total_count),
        token=props_loaded_card_limit_key,
        key=f"props_autoload_sentinel_{'_'.join(str(part) for part in button_key_parts)}_{loaded_card_limit}",
        default=None,
    )
    if not isinstance(event, dict):
        return
    if event.get("token") != props_loaded_card_limit_key:
        return
    try:
        triggered_limit = int(event.get("limit"))
    except (TypeError, ValueError):
        return
    if triggered_limit != loaded_card_limit:
        return

    last_trigger_key = f"{props_loaded_card_limit_key}_autoload_last_limit"
    if st.session_state.get(last_trigger_key) == loaded_card_limit:
        return
    st.session_state[last_trigger_key] = loaded_card_limit
    st.session_state[props_loaded_card_limit_key] = min(
        total_count,
        loaded_card_limit + props_card_batch_size,
    )
    st.rerun()


def _props_autoload_loading_html():
    return (
        "<style>"
        ".props-autoload-loading{display:flex;align-items:center;justify-content:center;gap:10px;"
        "margin:18px 0 8px 0;color:var(--dash-muted);font-size:12px;font-weight:800;}"
        ".props-autoload-spinner{width:18px;height:18px;border:2px solid var(--dash-control-border);"
        "border-top-color:var(--dash-accent);border-radius:999px;animation:props-autoload-spin .8s linear infinite;}"
        "@keyframes props-autoload-spin{to{transform:rotate(360deg)}}"
        "</style>"
        "<div class='props-autoload-loading'>"
        "<span class='props-autoload-spinner' aria-hidden='true'></span>"
        "<span>Loading more props</span>"
        "</div>"
    )


def _cached_record_value(record, *keys, default=""):
    value = record
    for key in keys:
        if not isinstance(value, dict):
            return default
        value = value.get(key)
    return default if value is None or value == "" else value


def _cached_homepage_filter_key(values):
    parts = []
    for value in values or []:
        value_key = normalize_name(value).replace(" ", "-")
        if value_key:
            parts.append(value_key)
    parts.sort()
    return "all" if not parts else "--".join(parts)


def _cached_available_prop_options(records):
    seen = {
        str(_cached_record_value(record, "prop", "label", default="")).strip()
        for record in records
    }
    options = [prop for prop in HOMEPAGE_PROP_OPTIONS if prop in seen]
    extras = sorted(prop for prop in seen if prop and prop not in HOMEPAGE_PROP_OPTIONS)
    return options + extras


def _cached_game_filter_options(records):
    game_entries = {}
    base_counts = {}
    for record in records:
        game_pk = normalize_game_pk(_cached_record_value(record, "game", "game_pk", default=""))
        matchup = str(_cached_record_value(record, "game", "matchup", default="")).strip()
        if not game_pk or not matchup or game_pk in game_entries:
            continue
        game_time = str(_cached_record_value(record, "game", "game_time", default="")).strip()
        game_entries[game_pk] = (matchup, game_time)
        base_counts[matchup] = base_counts.get(matchup, 0) + 1

    options = []
    lookup = {}
    for game_pk, (matchup, game_time) in game_entries.items():
        label = matchup
        if base_counts.get(matchup, 0) > 1:
            label = f"{matchup} {game_time or game_pk}"
        if label in lookup:
            label = f"{label} {game_pk}"
        lookup[label] = game_pk
        options.append(label)
    return options, lookup


def _cached_team_filter_options(records):
    option_by_label = {}
    for record in records:
        label = str(_cached_record_value(record, "game", "team_abbr", default="")).strip()
        team_id = str(_cached_record_value(record, "game", "team_id", default="")).strip()
        team_name = str(_cached_record_value(record, "game", "team", default="")).strip()
        if not label:
            continue
        option_by_label[label] = {
            "id": team_id,
            "name": team_name,
            "label": label,
        }
    options = sorted(option_by_label)
    return options, {label: option_by_label[label] for label in options}


def _cached_stat_display(record, label):
    value = _cached_record_value(record, "stats", label, "display", default="")
    return str(value or "—")


def _cached_stat_number(record, label):
    value = _cached_record_value(record, "stats", label, "value", default=None)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _cached_sort_value(record, selected_trend_sort):
    if selected_trend_sort in {"L5", "L10", "L15", "H2H", "SZN"}:
        return _cached_stat_number(record, selected_trend_sort)
    if selected_trend_sort == "AVG":
        avg_value = _cached_stat_number(record, "AVG")
        try:
            line_value = float(_cached_record_value(record, "prop", "line", default=None))
        except (TypeError, ValueError):
            return None
        if avg_value is None:
            return None
        return avg_value - line_value
    if selected_trend_sort == "Best Overall":
        trend_values = [
            _cached_stat_number(record, label)
            for label in ("L5", "L10", "L15", "H2H", "SZN")
        ]
        available_trends = [value for value in trend_values if value is not None]
        if not available_trends:
            trend_score = 0.0
        else:
            trend_score = sum(available_trends) / len(available_trends)

        avg_value = _cached_stat_number(record, "AVG")
        try:
            line_value = float(_cached_record_value(record, "prop", "line", default=None))
        except (TypeError, ValueError):
            line_value = None
        avg_edge = 0.0 if avg_value is None or line_value is None else avg_value - line_value
        avg_edge_bonus = max(min(avg_edge, 5.0), -5.0) * 2.0
        completeness_bonus = len(available_trends) * 0.5
        return trend_score + avg_edge_bonus + completeness_bonus
    return None


def _cached_sort_key(indexed_record, selected_trend_sort):
    index, record = indexed_record
    sort_value = _cached_sort_value(record, selected_trend_sort)
    if sort_value is None:
        return (1, 0.0, index)
    return (0, -sort_value, index)


def _cached_prop_card_tile(label, value):
    value_text = str(value or "—")
    tile_bg = "var(--dash-surface-2)"
    tile_color = "var(--dash-text)"
    try:
        pct_value = float(value_text.replace("%", ""))
        if value_text.endswith("%"):
            if pct_value >= 60:
                tile_bg = "#dcfce7"
                tile_color = "#166534"
            elif pct_value >= 45:
                tile_bg = "#fef3c7"
                tile_color = "#92400e"
            else:
                tile_bg = "#fee2e2"
                tile_color = "#991b1b"
    except (TypeError, ValueError):
        pass
    return (
        "<div style='min-width:88px; padding:10px 12px; border:1px solid var(--dash-border); border-radius:10px; "
        f"background:{tile_bg}; color:{tile_color}; text-align:center;'>"
        f"<div style='font-size:11px; font-weight:900; letter-spacing:.04em;'>{html.escape(str(label))}</div>"
        f"<div style='font-size:17px; font-weight:950; margin-top:4px;'>{html.escape(value_text)}</div>"
        "</div>"
    )


def _cached_player_initials(name):
    parts = [part for part in str(name or "").replace(".", "").split() if part]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return f"{parts[0][0]}{parts[-1][0]}".upper()


def _cached_line_badge(record):
    line_value = _cached_record_value(record, "prop", "line", default="")
    try:
        line_text = f"{float(line_value):.1f}"
    except (TypeError, ValueError):
        line_text = str(line_value or "—")

    source_badges = {
        normalize_name(value)
        for value in (_cached_record_value(record, "prop", "source_badges", default=[]) or [])
    }
    line_types = {
        normalize_name(value)
        for value in (_cached_record_value(record, "prop", "line_types", default=[]) or [])
    }
    show_prizepicks = not source_badges or "prizepicks" in source_badges
    book_badge_html = (
        badge_image_html(SPORTSBOOK_BADGE_ASSETS.get("prizepicks"), "PrizePicks", "book-badge", "book-badge-img")
        if show_prizepicks
        else ""
    )
    modifier_html = []
    if "goblin" in source_badges or "goblin" in line_types:
        modifier_html.append(badge_image_html(MODIFIER_BADGE_ASSETS.get("goblin"), "Goblin", "boost-badge", "modifier-badge-img"))
    if "demon" in source_badges or "demon" in line_types:
        modifier_html.append(badge_image_html(MODIFIER_BADGE_ASSETS.get("demon"), "Demon", "boost-badge", "modifier-badge-img"))
    return (
        '<div class="line-badge">'
        f'<span class="line-value">{html.escape(line_text)}</span>'
        f'{book_badge_html}'
        f'{"".join(modifier_html)}'
        '</div>'
    )


def _cached_props_card_html(record):
    player_name = str(_cached_record_value(record, "player", "name", default=""))
    player_text = html.escape(player_name)
    image_url = str(_cached_record_value(record, "player", "headshot_url", default=""))
    prop_label = str(_cached_record_value(record, "prop", "label", default=""))
    line_value = _cached_record_value(record, "prop", "line", default="")
    try:
        line_text = f"{float(line_value):.1f}"
    except (TypeError, ValueError):
        line_text = str(line_value or "—")
    matchup = str(_cached_record_value(record, "game", "matchup", default="")).strip()
    if not matchup:
        team = _cached_record_value(record, "game", "team", default="—")
        opponent = _cached_record_value(record, "game", "opponent", default="—")
        matchup = f"{team} vs {opponent}"
    game_time = str(_cached_record_value(record, "game", "game_time", default="")).strip()
    if game_time:
        matchup = f"{matchup} - {game_time}"
    hand = str(_cached_record_value(record, "player", "hand", default="")).strip()
    hand_text = f" • {hand}" if hand else ""
    initials_html = (
        f"<span style='font-size:20px; font-weight:950; color:var(--dash-accent);'>"
        f"{html.escape(_cached_player_initials(player_name))}</span>"
    )
    avatar_html = (
        f"<img src='{html.escape(image_url, quote=True)}' alt='{html.escape(player_name, quote=True)}' "
        "style='position:absolute; inset:0; display:block; width:100%; height:100%; object-fit:cover;' "
        "loading='lazy' decoding='async' onerror=\"this.style.display='none';\" />"
        f"{initials_html}"
        if image_url
        else initials_html
    )
    stat_tiles = "".join(
        _cached_prop_card_tile(label, _cached_stat_display(record, label))
        for label in ("L5", "L10", "L15", "H2H", "AVG", "SZN")
    )
    href = str(_cached_record_value(record, "routing", "href", default=""))
    open_link = (
        f"<a href='{html.escape(href, quote=True)}' target='_self' "
        "style='display:inline-flex; align-items:center; justify-content:center; padding:8px 12px; "
        "border-radius:999px; background:var(--dash-accent); color:white; font-size:12px; font-weight:900; "
        "text-decoration:none; white-space:nowrap;'>Open Player</a>"
        if href
        else "<span style='font-size:12px; color:var(--dash-muted); font-weight:700;'>Player detail unavailable</span>"
    )
    status = str(_cached_record_value(record, "prop", "status", default="PrizePicks") or "PrizePicks")
    return (
        "<div style='border:1px solid var(--dash-border); border-radius:14px; background:var(--dash-card-bg); "
        "box-shadow:0 2px 9px rgba(15,23,42,.10); padding:18px; margin:14px 0; color:var(--dash-text);'>"
        "<div style='display:grid; grid-template-columns:auto minmax(220px,1fr) auto; align-items:center; gap:16px;'>"
        "<div style='position:relative; width:68px; height:68px; flex:0 0 auto;'>"
        "<div style='width:68px; height:68px; border-radius:999px; overflow:hidden; border:1px solid var(--dash-border); "
        "background:var(--dash-surface-2); display:flex; align-items:center; justify-content:center;'>"
        f"{avatar_html}"
        "</div>"
        "<div style='position:absolute; right:-3px; top:-4px; width:22px; height:22px; border-radius:999px; "
        "background:var(--dash-card-bg); border:1px solid var(--dash-border); display:flex; align-items:center; "
        "justify-content:center; color:#f59e0b; font-size:13px; font-weight:900;'>☆</div>"
        "</div>"
        "<div style='min-width:0;'>"
        f"<div style='font-size:21px; font-weight:950; line-height:1.1;'>{player_text}</div>"
        f"<div style='font-size:16px; font-weight:950; margin-top:6px;'>O/U {html.escape(line_text)} {html.escape(prop_label)}</div>"
        f"<div style='font-size:12px; color:var(--dash-muted); font-weight:800; margin-top:5px;'>{html.escape(matchup)}{html.escape(hand_text)}</div>"
        "<div style='display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-top:10px;'>"
        f"{_cached_line_badge(record)}"
        f"<div style='font-size:12px; color:var(--dash-muted); font-weight:800;'>{html.escape(status)}</div>"
        f"{open_link}"
        "</div>"
        "</div>"
        "<div style='width:86px; height:86px; border-radius:999px; border:2px solid var(--dash-border); "
        "background:var(--dash-surface-2); display:flex; flex-direction:column; align-items:center; justify-content:center; "
        "font-weight:950; line-height:1.35; color:var(--dash-text);'>"
        "<div style='font-size:15px;'>O —</div>"
        "<div style='font-size:15px;'>U —</div>"
        "</div>"
        "</div>"
        f"<div style='display:flex; gap:10px; flex-wrap:wrap; margin-top:16px;'>{stat_tiles}</div>"
        "</div>"
    )


def _render_cached_homepage_props_tab(cache_payload):
    records = cache_payload.get("records", [])
    available_props = _cached_available_prop_options(records)
    selected_line_type = props_line_type_filter_label_from_query(
        st.session_state.get("props_line_type_filter", "All"),
        default="All",
    )
    st.session_state["props_line_type_filter"] = selected_line_type
    game_filter_options, game_filter_lookup = _cached_game_filter_options(records)
    team_filter_options, team_filter_lookup = _cached_team_filter_options(records)
    props_trend_sort_options = ("Best Overall", "Default", "L5", "L10", "L15", "H2H", "SZN", "AVG")
    props_filter_key = "homepage_props_filter_props"
    games_filter_key = "homepage_props_filter_games"
    teams_filter_key = "homepage_props_filter_teams"
    trend_filter_key = "homepage_props_trend_filter"
    if st.session_state.get(trend_filter_key) not in props_trend_sort_options:
        st.session_state[trend_filter_key] = "Best Overall"
    elif st.session_state.get(trend_filter_key) == "Default" and not st.session_state.get("homepage_props_cached_default_sort_migrated"):
        st.session_state[trend_filter_key] = "Best Overall"
        st.session_state["homepage_props_cached_default_sort_migrated"] = True
    st.session_state[props_filter_key] = [
        prop for prop in st.session_state.get(props_filter_key, []) if prop in available_props
    ]
    st.session_state[games_filter_key] = [
        game for game in st.session_state.get(games_filter_key, []) if game in game_filter_options
    ]
    st.session_state[teams_filter_key] = [
        team for team in st.session_state.get(teams_filter_key, []) if team in team_filter_options
    ]

    filter_cols = st.columns([1.1, 2.2, 2.1, 1.7])
    with filter_cols[0]:
        st.selectbox(
            "Line Type",
            PROPS_LINE_TYPE_FILTER_OPTIONS,
            key="props_line_type_filter",
            on_change=set_homepage_props_line_type,
        )
        st.selectbox(
            "Sort By Trend",
            props_trend_sort_options,
            key=trend_filter_key,
        )
    with filter_cols[1]:
        st.multiselect(
            "Props",
            available_props,
            key=props_filter_key,
            placeholder="All props",
        )
    with filter_cols[2]:
        st.multiselect(
            "Games",
            game_filter_options,
            key=games_filter_key,
            placeholder="All games",
        )
    with filter_cols[3]:
        st.multiselect(
            "Teams",
            team_filter_options,
            key=teams_filter_key,
            placeholder="All teams",
        )

    selected_props_filter = [
        prop for prop in st.session_state.get(props_filter_key, []) if prop in available_props
    ]
    selected_game_filter_labels = [
        game for game in st.session_state.get(games_filter_key, []) if game in game_filter_lookup
    ]
    selected_team_filter_labels = [
        team for team in st.session_state.get(teams_filter_key, []) if team in team_filter_lookup
    ]
    selected_trend_sort = st.session_state.get(trend_filter_key, "Best Overall")
    active_props = set(selected_props_filter or available_props)
    selected_game_filter_ids = {
        game_filter_lookup[label]
        for label in selected_game_filter_labels
        if game_filter_lookup.get(label)
    }
    selected_team_filter_ids = {
        str(team_filter_lookup[label].get("id") or "").strip()
        for label in selected_team_filter_labels
        if team_filter_lookup.get(label, {}).get("id")
    }
    selected_team_filter_labels_set = set(selected_team_filter_labels)

    def _cached_record_matches_filters(record):
        prop_label = str(_cached_record_value(record, "prop", "label", default="")).strip()
        if prop_label not in active_props:
            return False

        line_types = set(_cached_record_value(record, "prop", "line_types", default=[]) or [])
        if selected_line_type != "All" and selected_line_type not in line_types:
            return False

        if selected_game_filter_ids:
            game_pk = normalize_game_pk(_cached_record_value(record, "game", "game_pk", default=""))
            if not game_pk or game_pk not in selected_game_filter_ids:
                return False

        if selected_team_filter_ids or selected_team_filter_labels_set:
            team_id = str(_cached_record_value(record, "game", "team_id", default="")).strip()
            team_abbr = str(_cached_record_value(record, "game", "team_abbr", default="")).strip()
            if team_id and team_id in selected_team_filter_ids:
                return True
            if team_abbr and team_abbr in selected_team_filter_labels_set:
                return True
            return False

        return True

    filtered_records = [
        record for record in records
        if isinstance(record, dict) and _cached_record_matches_filters(record)
    ]
    if selected_trend_sort != "Default":
        indexed_records = list(enumerate(filtered_records))
        indexed_records.sort(key=lambda indexed_record: _cached_sort_key(indexed_record, selected_trend_sort))
        filtered_records = [record for _, record in indexed_records]

    if not filtered_records:
        if selected_line_type == "All":
            st.info("No lines found for the selected filters.")
        else:
            st.info(f"No {selected_line_type} lines found for the selected filters.")
        return

    props_card_batch_size = 12
    selected_date_key = st.session_state.get("selected_date", eastern_today()).isoformat()
    active_prop_filter_key = (
        f"selected-{_cached_homepage_filter_key(selected_props_filter)}"
        if selected_props_filter
        else "all"
    )
    selected_line_type_key = normalize_name(selected_line_type).replace(" ", "-")
    selected_games_key = _cached_homepage_filter_key(selected_game_filter_ids)
    selected_teams_key = _cached_homepage_filter_key(selected_team_filter_labels)
    selected_trend_sort_key = normalize_name(selected_trend_sort).replace(" ", "-")
    props_loaded_card_limit_key = (
        f"cached_props_loaded_card_limit_{selected_date_key}_{active_prop_filter_key}_"
        f"{selected_line_type_key}_{selected_games_key}_{selected_teams_key}_{selected_trend_sort_key}"
    )
    try:
        loaded_card_limit = int(st.session_state.get(props_loaded_card_limit_key, props_card_batch_size) or props_card_batch_size)
    except (TypeError, ValueError):
        loaded_card_limit = props_card_batch_size
    loaded_card_limit = max(props_card_batch_size, loaded_card_limit)
    visible_records = filtered_records[:loaded_card_limit]
    remaining_record_count = max(len(filtered_records) - loaded_card_limit, 0)

    for record in visible_records:
        st.markdown(_cached_props_card_html(record), unsafe_allow_html=True)

    if remaining_record_count > 0:
        load_more_key_parts = (
            selected_date_key,
            active_prop_filter_key,
            selected_line_type_key,
            selected_games_key,
            selected_teams_key,
            selected_trend_sort_key,
        )
        if _props_autoload_enabled():
            _render_props_autoload_sentinel(
                props_loaded_card_limit_key,
                loaded_card_limit,
                props_card_batch_size,
                len(filtered_records),
                load_more_key_parts,
            )
            st.markdown(_props_autoload_loading_html(), unsafe_allow_html=True)
        else:
            st.caption(f"Showing {len(visible_records)} of {len(filtered_records)} props")

            def _load_more_cached_props_rows():
                st.session_state[props_loaded_card_limit_key] = min(
                    len(filtered_records),
                    loaded_card_limit + props_card_batch_size,
                )

            st.button(
                f"Load next {props_card_batch_size} props",
                key=(
                    f"load_more_cached_props_{selected_date_key}_{active_prop_filter_key}_"
                    f"{selected_line_type_key}_{selected_games_key}_{selected_teams_key}_{selected_trend_sort_key}"
                ),
                on_click=_load_more_cached_props_rows,
            )


def render_homepage_props_tab():
    st.markdown("## Props")
    if "games" not in st.session_state:
        st.session_state["games"] = load_schedule(st.session_state["selected_date"])
    games = st.session_state.get("games", pd.DataFrame())

    props_cache_mode = _props_cache_mode()
    if props_cache_mode != "force_live":
        selected_date_key = st.session_state.get("selected_date", eastern_today()).isoformat()
        cache_payload, cache_unavailable_reason = load_props_summary_cache(selected_date_key)
        if cache_payload:
            if props_cache_mode == "force_cache":
                generated_at = cache_payload.get("generated_at", "")
                if generated_at:
                    st.caption(f"Using cached Props summaries generated at {generated_at}.")
                else:
                    st.caption("Using cached Props summaries.")
            _render_cached_homepage_props_tab(cache_payload)
            return
        if props_cache_mode == "force_cache":
            logger.info("Props summary cache unavailable for %s: %s", selected_date_key, cache_unavailable_reason)
            st.caption("Props cache unavailable; using live summaries.")

    try:
        st.session_state["prizepicks_projections"] = load_prizepicks_mlb_projections()
    except Exception as exc:
        logger.warning("Unable to load PrizePicks projections for Props tab: %s", exc)
        st.info("Prop data is unavailable right now.")
        return

    def _projection_matches_homepage_prop(record, prop):
        stat_type = record.get("stat_display_name") or _projection_stat_type(record)
        if prop in PITCHER_GAME_LOG_PROPS:
            return pitcher_prizepicks_prop_match_key(stat_type) == pitcher_prizepicks_prop_match_key(prop)
        return _prop_match_key(stat_type) == _prop_match_key(prop)

    def _homepage_available_prop_options(projections):
        options = list(GAME_LOG_PROPS)
        for prop in PITCHER_GAME_LOG_PROPS:
            if any(
                isinstance(record, dict) and _projection_matches_homepage_prop(record, prop)
                for record in projections
            ):
                options.append(prop)
        return options

    def _homepage_filter_key(values):
        parts = []
        for value in values or []:
            value_key = normalize_name(value).replace(" ", "-")
            if value_key:
                parts.append(value_key)
        parts.sort()
        return "all" if not parts else "--".join(parts)

    def _homepage_game_filter_options(games_df):
        if games_df is None or (isinstance(games_df, pd.DataFrame) and games_df.empty):
            return [], {}

        game_entries = []
        base_counts = {}
        for _, game in games_df.iterrows():
            game_key = normalize_game_pk(game.get("game_pk"))
            if not game_key:
                continue
            away = str(game.get("away_abbrev") or game.get("away_team") or "").strip()
            home = str(game.get("home_abbrev") or game.get("home_team") or "").strip()
            if not away or not home:
                continue
            base_label = f"{away} @ {home}"
            game_time = str(game.get("game_time_et") or "").strip()
            game_entries.append((base_label, game_time, game_key))
            base_counts[base_label] = base_counts.get(base_label, 0) + 1

        options = []
        lookup = {}
        for base_label, game_time, game_key in game_entries:
            label = base_label
            if base_counts.get(base_label, 0) > 1:
                label = f"{base_label} {game_time or game_key}"
            if label in lookup:
                label = f"{label} {game_key}"
            options.append(label)
            lookup[label] = game_key
        return options, lookup

    def _homepage_team_filter_options(games_df):
        if games_df is None or (isinstance(games_df, pd.DataFrame) and games_df.empty):
            return [], {}

        option_by_label = {}
        for _, game in games_df.iterrows():
            for side in ("away", "home"):
                label = str(game.get(f"{side}_abbrev") or game.get(f"{side}_team") or "").strip()
                team_name = str(game.get(f"{side}_team") or "").strip()
                team_id = str(game.get(f"{side}_team_id") or "").strip()
                if not label:
                    continue
                option_by_label[label] = {
                    "id": team_id,
                    "name": team_name,
                    "label": label,
                }
        options = sorted(option_by_label)
        return options, {label: option_by_label[label] for label in options}

    available_props = _homepage_available_prop_options(st.session_state.get("prizepicks_projections", []))
    selected_line_type = props_line_type_filter_label_from_query(
        st.session_state.get("props_line_type_filter", "All"),
        default="All",
    )
    st.session_state["props_line_type_filter"] = selected_line_type
    game_filter_options, game_filter_lookup = _homepage_game_filter_options(games)
    team_filter_options, team_filter_lookup = _homepage_team_filter_options(games)

    props_trend_sort_options = (
        "Default",
        "L5",
        "L10",
        "L15",
        "H2H",
        "SZN",
        "AVG",
    )
    props_filter_key = "homepage_props_filter_props"
    games_filter_key = "homepage_props_filter_games"
    teams_filter_key = "homepage_props_filter_teams"
    trend_filter_key = "homepage_props_trend_filter"
    if st.session_state.get(trend_filter_key) not in props_trend_sort_options:
        st.session_state[trend_filter_key] = "Default"
    st.session_state[props_filter_key] = [
        prop for prop in st.session_state.get(props_filter_key, []) if prop in available_props
    ]
    st.session_state[games_filter_key] = [
        game for game in st.session_state.get(games_filter_key, []) if game in game_filter_options
    ]
    st.session_state[teams_filter_key] = [
        team for team in st.session_state.get(teams_filter_key, []) if team in team_filter_options
    ]

    filter_cols = st.columns([1.1, 2.2, 2.1, 1.7])
    with filter_cols[0]:
        st.selectbox(
            "Line Type",
            PROPS_LINE_TYPE_FILTER_OPTIONS,
            key="props_line_type_filter",
            on_change=set_homepage_props_line_type,
        )
        st.selectbox(
            "Sort By Trend",
            props_trend_sort_options,
            key=trend_filter_key,
        )
    with filter_cols[1]:
        st.multiselect(
            "Props",
            available_props,
            key=props_filter_key,
            placeholder="All props",
        )
    with filter_cols[2]:
        st.multiselect(
            "Games",
            game_filter_options,
            key=games_filter_key,
            placeholder="All games",
        )
    with filter_cols[3]:
        st.multiselect(
            "Teams",
            team_filter_options,
            key=teams_filter_key,
            placeholder="All teams",
        )

    selected_props_filter = [
        prop for prop in st.session_state.get(props_filter_key, []) if prop in available_props
    ]
    selected_game_filter_labels = [
        game for game in st.session_state.get(games_filter_key, []) if game in game_filter_lookup
    ]
    selected_team_filter_labels = [
        team for team in st.session_state.get(teams_filter_key, []) if team in team_filter_lookup
    ]
    selected_trend_sort = st.session_state.get(trend_filter_key, "Default")
    active_props = selected_props_filter or available_props
    active_prop_filter_key = (
        f"selected-{_homepage_filter_key(active_props)}"
        if selected_props_filter
        else "all"
    )
    selected_game_filter_ids = {
        game_filter_lookup[label]
        for label in selected_game_filter_labels
        if game_filter_lookup.get(label)
    }
    selected_team_filter_ids = {
        str(team_filter_lookup[label].get("id") or "").strip()
        for label in selected_team_filter_labels
        if team_filter_lookup.get(label, {}).get("id")
    }

    def _team_lookup_keys(value):
        normalized = normalize_name(value)
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

    selected_team_filter_lookup_keys = set()
    for label in selected_team_filter_labels:
        team_info = team_filter_lookup.get(label, {})
        selected_team_filter_lookup_keys.update(_team_lookup_keys(label))
        selected_team_filter_lookup_keys.update(_team_lookup_keys(team_info.get("name", "")))

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
                pitcher_name_key = normalize_name(pitcher_name)
                if pitcher_name_key and pitcher_name_key != "tbd":
                    pitcher_lookup[f"name:{pitcher_name_key}"] = context
        return pitcher_lookup

    team_context_lookup = _homepage_team_context_lookup(games)
    pitcher_context_lookup = _homepage_pitcher_context_lookup(games)
    player_id_cache = {}
    lineup_fallback_cache = {}

    def _lineup_fallback_info(player_name, team_context):
        game_pk = team_context.get("game_pk", "") if team_context else ""
        if not player_name or not game_pk:
            return {}
        if game_pk not in lineup_fallback_cache:
            lineup_fallback_cache[game_pk] = get_game_lineups(game_pk, team_context.get("game") if team_context else None)
        lineup_context = lineup_fallback_cache.get(game_pk, {}) or {}
        player_key = normalize_name(player_name)
        for side in ("away", "home"):
            for player in lineup_context.get(side, []) or []:
                if normalize_name(player.get("name", "")) == player_key:
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

    def _props_line_match_key(value):
        try:
            return f"{float(value):.4f}"
        except (TypeError, ValueError):
            return str(value or "").strip()

    def _projection_identity_match_key(record, player_name):
        projection_player_id = _projection_player_id(record)
        if projection_player_id:
            return f"id:{projection_player_id}"
        return f"name:{normalize_name(player_name)}"

    def _props_status_from_projection_matches(exact_projection_lines):
        labels = []
        seen_labels = set()
        for projection_line in exact_projection_lines or []:
            odds_type = normalize_name(_projection_value(projection_line, "odds_type", "oddsType", default=""))
            label = "Goblin" if odds_type == "goblin" else "Demon" if odds_type == "demon" else "PP Reg Line"
            if label not in seen_labels:
                labels.append(label)
                seen_labels.add(label)
        return f"PrizePicks • {'/'.join(labels)}" if labels else "PrizePicks"

    def _projection_line_type(record):
        odds_type = normalize_name(_projection_value(record, "odds_type", "oddsType", default=""))
        if odds_type == "goblin":
            return "Goblin"
        if odds_type == "demon":
            return "Demon"
        return "PP Reg Line"

    def _homepage_prop_match_key(prop):
        if prop in PITCHER_GAME_LOG_PROPS:
            return pitcher_prizepicks_prop_match_key(prop)
        return _prop_match_key(prop)

    def _projection_looks_like_pitcher(record, player_name):
        projection_player_id = _projection_player_id(record)
        if projection_player_id and pitcher_context_lookup.get(f"id:{projection_player_id}"):
            return True
        return bool(pitcher_context_lookup.get(f"name:{normalize_name(player_name)}"))

    def _projection_homepage_prop(record, candidate_props):
        player_name = str(record.get("player") or _projection_player_name(record) or "").strip()
        stat_type = record.get("stat_display_name") or _projection_stat_type(record)
        pitcher_like = _projection_looks_like_pitcher(record, player_name)
        pitcher_matches = [
            prop for prop in candidate_props
            if prop in PITCHER_GAME_LOG_PROPS
            and pitcher_prizepicks_prop_match_key(stat_type) == pitcher_prizepicks_prop_match_key(prop)
        ]
        batter_matches = [
            prop for prop in candidate_props
            if prop not in PITCHER_GAME_LOG_PROPS
            and _prop_match_key(stat_type) == _prop_match_key(prop)
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

    selected_prop_projection_records = []
    for record in st.session_state.get("prizepicks_projections", []):
        if not isinstance(record, dict):
            continue
        record_prop = _projection_homepage_prop(record, active_props)
        if not record_prop:
            continue
        selected_prop_projection_records.append((record, record_prop))

    if selected_line_type == "All":
        selected_projection_records = list(selected_prop_projection_records)
    else:
        selected_projection_records = [
            (record, record_prop) for record, record_prop in selected_prop_projection_records
            if _projection_line_type(record) == selected_line_type
        ]

    records_by_exact_key = {}
    for record, record_prop in selected_prop_projection_records:
        player_name = str(record.get("player") or _projection_player_name(record) or "").strip()
        line_value = _projection_line_value(record)
        record_prop_key = _homepage_prop_match_key(record_prop)
        exact_key = (
            _projection_identity_match_key(record, player_name),
            record_prop_key,
            _props_line_match_key(line_value),
        )
        records_by_exact_key.setdefault(exact_key, []).append(record)

    rows = []
    seen = set()
    for record, record_prop in selected_projection_records:
        player_name = str(record.get("player") or _projection_player_name(record) or "").strip()
        if not player_name:
            continue
        line_value = _projection_line_value(record)
        record_prop_key = _homepage_prop_match_key(record_prop)
        exact_key = (
            _projection_identity_match_key(record, player_name),
            record_prop_key,
            _props_line_match_key(line_value),
        )
        unique_key = exact_key
        if unique_key in seen:
            continue
        seen.add(unique_key)

        exact_projection_lines = records_by_exact_key.get(exact_key, [record])
        preferred_line = preferred_projection_line(exact_projection_lines) or record
        odds_type = _projection_value(preferred_line, "odds_type", "oddsType", default="")
        projection_player_id = _projection_player_id(record)
        pitcher_context = {}
        selected_is_pitcher_prop = record_prop in PITCHER_GAME_LOG_PROPS
        if selected_is_pitcher_prop:
            if projection_player_id:
                pitcher_context = pitcher_context_lookup.get(f"id:{projection_player_id}", {})
            if not pitcher_context:
                pitcher_context = pitcher_context_lookup.get(f"name:{normalize_name(player_name)}", {})

        projection_team = _projection_value(record, "team", default="")
        team_context = pitcher_context if selected_is_pitcher_prop else {}
        for key in _team_lookup_keys(projection_team):
            team_context = team_context or team_context_lookup.get(key, {})
            if team_context:
                break
        team = team_context.get("team") or projection_team
        team_id = team_context.get("team_id", "")
        opponent = team_context.get("opponent") or _projection_value(record, "description", default="")
        opponent_id = team_context.get("opponent_id", "")
        game_pk = team_context.get("game_pk", "")
        game_time = team_context.get("game_time", "")

        rows.append({
            "player": player_name,
            "href": "",
            "team": team,
            "team_abbr": team_context.get("team_abbr", ""),
            "team_id": team_id,
            "opponent": opponent,
            "opponent_id": opponent_id,
            "opponent_abbr": team_context.get("opponent_abbr", ""),
            "hand": team_context.get("hand", "") if selected_is_pitcher_prop else "",
            "player_id": "",
            "projection_player_id": projection_player_id or team_context.get("player_id", ""),
            "projection_image_url": _projection_value(record, "image_url", "imageUrl", default=""),
            "team_context": team_context,
            "game_pk": game_pk,
            "side": team_context.get("side", ""),
            "player_type": "pitcher" if selected_is_pitcher_prop else "batter",
            "prop": record_prop,
            "line": line_value,
            "odds_type": odds_type,
            "exact_projection_lines": exact_projection_lines,
            "status": _props_status_from_projection_matches(exact_projection_lines),
            "image_url": _projection_value(record, "image_url", "imageUrl", default=""),
            "game_time": game_time,
        })

    def _props_row_matches_multiselect_filters(row):
        if selected_game_filter_ids:
            row_game_key = normalize_game_pk(row.get("game_pk"))
            if not row_game_key or row_game_key not in selected_game_filter_ids:
                return False

        if selected_team_filter_ids or selected_team_filter_lookup_keys:
            row_team_id = str(row.get("team_id") or "").strip()
            row_team_keys = set()
            row_team_keys.update(_team_lookup_keys(row.get("team", "")))
            row_team_keys.update(_team_lookup_keys(row.get("team_abbr", "")))
            if row_team_id and row_team_id in selected_team_filter_ids:
                return True
            if row_team_keys and row_team_keys.intersection(selected_team_filter_lookup_keys):
                return True
            return False

        return True

    rows = [
        row for row in rows
        if _props_row_matches_multiselect_filters(row)
    ]

    def _props_sort_line(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    rows.sort(key=lambda row: (str(row.get("team", "")), str(row.get("player", "")), _props_sort_line(row.get("line"))))
    if not rows:
        if selected_line_type == "All":
            st.info("No lines found for the selected filters.")
        else:
            st.info(f"No {selected_line_type} lines found for the selected filters.")
        return

    def _prop_card_tile(label, value):
        value_text = str(value or "—")
        tile_bg = "var(--dash-surface-2)"
        tile_color = "var(--dash-text)"
        try:
            pct_value = float(value_text.replace("%", ""))
            if value_text.endswith("%"):
                if pct_value >= 60:
                    tile_bg = "#dcfce7"
                    tile_color = "#166534"
                elif pct_value >= 45:
                    tile_bg = "#fef3c7"
                    tile_color = "#92400e"
                else:
                    tile_bg = "#fee2e2"
                    tile_color = "#991b1b"
        except (TypeError, ValueError):
            pass
        return (
            "<div style='min-width:88px; padding:10px 12px; border:1px solid var(--dash-border); border-radius:10px; "
            f"background:{tile_bg}; color:{tile_color}; text-align:center;'>"
            f"<div style='font-size:11px; font-weight:900; letter-spacing:.04em;'>{html.escape(str(label))}</div>"
            f"<div style='font-size:17px; font-weight:950; margin-top:4px;'>{html.escape(value_text)}</div>"
            "</div>"
        )

    def _player_initials(name):
        parts = [part for part in str(name or "").replace(".", "").split() if part]
        if not parts:
            return "?"
        if len(parts) == 1:
            return parts[0][:2].upper()
        return f"{parts[0][0]}{parts[-1][0]}".upper()

    def _props_blank_stat_values():
        return {label: "—" for label in ("L5", "L10", "L15", "H2H", "AVG", "SZN")}

    def _props_stat_cache_key(row):
        player_type = row.get("player_type") or "batter"
        if player_type == "pitcher":
            prop_column = PITCHER_GAME_LOG_PROP_COLUMNS.get(row.get("prop"))
        else:
            prop_column = GAME_LOG_PROP_COLUMNS.get(row.get("prop"))
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
            normalize_name(row.get("opponent", "")),
        )

    def _props_summary_from_values(values, selected_prop_line, prop_column, empty_hit_rate_text="--", empty_avg_text="--"):
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
            "avg_text": prop_average_text(avg_value, prop_column),
            "indicator": indicator,
            "games": int(len(values)),
        }

    def _props_numeric_sample_values(game_log_df, prop_column, sample_label):
        sample_df = game_log_sample_dataframe(game_log_df, sample_label)
        if sample_df.empty or prop_column not in sample_df.columns:
            return pd.Series(dtype="float64")
        return pd.to_numeric(sample_df[prop_column], errors="coerce").dropna()

    def _build_props_stat_summary_cache(rows):
        stat_summary_cache = {}
        rows_by_game_log_key = {}
        for row in rows:
            cache_key = _props_stat_cache_key(row)
            if not cache_key:
                continue
            player_type, player_id, prop_column, _, _, _ = cache_key
            include_first_inning = player_type == "batter" and prop_column == "first_inning_hrrrbi"
            rows_by_game_log_key.setdefault((player_type, player_id, include_first_inning), []).append((row, cache_key))

        for (player_type, player_id, include_first_inning), player_rows in rows_by_game_log_key.items():
            if player_type == "pitcher":
                game_log_df = load_pitcher_prop_game_log(player_id)
            else:
                game_log_df = load_batter_prop_game_log(
                    player_id,
                    include_first_inning=include_first_inning,
                )
            if game_log_df.empty:
                for _, cache_key in player_rows:
                    stat_summary_cache[cache_key] = _props_blank_stat_values()
                continue

            rows_by_prop = {}
            for row, cache_key in player_rows:
                prop_column = cache_key[2]
                rows_by_prop.setdefault(prop_column, []).append((row, cache_key))

            for prop_column, prop_rows in rows_by_prop.items():
                if prop_column not in game_log_df.columns:
                    for _, cache_key in prop_rows:
                        stat_summary_cache[cache_key] = _props_blank_stat_values()
                    continue

                sample_values = {
                    sample_label: _props_numeric_sample_values(game_log_df, prop_column, sample_label)
                    for sample_label in ("L5", "L10", "L15", "2026")
                }
                h2h_values_cache = {}
                for row, cache_key in prop_rows:
                    _, _, _, selected_prop_line, opponent_id, opponent_name_key = cache_key
                    stat_values = _props_blank_stat_values()

                    for sample_label in ("L5", "L10", "L15"):
                        summary = _props_summary_from_values(sample_values[sample_label], selected_prop_line, prop_column)
                        stat_values[sample_label] = summary.get("hit_rate_text", "--")

                    season_summary = _props_summary_from_values(sample_values["2026"], selected_prop_line, prop_column)
                    stat_values["AVG"] = season_summary.get("avg_text", "--")
                    stat_values["SZN"] = season_summary.get("hit_rate_text", "--")

                    if opponent_id or opponent_name_key:
                        h2h_cache_key = (opponent_id, opponent_name_key)
                        if h2h_cache_key not in h2h_values_cache:
                            opponent_context = {
                                "id": opponent_id,
                                "name": str(row.get("opponent") or "").strip(),
                                "abbr": "",
                            }
                            h2h_df = filter_game_logs_vs_opponent(game_log_df, opponent_context)
                            if h2h_df.empty or prop_column not in h2h_df.columns:
                                h2h_values_cache[h2h_cache_key] = pd.Series(dtype="float64")
                            else:
                                h2h_values_cache[h2h_cache_key] = pd.to_numeric(
                                    h2h_df[prop_column],
                                    errors="coerce",
                                ).dropna()
                        h2h_summary = _props_summary_from_values(
                            h2h_values_cache[h2h_cache_key],
                            selected_prop_line,
                            prop_column,
                            empty_hit_rate_text="N/A",
                            empty_avg_text="—",
                        )
                        if h2h_summary.get("games", 0) > 0:
                            stat_values["H2H"] = h2h_summary.get("hit_rate_text", "—")

                    stat_summary_cache[cache_key] = stat_values

        return stat_summary_cache

    def _props_card_stat_values(row, stat_summary_cache):
        cache_key = _props_stat_cache_key(row)
        if not cache_key:
            return _props_blank_stat_values()
        return stat_summary_cache.get(cache_key, _props_blank_stat_values())

    def _props_stat_number(value, *, percent=False):
        value_text = str(value or "").strip()
        if not value_text or value_text in {"—", "--", "N/A"}:
            return None
        if percent and not value_text.endswith("%"):
            return None
        try:
            return float(value_text.replace("%", "").replace(",", ""))
        except (TypeError, ValueError):
            return None

    def _props_trend_sort_value(row, stat_values):
        percent_sorts = {
            "L5": "L5",
            "L10": "L10",
            "L15": "L15",
            "H2H": "H2H",
            "SZN": "SZN",
        }
        if selected_trend_sort in percent_sorts:
            return _props_stat_number(
                stat_values.get(percent_sorts[selected_trend_sort]),
                percent=True,
            )

        if selected_trend_sort == "AVG":
            avg_value = _props_stat_number(stat_values.get("AVG"))
            try:
                line_value = float(row.get("line"))
            except (TypeError, ValueError):
                return None
            if avg_value is None:
                return None
            return avg_value - line_value

        return None

    def _props_trend_sort_key(indexed_row):
        index, row, stat_values = indexed_row
        sort_value = _props_trend_sort_value(row, stat_values)
        if sort_value is None:
            return (1, 0.0, index)
        return (0, -sort_value, index)

    def _props_card_html(row, stat_values):
        player_text = html.escape(row["player"])
        exact_projection_lines = row.get("exact_projection_lines") or []
        if exact_projection_lines:
            line_html = render_line_badge_for_projection_matches(row.get("line"), exact_projection_lines)
        else:
            line_html = render_line_badge(row.get("line"), row.get("odds_type", ""), show_book_badge=True)
        try:
            line_text = f"{float(row.get('line')):.1f}"
        except (TypeError, ValueError):
            line_text = str(row.get("line") or "—")
        matchup = f"{row.get('team') or '—'} vs {row.get('opponent') or '—'}"
        if row.get("game_time"):
            matchup = f"{matchup} - {row.get('game_time')}"
        hand_text = f" • {row.get('hand')}" if row.get("hand") else ""
        initials_html = (
            f"<span style='font-size:20px; font-weight:950; color:var(--dash-accent);'>"
            f"{html.escape(_player_initials(row['player']))}</span>"
        )
        avatar_html = (
            f"<img src='{html.escape(str(row.get('image_url')), quote=True)}' alt='{html.escape(row['player'], quote=True)}' "
            "style='position:absolute; inset:0; display:block; width:100%; height:100%; object-fit:cover;' "
            "loading='lazy' decoding='async' onerror=\"this.style.display='none';\" />"
            f"{initials_html}"
            if row.get("image_url")
            else initials_html
        )
        stat_tiles = "".join(
            _prop_card_tile(label, stat_values.get(label, "—"))
            for label in ("L5", "L10", "L15", "H2H", "AVG", "SZN")
        )
        open_link = (
            f"<a href='{html.escape(row['href'], quote=True)}' target='_self' "
            "style='display:inline-flex; align-items:center; justify-content:center; padding:8px 12px; "
            "border-radius:999px; background:var(--dash-accent); color:white; font-size:12px; font-weight:900; "
            "text-decoration:none; white-space:nowrap;'>Open Player</a>"
            if row.get("href")
            else "<span style='font-size:12px; color:var(--dash-muted); font-weight:700;'>Player detail unavailable</span>"
        )
        return (
            "<div style='border:1px solid var(--dash-border); border-radius:14px; background:var(--dash-card-bg); "
            "box-shadow:0 2px 9px rgba(15,23,42,.10); padding:18px; margin:14px 0; color:var(--dash-text);'>"
            "<div style='display:grid; grid-template-columns:auto minmax(220px,1fr) auto; align-items:center; gap:16px;'>"
            "<div style='position:relative; width:68px; height:68px; flex:0 0 auto;'>"
            "<div style='width:68px; height:68px; border-radius:999px; overflow:hidden; border:1px solid var(--dash-border); "
            "background:var(--dash-surface-2); display:flex; align-items:center; justify-content:center;'>"
            f"{avatar_html}"
            "</div>"
            "<div style='position:absolute; right:-3px; top:-4px; width:22px; height:22px; border-radius:999px; "
            "background:var(--dash-card-bg); border:1px solid var(--dash-border); display:flex; align-items:center; "
            "justify-content:center; color:#f59e0b; font-size:13px; font-weight:900;'>☆</div>"
            "</div>"
            "<div style='min-width:0;'>"
            f"<div style='font-size:21px; font-weight:950; line-height:1.1;'>{player_text}</div>"
            f"<div style='font-size:16px; font-weight:950; margin-top:6px;'>O/U {html.escape(line_text)} {html.escape(str(row.get('prop') or ''))}</div>"
            f"<div style='font-size:12px; color:var(--dash-muted); font-weight:800; margin-top:5px;'>{html.escape(matchup)}{html.escape(hand_text)}</div>"
            "<div style='display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-top:10px;'>"
            f"{line_html}"
            f"<div style='font-size:12px; color:var(--dash-muted); font-weight:800;'>{html.escape(str(row.get('status', '') or 'PrizePicks'))}</div>"
            f"{open_link}"
            "</div>"
            "</div>"
            "<div style='width:86px; height:86px; border-radius:999px; border:2px solid var(--dash-border); "
            "background:var(--dash-surface-2); display:flex; flex-direction:column; align-items:center; justify-content:center; "
            "font-weight:950; line-height:1.35; color:var(--dash-text);'>"
            "<div style='font-size:15px;'>O —</div>"
            "<div style='font-size:15px;'>U —</div>"
            "</div>"
            "</div>"
            f"<div style='display:flex; gap:10px; flex-wrap:wrap; margin-top:16px;'>{stat_tiles}</div>"
            "</div>"
        )

    def _enrich_props_card_identity(row):
        player_name = row.get("player", "")
        player_type = row.get("player_type") or "batter"
        row_prop = row.get("prop") or selected_prop
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
            player_cache_key = (normalize_name(player_name), str(team_id or ""))
            if player_cache_key not in player_id_cache:
                player_id_cache[player_cache_key] = resolve_player_id_from_team_roster(player_name, team_id)
            player_id = player_id_cache[player_cache_key]

        if player_type == "batter" and not player_id:
            lineup_info = _lineup_fallback_info(player_name, team_context)
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
                pitcher_info = get_players_info((int(float(player_id)),))
                hand = format_pitcher_hand(normalize_hand_code(pitcher_info.get(int(float(player_id)), {}).get("pitchHand", "")))
            except (TypeError, ValueError):
                hand = hand or ""

        image_url = mlb_player_headshot_url(player_id) or row.get("projection_image_url", "")

        detail_href = ""
        if player_type == "pitcher":
            detail_href = _build_pitcher_detail_href(
                player_id,
                pitcher_name=player_name,
                pitcher_hand=hand,
                pitcher_side=side,
                game_pk=game_pk,
                prop=row_prop,
                line=row.get("line"),
            )
        elif player_id:
            detail_href = _build_batter_detail_href(
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

    props_card_batch_size = 12
    selected_date_key = st.session_state.get("selected_date", eastern_today()).isoformat()
    selected_line_type_key = normalize_name(selected_line_type).replace(" ", "-")
    selected_games_key = _homepage_filter_key(selected_game_filter_ids)
    selected_teams_key = _homepage_filter_key(selected_team_filter_labels)
    selected_trend_sort_key = normalize_name(selected_trend_sort).replace(" ", "-")
    props_loaded_card_limit_key = (
        f"props_loaded_card_limit_{selected_date_key}_{active_prop_filter_key}_"
        f"{selected_line_type_key}_{selected_games_key}_{selected_teams_key}_{selected_trend_sort_key}"
    )
    try:
        loaded_card_limit = int(st.session_state.get(props_loaded_card_limit_key, props_card_batch_size) or props_card_batch_size)
    except (TypeError, ValueError):
        loaded_card_limit = props_card_batch_size
    loaded_card_limit = max(props_card_batch_size, loaded_card_limit)
    visible_rows = rows[:loaded_card_limit]
    remaining_row_count = max(len(rows) - loaded_card_limit, 0)

    with st.spinner("Loading prop cards..."):
        enriched_visible_rows = [
            _enrich_props_card_identity(dict(row))
            for row in visible_rows
        ]
        stat_summary_cache = _build_props_stat_summary_cache(enriched_visible_rows)

    trend_sorted_visible_rows = []
    for index, row in enumerate(enriched_visible_rows):
        stat_values = _props_card_stat_values(row, stat_summary_cache)
        trend_sorted_visible_rows.append((index, row, stat_values))

    if selected_trend_sort != "Default":
        trend_sorted_visible_rows.sort(key=_props_trend_sort_key)

    for _, row, stat_values in trend_sorted_visible_rows:
        st.markdown(
            _props_card_html(row, stat_values),
            unsafe_allow_html=True,
        )

    if remaining_row_count > 0:
        st.caption(f"Showing {len(visible_rows)} of {len(rows)} props")

        def _load_more_props_rows():
            st.session_state[props_loaded_card_limit_key] = min(
                len(rows),
                loaded_card_limit + props_card_batch_size,
            )

        st.button(
            f"Load next {props_card_batch_size} props",
            key=(
                f"load_more_props_{selected_date_key}_{active_prop_filter_key}_"
                f"{selected_line_type_key}_{selected_games_key}_{selected_teams_key}_{selected_trend_sort_key}"
            ),
            on_click=_load_more_props_rows,
        )


def render_homepage():
    if st.session_state["calendar_date"] != st.session_state["selected_date"]:
        st.session_state["calendar_date"] = st.session_state["selected_date"]

    homepage_tab_label = "Props" if st.session_state.get("home_tab") == "props" else "Lineups"
    if st.session_state.get("homepage_tab_switch") != homepage_tab_label:
        st.session_state["homepage_tab_switch"] = homepage_tab_label

    st.segmented_control(
        "Homepage View",
        ["Lineups", "Props"],
        key="homepage_tab_switch",
        on_change=set_homepage_tab,
        label_visibility="collapsed",
    )

    if st.session_state.get("home_tab") == "props":
        _ensure_query_params(_with_props_cache_query_param({
            "date": st.session_state.get("selected_date", eastern_today()).isoformat(),
            "home_tab": "props",
            "prop": st.session_state.get("homepage_selected_prop", "Hits"),
            "line_type": st.session_state.get("props_line_type_filter", "All"),
        }))
        render_homepage_props_tab()
        st.stop()

    _ensure_query_params({
        "date": st.session_state.get("selected_date", eastern_today()).isoformat(),
        "home_tab": "lineups",
    })

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


def main():
    _render_page_header_and_styles()
    _initialize_page_state_from_query()
    render_selected_batter_view()
    render_selected_pitcher_view()
    render_homepage()


if __name__ == "__main__":
    main()
