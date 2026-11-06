"""Measure Streamlit Python rendering and HTTP costs without business writes.

Run with: python -m scripts.profile_ui --base-url http://127.0.0.1:8011
This is not a browser paint/network benchmark. Reports contain timings only.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from statistics import median
from time import perf_counter

from streamlit.testing.v1 import AppTest

from app.api_client import ApiClientError, HospitalApiClient


PAGES = ("overview", "data", "training", "training_results", "models", "forecast", "monitoring", "demo_reset")
READ_ROUTES = {
    "/health", "/data/status", "/departments", "/pipeline/runs", "/data-quality",
    "/history", "/training/runs", "/models", "/models/production",
    "/forecasts/official", "/forecasts/drafts", "/monitoring", "/demo/reset/status",
}


def is_read_only_request(method, path, json_body=None):
    if method == "GET":
        return path in READ_ROUTES or bool(re.fullmatch(r"/training/(results|evaluation|status)/[A-Za-z0-9_-]+", path))
    # Existing backend contract: missing confirmation returns only a read-only plan.
    return (method == "POST" and path == "/forecasts/official/confirm"
            and isinstance(json_body, dict) and "confirmation" not in json_body)


class ProfilingClient(HospitalApiClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.measurements = []
        self.request_keys = []

    def _request(self, method, path, *, params=None, json_body=None):
        if not is_read_only_request(method, path, json_body):
            raise RuntimeError(f"Profiling blocks non-read-only request: {method} {path}")
        started = perf_counter()
        error = None
        try:
            return super()._request(method, path, params=params, json_body=json_body)
        except ApiClientError as exc:
            error = exc.code
            raise
        finally:
            # Keep IDs, dates, query values and response contents out of reports.
            route = re.sub(r"(/training/(?:results|evaluation|status))/[^/]+", r"\1/{id}", path)
            self.measurements.append({"method": method, "route": route,
                                      "elapsed_ms": round((perf_counter() - started) * 1000, 2), "error": error})
            self.request_keys.append((method, path, json.dumps(params, sort_keys=True), json.dumps(json_body, sort_keys=True)))


def profile_pages(base_url, *, repeats=3, page_names=PAGES):
    result = {"measured_at": datetime.now(timezone.utc).isoformat(), "repeats": repeats,
              "scope": "Streamlit AppTest render + real read-only HTTP; excludes browser paint",
              "pages": {}}
    client = ProfilingClient(base_url, timeout_seconds=30)
    for name in page_names:
        app = AppTest.from_string('''
import importlib
import streamlit as st
from contextlib import nullcontext
from time import perf_counter
from app.styles import apply_global_styles
client = st.session_state["profile_client"]
apply_global_styles()
scope = client.request_scope() if hasattr(client, "request_scope") else nullcontext()
started = perf_counter()
with scope:
    st.session_state["profile_scope_setup_ms"] = (perf_counter() - started) * 1000
    importlib.import_module("app.pages." + st.session_state["profile_page"]).render(client)
''', default_timeout=180)
        app.session_state["profile_client"] = client
        app.session_state["profile_page"] = name
        samples = []
        # First load is separate; subsequent runs have Python/Streamlit imports warmed.
        for index in range(repeats + 1):
            client.measurements.clear()
            client.request_keys.clear()
            started = perf_counter()
            app.run()
            elapsed = (perf_counter() - started) * 1000
            setup_ms = app.session_state["profile_scope_setup_ms"]
            counts = Counter(client.request_keys)
            sample = {"phase": "first_load" if index == 0 else "rerun", "render_ms": round(elapsed, 2),
                      "scope_setup_ms": round(setup_ms, 2),
                      "api_ms": round(setup_ms + sum(r["elapsed_ms"] for r in client.measurements), 2),
                      "request_count": len(client.measurements),
                      "duplicate_request_count": sum(n - 1 for n in counts.values()),
                      "exception_count": len(app.exception), "requests": list(client.measurements)}
            samples.append(sample)
        warm = samples[1:]
        summary = {"render_median_ms": round(median(r["render_ms"] for r in warm), 2),
                   "api_median_ms": round(median(r["api_ms"] for r in warm), 2),
                   "request_counts": [r["request_count"] for r in warm],
                   "duplicate_counts": [r["duplicate_request_count"] for r in warm],
                   "error_count": sum(r["exception_count"] + sum(bool(c["error"]) for c in r["requests"]) for r in samples)}
        result["pages"][name] = {"summary": summary, "samples": samples}
        print(f"{name}: {json.dumps(summary)}", flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--pages", nargs="+", choices=PAGES, default=list(PAGES))
    parser.add_argument("--output", type=Path, default=Path("reports/ui_performance/latest.json"))
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    result = profile_pages(args.base_url, repeats=args.repeats, page_names=args.pages)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 1 if any(p["summary"]["error_count"] for p in result["pages"].values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
