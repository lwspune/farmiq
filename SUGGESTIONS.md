# Suggestions and backfill ledger

## Backfill ledger

Learnings that may apply to work already shipped. Each needs a 360 review and
the owner's OK before shipped work is changed.

| Date | Learning | Affects | Status |
|---|---|---|---|
| 2026-11-18 | CEDA returns 2-4 rows for the same market and day (no variety field). For onion, 9,014 market-days; 97% of them carry different prices, so they are separate lots or varieties. The current rule keeps the last row, which is arbitrary. Proposed: combine a day's rows (median of modal prices, lowest min, highest max, record the count), or drop those days. | `farmiq_data/normalise.py` duplicate rule; all onion statistics (unpublished); 5 tomato market-days on the live site | Done 2026-11-18 (owner OK'd "combine"): 8,893 market-days combined; verdicts unchanged |

## Open items

- Done 2026-11-18: Agmarknet prices 31 Oct 2025 - 18 Nov 2026 for tomato and onion (4 CAPTCHAs). Repeat monthly-ish to keep current.
- Agmarknet "Both" (price + arrivals) report exists from 7 Nov 2025; could add arrivals for the post-CEDA period.
- Done 2026-11-18: other states' supply (state-level arrivals for 7 states + all India) on the site.
- State-level prices are downloaded but not yet used: compare price levels across states (where is it cheapest to buy, dearest to sell).
- Site data is about 3 MB (onion 2 MB, mostly planner grids); GitHub Pages gzips it, but split per market if phones load slowly.
- Automatic monthly rebuild: revisit once data is complete (raw history is not in the repo by design).
- Owner request 2026-11-19, parked ("ignore for now"): a price table under a chart, years as columns, months as rows, median ₹/kg per cell for the chosen market. Data is already in `monthly`; open question is which card it sits under.
- Done 2026-11-19: season, heatmap, compare and verdicts switched to the last-twelve-months baseline (owner's choice). Weather, supply and arrivals checks stay on the calendar-year index on purpose (LTM carries last year's boom or bust into every month and blurs those correlations).
