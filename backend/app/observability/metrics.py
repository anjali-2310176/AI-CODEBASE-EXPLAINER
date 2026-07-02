import time
from collections import defaultdict

# Simple in-process metrics. Replace with Prometheus in production.
_counters: dict[str, int] = defaultdict(int)
_histograms: dict[str, list[float]] = defaultdict(list)


def increment(metric: str, value: int = 1) -> None:
    _counters[metric] += value


def observe(metric: str, value: float) -> None:
    _histograms[metric].append(value)
    if len(_histograms[metric]) > 1000:
        _histograms[metric] = _histograms[metric][-500:]


def get_metrics() -> dict:
    result: dict = {"counters": dict(_counters)}
    for name, values in _histograms.items():
        if values:
            result.setdefault("histograms", {})[name] = {
                "count": len(values),
                "avg_ms": round(sum(values) / len(values), 2),
                "max_ms": round(max(values), 2),
            }
    return result
