import json
import os
from pathlib import Path


SCHEMA_VERSION = 1
DEFAULT_CACHE_DIR = Path("data") / "cache"


def props_summary_cache_path(cache_date, cache_dir=DEFAULT_CACHE_DIR):
    return Path(cache_dir) / f"props_summary_{cache_date}.json"


def write_json_atomic(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temp_path, path)
    return path
