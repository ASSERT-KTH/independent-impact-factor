# Independent Impact Factor for CS Journals

Computes the 2024 impact factor for key software-engineering journals using
the [Semantic Scholar](https://www.semanticscholar.org/) API.

**Key difference from the official JCR impact factor:** citations from
*conference papers* are included (not just journal-to-journal citations),
giving a more complete picture of how widely the research is actually cited
in the CS community.

## Journals covered

| Key | Journal |
|-----|---------|
| `IEEE TSE` | IEEE Transactions on Software Engineering |
| `ACM TOSEM` | ACM Transactions on Software Engineering and Methodology |
| `Springer EMSE` | Empirical Software Engineering |

## Formula

```
IF_2024 = citations_in_2024_to_papers_published_in_2022_or_2023
          ────────────────────────────────────────────────────────
          number_of_papers_published_in_2022_or_2023
```

This is the same two-year sliding window used by Clarivate/JCR.

## Requirements

- Python 3.9+
- `requests` library

```bash
pip install -r requirements.txt
```

## Usage

```bash
# Run for all three journals (no API key — public rate limit applies)
python compute_impact_factor.py

# With a Semantic Scholar API key (higher rate limits)
python compute_impact_factor.py --api-key YOUR_KEY

# Run for a single journal
python compute_impact_factor.py --journals "IEEE TSE"

# Custom output file
python compute_impact_factor.py --output my_results.json
```

Results are printed as a summary table and written to `results.json`
(or the file specified via `--output`).

## Notes

- The script uses the public Semantic Scholar Graph API v1.
  Request a free API key at https://www.semanticscholar.org/product/api
  to avoid hitting the anonymous rate limit (≈ 1 req/s).
- Semantic Scholar's coverage of older or smaller venues may be incomplete;
  the numbers therefore represent a lower bound.
- Because venue names vary across records, the script accepts several
  spelling variants for each journal and matches them case-insensitively.
