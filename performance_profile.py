from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Iterator
import threading


@dataclass
class RequestStats:
    total: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    unique_keys: set[str] = field(default_factory=set)
    response_times: list[float] = field(default_factory=list)


@dataclass
class PerformanceProfile:
    label: str
    started_at: float = field(default_factory=perf_counter)
    timings: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    request_stats: dict[str, RequestStats] = field(
        default_factory=lambda: {
            "savant": RequestStats(),
            "mlb": RequestStats(),
        }
    )

    def elapsed(self) -> float:
        return perf_counter() - self.started_at


_ACTIVE_PROFILE: PerformanceProfile | None = None
_PROFILE_LOCK = threading.Lock()


def start_profile(label: str) -> PerformanceProfile:
    profile = PerformanceProfile(label=label)
    set_active_profile(profile)
    return profile


def set_active_profile(profile: PerformanceProfile | None) -> None:
    global _ACTIVE_PROFILE
    with _PROFILE_LOCK:
        _ACTIVE_PROFILE = profile


def active_profile() -> PerformanceProfile | None:
    with _PROFILE_LOCK:
        return _ACTIVE_PROFILE


def record_timing(label: str, seconds: float, profile: PerformanceProfile | None = None) -> None:
    target = profile or active_profile()
    if target is None:
        return
    with _PROFILE_LOCK:
        target.timings[label] += float(seconds)


@contextmanager
def timed(label: str, profile: PerformanceProfile | None = None) -> Iterator[None]:
    started_at = perf_counter()
    try:
        yield
    finally:
        record_timing(label, perf_counter() - started_at, profile=profile)


def record_request(
    service: str,
    key: Any,
    elapsed_seconds: float | None = None,
    cache_status: str = "miss",
    profile: PerformanceProfile | None = None,
) -> None:
    target = profile or active_profile()
    if target is None:
        return

    service_key = "savant" if str(service).lower() == "savant" else "mlb"
    with _PROFILE_LOCK:
        stats = target.request_stats.setdefault(service_key, RequestStats())
        stats.total += 1
        stats.unique_keys.add(str(key))
        if cache_status == "hit":
            stats.cache_hits += 1
        else:
            stats.cache_misses += 1
            if elapsed_seconds is not None:
                stats.response_times.append(float(elapsed_seconds))


def merge_profile_metrics(target: PerformanceProfile, source: PerformanceProfile) -> None:
    with _PROFILE_LOCK:
        for label, seconds in source.timings.items():
            target.timings[label] += seconds
        for service, source_stats in source.request_stats.items():
            target_stats = target.request_stats.setdefault(service, RequestStats())
            target_stats.total += source_stats.total
            target_stats.cache_hits += source_stats.cache_hits
            target_stats.cache_misses += source_stats.cache_misses
            target_stats.unique_keys.update(source_stats.unique_keys)
            target_stats.response_times.extend(source_stats.response_times)


def _fmt(seconds: float) -> str:
    return f"{seconds:.2f}s"


def _avg(values: list[float]) -> float:
    return (sum(values) / len(values)) if values else 0.0


def format_report(profile: PerformanceProfile) -> str:
    total = profile.elapsed()
    timing_order = [
        "Load schedule",
        "Find lineup",
        "Load handedness",
        "Load pitcher data",
        "Load batter data",
        "Load pitch mix",
        "Load strike zone",
        "Load run values",
        "Load game logs",
        "HR analysis",
        "Walk analysis",
        "Ranking",
        "Discord embed",
        "Discord send",
    ]

    lines = ["==========================", profile.label, ""]
    for label in timing_order:
        seconds = profile.timings.get(label, 0.0)
        if seconds > 0:
            lines.append(f"{label:<30}{_fmt(seconds)}")
    lines.append("")
    lines.append(f"{'TOTAL':<30}{_fmt(total)}")
    lines.append("==========================")

    savant = profile.request_stats.get("savant", RequestStats())
    mlb = profile.request_stats.get("mlb", RequestStats())
    lines.extend(
        [
            "",
            "Network Summary",
            "",
            "Baseball Savant requests:",
            f"Total lookups: {savant.total}",
            f"Unique: {len(savant.unique_keys)}",
            f"Cache hits: {savant.cache_hits}",
            f"Cache misses: {savant.cache_misses}",
            "",
            "MLB API requests:",
            f"Total lookups: {mlb.total}",
            f"Unique: {len(mlb.unique_keys)}",
            f"Cache hits: {mlb.cache_hits}",
            f"Cache misses: {mlb.cache_misses}",
            "",
            "Average Savant response:",
            f"{_avg(savant.response_times):.2f} sec",
            "",
            "Average MLB response:",
            f"{_avg(mlb.response_times):.2f} sec",
        ]
    )

    bottlenecks = sorted(profile.timings.items(), key=lambda item: item[1], reverse=True)[:3]
    if bottlenecks:
        lines.extend(["", "Top Bottlenecks"])
        for idx, (label, seconds) in enumerate(bottlenecks, start=1):
            pct = (seconds / total * 100.0) if total else 0.0
            lines.append(f"{idx}. {label}: {_fmt(seconds)} ({pct:.1f}%)")

    return "\n".join(lines)
