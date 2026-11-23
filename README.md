# Florida Bank Peer Benchmark

**Question:** how does each Florida bank compare with its peers on profitability, efficiency, and credit quality, and is it improving or slipping?

A pipeline pulls quarterly FDIC data for six publicly traded Florida banks, computes peer medians and year-over-year changes in SQL, and feeds a Power BI dashboard. It refreshes itself twice a month.

![Executive overview dashboard](docs/dashboard-overview.png)

## Results (Q2 2026)

- **Profitability:** SouthState, U.S. Century and Capital City lead on ROA at 1.42% to 1.52%. Amerant, Seacoast and BankUnited trail near 0.9%.
- **Credit:** Credit stress is concentrated at Amerant (2.49% noncurrent loans) and BankUnited (1.69%). The other four are at or below 0.66%.
- **Capital:** All six banks hold CET1 above 12%, so the gaps are in asset quality and earnings, not capital.
- **Trajectory:** Amerant's ROA fell below zero in late 2024 and has recovered only to about 0.9%. BankUnited runs the thinnest net interest margin, roughly 2.5% to 3%.

## Peer set

| Ticker | Bank |
|---|---|
| SSB | SouthState Bank |
| BKU | BankUnited |
| SBCF | Seacoast National Bank |
| AMTB | Amerant Bank |
| CCBG | Capital City Bank |
| USCB | U.S. Century Bank |

Data: quarterly call reports from Q1 2019 onward.

## How it works

```
FDIC BankFind API  ->  fetch_financials.py  ->  Postgres (Neon)  ->  v_bank_financials view  ->  Power BI
                                 ^
                 GitHub Actions (1st and 15th of each month)
```

1. **Ingest.** `fetch_financials.py` pulls 16 fields for each bank and pages through the FDIC API.
2. **Store.** Rows are upserted on `(cert, repdte)`, so reruns update existing rows and never duplicate them.
3. **Validate.** After each load, a completeness check confirms every bank has the same quarters and no key field is null. If the check fails, the GitHub Actions run turns red.
4. **Transform.** The `v_bank_financials` view calculates quarter-over-quarter and year-over-year changes with `LAG()`, peer medians with `PERCENTILE_CONT`, and each bank's gap to the median.
5. **Report.** The Power BI dashboard reads the view directly.

## Metrics

| Group | Fields |
|---|---|
| Income | Total assets, net interest margin, ROA, ROE, interest expense, deposits |
| Credit | Noncurrent loan ratio, net charge-off rate, provision rate |
| Efficiency | Efficiency ratio, noninterest expense rate, noninterest income rate |
| Funding and capital | Loans to deposits, CET1 capital ratio |

Credit is shown as three separate signals, because they measure different things and move at different times:
- **Noncurrent loan ratio:** loans 90+ days past due or not accruing interest. An early warning.
- **Provision rate:** money set aside for expected losses.
- **Net charge-off rate:** losses already realized.

## Dashboard

The Power BI project in [`powerbi/`](powerbi) has three pages.

**Executive Overview:** peer share of assets, ROA against the peer median, and a quarter-and-year selector.

![Executive overview](docs/dashboard-overview.png)

**Profit Trajectory:** ROA, efficiency ratio, and net interest margin for each bank from 2019 to 2026.

![Profit trajectory](docs/dashboard-profit-trajectory.png)

**Credit Risk:** profitability against noncurrent loans, CET1 by bank, and net charge-off and provision trends.

![Credit risk](docs/dashboard-credit-risk.png)

The project is saved in Power BI's `.pbip` format, so the model and report definitions are readable text.

## Run it yourself

1. Create a Postgres database. Run the statements in `schema.sql` one at a time. The file describes the current structure, so running it in full against an existing database will fail on the `CREATE TABLE` lines.
2. Install dependencies and load the data:
   ```bash
   pip install -r requirements.txt
   echo "DATABASE_URL=postgresql://user:password@host/dbname" > .env
   python fetch_financials.py
   ```
3. To use the dashboard, open `powerbi/Banking-dashboard-Cl1.pbip` in Power BI Desktop and point the data source at your database. The committed file points at the author's database, so this step is required.

## Limitations

- **Small peer set.** A median of six banks moves a lot after one unusual quarter, and the bank being compared is part of its own median.
- **Lagged data.** Call reports post weeks after quarter end, so the newest numbers are always behind.
- **Basic alerting.** A failed run sends GitHub's standard failure email and nothing else.

## Next steps

- Run the missing-quarter check from `sql/exploration.sql` automatically after each load, so a gap in the middle of a bank's history fails the run
- Add a market valuation layer from SEC filings
- Publish the dashboard so it can be viewed without Power BI Desktop

## Tech

Python (`requests`, `psycopg2`, `python-dotenv`), PostgreSQL on Neon, SQL (CTEs, window functions, `PERCENTILE_CONT`), Power BI, GitHub Actions.
