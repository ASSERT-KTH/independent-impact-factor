# Independent Impact Factor for CS Journals

Computes an independent impact factor for a journal using
the [Semantic Scholar](https://www.semanticscholar.org/) API.

Our research systems — funding allocation, hiring decisions, tenure evaluation, venue rankings — must not be steered by proprietary data, closed algorithms, or opaque commercial products. When the metrics that shape academic careers and institutional priorities are locked behind paywalls or black boxes, the scientific community loses the ability to scrutinize, reproduce, or challenge them. This repository exists as a principled alternative: all data sources, computation logic, and results are fully open and reproducible.

See the [Software Engineering results](if-se.md) for the current numbers.

## Methodology

This code addresses two independent improvements over the official JCR/WoS impact factor:

1. **Recompute outside WoS** (`wos_replica` mode): replace the proprietary Web of Science database with the open Semantic Scholar API, keeping the same JCR methodology (journal-to-journal citations only). This makes the computation fully reproducible and auditable.

2. **Broader citation base** (`extended` mode, the default): in addition to using Semantic Scholar, count citations from *all* paper types — including conference papers. In CS, a large fraction of influential work appears at conferences, so the journal-only restriction systematically understates real-world impact. This is the primary "independent IF" metric.

These two dimensions are kept separate in both the code (`--mode` flag) and the results so each contribution can be evaluated independently.

## Formula

```
IF_Y = citations_in_Y_to_papers_published_in_(Y-2)_or_(Y-1)
       ──────────────────────────────────────────────────────────
       number_of_papers_published_in_(Y-2)_or_(Y-1)
```

This is the same two-year sliding window used by Clarivate/JCR.

## Requirements

- Python 3.9+
- `requests` library

```bash
pip install -r requirements.txt
```

## Usage

### Single-year / multi-year computation (`compute_impact_factor.py`)

The list of journals is defined in a JSON file (e.g. `se.json`).
Output filenames are derived from that file's stem.

```bash
# Extended mode (default) — all citations including conferences
python compute_impact_factor.py --journals-file se.json 2024

# WoS-replica mode — journal-to-journal citations only
python compute_impact_factor.py --journals-file se.json 2024 --mode wos_replica

# All years (2023–2025) combined summary
python compute_impact_factor.py --journals-file se.json --all

# With a Semantic Scholar API key (higher rate limits)
python compute_impact_factor.py --journals-file se.json 2024 --api-key YOUR_KEY

# Subset of journals
python compute_impact_factor.py --journals-file se.json 2024 --journals "IEEE TSE"
```

Results are written to `if-{stem}.md` (Markdown) and `results-{stem}.json`.

### Longitudinal comparison (`longitudinal_analysis.py`)

Computes both modes for TSE and TOSEM over citation years 2021–2025 and
produces a CSV and a line chart comparing WoS-replica vs Extended IFs.

```bash
python longitudinal_analysis.py [--api-key YOUR_KEY]

# Regenerate the chart from an existing CSV without API calls
python longitudinal_analysis.py --plot-only
```

Outputs:
- `longitudinal_tse_tosem.csv` — 20 rows (2 journals × 5 years × 2 modes)
- `longitudinal_tse_tosem.png` — line chart with 4 series

## Notes

- The script uses the public Semantic Scholar Graph API v1.
  Request a free API key at https://www.semanticscholar.org/product/api
  to avoid hitting the anonymous rate limit (≈ 1 req/s).
- Semantic Scholar's coverage of older or smaller venues may be incomplete;
  the numbers therefore represent a lower bound.
- Because venue names vary across records, the script accepts several
  spelling variants for each journal and matches them case-insensitively.
