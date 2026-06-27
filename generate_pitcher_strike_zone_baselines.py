import json
from datetime import date
from pathlib import Path

import pandas as pd
import requests
from pybaseball import statcast

import strike_zone


SEASON_YEAR = 2026
START_DATE = f"{SEASON_YEAR}-03-01"
END_DATE = date.today().isoformat()
SUMMARY_COLUMNS = [
    "zone",
    "qualified_pitchers",
    "mean",
    "median",
    "std",
    "min",
    "max",
    "p10",
    "p25",
    "p50",
    "p75",
    "p90",
]


def _extract_json_array(text, marker):
    idx = text.find(marker)
    if idx == -1:
        return []

    start = text.find("[", idx)
    if start == -1:
        return []

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
        return []

    return json.loads(text[start:end])


def load_qualified_pitcher_ids(season_year=SEASON_YEAR):
    url = f"https://baseballsavant.mlb.com/leaderboard/custom?year={season_year}&type=pitcher"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    rows = _extract_json_array(response.text, "var data = ")

    pitcher_ids = []
    for row in rows:
        player_id = row.get("player_id")
        if player_id is None:
            continue
        try:
            pitcher_ids.append(int(player_id))
        except (TypeError, ValueError):
            continue

    return sorted(set(pitcher_ids))


def _zone_values_from_outputs(zone_df, outer_stats):
    values = {}
    if not zone_df.empty:
        for _, row in zone_df.iterrows():
            values[int(row["zone_id"])] = {
                "count": int(row["pitch_count"]),
                "value": float(row["pitch_pct"]),
            }

    for quad_key, zone_id in strike_zone.OUTER_QUAD_TO_ZONE.items():
        values[zone_id] = {
            "count": int(outer_stats[quad_key]["pitch_count"]),
            "value": float(outer_stats[quad_key]["pitch_pct"]),
        }

    return values


def _metric_has_defined_sample(metric, zone_value):
    if metric == "Pitch %":
        return True
    return zone_value["count"] > 0


def build_pitcher_metric_values(statcast_df, qualified_pitcher_ids):
    rows = []
    qualified_ids = set(int(pid) for pid in qualified_pitcher_ids)
    working_df = statcast_df[statcast_df["pitcher"].astype("Int64").isin(qualified_ids)].copy()
    if "game_type" in working_df.columns:
        working_df = working_df[working_df["game_type"] == "R"].copy()

    for pitcher_id, pitcher_df in working_df.groupby("pitcher"):
        for metric in strike_zone.PITCHER_STRIKE_ZONE_METRICS:
            zone_df, outer_stats, _ = strike_zone._build_pitcher_metric_zone_outputs(pitcher_df, metric)
            zone_values = _zone_values_from_outputs(zone_df, outer_stats)
            for zone_id in sorted(strike_zone.DISPLAY_ZONE_IDS):
                zone_value = zone_values.get(zone_id, {"count": 0, "value": 0.0})
                if not _metric_has_defined_sample(metric, zone_value):
                    continue
                rows.append(
                    {
                        "pitcher_id": int(pitcher_id),
                        "metric": metric,
                        "zone": int(zone_id),
                        "value": float(zone_value["value"]),
                    }
                )

    return pd.DataFrame(rows)


def summarize_metric(metric_values_df, metric):
    metric_df = metric_values_df[metric_values_df["metric"] == metric].copy()
    rows = []
    for zone_id in sorted(strike_zone.DISPLAY_ZONE_IDS):
        zone_values = metric_df.loc[metric_df["zone"] == zone_id, "value"].dropna().astype(float)
        if zone_values.empty:
            rows.append({column: "" for column in SUMMARY_COLUMNS})
            rows[-1]["zone"] = zone_id
            rows[-1]["qualified_pitchers"] = 0
            continue

        rows.append(
            {
                "zone": zone_id,
                "qualified_pitchers": int(zone_values.count()),
                "mean": round(float(zone_values.mean()), 4),
                "median": round(float(zone_values.median()), 4),
                "std": round(float(zone_values.std(ddof=1)), 4) if len(zone_values) > 1 else 0.0,
                "min": round(float(zone_values.min()), 4),
                "max": round(float(zone_values.max()), 4),
                "p10": round(float(zone_values.quantile(0.10)), 4),
                "p25": round(float(zone_values.quantile(0.25)), 4),
                "p50": round(float(zone_values.quantile(0.50)), 4),
                "p75": round(float(zone_values.quantile(0.75)), 4),
                "p90": round(float(zone_values.quantile(0.90)), 4),
            }
        )

    return pd.DataFrame(rows, columns=SUMMARY_COLUMNS)


def main():
    output_dir = Path(__file__).resolve().parent
    qualified_pitcher_ids = load_qualified_pitcher_ids()
    if not qualified_pitcher_ids:
        raise RuntimeError("No qualified pitchers were returned by the Baseball Savant pitcher leaderboard.")

    print(f"Qualified pitchers: {len(qualified_pitcher_ids)}")
    print(f"Loading Statcast from {START_DATE} to {END_DATE}...")
    statcast_df = statcast(START_DATE, END_DATE)
    if statcast_df is None or statcast_df.empty:
        raise RuntimeError("Statcast returned no rows.")

    required_columns = {"pitcher", "zone"}
    missing = sorted(required_columns - set(statcast_df.columns))
    if missing:
        raise RuntimeError(f"Statcast data is missing required columns: {', '.join(missing)}")

    metric_values_df = build_pitcher_metric_values(statcast_df, qualified_pitcher_ids)
    if metric_values_df.empty:
        raise RuntimeError("No pitcher metric values were generated.")

    for metric, filename in strike_zone.PITCHER_BASELINE_CSVS.items():
        summary_df = summarize_metric(metric_values_df, metric)
        path = output_dir / filename
        summary_df.to_csv(path, index=False)
        print(f"Wrote {filename}")


if __name__ == "__main__":
    main()
