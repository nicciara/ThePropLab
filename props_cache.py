import json
import os
from pathlib import Path


SCHEMA_VERSION = 1
DEFAULT_CACHE_DIR = Path("data") / "cache"


def props_summary_cache_path(cache_date, cache_dir=DEFAULT_CACHE_DIR):
    return Path(cache_dir) / f"props_summary_{cache_date}.json"


def load_props_summary_cache(cache_date, cache_dir=DEFAULT_CACHE_DIR, schema_version=SCHEMA_VERSION):
    path = props_summary_cache_path(cache_date, cache_dir)
    if not path.exists():
        return None, f"cache file not found: {path}"

    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"cache file could not be read: {exc}"

    if not isinstance(payload, dict):
        return None, "cache payload is not an object"
    if payload.get("schema_version") != schema_version:
        return None, f"unsupported schema_version: {payload.get('schema_version')!r}"
    if payload.get("date") != str(cache_date):
        return None, f"cache date mismatch: {payload.get('date')!r}"

    records = payload.get("records")
    if not isinstance(records, list):
        return None, "cache records is not a list"

    return payload, ""


def write_json_atomic(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temp_path, path)
    return path
