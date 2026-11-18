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
- **Weather:** do unusually wet or hot months line up with price surprises later?

It also has a **planting-window planner**: pick a transplant month and crop
timing, and see the low / typical / high mandi price in the harvest months that
followed in past years. Enter your own cost per acre, marketable yield and
selling cost to see your break-even price and how many past years cleared it.
Nothing is pre-filled; the page never invents cost or yield figures.

Results are shown on a static site in [`docs/`](docs/) (served by GitHub Pages).
It is the first, data-only step of the FarmIQ crop-planning idea.

> Patterns in past prices are not a forecast. This is an educational analysis,
> not financial or agronomic advice.

## Data

| Source | What | Period | Notes |
|---|---|---|---|
| [CEDA Agri Market API](https://api.ceda.ashoka.edu.in/) (Ashoka University) | Daily min / max / modal price and arrivals per market | 2003 to latest monthly update | Mirrors Agmarknet; free for non-commercial use with credit |
| [Agmarknet 2.0](https://agmarknet.gov.in/) Daily Price and Arrival report | Daily prices per market, variety and grade | 2021 onward | Downloaded by hand (the site uses a CAPTCHA). Cross-checks CEDA where they overlap, and extends prices past CEDA's last date (added only after it, so nothing is counted twice) |
| [Open-Meteo historical weather](https://open-meteo.com/en/docs/historical-weather-api) (ERA5) | Daily rainfall and maximum temperature at each district centre | 2003 onward | CC BY 4.0; free for non-commercial use |

Districts planned: Ahilyanagar (Ahmednagar), Chh. Sambhajinagar (Aurangabad),
Beed, Jalna, Nashik, Pune, Solapur, Dharashiv (Osmanabad).

**Published:** tomato and onion for all eight districts, 2003 to 18 November
2026: CEDA to 30 October 2025, then Agmarknet downloads (Beed and Jalna have
little or no tomato data in the source). Arrivals come from CEDA only.

On 9,938 market-days present in both sources, CEDA's modal price matched
Agmarknet's exactly on all but one day.

**Credit:** Price and arrival data: Agmarknet (Directorate of Marketing &
Inspection, Government of India), via the CEDA Agri Market API, Centre for
Economic Data and Analysis, Ashoka University. Weather: Open-Meteo historical
weather API (ERA5 reanalysis), CC BY 4.0.

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
  rows are returned with a reason, never dropped silently. When a market reports
  several lots or varieties for the same day (CEDA has no variety field), they
  are combined: median of the modal prices, lowest min, highest max, and the
  number of rows combined is kept.
- `patterns.py`: seasonal index (each month / that year's average), month
  summaries, year-to-year autocorrelation, within-month volatility.
- `report.py`: verdict rules and the cross-source check.
- `ceda.py`: API client (key from `CEDA_API_KEY` or a local `.env`, never logged).
- `planner.py`: harvest months for a transplant month and crop timing (a month
  counts when 10+ harvest days fall in it), harvest-window prices per year,
  low/typical/high over the last 10 years or all years, break-even price.
- `weather.py`: Open-Meteo client, monthly rainfall and heat anomalies, and
  their lagged correlation with "price surprises" (a month's price versus the
  usual level for that month).

Findings so far:

- Tomato: a strong seasonal pattern (June-July dear, January-April cheap), a
  boom-and-bust tendency between years, and only a weak link to local weather.
- Onion: October-November dear, March-July cheap, and a stronger boom-and-bust
  cycle between years.
- Prices are mostly set by supply from across India, not local weather.

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
.venv/Scripts/python scripts/fetch_weather.py
.venv/Scripts/python scripts/build_site.py
.venv/Scripts/python -m http.server 8765 --directory docs   # open http://127.0.0.1:8765
```

## Known limitations

- CEDA updates monthly and lags; newer prices need a manual Agmarknet download
  (a CAPTCHA per year of data per crop). Arrivals after CEDA's last date are not included.
- Some markets report irregularly; years with too little data are left blank
  rather than filled in.
- Arrivals at one market are a weak proxy for regional supply.
- Production and yield data (annual, mostly state-level) are not yet included.
