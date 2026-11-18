# Suggestions and backfill ledger

## Backfill ledger

Learnings that may apply to work already shipped. Each needs a 360 review and
the owner's OK before shipped work is changed.

| Date | Learning | Affects | Status |
|---|---|---|---|
| 2026-11-18 | CEDA returns 2-4 rows for the same market and day (no variety field). For onion, 9,014 market-days; 97% of them carry different prices, so they are separate lots or varieties. The current rule keeps the last row, which is arbitrary. Proposed: combine a day's rows (median of modal prices, lowest min, highest max, record the count), or drop those days. | `farmiq_data/normalise.py` duplicate rule; all onion statistics (unpublished); 5 tomato market-days on the live site | Done 2026-11-18 (owner OK'd "combine"): 8,893 market-days combined; verdicts unchanged |

## Open items

- Agmarknet download for Nov 2025 to today (tomato, onion): needs the owner to solve 2 CAPTCHAs.
- Other states' supply (Karnataka, Andhra Pradesh, Madhya Pradesh markets) via CEDA, within its daily quota.
- Site data is about 3 MB (onion 2 MB, mostly planner grids); GitHub Pages gzips it, but split per market if phones load slowly.
- Automatic monthly rebuild: revisit once data is complete (raw history is not in the repo by design).
