# FarmIQ: mandi price patterns

Do tomato and onion wholesale prices in the markets around Newasa (Ahilyanagar
district, Maharashtra) follow a pattern? This project gathers 20+ years of
daily mandi prices and arrivals, checks their quality, and tests a few plain
questions:

- **Seasonality:** are the same months reliably dear or cheap, year after year?
- **Boom and bust:** does a year of rising prices tend to be followed by a fall?
- **Supply:** do months with more produce arriving have lower prices?
- **Risk:** in which months do prices swing most?
- **Markets:** do nearby markets share the same seasonal shape?

Results are shown on a static site in [`docs/`](docs/) (served by GitHub Pages).
It is the first, data-only step of the FarmIQ crop-planning idea.

> Patterns in past prices are not a forecast. This is an educational analysis,
> not financial or agronomic advice.

## Data

| Source | What | Period | Notes |
|---|---|---|---|
| [CEDA Agri Market API](https://api.ceda.ashoka.edu.in/) (Ashoka University) | Daily min / max / modal price and arrivals per market | 2003 to latest monthly update | Mirrors Agmarknet; free for non-commercial use with credit |
| [Agmarknet 2.0](https://agmarknet.gov.in/) Daily Price and Arrival report | Daily prices per market, variety and grade | 2021 onward | Downloaded by hand (the site uses a CAPTCHA); used to cross-check CEDA |

Districts: Ahilyanagar (Ahmednagar), Chh. Sambhajinagar (Aurangabad), Beed,
Jalna, Nashik, Pune, Solapur, Dharashiv (Osmanabad).

On 3,226 market-days present in both sources, CEDA's modal price matched
Agmarknet's exactly on every day.

**Credit:** Price and arrival data: Agmarknet (Directorate of Marketing &
Inspection, Government of India), via the CEDA Agri Market API, Centre for
Economic Data and Analysis, Ashoka University.

Raw downloads are **not** committed (see `.gitignore`); only computed summaries
in `docs/data/` are.

## How it works

```
scripts/fetch_ceda.py   -> data/raw/ceda/        raw API responses (local only)
raw/*.csv               -> Agmarknet downloads   (local only)
scripts/build_site.py   -> docs/data/*.json      monthly summaries + verdicts
docs/index.html         -> charts (Observable Plot, no build step)
```

Code in `farmiq_data/`:

- `normalise.py`: one tidy table; ₹/quintal -> ₹/kg converted once; invalid
  rows are returned with a reason, never dropped silently.
- `patterns.py`: seasonal index (each month / that year's average), month
  summaries, year-to-year autocorrelation, within-month volatility.
- `report.py`: verdict rules and the cross-source check.
- `ceda.py`: API client (key from `CEDA_API_KEY` or a local `.env`, never logged).

### Rules behind the verdicts

- A month counts only with at least 5 reporting days; a year only with at least 9 such months.
- A seasonal verdict needs 8+ full years. A month is *reliably* dear (cheap) if
  it was above (below) that year's average in at least 75% of years.
- Boom and bust: correlation between one year's price change and the next;
  r <= -0.3 over at least 6 pairs of consecutive years.
- Supply: correlation between a month's arrivals and its price, each relative to
  its own year's average; at least 24 months.
- Prices are nominal. Modal price is the most common wholesale price at the
  mandi, not the farmer's net realisation.

## Run it

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"      # Windows; use .venv/bin on macOS/Linux
echo CEDA_API_KEY=your-key > .env                     # free key from api.ceda.ashoka.edu.in
.venv/Scripts/python -m pytest                        # tests
.venv/Scripts/python scripts/fetch_ceda.py            # slow on purpose (API rate limit)
.venv/Scripts/python scripts/build_site.py
.venv/Scripts/python -m http.server 8765 --directory docs   # open http://127.0.0.1:8765
```

## Known limitations

- CEDA updates monthly, so the newest weeks are missing; Agmarknet covers them
  but needs a manual download.
- Some markets report irregularly; years with too little data are left blank
  rather than filled in.
- Arrivals at one market are a weak proxy for regional supply.
- Production and yield data (annual, mostly state-level) are not yet included.
