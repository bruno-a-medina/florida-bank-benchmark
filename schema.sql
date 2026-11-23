-- schema.sql
--
-- Florida Bank Peer Benchmark: schema and views for tracking quarterly
-- financial performance across 6 public Florida banks, sourced from
-- the FDIC BankFind API.
--
-- This file describes the CURRENT structure. Do not run it in full against
-- the live database (the CREATE TABLE statements would error because the
-- tables already exist). Run individual statements as needed.
--
-- Income ratios: ROA, NIM and ROE use the single-quarter FDIC fields
-- (ROAQ, NIMYQ, ROEQ). The plain FDIC ROA, NIMY and ROE are year-to-date
-- and are kept in the table for reference only.
-- Efficiency ratio and cost of funds are year-to-date in FDIC's data.

-- =====================================================
-- TABLES
-- =====================================================

-- One row per bank. Static info that does not change quarter to quarter.
-- cert is the FDIC's permanent bank identifier.
CREATE TABLE banks (
    cert         INTEGER PRIMARY KEY,
    namehcr      TEXT,
    namefull     TEXT NOT NULL,
    ticker       TEXT NOT NULL
);

-- One row per bank per quarter. cert + repdte form the primary key, which
-- makes reruns of the ingestion script safe (ON CONFLICT DO UPDATE
-- instead of duplicate rows).
CREATE TABLE quarterly_financials (
    cert         INTEGER NOT NULL REFERENCES banks(cert),
    repdte       DATE NOT NULL,

    -- Income engine
    asset        NUMERIC NOT NULL,
    nimy         NUMERIC NOT NULL,   -- year-to-date NIM (reference)
    roa          NUMERIC,            -- year-to-date ROA (reference)
    roe          NUMERIC,            -- year-to-date ROE (reference)
    intexpy      NUMERIC,            -- cost of funds, year-to-date
    dep          NUMERIC,

    -- Single-quarter income (used by the dashboard)
    roaq         NUMERIC,            -- quarterly ROA
    nimyq        NUMERIC,            -- quarterly net interest margin
    roeq         NUMERIC,            -- quarterly ROE

    -- Credit risk
    -- NOTE: ncnlsr stores the FDIC field NCLNLSR, the NONCURRENT LOAN RATIO
    -- (loans 90+ days past due or not accruing interest), an early-warning
    -- signal. The column name is a historical typo and does not mean
    -- "net charge-off." The true net charge-off rate is ntlnlsr (FDIC NTLNLSR).
    ncnlsr       NUMERIC NOT NULL,
    ntlnlsr      NUMERIC,
    elnatry      NUMERIC,

    -- Operating leverage / efficiency
    eeffr        NUMERIC,            -- efficiency ratio, year-to-date
    nonixay      NUMERIC,
    noniiay      NUMERIC,

    -- Funding / capital
    lnlsdepr     NUMERIC,
    idt1cer      NUMERIC,

    PRIMARY KEY (cert, repdte)
);

-- =====================================================
-- SEED DATA: banks
-- =====================================================

INSERT INTO banks (cert, namehcr, namefull, ticker)
VALUES
    (33555, 'SOUTHSTATE BANK CORP', 'SOUTHSTATE BANK, NATIONAL ASSOCIATION', 'SSB'),
    (58979, 'BANKUNITED INC', 'BANKUNITED, NATIONAL ASSOCIATION', 'BKU'),
    (131,   'SEACOAST BANKING CORP OF FL', 'SEACOAST NATIONAL BANK', 'SBCF'),
    (22953, 'AMERANT BCORP INC', 'AMERANT BANK, NATIONAL ASSOCIATION', 'AMTB'),
    (9622,  'CAPITAL CITY BANK GROUP INC', 'CAPITAL CITY BANK', 'CCBG'),
    (57369, 'USCB FINANCIAL HOLDINGS INC', 'U. S. CENTURY BANK', 'USCB');

-- =====================================================
-- VIEW: v_bank_financials
-- =====================================================
--
-- One row per bank per quarter, joined to bank info, with:
--   - clear, Power BI-friendly column names
--   - quarterly ROA, NIM and ROE (single-quarter FDIC fields)
--   - quarter-over-quarter (QoQ) and year-over-year (YoY) changes
--   - peer group median for the same quarter, and each bank's
--     variance against that median
-- All computed here in SQL so Power BI reads clean, ready-to-chart columns.
--
-- Columns changed in this version, so run DROP VIEW IF EXISTS first:
-- CREATE OR REPLACE VIEW cannot rename or remove existing view columns.

DROP VIEW IF EXISTS v_bank_financials;

CREATE VIEW v_bank_financials AS
WITH base AS (
    SELECT
        qf.cert,
        b.namefull,
        b.ticker,
        qf.repdte AS date,
        EXTRACT(YEAR FROM qf.repdte)::INTEGER AS year,
        EXTRACT(QUARTER FROM qf.repdte)::INTEGER AS quarter,
        qf.asset AS total_assets,
        qf.nimyq AS net_interest_margin,        -- quarterly NIM
        qf.roaq AS return_on_assets,            -- quarterly ROA
        qf.roeq AS return_on_equity,            -- quarterly ROE
        qf.ncnlsr AS noncurrent_loan_rate,
        qf.ntlnlsr AS net_charge_off_rate,
        qf.elnatry AS provision_rate,
        qf.eeffr AS efficiency_ratio,           -- year-to-date
        qf.nonixay AS noninterest_expense_rate,
        qf.noniiay AS noninterest_income_rate,
        qf.lnlsdepr AS loans_to_deposits,
        qf.idt1cer AS cet1_capital_ratio,
        qf.intexpy AS cost_of_funds             -- year-to-date
    FROM quarterly_financials qf
    JOIN banks b ON b.cert = qf.cert
),
with_changes AS (
    SELECT
        base.*,
        return_on_assets - LAG(return_on_assets, 1) OVER (PARTITION BY cert ORDER BY date) AS roa_qoq,
        return_on_assets - LAG(return_on_assets, 4) OVER (PARTITION BY cert ORDER BY date) AS roa_yoy,
        net_interest_margin - LAG(net_interest_margin, 1) OVER (PARTITION BY cert ORDER BY date) AS nim_qoq,
        net_interest_margin - LAG(net_interest_margin, 4) OVER (PARTITION BY cert ORDER BY date) AS nim_yoy,
        efficiency_ratio - LAG(efficiency_ratio, 4) OVER (PARTITION BY cert ORDER BY date) AS efficiency_yoy,
        noncurrent_loan_rate - LAG(noncurrent_loan_rate, 4) OVER (PARTITION BY cert ORDER BY date) AS noncurrent_yoy,
        net_charge_off_rate - LAG(net_charge_off_rate, 4) OVER (PARTITION BY cert ORDER BY date) AS net_charge_off_yoy,
        total_assets - LAG(total_assets, 4) OVER (PARTITION BY cert ORDER BY date) AS asset_growth_yoy
    FROM base
),
peer_medians AS (
    SELECT
        date,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY return_on_assets) AS peer_median_roa,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY net_interest_margin) AS peer_median_nim,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY efficiency_ratio) AS peer_median_efficiency,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY noncurrent_loan_rate) AS peer_median_noncurrent,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY net_charge_off_rate) AS peer_median_net_charge_off
    FROM base
    GROUP BY date
)
SELECT
    wc.*,
    pm.peer_median_roa,
    pm.peer_median_nim,
    pm.peer_median_efficiency,
    pm.peer_median_noncurrent,
    pm.peer_median_net_charge_off,
    wc.return_on_assets - pm.peer_median_roa AS roa_vs_peer,
    wc.net_interest_margin - pm.peer_median_nim AS nim_vs_peer,
    wc.efficiency_ratio - pm.peer_median_efficiency AS efficiency_vs_peer,
    wc.noncurrent_loan_rate - pm.peer_median_noncurrent AS noncurrent_vs_peer,
    wc.net_charge_off_rate - pm.peer_median_net_charge_off AS net_charge_off_vs_peer
FROM with_changes wc
JOIN peer_medians pm ON pm.date = wc.date
ORDER BY wc.cert, wc.date;
