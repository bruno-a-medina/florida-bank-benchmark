-- exploration.sql
--
-- Sanity checks and starter queries for the Florida Bank Peer Benchmark.
-- Run these one at a time after a load to confirm the data looks right
-- before opening the dashboard. They read from the tables and view defined
-- in schema.sql (banks, quarterly_financials, v_bank_financials).


-- 1. Coverage: rows, first quarter and latest quarter per bank.
--    Every bank should show the same row count and the same latest date.
SELECT
    b.ticker,
    COUNT(qf.repdte) AS quarters_loaded,
    MIN(qf.repdte)   AS first_quarter,
    MAX(qf.repdte)   AS latest_quarter
FROM banks b
LEFT JOIN quarterly_financials qf ON qf.cert = b.cert
GROUP BY b.ticker
ORDER BY b.ticker;


-- 2. Gaps: any quarter missing from the middle of a bank's history.
--    Builds every expected quarter-end from the first loaded quarter to the
--    latest, then lists the ones a bank does not have. No rows means no gaps.
WITH bounds AS (
    SELECT MIN(repdte) AS first_q, MAX(repdte) AS last_q
    FROM quarterly_financials
),
expected AS (
    SELECT (gs + INTERVAL '3 months' - INTERVAL '1 day')::date AS repdte
    FROM bounds,
         generate_series(
             DATE_TRUNC('quarter', bounds.first_q),
             DATE_TRUNC('quarter', bounds.last_q),
             INTERVAL '3 months'
         ) AS gs
)
SELECT b.ticker, e.repdte AS missing_quarter
FROM banks b
CROSS JOIN expected e
LEFT JOIN quarterly_financials qf
       ON qf.cert = b.cert AND qf.repdte = e.repdte
WHERE qf.cert IS NULL
ORDER BY b.ticker, e.repdte;


-- 3. Nulls: how many rows are missing each key field, by bank.
SELECT
    b.ticker,
    COUNT(*) FILTER (WHERE qf.roa      IS NULL) AS null_roa,
    COUNT(*) FILTER (WHERE qf.ntlnlsr  IS NULL) AS null_net_charge_off,
    COUNT(*) FILTER (WHERE qf.eeffr    IS NULL) AS null_efficiency,
    COUNT(*) FILTER (WHERE qf.idt1cer  IS NULL) AS null_cet1
FROM quarterly_financials qf
JOIN banks b ON b.cert = qf.cert
GROUP BY b.ticker
ORDER BY b.ticker;


-- 4. Latest quarter snapshot with each bank's gap to the peer median.
SELECT
    ticker,
    ROUND(return_on_assets::numeric, 2)      AS roa,
    ROUND(roa_vs_peer::numeric, 2)           AS roa_vs_peer,
    ROUND(efficiency_ratio::numeric, 1)      AS efficiency,
    ROUND(noncurrent_loan_rate::numeric, 2)  AS noncurrent,
    ROUND(net_charge_off_rate::numeric, 2)   AS net_charge_off,
    ROUND(cet1_capital_ratio::numeric, 1)    AS cet1
FROM v_bank_financials
WHERE date = (SELECT MAX(date) FROM v_bank_financials)
ORDER BY return_on_assets DESC NULLS LAST;


-- 5. Credit signals side by side for the latest quarter.
--    Noncurrent loans (early warning), provision (expected loss) and net
--    charge-offs (realized loss) are different measures. If two of these
--    columns ever match exactly for every bank, a field mapping is wrong.
SELECT
    ticker,
    ROUND(noncurrent_loan_rate::numeric, 2) AS noncurrent_loans,
    ROUND(provision_rate::numeric, 2)       AS provision,
    ROUND(net_charge_off_rate::numeric, 2)  AS net_charge_offs
FROM v_bank_financials
WHERE date = (SELECT MAX(date) FROM v_bank_financials)
ORDER BY noncurrent_loan_rate DESC;


-- 6. Biggest year-over-year ROA moves, up and down.
SELECT
    ticker,
    date,
    ROUND(return_on_assets::numeric, 2) AS roa,
    ROUND(roa_yoy::numeric, 2)          AS roa_change_vs_year_ago
FROM v_bank_financials
WHERE roa_yoy IS NOT NULL
ORDER BY ABS(roa_yoy) DESC
LIMIT 10;


-- 7. Peer median trend: how the group as a whole has moved over time.
SELECT DISTINCT
    date,
    ROUND(peer_median_roa::numeric, 2)         AS median_roa,
    ROUND(peer_median_nim::numeric, 2)         AS median_nim,
    ROUND(peer_median_efficiency::numeric, 1)  AS median_efficiency
FROM v_bank_financials
ORDER BY date;
