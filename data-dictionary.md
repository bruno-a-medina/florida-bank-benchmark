# Data Dictionary

Source: FDIC BankFind Suite, financials endpoint (https://banks.data.fdic.gov/docs/). One row per bank per quarter.

**Units.** Ratio fields are already percent numbers, so `1.42` means 1.42%. `ASSET` and `DEP` are in thousands of dollars. Power BI converts ratios with measures that divide by 100 so they display as true percentages.

## Fields stored in `quarterly_financials`

| FDIC field | Database column | Meaning | Unit | Better |
|---|---|---|---|---|
| CERT | `cert` | FDIC certificate number, the bank's unique ID | integer | n/a |
| REPDTE | `repdte` | Quarter-end report date | date | n/a |
| ASSET | `asset` | Total assets | $ thousands | n/a |
| NIMY | `nimy` | Net interest margin: net interest income relative to average earning assets | % | Higher |
| ROA | `roa` | Return on assets: net income relative to average assets | % | Higher |
| ROE | `roe` | Return on equity: net income relative to average equity | % | Higher |
| INTEXPY | `intexpy` | Interest expense relative to average earning assets (cost of funding) | % | Lower |
| DEP | `dep` | Total deposits | $ thousands | n/a |
| NCLNLSR | `ncnlsr` | **Noncurrent loan ratio**: loans 90+ days past due or not accruing interest, as a share of total loans. Early warning of credit stress. (Column name is a historical typo of the FDIC field name) | % | Lower |
| NTLNLSR | `ntlnlsr` | **Net charge-off rate**: loans written off net of recoveries, as a share of average loans. Realized losses | % | Lower |
| ELNATRY | `elnatry` | Provision for credit losses relative to assets. Expected losses the bank sets aside | % | Lower |
| EEFFR | `eeffr` | Efficiency ratio: noninterest expense relative to net interest income plus noninterest income | % | Lower |
| NONIXAY | `nonixay` | Noninterest expense relative to average assets | % | Lower |
| NONIIAY | `noniiay` | Noninterest income relative to average assets | % | Higher |
| LNLSDEPR | `lnlsdepr` | Loans relative to deposits | % | Context |
| IDT1CER | `idt1cer` | Common equity tier 1 (CET1) capital ratio: the core loss-absorbing capital cushion | % | Higher |

## Credit quality: three different signals

| Signal | Field | What it tells you |
|---|---|---|
| Noncurrent loan rate | NCLNLSR | Loans already in trouble, before any loss is booked (leading) |
| Provision rate | ELNATRY | Losses the bank expects, set aside in advance |
| Net charge-off rate | NTLNLSR | Losses actually taken (lagging) |

Reading them together matters. A rising noncurrent rate with a low charge-off rate means problems are building but have not hit earnings yet.

## Columns added by the view `v_bank_financials`

| Column | Definition |
|---|---|
| `date`, `year`, `quarter` | Report date and its calendar year and quarter |
| `total_assets`, `net_interest_margin`, `return_on_assets`, `return_on_equity`, `noncurrent_loan_rate`, `net_charge_off_rate`, `provision_rate`, `efficiency_ratio`, `noninterest_expense_rate`, `noninterest_income_rate`, `loans_to_deposits`, `cet1_capital_ratio` | Friendly names for the stored fields above |
| `roa_qoq`, `nim_qoq` | Change from the prior quarter, in percentage points |
| `roa_yoy`, `nim_yoy`, `efficiency_yoy`, `noncurrent_yoy`, `net_charge_off_yoy` | Change from the same quarter a year earlier, in percentage points |
| `asset_growth_yoy` | Change in total assets versus the same quarter a year earlier, in $ thousands |
| `peer_median_*` | Median across the six banks for the same quarter. Median is used instead of mean because six banks is too few for an average to resist one outlier |
| `*_vs_peer` | The bank's value minus the peer median, in percentage points |

## Known issues and caveats

- `cost_of_deposits` in the view divides a rate by a dollar amount and is not meaningful. Use `intexpy` as the cost-of-funds measure. Nothing on the dashboard uses it.
- FDIC income ratios such as ROA and NIM are annualized from year-to-date figures. Quarter-to-quarter comparisons are worth validating against the FDIC's quarterly versions (for example ROAQ) before relying on short-term trends.
- Data posts roughly seven weeks after quarter-end, so the newest quarter may not be available yet.
- Six banks and a descriptive analysis: differences shown are not causal.
