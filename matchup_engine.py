"""
Reusable raw matchup-data access for non-Streamlit consumers.

This module intentionally does not score, rank, or render anything. It gathers
the baseball data that already exists in app.py and strike_zone.py so a Discord
bot can consume the same foundation later.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import importlib
import os
from time import perf_counter
from datetime import date
from typing import Any, Callable

import pandas as pd

import strike_zone
import performance_profile

__all__ = ["get_matchup_data"]


def _timing_enabled() -> bool:
    return os.getenv("TEST_MODE", "").strip().lower() in {"1", "true", "yes", "on"} or os.getenv(
        "MATCHUP_TIMING_LOGS", ""
    ).strip().lower() in {"1", "true", "yes", "on"}


class _TimingLogger:
    def __init__(self, enabled: bool | None = None) -> None:
        self.enabled = _timing_enabled() if enabled is None else enabled
        self.started_at = perf_counter()

    def log(self, label: str, step_started_at: float | None = None) -> None:
        if not self.enabled:
            return
        elapsed = perf_counter() - self.started_at
        if step_started_at is None:
            print(f"[{elapsed:.2f}s] {label}")
            return
        step_elapsed = perf_counter() - step_started_at
        print(f"[{elapsed:.2f}s] {label} (+{step_elapsed:.2f}s)")

    def timed(self, label: str, function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        step_started_at = perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            self.log(label, step_started_at)


def _safe_int_id(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _json_safe(value: Any) -> Any:
    if isinstance(value, pd.DataFrame):
        return [_json_safe(record) for record in value.to_dict("records")]
    if isinstance(value, pd.Series):
        return [_json_safe(item) for item in value.tolist()]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _call_existing(
    errors: list[str],
    label: str,
    func: Callable[..., Any],
    *args: Any,
    default: Any = None,
    **kwargs: Any,
) -> Any:
    try:
        return func(*args, **kwargs)
    except Exception as exc:
        errors.append(f"{label} failed: {exc}")
        return default


def _profiled_existing_call(
    profile_label: str,
    timer: _TimingLogger,
    timing_label: str,
    errors: list[str],
    error_label: str,
    function: Callable[..., Any],
    args: tuple[Any, ...],
    default: Any,
) -> Any:
    with performance_profile.timed(profile_label):
        return timer.timed(
            timing_label,
            _call_existing,
            errors,
            error_label,
            function,
            *args,
            default=default,
        )


def _load_app_module(errors: list[str]) -> Any | None:
    try:
        return importlib.import_module("app")
    except Exception as exc:
        errors.append(
            "Unable to import app.py. TODO: app.py currently mixes reusable "
            f"data functions with top-level Streamlit rendering, so importing "
            f"it can execute the website instead of acting like a pure library. "
            f"Original error: {exc}"
        )
        return None


def _zone_payload(zone_df: Any, outer_stats: Any, denominator: Any) -> dict[str, Any]:
    return {
        "zone_rows": _json_safe(zone_df),
        "outer_stats": _json_safe(outer_stats),
        "denominator": _json_safe(denominator),
    }


def _batter_home_run_zone_data(
    errors: list[str],
    batter_id: Any,
    pitcher_hand: str = "",
) -> dict[str, Any] | None:
    season_year = date.today().year
    start_date = f"{season_year}-03-01"
    end_date = date.today().isoformat()

    raw_df = _call_existing(
        errors,
        "strike_zone.load_batter_pitch_location_data",
        strike_zone.load_batter_pitch_location_data,
        batter_id,
        start_date,
        end_date,
        default=pd.DataFrame(),
    )
    if raw_df is None or raw_df.empty:
        return None

    overall_zone_df, overall_outer_stats, overall_denominator = _call_existing(
        errors,
        "strike_zone._build_distribution_zone_outputs(Home Runs)",
        strike_zone._build_distribution_zone_outputs,
        raw_df,
        "Home Runs",
        default=(pd.DataFrame(), {}, 0),
    )

    payload = {
        "overall": _zone_payload(overall_zone_df, overall_outer_stats, overall_denominator),
        "vs_pitcher_hand": None,
        "source_functions": [
            "strike_zone.load_batter_pitch_location_data",
            "strike_zone._build_distribution_zone_outputs",
        ],
    }

    if pitcher_hand in {"RHP", "LHP"}:
        filtered_df = _call_existing(
            errors,
            f"strike_zone.filter_by_pitcher_throws({pitcher_hand})",
            strike_zone.filter_by_pitcher_throws,
            raw_df,
            pitcher_hand,
            default=pd.DataFrame(),
        )
        split_zone_df, split_outer_stats, split_denominator = _call_existing(
            errors,
            f"strike_zone._build_distribution_zone_outputs(Home Runs, {pitcher_hand})",
            strike_zone._build_distribution_zone_outputs,
            filtered_df,
            "Home Runs",
            default=(pd.DataFrame(), {}, 0),
        )
        payload["vs_pitcher_hand"] = {
            "pitcher_hand": pitcher_hand,
            **_zone_payload(split_zone_df, split_outer_stats, split_denominator),
        }
        payload["source_functions"].append("strike_zone.filter_by_pitcher_throws")

    return payload


def _batter_plate_discipline_zone_data(
    errors: list[str],
    batter_id: Any,
    pitcher_hand: str = "",
) -> dict[str, Any] | None:
    season_year = date.today().year
    start_date = f"{season_year}-03-01"
    end_date = date.today().isoformat()

    raw_df = _call_existing(
        errors,
        "strike_zone.load_batter_pitch_location_data(plate discipline)",
        strike_zone.load_batter_pitch_location_data,
        batter_id,
        start_date,
        end_date,
        default=pd.DataFrame(),
    )
    if raw_df is None or raw_df.empty or "zone" not in raw_df.columns:
        return None

    working_df = raw_df.copy()
    if pitcher_hand in {"RHP", "LHP"}:
        filtered_df = _call_existing(
            errors,
            f"strike_zone.filter_by_pitcher_throws(plate discipline, {pitcher_hand})",
            strike_zone.filter_by_pitcher_throws,
            working_df,
            pitcher_hand,
            default=pd.DataFrame(),
        )
        if filtered_df is not None and not filtered_df.empty:
            working_df = filtered_df

    zone_ids = working_df["zone"].apply(strike_zone._normalize_zone_value)
    outside_mask = zone_ids.isin(set(strike_zone.OUTER_ZONE_TO_QUAD))
    outside_df = working_df[outside_mask].copy()
    if outside_df.empty:
        return {
            "pitcher_hand_filter": pitcher_hand or "All",
            "outside_pitch_count": 0,
            "outside_take_count": 0,
            "outside_take_pct": None,
            "source_functions": [
                "strike_zone.load_batter_pitch_location_data",
                "strike_zone.filter_by_pitcher_throws",
                "strike_zone._is_take_description",
            ],
        }

    descriptions = (
        outside_df["description"]
        if "description" in outside_df.columns
        else pd.Series("", index=outside_df.index)
    )
    take_mask = descriptions.apply(strike_zone._is_take_description)
    outside_pitch_count = int(len(outside_df))
    outside_take_count = int(take_mask.sum())

    return {
        "pitcher_hand_filter": pitcher_hand or "All",
        "outside_pitch_count": outside_pitch_count,
        "outside_take_count": outside_take_count,
        "outside_take_pct": (outside_take_count / outside_pitch_count * 100.0) if outside_pitch_count else None,
        "source_functions": [
            "strike_zone.load_batter_pitch_location_data",
            "strike_zone.filter_by_pitcher_throws",
            "strike_zone._is_take_description",
        ],
    }


def _to_float(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return float(str(value).replace("%", "").strip())
    except (TypeError, ValueError):
        return None


RARE_PITCH_USAGE_CUTOFF = 1.0


def _pitch_name_key(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return ""

    normalized = normalized.replace("_", " ").replace("-", " ")
    normalized = " ".join(normalized.split())

    if "sweeper" in normalized or "slider" in normalized or "slurve" in normalized:
        return "slider_sweeper"
    if "knuckle curve" in normalized or "knucklecurve" in normalized or "curveball" in normalized:
        return "curveball"
    if "split" in normalized or "forkball" in normalized:
        return "splitter"
    if "4 seam" in normalized or "four seam" in normalized:
        return "four_seam_fastball"
    if "sinker" in normalized or "2 seam" in normalized or "two seam" in normalized:
        return "sinker"
    if "cutter" in normalized or "cut fastball" in normalized:
        return "cutter"
    if "changeup" in normalized or "change up" in normalized:
        return "changeup"
    if "fastball" in normalized:
        return "fastball"
    return normalized


def _pitch_variant_key(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return ""

    normalized = normalized.replace("_", " ").replace("-", " ")
    normalized = " ".join(normalized.split())

    if "sweeper" in normalized:
        return "sweeper"
    if "slider" in normalized:
        return "slider"
    if "slurve" in normalized:
        return "slurve"
    if "knuckle curve" in normalized or "knucklecurve" in normalized:
        return "knuckle_curve"
    if "curveball" in normalized:
        return "curveball"
    if "split" in normalized:
        return "splitter"
    if "forkball" in normalized:
        return "forkball"
    if "4 seam" in normalized or "four seam" in normalized:
        return "four_seam_fastball"
    if "sinker" in normalized:
        return "sinker"
    if "2 seam" in normalized or "two seam" in normalized:
        return "two_seam_fastball"
    if "cutter" in normalized or "cut fastball" in normalized:
        return "cutter"
    if "changeup" in normalized or "change up" in normalized:
        return "changeup"
    if "fastball" in normalized:
        return "fastball"
    return normalized


def _pitch_column(df: pd.DataFrame) -> str:
    return "pitch_name" if "pitch_name" in df.columns else "pitch_type" if "pitch_type" in df.columns else ""


def _pitch_mix_for_batter_hand(matchup: dict[str, Any]) -> list[dict[str, Any]]:
    pitch_mix = matchup.get("pitch_mix") or {}
    batter_hand = str(matchup.get("batter_handedness") or "").upper()
    split_key = batter_hand if batter_hand in {"R", "L"} else "all"
    split_rows = pitch_mix.get(split_key) if isinstance(pitch_mix, dict) else None
    if split_rows:
        return split_rows
    return pitch_mix.get("all", []) if isinstance(pitch_mix, dict) else []


def _pitch_family_label(key: str, names: list[Any] | None = None) -> str:
    labels = {
        "slider_sweeper": "Slider/Sweeper",
        "curveball": "Curveball/Knuckle Curve",
        "splitter": "Splitter/Split-Finger",
        "four_seam_fastball": "4-Seam Fastball",
        "sinker": "Sinker/Two-Seam",
        "cutter": "Cutter",
        "changeup": "Changeup",
        "fastball": "Fastball",
    }
    if key in labels:
        return labels[key]
    clean_names = [str(name).strip() for name in names or [] if str(name or "").strip()]
    return "/".join(sorted(set(clean_names))) if clean_names else key


def _pitch_variant_label(key: str, names: list[Any] | None = None) -> str:
    labels = {
        "slider": "Slider",
        "sweeper": "Sweeper",
        "slurve": "Slurve",
        "curveball": "Curveball",
        "knuckle_curve": "Knuckle Curve",
        "splitter": "Splitter/Split-Finger",
        "forkball": "Forkball",
        "four_seam_fastball": "4-Seam Fastball",
        "sinker": "Sinker",
        "two_seam_fastball": "Two-Seam Fastball",
        "cutter": "Cutter",
        "changeup": "Changeup",
        "fastball": "Fastball",
    }
    if key in labels:
        return labels[key]
    clean_names = [str(name).strip() for name in names or [] if str(name or "").strip()]
    return "/".join(sorted(set(clean_names))) if clean_names else key


def _pitcher_arsenal_by_family(matchup: dict[str, Any]) -> list[dict[str, Any]]:
    family_map: dict[str, dict[str, Any]] = {}
    for pitch in _pitch_mix_for_batter_hand(matchup):
        if not isinstance(pitch, dict):
            continue
        pitch_name = pitch.get("name")
        key = _pitch_name_key(pitch_name)
        variant_key = _pitch_variant_key(pitch_name)
        if not key:
            continue
        family = family_map.setdefault(
            key,
            {
                "pitch_family": key,
                "label": _pitch_family_label(key),
                "pitcher_pitch_names": [],
                "pitcher_variants": {},
                "pitcher_usage_pct": 0.0,
                "pitcher_usage_pct_available": False,
            },
        )
        if pitch_name and pitch_name not in family["pitcher_pitch_names"]:
            family["pitcher_pitch_names"].append(pitch_name)
            family["label"] = _pitch_family_label(key, family["pitcher_pitch_names"])
        usage_pct = _to_float(pitch.get("usage_pct"))
        if usage_pct is not None:
            family["pitcher_usage_pct"] += usage_pct
            family["pitcher_usage_pct_available"] = True
        variant = family["pitcher_variants"].setdefault(
            variant_key or key,
            {
                "pitch_variant": variant_key or key,
                "label": _pitch_variant_label(variant_key or key, [pitch_name]),
                "pitcher_pitch_names": [],
                "usage_pct": 0.0,
                "usage_pct_available": False,
            },
        )
        if pitch_name and pitch_name not in variant["pitcher_pitch_names"]:
            variant["pitcher_pitch_names"].append(pitch_name)
            variant["label"] = _pitch_variant_label(variant_key or key, variant["pitcher_pitch_names"])
        if usage_pct is not None:
            variant["usage_pct"] += usage_pct
            variant["usage_pct_available"] = True

    families = []
    for family in family_map.values():
        variants = sorted(
            family["pitcher_variants"].values(),
            key=lambda row: row["usage_pct"] if row["usage_pct_available"] else -1,
            reverse=True,
        )
        if len(variants) == 1:
            evaluated_variants = variants
            ignored_rare_variants = []
        else:
            evaluated_variants = [
                variant
                for variant in variants
                if not variant["usage_pct_available"] or variant["usage_pct"] >= RARE_PITCH_USAGE_CUTOFF
            ]
            ignored_rare_variants = [
                variant
                for variant in variants
                if variant["usage_pct_available"] and variant["usage_pct"] < RARE_PITCH_USAGE_CUTOFF
            ]
        family["pitcher_variants"] = variants
        family["evaluated_variants"] = evaluated_variants
        family["ignored_rare_variants"] = ignored_rare_variants
        family["evaluated_usage_pct"] = sum(
            variant["usage_pct"] for variant in evaluated_variants if variant["usage_pct_available"]
        )
        families.append(family)

    return sorted(
        families,
        key=lambda row: row["pitcher_usage_pct"] if row["pitcher_usage_pct_available"] else -1,
        reverse=True,
    )


def _pitcher_zone_tendency_data(
    errors: list[str],
    pitcher_id: Any,
    batter_hand: str = "",
) -> dict[str, Any] | None:
    season_year = date.today().year
    start_date = f"{season_year}-03-01"
    end_date = date.today().isoformat()

    raw_df = _call_existing(
        errors,
        "strike_zone.load_pitch_location_data",
        strike_zone.load_pitch_location_data,
        pitcher_id,
        start_date,
        end_date,
        default=pd.DataFrame(),
    )
    if raw_df is None or raw_df.empty:
        return None

    working_df = raw_df.copy()
    if batter_hand in {"R", "L"}:
        batter_stands_label = "RHB" if batter_hand == "R" else "LHB"
        filtered_by_stand = _call_existing(
            errors,
            f"strike_zone.filter_by_batter_stands({batter_stands_label})",
            strike_zone.filter_by_batter_stands,
            working_df,
            batter_stands_label,
            default=pd.DataFrame(),
        )
        if filtered_by_stand is not None and not filtered_by_stand.empty:
            working_df = filtered_by_stand

    zone_df, outer_stats, denominator = _call_existing(
        errors,
        "strike_zone._build_pitcher_metric_zone_outputs(Pitch %)",
        strike_zone._build_pitcher_metric_zone_outputs,
        working_df,
        "Pitch %",
        default=(pd.DataFrame(), {}, 0),
    )

    payload = {
        "overall": _zone_payload(zone_df, outer_stats, denominator),
        "batter_stands_filter": batter_hand or "All",
        "by_pitch_family": {},
        "source_functions": [
            "strike_zone.load_pitch_location_data",
            "strike_zone.filter_by_batter_stands",
            "strike_zone._build_pitcher_metric_zone_outputs",
        ],
    }

    pitch_col = _pitch_column(working_df)
    if not pitch_col:
        return payload

    family_keys = working_df[pitch_col].apply(_pitch_name_key)
    for family_key in sorted(key for key in family_keys.dropna().unique().tolist() if key):
        family_df = working_df[family_keys == family_key].copy()
        if family_df.empty:
            continue
        family_zone_df, family_outer_stats, family_denominator = _call_existing(
            errors,
            f"strike_zone._build_pitcher_metric_zone_outputs(Pitch %, {family_key})",
            strike_zone._build_pitcher_metric_zone_outputs,
            family_df,
            "Pitch %",
            default=(pd.DataFrame(), {}, 0),
        )
        pitch_names = sorted(
            {
                str(name).strip()
                for name in family_df[pitch_col].dropna().astype(str).tolist()
                if str(name).strip()
            }
        )
        payload["by_pitch_family"][family_key] = {
            "pitch_family": family_key,
            "label": _pitch_family_label(family_key, pitch_names),
            "pitcher_pitch_names": pitch_names,
            **_zone_payload(family_zone_df, family_outer_stats, family_denominator),
        }

    return payload


def _run_value_rows_by_pitch(matchup: dict[str, Any]) -> dict[str, dict[str, list[dict[str, Any]]]]:
    rows = matchup.get("batter_run_value_by_pitch_type") or []
    if not isinstance(rows, list):
        return {}

    row_map: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        pitch_name = row.get("Pitch Type") or row.get("pitch_type") or row.get("pitch_name")
        family_key = _pitch_name_key(pitch_name)
        variant_key = _pitch_variant_key(pitch_name) or family_key
        if family_key and variant_key:
            row_map.setdefault(family_key, {}).setdefault(variant_key, []).append(row)
    return row_map


def _mean_metric_value(rows: list[dict[str, Any]], metric: str) -> float | None:
    values = []
    for row in rows:
        value = _to_float(row.get(metric))
        if value is not None:
            values.append(value)
    return (sum(values) / len(values)) if values else None


def _weighted_metric_for_family(
    family: dict[str, Any],
    batter_rows_by_variant: dict[str, list[dict[str, Any]]],
    metric: str,
) -> dict[str, Any]:
    # Weighting approach:
    # 1. Keep pitch families grouped for matchup readability (Slider/Sweeper,
    #    Curveball/Knuckle Curve, etc.), but retain the pitcher's actual variants.
    # 2. Ignore pitcher variants under 1% usage unless that variant is the only
    #    pitch in the family. This keeps tiny show-me pitches from moving a read.
    # 3. For each metric, use only variants the pitcher actually throws and only
    #    variants where batter data exists. We then renormalize the weights across
    #    those available variants so missing batter data does not count as zero.
    # 4. If usage is unavailable for the evaluated variants, fall back to equal
    #    weights rather than inventing a usage split.
    components = []
    missing_variants = []
    for variant in family.get("evaluated_variants", []) or []:
        variant_key = variant.get("pitch_variant")
        rows = batter_rows_by_variant.get(variant_key, [])
        metric_value = _mean_metric_value(rows, metric)
        if metric_value is None:
            missing_variants.append(variant.get("label") or variant_key)
            continue
        components.append(
            {
                "pitch_variant": variant_key,
                "label": variant.get("label") or variant_key,
                "pitcher_usage_pct": variant.get("usage_pct") if variant.get("usage_pct_available") else None,
                "batter_metric": metric_value,
                "batter_rows": rows,
            }
        )

    usage_values = [component["pitcher_usage_pct"] for component in components]
    use_equal_weights = not usage_values or any(value is None for value in usage_values)
    if use_equal_weights and components:
        equal_weight = 1.0 / len(components)
        for component in components:
            component["weight"] = equal_weight
    else:
        total_usage = sum(float(value) for value in usage_values)
        for component in components:
            component["weight"] = (float(component["pitcher_usage_pct"]) / total_usage) if total_usage else 0.0

    weighted_value = None
    if components:
        weighted_value = sum(component["batter_metric"] * component["weight"] for component in components)

    return {
        "metric": metric,
        "value": weighted_value,
        "components": components,
        "missing_variants": missing_variants,
        "weighting": "equal" if use_equal_weights and components else "pitcher_usage",
    }


def _usage_importance(usage_pct: float | None) -> dict[str, Any]:
    if usage_pct is None:
        return {
            "label": "unknown usage",
            "written_priority": "supporting",
            "include_in_top_level": False,
        }
    if usage_pct >= 25:
        return {
            "label": "primary",
            "written_priority": "lead",
            "include_in_top_level": True,
        }
    if usage_pct >= 15:
        return {
            "label": "major",
            "written_priority": "high",
            "include_in_top_level": True,
        }
    if usage_pct >= 8:
        return {
            "label": "secondary",
            "written_priority": "medium",
            "include_in_top_level": True,
        }
    return {
        "label": "low usage",
        "written_priority": "low",
        "include_in_top_level": False,
    }


def _format_pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.1f}%"


def _format_decimal(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.3f}"


def _contact_evidence(hard_hit_pct: float | None) -> dict[str, Any]:
    if hard_hit_pct is None:
        return {
            "label": "Quality of contact",
            "value": None,
            "read": "missing",
            "text": "Hard Hit% unavailable.",
        }
    if hard_hit_pct >= 45:
        read = "strength"
        text = f"Hard-hit contact is supportive ({hard_hit_pct:.1f}%)."
    elif hard_hit_pct < 35:
        read = "concern"
        text = f"Hard-hit contact is light ({hard_hit_pct:.1f}%)."
    else:
        read = "neutral"
        text = f"Hard-hit contact is moderate ({hard_hit_pct:.1f}%)."
    return {
        "label": "Quality of contact",
        "value": hard_hit_pct,
        "read": read,
        "text": text,
    }


def _expected_power_evidence(xslg: float | None, xwoba: float | None) -> dict[str, Any]:
    parts = []
    if xslg is not None:
        parts.append(f"xSLG {_format_decimal(xslg)}")
    if xwoba is not None:
        parts.append(f"xwOBA {_format_decimal(xwoba)}")
    if not parts:
        return {
            "label": "Expected power",
            "values": {"xSLG": xslg, "xwOBA": xwoba},
            "read": "missing",
            "text": "xSLG/xwOBA unavailable.",
        }
    if (xslg is not None and xslg >= 0.500) or (xwoba is not None and xwoba >= 0.360):
        read = "strength"
        text = f"Expected power is supportive ({', '.join(parts)})."
    elif (xslg is not None and xslg < 0.350) and (xwoba is None or xwoba < 0.300):
        read = "concern"
        text = f"Expected power is muted ({', '.join(parts)})."
    else:
        read = "neutral"
        text = f"Expected power is mixed ({', '.join(parts)})."
    return {
        "label": "Expected power",
        "values": {"xSLG": xslg, "xwOBA": xwoba},
        "read": read,
        "text": text,
    }


def _actual_production_evidence(slg: float | None) -> dict[str, Any]:
    if slg is None:
        return {
            "label": "Actual production",
            "value": None,
            "read": "missing",
            "text": "SLG unavailable.",
        }
    if slg >= 0.500:
        read = "strength"
        text = f"Actual slugging is supportive ({slg:.3f} SLG)."
    elif slg < 0.350:
        read = "concern"
        text = f"Actual slugging is muted ({slg:.3f} SLG)."
    else:
        read = "neutral"
        text = f"Actual slugging is moderate ({slg:.3f} SLG)."
    return {
        "label": "Actual production",
        "value": slg,
        "read": read,
        "text": text,
    }


def _swing_miss_evidence(whiff_pct: float | None, putaway_pct: float | None) -> dict[str, Any]:
    parts = []
    if whiff_pct is not None:
        parts.append(f"Whiff% {_format_pct(whiff_pct)}")
    if putaway_pct is not None:
        parts.append(f"PutAway% {_format_pct(putaway_pct)}")
    if not parts:
        return {
            "label": "Swing-and-miss risk",
            "values": {"Whiff%": whiff_pct, "PutAway%": putaway_pct},
            "read": "missing",
            "text": "Whiff%/PutAway% unavailable.",
        }
    if (whiff_pct is not None and whiff_pct >= 30) or (putaway_pct is not None and putaway_pct >= 25):
        read = "concern"
        text = f"Swing-and-miss risk is elevated ({', '.join(parts)})."
    elif (whiff_pct is not None and whiff_pct < 20) and (putaway_pct is None or putaway_pct < 15):
        read = "strength"
        text = f"Swing-and-miss risk is manageable ({', '.join(parts)})."
    else:
        read = "neutral"
        text = f"Swing-and-miss risk is moderate ({', '.join(parts)})."
    return {
        "label": "Swing-and-miss risk",
        "values": {"Whiff%": whiff_pct, "PutAway%": putaway_pct},
        "read": read,
        "text": text,
    }


def _family_read_summary(
    pitch_label: str,
    usage_pct: float | None,
    evidence: dict[str, dict[str, Any]],
) -> str:
    usage_text = _format_pct(usage_pct)
    evidence_text = "; ".join(item["text"] for item in evidence.values())
    return f"{pitch_label} ({usage_text} usage): {evidence_text}"


def _describe_run_value_matchup(matchup: dict[str, Any]) -> dict[str, Any]:
    arsenal_families = _pitcher_arsenal_by_family(matchup)
    run_value_by_pitch = _run_value_rows_by_pitch(matchup)
    pitch_matches = []
    strengths = []
    concerns = []
    missing = []

    if not arsenal_families:
        missing.append("Pitch mix unavailable, so arsenal-to-run-value comparison could not be made.")
    if not run_value_by_pitch:
        missing.append("Batter run value by pitch type unavailable.")

    arsenal_keys = {family["pitch_family"] for family in arsenal_families}
    ignored_batter_pitch_types = []
    family_reads = []
    for key, variants in run_value_by_pitch.items():
        if key not in arsenal_keys:
            ignored_batter_pitch_types.extend(
                row.get("Pitch Type") or row.get("pitch_type") or row.get("pitch_name")
                for rows in variants.values()
                for row in rows
                if isinstance(row, dict)
            )

    for family in arsenal_families:
        pitch_key = family["pitch_family"]
        pitch_label = family["label"]
        usage_pct = family["pitcher_usage_pct"] if family["pitcher_usage_pct_available"] else None
        batter_rows_by_variant = run_value_by_pitch.get(pitch_key, {})
        if not batter_rows_by_variant:
            importance = _usage_importance(usage_pct)
            pitch_matches.append(
                {
                    "pitch_family": pitch_key,
                    "pitch_type": pitch_label,
                    "pitcher_pitch_names": family["pitcher_pitch_names"],
                    "pitcher_variants": family.get("pitcher_variants", []),
                    "evaluated_variants": family.get("evaluated_variants", []),
                    "ignored_rare_variants": family.get("ignored_rare_variants", []),
                    "pitcher_usage_pct": usage_pct,
                    "importance": importance,
                    "batter_row_available": False,
                }
            )
            continue

        weighted_metrics = {
            metric: _weighted_metric_for_family(family, batter_rows_by_variant, metric)
            for metric in ("xwOBA", "xSLG", "SLG", "Hard Hit%", "Whiff%", "PutAway%")
        }
        xwoba = weighted_metrics["xwOBA"]["value"]
        xslg = weighted_metrics["xSLG"]["value"]
        slg = weighted_metrics["SLG"]["value"]
        hard_hit_pct = weighted_metrics["Hard Hit%"]["value"]
        whiff_pct = weighted_metrics["Whiff%"]["value"]
        putaway_pct = weighted_metrics["PutAway%"]["value"]
        importance = _usage_importance(usage_pct)
        evidence = {
            "quality_of_contact": _contact_evidence(hard_hit_pct),
            "expected_power": _expected_power_evidence(xslg, xwoba),
            "actual_production": _actual_production_evidence(slg),
            "swing_and_miss_risk": _swing_miss_evidence(whiff_pct, putaway_pct),
        }
        family_summary = _family_read_summary(pitch_label, usage_pct, evidence)
        family_read = {
            "pitch_family": pitch_key,
            "pitch_type": pitch_label,
            "pitcher_usage_pct": usage_pct,
            "importance": importance,
            "summary": family_summary,
            "evidence": evidence,
        }
        family_reads.append(family_read)

        pitch_matches.append(
            {
                "pitch_family": pitch_key,
                "pitch_type": pitch_label,
                "pitcher_pitch_names": family["pitcher_pitch_names"],
                "pitcher_variants": family.get("pitcher_variants", []),
                "evaluated_variants": family.get("evaluated_variants", []),
                "ignored_rare_variants": family.get("ignored_rare_variants", []),
                "pitcher_usage_pct": usage_pct,
                "importance": importance,
                "family_read": family_read,
                "weighted_metrics": weighted_metrics,
                "batter_run_value_rows_by_variant": batter_rows_by_variant,
            }
        )

        if importance["include_in_top_level"]:
            strength_evidence = [
                item["label"]
                for item in evidence.values()
                if item.get("read") == "strength"
            ]
            concern_evidence = [
                item["label"]
                for item in evidence.values()
                if item.get("read") == "concern"
            ]
            if strength_evidence:
                strengths.append(
                    f"{importance['label'].title()} family: {family_summary}"
                )
            if concern_evidence:
                concerns.append(
                    f"{importance['label'].title()} family: {family_summary}"
                )

    if arsenal_families and run_value_by_pitch and not pitch_matches:
        missing.append("No pitch-type names matched between pitcher arsenal and batter run value table.")

    return {
        "pitch_mix_split_used": str(matchup.get("batter_handedness") or "all"),
        "pitcher_arsenal_families": arsenal_families,
        "ignored_batter_pitch_types": sorted({str(name) for name in ignored_batter_pitch_types if name}),
        "usage_ordered_family_reads": family_reads,
        "pitch_matches": pitch_matches,
        "strengths": strengths,
        "concerns": concerns,
        "missing_data": missing,
    }


def _zone_entries(zone_payload: dict[str, Any] | None, count_label: str, pct_label: str) -> list[dict[str, Any]]:
    if not zone_payload:
        return []
    zone_rows = zone_payload.get("zone_rows") or []
    zones = []
    for row in zone_rows:
        if not isinstance(row, dict):
            continue
        pitch_count = _to_float(row.get("pitch_count")) or 0
        pitch_pct = _to_float(row.get("pitch_pct")) or 0
        if pitch_count <= 0 and pitch_pct <= 0:
            continue
        zones.append(
            {
                "zone_id": row.get("zone_id"),
                count_label: int(pitch_count),
                pct_label: pitch_pct,
                "zone_group": "inner",
            }
        )
    outer_stats = zone_payload.get("outer_stats") or {}
    if isinstance(outer_stats, dict):
        for quad, stats in outer_stats.items():
            if not isinstance(stats, dict):
                continue
            pitch_count = _to_float(stats.get("pitch_count")) or 0
            pitch_pct = _to_float(stats.get("pitch_pct")) or 0
            if pitch_count <= 0 and pitch_pct <= 0:
                continue
            zone_id = getattr(strike_zone, "OUTER_QUAD_TO_ZONE", {}).get(quad)
            zones.append(
                {
                    "zone_id": zone_id,
                    count_label: int(pitch_count),
                    pct_label: pitch_pct,
                    "zone_group": "outer",
                    "outer_quadrant": quad,
                }
            )
    return zones


def _top_home_run_zones(zone_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    zones = _zone_entries(zone_payload, "home_run_count", "home_run_pct")
    return sorted(zones, key=lambda item: item["home_run_pct"], reverse=True)[:5]


def _top_pitcher_attack_zones(zone_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    zones = _zone_entries(zone_payload, "pitch_count", "pitch_pct")
    return sorted(zones, key=lambda item: item["pitch_pct"], reverse=True)[:5]


def _describe_strike_zone_matchup(matchup: dict[str, Any]) -> dict[str, Any]:
    batter_zone_data = matchup.get("batter_strike_zone_home_run_data") or {}
    pitcher_zone_data = matchup.get("pitcher_strike_zone_tendency_data") or {}
    split_payload = batter_zone_data.get("vs_pitcher_hand") if isinstance(batter_zone_data, dict) else None
    overall_payload = batter_zone_data.get("overall") if isinstance(batter_zone_data, dict) else None
    preferred_payload = split_payload or overall_payload
    top_batter_zones = _top_home_run_zones(preferred_payload)
    top_pitcher_zones = _top_pitcher_attack_zones(
        pitcher_zone_data.get("overall") if isinstance(pitcher_zone_data, dict) else None
    )
    batter_zone_ids = {zone.get("zone_id") for zone in top_batter_zones if zone.get("zone_id") is not None}
    pitcher_zone_ids = {zone.get("zone_id") for zone in top_pitcher_zones if zone.get("zone_id") is not None}
    overlap_ids = batter_zone_ids & pitcher_zone_ids
    overlap_zones = [
        {
            "zone_id": zone_id,
            "batter_home_run_zone": next((zone for zone in top_batter_zones if zone.get("zone_id") == zone_id), {}),
            "pitcher_attack_zone": next((zone for zone in top_pitcher_zones if zone.get("zone_id") == zone_id), {}),
        }
        for zone_id in sorted(overlap_ids, key=lambda value: str(value))
    ]

    pitch_family_overlaps = []
    by_family = pitcher_zone_data.get("by_pitch_family", {}) if isinstance(pitcher_zone_data, dict) else {}
    if isinstance(by_family, dict):
        for family_key, family_payload in by_family.items():
            family_top_zones = _top_pitcher_attack_zones(family_payload)
            family_zone_ids = {zone.get("zone_id") for zone in family_top_zones if zone.get("zone_id") is not None}
            family_overlap_ids = batter_zone_ids & family_zone_ids
            if not family_overlap_ids:
                continue
            pitch_family_overlaps.append(
                {
                    "pitch_family": family_key,
                    "label": family_payload.get("label", family_key) if isinstance(family_payload, dict) else family_key,
                    "pitcher_pitch_names": family_payload.get("pitcher_pitch_names", []) if isinstance(family_payload, dict) else [],
                    "top_pitcher_attack_zones": family_top_zones,
                    "overlap_zones": [
                        {
                            "zone_id": zone_id,
                            "batter_home_run_zone": next(
                                (zone for zone in top_batter_zones if zone.get("zone_id") == zone_id),
                                {},
                            ),
                            "pitcher_attack_zone": next(
                                (zone for zone in family_top_zones if zone.get("zone_id") == zone_id),
                                {},
                            ),
                        }
                        for zone_id in sorted(family_overlap_ids, key=lambda value: str(value))
                    ],
                }
            )

    strengths = []
    concerns = []
    missing = []

    if top_batter_zones:
        strengths.append(
            "Batter strike-zone Home Run data is available; top HR zones are included for review."
        )
    else:
        missing.append("Batter strike-zone Home Run data is unavailable or empty.")

    if top_pitcher_zones:
        strengths.append("Pitcher attack-zone tendency data is available for overlap review.")
    else:
        missing.append(
            "Pitcher strike-zone tendency data is unavailable, so true zone-overlap comparison cannot be completed."
        )

    overlap_available = bool(top_batter_zones and top_pitcher_zones)
    if overlap_zones:
        strengths.append(
            "Pitcher frequently attacks at least one of the batter's strongest Home Run zones."
        )
        overlap_read = "Overlap favors the hitter because pitcher attack zones intersect with batter HR zones."
    elif overlap_available:
        concerns.append("There is little or no overlap between pitcher attack zones and batter HR zones.")
        overlap_read = "Little or no strike-zone overlap."
    else:
        overlap_read = "Strike-zone overlap could not be evaluated."

    return {
        "overlap_available": overlap_available,
        "top_batter_home_run_zones": top_batter_zones,
        "top_pitcher_attack_zones": top_pitcher_zones,
        "overlap_zones": overlap_zones,
        "pitch_family_overlaps": pitch_family_overlaps,
        "favors_hitter": bool(overlap_zones),
        "little_or_no_overlap": bool(overlap_available and not overlap_zones),
        "overlap_read": overlap_read,
        "strengths": strengths,
        "concerns": concerns,
        "missing_data": missing,
    }


def _outside_zone_pct(zone_payload: dict[str, Any] | None) -> float | None:
    if not isinstance(zone_payload, dict):
        return None
    outer_stats = zone_payload.get("outer_stats") or {}
    if not isinstance(outer_stats, dict) or not outer_stats:
        return None
    values = []
    for stats in outer_stats.values():
        if isinstance(stats, dict):
            value = _to_float(stats.get("pitch_pct"))
            if value is not None:
                values.append(value)
    return sum(values) if values else None


def _walk_risk_level(high_signals: int, moderate_signals: int, reducing_signals: int) -> str:
    adjusted_high = max(high_signals - reducing_signals, 0)
    if adjusted_high >= 2 or (adjusted_high >= 1 and moderate_signals >= 2):
        return "High"
    if adjusted_high >= 1 or moderate_signals >= 2:
        return "Moderate"
    return "Low"


def _describe_walk_risk(
    matchup: dict[str, Any],
    strike_zone_matchup: dict[str, Any],
    arsenal: dict[str, Any],
) -> dict[str, Any]:
    pitcher_zone_data = matchup.get("pitcher_strike_zone_tendency_data") or {}
    batter_discipline = matchup.get("batter_plate_discipline_zone_data") or {}
    pitcher_overall_zone = pitcher_zone_data.get("overall") if isinstance(pitcher_zone_data, dict) else None
    pitcher_ooz_pct = _outside_zone_pct(pitcher_overall_zone)
    batter_outside_take_pct = _to_float(batter_discipline.get("outside_take_pct")) if isinstance(batter_discipline, dict) else None

    reasoning = []
    high_signals = 0
    moderate_signals = 0
    reducing_signals = 0

    if pitcher_ooz_pct is None:
        reasoning.append("Pitcher outside-zone attack rate is unavailable.")
    elif pitcher_ooz_pct >= 35:
        high_signals += 1
        reasoning.append(f"Pitcher works outside the zone frequently ({pitcher_ooz_pct:.1f}% OOZ).")
    elif pitcher_ooz_pct >= 28:
        moderate_signals += 1
        reasoning.append(f"Pitcher shows a moderate outside-zone tendency ({pitcher_ooz_pct:.1f}% OOZ).")
    else:
        reducing_signals += 1
        reasoning.append(f"Pitcher attacks the strike zone consistently ({pitcher_ooz_pct:.1f}% OOZ).")

    if batter_outside_take_pct is None:
        reasoning.append("Batter outside-zone take tendency is unavailable.")
    elif batter_outside_take_pct >= 65:
        high_signals += 1
        reasoning.append(f"Batter takes outside-zone pitches at a high rate ({batter_outside_take_pct:.1f}%).")
    elif batter_outside_take_pct >= 55:
        moderate_signals += 1
        reasoning.append(f"Batter shows some outside-zone discipline ({batter_outside_take_pct:.1f}% take rate).")
    else:
        reducing_signals += 1
        reasoning.append(f"Batter has not shown a high outside-zone take profile ({batter_outside_take_pct:.1f}% take rate).")

    family_tendencies = []
    family_reads = arsenal.get("usage_ordered_family_reads", []) if isinstance(arsenal, dict) else []
    by_family = pitcher_zone_data.get("by_pitch_family", {}) if isinstance(pitcher_zone_data, dict) else {}
    for family_read in family_reads:
        importance = str((family_read.get("importance") or {}).get("label", "")).lower()
        if importance not in {"primary", "major", "secondary"}:
            continue
        family_key = family_read.get("pitch_family")
        family_zone_payload = by_family.get(family_key, {}) if isinstance(by_family, dict) else {}
        family_ooz_pct = _outside_zone_pct(family_zone_payload)
        if family_ooz_pct is None:
            continue
        family_tendency = {
            "pitch_family": family_key,
            "pitch_type": family_read.get("pitch_type"),
            "pitcher_usage_pct": family_read.get("pitcher_usage_pct"),
            "outside_zone_pct": family_ooz_pct,
            "importance": family_read.get("importance"),
        }
        family_tendencies.append(family_tendency)
        if family_ooz_pct >= 40:
            high_signals += 1
            reasoning.append(
                f"{family_read.get('pitch_type')} is a key family that is often located outside the zone ({family_ooz_pct:.1f}% OOZ)."
            )
        elif family_ooz_pct >= 32:
            moderate_signals += 1
            reasoning.append(
                f"{family_read.get('pitch_type')} has a moderate outside-zone tendency ({family_ooz_pct:.1f}% OOZ)."
            )

    if strike_zone_matchup.get("little_or_no_overlap"):
        moderate_signals += 1
        reasoning.append("There is little overlap between pitcher attack zones and batter HR zones, which may reduce hittable pitches.")
    elif strike_zone_matchup.get("favors_hitter"):
        reducing_signals += 1
        reasoning.append("Pitcher attack zones overlap with batter HR zones, which supports hittable pitch access.")

    level = _walk_risk_level(high_signals, moderate_signals, reducing_signals)
    if level == "High":
        reasoning.append("This matchup may reduce hittable pitches despite any favorable power indicators.")
    elif level == "Low":
        reasoning.append("The available zone data does not show a strong deep-count or walk-profile warning.")

    return {
        "level": level,
        "reasoning": reasoning,
        "supporting_data": {
            "pitcher_overall_ooz_pct": pitcher_ooz_pct,
            "batter_outside_take_pct": batter_outside_take_pct,
            "pitch_family_outside_zone_tendencies": family_tendencies,
            "strike_zone_overlap": {
                "favors_hitter": strike_zone_matchup.get("favors_hitter"),
                "little_or_no_overlap": strike_zone_matchup.get("little_or_no_overlap"),
                "overlap_read": strike_zone_matchup.get("overlap_read"),
            },
        },
    }


def _describe_expected_power(matchup: dict[str, Any]) -> dict[str, Any]:
    run_value_by_pitch = _run_value_rows_by_pitch(matchup)
    batter_stats = matchup.get("batter_season_stats") or {}
    arsenal_families = _pitcher_arsenal_by_family(matchup)
    arsenal_keys = {family["pitch_family"] for family in arsenal_families}
    strengths = []
    concerns = []
    missing = []

    ignored_rows = []
    for pitch_key, variants in run_value_by_pitch.items():
        if pitch_key not in arsenal_keys:
            for rows in variants.values():
                ignored_rows.extend(
                    row.get("Pitch Type") or row.get("pitch_type") or row.get("pitch_name")
                    for row in rows
                    if isinstance(row, dict)
                )
            continue
        for rows in variants.values():
            for row in rows:
                if not isinstance(row, dict):
                    continue
                xwoba = _to_float(row.get("xwOBA"))
                xslg = _to_float(row.get("xSLG"))
                if xwoba is None and xslg is None:
                    pitch_type = row.get("Pitch Type") or row.get("pitch_type") or row.get("pitch_name")
                    ignored_rows.append(pitch_type)

    expected_rows = []
    for family in arsenal_families:
        pitch_key = family["pitch_family"]
        batter_rows_by_variant = run_value_by_pitch.get(pitch_key, {})
        if not batter_rows_by_variant:
            continue
        weighted_xwoba = _weighted_metric_for_family(family, batter_rows_by_variant, "xwOBA")
        weighted_xslg = _weighted_metric_for_family(family, batter_rows_by_variant, "xSLG")
        if weighted_xwoba["value"] is None and weighted_xslg["value"] is None:
            for rows in batter_rows_by_variant.values():
                for row in rows:
                    pitch_type = row.get("Pitch Type") or row.get("pitch_type") or row.get("pitch_name")
                    ignored_rows.append(pitch_type)
            continue
        expected_rows.append(
            {
                "pitch_family": pitch_key,
                "pitch_family_label": family["label"],
                "pitcher_pitch_names": family["pitcher_pitch_names"],
                "pitcher_variants": family.get("pitcher_variants", []),
                "evaluated_variants": family.get("evaluated_variants", []),
                "ignored_rare_variants": family.get("ignored_rare_variants", []),
                "weighted_xwOBA": weighted_xwoba,
                "weighted_xSLG": weighted_xslg,
                "batter_rows_by_variant": batter_rows_by_variant,
            }
        )

    if not expected_rows:
        if arsenal_keys:
            missing.append("Relevant arsenal pitch-type xwOBA/xSLG data unavailable.")
        else:
            missing.append("Pitch arsenal unavailable, so expected pitch-type power was not evaluated.")

    if isinstance(batter_stats, dict):
        hard_contact_proxy = _to_float(batter_stats.get("SLG"))
        if hard_contact_proxy is not None and hard_contact_proxy >= 0.450:
            strengths.append(f"Batter season SLG is supportive ({hard_contact_proxy:.3f}).")
        elif hard_contact_proxy is None:
            missing.append("Batter season SLG unavailable in contact stats.")

        whiff_pct = _to_float(batter_stats.get("Whiff%"))
        k_pct = _to_float(batter_stats.get("K%"))
        if whiff_pct is not None and whiff_pct >= 30:
            concerns.append(f"Season Whiff% is elevated ({whiff_pct:.1f}%).")
        if k_pct is not None and k_pct >= 25:
            concerns.append(f"Season K% is elevated ({k_pct:.1f}%).")
    else:
        missing.append("Batter contact stats unavailable.")

    return {
        "expected_pitch_type_rows": expected_rows,
        "pitcher_arsenal_families_evaluated": arsenal_families,
        "ignored_batter_pitch_types": sorted({str(name) for name in ignored_rows if name}),
        "strengths": strengths,
        "concerns": concerns,
        "missing_data": missing,
    }


def _describe_pitcher_context(matchup: dict[str, Any]) -> dict[str, Any]:
    pitcher_stats = matchup.get("pitcher_season_stats") or {}
    strengths = []
    concerns = []
    missing = []

    if not isinstance(pitcher_stats, dict) or not pitcher_stats:
        missing.append("Pitcher season stats unavailable.")
        return {"strengths": strengths, "concerns": concerns, "missing_data": missing}

    hr_allowed = _to_float(pitcher_stats.get("hr_allowed"))
    era = _to_float(pitcher_stats.get("era"))
    whip = _to_float(pitcher_stats.get("whip"))

    if hr_allowed is not None and hr_allowed >= 10:
        strengths.append(f"Pitcher has allowed {int(hr_allowed)} home runs this season.")
    elif hr_allowed is None:
        missing.append("Pitcher HR allowed unavailable.")

    if era is not None and era >= 4.50:
        strengths.append(f"Pitcher ERA context is hitter-friendly ({era:.2f}).")
    if whip is not None and whip >= 1.30:
        strengths.append(f"Pitcher WHIP context may create traffic ({whip:.2f}).")

    return {"strengths": strengths, "concerns": concerns, "missing_data": missing}


def _build_home_run_analysis(matchup: dict[str, Any]) -> dict[str, Any]:
    arsenal = _describe_run_value_matchup(matchup)
    strike_zone_matchup = _describe_strike_zone_matchup(matchup)
    walk_risk = _describe_walk_risk(matchup, strike_zone_matchup, arsenal)
    expected_power = _describe_expected_power(matchup)
    pitcher_context = _describe_pitcher_context(matchup)

    strengths = (
        arsenal["strengths"]
        + strike_zone_matchup["strengths"]
        + expected_power["strengths"]
        + pitcher_context["strengths"]
    )
    concerns = (
        arsenal["concerns"]
        + strike_zone_matchup["concerns"]
        + expected_power["concerns"]
        + pitcher_context["concerns"]
    )
    missing_data = (
        arsenal["missing_data"]
        + strike_zone_matchup["missing_data"]
        + expected_power["missing_data"]
        + pitcher_context["missing_data"]
    )

    if strengths and concerns:
        summary = "Raw matchup data shows both home-run positives and swing/miss concerns."
    elif strengths:
        summary = "Raw matchup data shows home-run indicators worth reviewing."
    elif concerns:
        summary = "Raw matchup data is available, but the visible indicators lean cautious."
    else:
        summary = "Not enough raw matchup data is available to form a home-run read."

    return {
        "summary": summary,
        "strengths": strengths,
        "concerns": concerns,
        "missing_data": missing_data,
        "details": {
            "arsenal_vs_batter_run_value": arsenal,
            "strike_zone_overlap": strike_zone_matchup,
            "walk_risk": walk_risk,
            "expected_power": expected_power,
            "pitcher_context": pitcher_context,
        },
        "walk_risk": walk_risk,
        "scoring": None,
        "note": "No numeric confidence score, ranking, or betting recommendation is calculated.",
    }


def get_matchup_data(batter_id: Any, pitcher_id: Any) -> dict[str, Any]:
    """
    Return raw matchup inputs already available in the project.

    This function does not calculate confidence, rank matchups, post to Discord,
    or render Streamlit UI.
    """

    timer = _TimingLogger()
    errors: list[str] = []
    todos: list[str] = []
    batter_id_int = timer.timed("_safe_int_id batter_id", _safe_int_id, batter_id)
    pitcher_id_int = timer.timed("_safe_int_id pitcher_id", _safe_int_id, pitcher_id)

    result: dict[str, Any] = {
        "batter_id": batter_id_int or batter_id,
        "pitcher_id": pitcher_id_int or pitcher_id,
        "batter_name": None,
        "pitcher_name": None,
        "batter_handedness": None,
        "pitcher_handedness": None,
        "pitch_mix": None,
        "batter_run_value_by_pitch_type": None,
        "batter_strike_zone_home_run_data": None,
        "batter_plate_discipline_zone_data": None,
        "pitcher_strike_zone_home_run_data": None,
        "pitcher_strike_zone_tendency_data": None,
        "pitcher_strike_zone_available_metrics": list(strike_zone.PITCHER_STRIKE_ZONE_METRICS),
        "pitcher_season_stats": None,
        "batter_season_stats": None,
        "batter_game_log": None,
        "batter_hit_details_by_game": None,
        "existing_matchup_data": None,
        "home_run_analysis": None,
        "source_functions": {
            "app.py": [],
            "strike_zone.py": [],
        },
        "todos": todos,
        "errors": errors,
    }

    app = timer.timed("_load_app_module", _load_app_module, errors)
    if app is None:
        todos.append(
            "Move reusable data functions out of app.py top-level Streamlit code "
            "so matchup_engine.py can import them without rendering the website."
        )
        result["home_run_analysis"] = timer.timed("Home run analysis", _build_home_run_analysis, result)
        timer.log("get_matchup_data complete")
        return result

    player_ids = tuple(pid for pid in (batter_id_int, pitcher_id_int) if pid)
    with performance_profile.timed("Load handedness"):
        player_info = timer.timed(
            "Player info",
            _call_existing,
            errors,
            "app.get_players_info",
            app.get_players_info,
            player_ids,
            default={},
        )
    result["source_functions"]["app.py"].append("get_players_info")

    batter_info = player_info.get(batter_id_int, {}) if batter_id_int else {}
    pitcher_info = player_info.get(pitcher_id_int, {}) if pitcher_id_int else {}
    result["batter_name"] = batter_info.get("fullName")
    result["pitcher_name"] = pitcher_info.get("fullName")
    result["batter_handedness"] = timer.timed(
        "app.normalize_hand_code batter",
        app.normalize_hand_code,
        batter_info.get("batSide", ""),
    )
    pitcher_hand = timer.timed(
        "app.normalize_hand_code pitcher",
        app.normalize_hand_code,
        pitcher_info.get("pitchHand", ""),
    )
    result["pitcher_handedness"] = timer.timed(
        "app.format_pitcher_hand",
        app.format_pitcher_hand,
        pitcher_hand,
    )
    result["source_functions"]["app.py"].extend(["normalize_hand_code", "format_pitcher_hand"])

    app_data_started_at = perf_counter()
    app_load_tasks = {
        "pitcher_season_stats": (
            "Load pitcher data",
            "app.load_pitcher_stats",
            "app.load_pitcher_stats",
            app.load_pitcher_stats,
            (pitcher_id,),
            {},
        ),
        "pitch_mix": (
            "Load pitch mix",
            "Pitch mix",
            "app.load_regular_season_pitch_mix",
            app.load_regular_season_pitch_mix,
            (pitcher_id,),
            {"R": [], "L": [], "all": []},
        ),
        "batter_season_stats": (
            "Load batter data",
            "Batter contact stats",
            "app.load_batter_overall_contact_stats",
            app.load_batter_overall_contact_stats,
            (batter_id,),
            {},
        ),
        "batter_run_value": (
            "Load run values",
            "Batter run value",
            "app.load_batter_run_value_pitch_type_table",
            app.load_batter_run_value_pitch_type_table,
            (batter_id,),
            pd.DataFrame(),
        ),
        "batter_game_log": (
            "Load game logs",
            "Game logs",
            "app.load_batter_prop_game_log",
            app.load_batter_prop_game_log,
            (batter_id,),
            pd.DataFrame(),
        ),
        "batter_hit_details": (
            "Load game logs",
            "Hit details",
            "app.load_batter_hit_details_by_game",
            app.load_batter_hit_details_by_game,
            (batter_id, date.today().year),
            {},
        ),
    }
    with ThreadPoolExecutor(max_workers=len(app_load_tasks)) as executor:
        app_futures = {
            key: executor.submit(
                _profiled_existing_call,
                profile_label,
                timer,
                timing_label,
                errors,
                error_label,
                function,
                args,
                default,
            )
            for key, (profile_label, timing_label, error_label, function, args, default) in app_load_tasks.items()
        }
        app_loaded = {key: app_futures[key].result() for key in app_load_tasks}
    timer.log("Independent app data loads", app_data_started_at)

    pitcher_season_stats = app_loaded["pitcher_season_stats"]
    result["pitcher_season_stats"] = timer.timed("_json_safe pitcher season stats", _json_safe, pitcher_season_stats)
    result["source_functions"]["app.py"].append("load_pitcher_stats")

    pitch_mix = app_loaded["pitch_mix"]
    result["pitch_mix"] = timer.timed("_json_safe pitch mix", _json_safe, pitch_mix)
    result["source_functions"]["app.py"].append("load_regular_season_pitch_mix")

    batter_season_stats = app_loaded["batter_season_stats"]
    result["batter_season_stats"] = timer.timed("_json_safe batter contact stats", _json_safe, batter_season_stats)
    result["source_functions"]["app.py"].append("load_batter_overall_contact_stats")

    batter_run_value = app_loaded["batter_run_value"]
    result["batter_run_value_by_pitch_type"] = timer.timed(
        "_json_safe batter run value",
        _json_safe,
        batter_run_value,
    )
    result["source_functions"]["app.py"].append("load_batter_run_value_pitch_type_table")

    batter_game_log = app_loaded["batter_game_log"]
    result["batter_game_log"] = timer.timed("_json_safe game logs", _json_safe, batter_game_log)
    result["source_functions"]["app.py"].append("load_batter_prop_game_log")

    batter_hit_details = app_loaded["batter_hit_details"]
    result["batter_hit_details_by_game"] = timer.timed("_json_safe hit details", _json_safe, batter_hit_details)
    result["source_functions"]["app.py"].append("load_batter_hit_details_by_game")

    strike_zone_started_at = perf_counter()
    with performance_profile.timed("Load strike zone"):
        batter_hr_zone_data = timer.timed(
            "Batter HR strike zone data",
            _batter_home_run_zone_data,
            errors,
            batter_id,
            result["pitcher_handedness"] or "",
        )
        result["batter_strike_zone_home_run_data"] = timer.timed(
            "_json_safe batter HR strike zone data",
            _json_safe,
            batter_hr_zone_data,
        )
        batter_plate_discipline = timer.timed(
            "Batter plate discipline zone data",
            _batter_plate_discipline_zone_data,
            errors,
            batter_id,
            result["pitcher_handedness"] or "",
        )
        result["batter_plate_discipline_zone_data"] = timer.timed(
            "_json_safe batter plate discipline zone data",
            _json_safe,
            batter_plate_discipline,
        )
        pitcher_zone_tendencies = timer.timed(
            "Pitcher strike zone tendency data",
            _pitcher_zone_tendency_data,
            errors,
            pitcher_id,
            result["batter_handedness"] or "",
        )
        result["pitcher_strike_zone_tendency_data"] = timer.timed(
            "_json_safe pitcher strike zone tendency data",
            _json_safe,
            pitcher_zone_tendencies,
        )
    timer.log("Strike zone data", strike_zone_started_at)
    result["source_functions"]["strike_zone.py"].extend(
        [
            "load_batter_pitch_location_data",
            "load_pitch_location_data",
            "filter_by_pitcher_throws",
            "filter_by_batter_stands",
            "_is_take_description",
            "_build_distribution_zone_outputs",
            "_build_pitcher_metric_zone_outputs",
        ]
    )

    todos.append(
        "Pitcher strike-zone Home Run data is not exposed by existing project "
        "logic. strike_zone.PITCHER_STRIKE_ZONE_METRICS currently includes "
        "Pitch %, Whiff %, PutAway %, Hard Hit %, xwOBA, and K %, but not "
        "Home Runs. Pitcher attack-zone tendencies are collected separately "
        "via existing Pitch % zone utilities."
    )
    todos.append(
        "Direct batter-vs-pitcher matchup history is not currently exposed as "
        "a reusable function. app.py has opponent/team H2H helpers for game logs "
        "and hit-detail tooltips, but no existing function filters by both "
        "batter_id and pitcher_id."
    )
    todos.append(
        "Several useful app.py functions are Streamlit UI-only or depend on "
        "st.session_state, including render_batter_prop_game_log_section, "
        "render_batter_game_log_sample_section, selected_batter_opponent_context, "
        "and render_lineup_table. They are intentionally not called here."
    )

    with performance_profile.timed("HR analysis"):
        result["home_run_analysis"] = timer.timed("Home run analysis", _build_home_run_analysis, result)
    timer.log("get_matchup_data complete")
    return result
