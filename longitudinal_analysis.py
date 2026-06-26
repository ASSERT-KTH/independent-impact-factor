#!/usr/bin/env python3
"""
Longitudinal comparison of two impact-factor computation modes for TSE and TOSEM
over citation years 2021–2025 (10 years × 2 modes = 20 data points).

Two modes (see compute_impact_factor.py for full description):

  wos_replica — Uses Semantic Scholar data but counts only journal-to-journal
    citations, replicating the JCR/WoS methodology with open data.

  extended — Counts citations from all paper types (journals + conferences),
    giving a more complete picture of impact in CS where conferences matter.

Outputs:
  longitudinal_tse_tosem.csv  — 20-row CSV with all results
  longitudinal_tse_tosem.png  — line chart with 4 series
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

from compute_impact_factor import (
    RequestCache,
    _SS_API_KEY,
    compute_impact_factor,
    load_journals,
    CACHE_PATH,
)

JOURNALS_FILE = "se.json"
TARGET_JOURNALS = ["IEEE TSE", "ACM TOSEM"]
CITATION_YEARS = list(range(2021, 2026))
CSV_PATH = "longitudinal_tse_tosem.csv"
PNG_PATH = "longitudinal_tse_tosem.png"

MODES: list[tuple[str, bool]] = [
    ("wos_replica", True),
    ("extended", False),
]


def run(api_key: str | None, cache_path: str) -> list[dict]:
    journals = load_journals(JOURNALS_FILE)
    cache = RequestCache(cache_path)
    rows: list[dict] = []
    try:
        for journal_key in TARGET_JOURNALS:
            for mode_name, journal_only in MODES:
                for year in CITATION_YEARS:
                    result = compute_impact_factor(
                        journal_key,
                        year,
                        journals,
                        journal_only=journal_only,
                        api_key=api_key,
                        cache=cache,
                    )
                    rows.append({
                        "journal": journal_key,
                        "citation_year": year,
                        "mode": mode_name,
                        "papers_in_window": result["papers_in_window"],
                        "citations_in_year": result["citations_in_year"],
                        "impact_factor": result["impact_factor"],
                    })
    finally:
        cache.close()
    return rows


def write_csv(rows: list[dict], path: str) -> None:
    fields = ["journal", "citation_year", "mode", "papers_in_window",
              "citations_in_year", "impact_factor"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"CSV written to {path}")


SeriesKey = tuple[str, str]


def plot(rows: list[dict], path: str) -> None:
    series: dict[SeriesKey, dict[int, float]] = {}
    labels: dict[SeriesKey, str] = {
        ("IEEE TSE", "wos_replica"): "TSE — WoS-replica",
        ("IEEE TSE", "extended"): "TSE — Extended (incl. conferences)",
        ("ACM TOSEM", "wos_replica"): "TOSEM — WoS-replica",
        ("ACM TOSEM", "extended"): "TOSEM — Extended (incl. conferences)",
    }
    # Each journal gets a color; each mode gets a marker.
    colors: dict[str, str] = {
        "IEEE TSE":   "#1f77b4",
        "ACM TOSEM":  "#ff7f0e",
    }
    markers: dict[str, str] = {
        "wos_replica": "x",
        "extended":    "^",
    }

    for row in rows:
        key: SeriesKey = (row["journal"], row["mode"])
        if key not in series:
            series[key] = {}
        if row["impact_factor"] is not None:
            series[key][int(row["citation_year"])] = float(row["impact_factor"])

    fig, ax = plt.subplots(figsize=(9, 5))
    for key, label in labels.items():
        data = series.get(key, {})
        xs = sorted(data)
        ys = [data[x] for x in xs]
        ax.plot(
            xs, ys,
            label=label,
            color=colors[key[0]],
            linestyle="-",
            marker=markers[key[1]],
            markersize=8,
            linewidth=2,
        )

    ax.set_xlabel("Citation year")
    ax.set_ylabel("Impact factor")
    ax.set_title("Independent Impact Factor: WoS-replica vs Extended\n(IEEE TSE and ACM TOSEM, 2021–2025)")
    ax.xaxis.set_major_locator(ticker.MultipleLocator(1))
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(True, linestyle=":", alpha=0.5)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"Chart saved to {path}")


def load_existing_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = []
        for row in reader:
            row["citation_year"] = int(row["citation_year"])
            row["papers_in_window"] = int(row["papers_in_window"])
            row["citations_in_year"] = int(row["citations_in_year"])
            val = row["impact_factor"]
            row["impact_factor"] = float(val) if val not in ("", "None") else None
            rows.append(row)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-key", metavar="KEY", default=None,
        help="Semantic Scholar API key (defaults to keyring value).",
    )
    parser.add_argument("--cache-path", default=CACHE_PATH)
    parser.add_argument(
        "--plot-only",
        action="store_true",
        help=f"Skip API calls; regenerate the chart from an existing {CSV_PATH}.",
    )
    args = parser.parse_args()

    if args.api_key is None:
        args.api_key = _SS_API_KEY
    if args.plot_only:
        if not Path(CSV_PATH).exists():
            sys.exit(f"No {CSV_PATH} found — run without --plot-only first.")
        rows = load_existing_csv(CSV_PATH)
    else:
        rows = run(args.api_key, args.cache_path)
        write_csv(rows, CSV_PATH)

    plot(rows, PNG_PATH)


if __name__ == "__main__":
    main()
