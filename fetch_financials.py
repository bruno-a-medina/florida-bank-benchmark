"""
fetch_financials.py

Pulls quarterly financial data from the FDIC BankFind API for every bank
in the `banks` table and upserts it into `quarterly_financials` in Neon.

Fields pulled:
  - Income engine: ASSET, NIMY, ROA, ROE, INTEXPY, DEP
  - Quarterly income (single-quarter figures): NIMYQ, ROAQ, ROEQ
    FDIC's plain ROA, NIMY and ROE are year-to-date, so they reset each
    January and drift within the year. The Q versions are the true
    single-quarter figures and are what the dashboard uses.
  - Credit risk: NCLNLSR (noncurrent loans / loans, an early-warning
    signal), NTLNLSR (net charge-offs / loans, realized losses),
    ELNATRY (provision rate, expected losses)
  - Operating leverage: EEFFR, NONIXAY, NONIIAY (year-to-date)
  - Funding/capital: LNLSDEPR, IDT1CER

Run manually: python fetch_financials.py
Also runs on a schedule via GitHub Actions.
"""

import os
import requests
import psycopg2
from datetime import date
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
FDIC_BASE_URL = "https://api.fdic.gov/banks/financials"


def get_bank_certs(conn):
    """Return every CERT currently in the banks table."""
    cur = conn.cursor()
    cur.execute("SELECT cert FROM banks;")
    rows = cur.fetchall()
    cur.close()
    return [row[0] for row in rows]


def build_cert_filter(cert_list):
    """Turn [33555, 58979] into: CERT:(33555 OR 58979)"""
    cert_values = " OR ".join([f"{c}" for c in cert_list])
    return f"CERT:({cert_values})"


def fetch_financials(cert_filter):
    """Call the FDIC API for all quarters from 2019 onward, paginated."""
    all_records = []
    offset = 0
    limit = 200

    date_filter = "REPDTE:[2019-01-01 TO *]"
    full_filter = f"({cert_filter}) AND {date_filter}"

    while True:
        params = {
            "filters": full_filter,
            # NEW: ROAQ, NIMYQ and ROEQ are the single-quarter figures.
            # The plain ROA, NIMY and ROE are year-to-date.
            "fields": (
                "CERT,REPDTE,ASSET,NIMY,ROA,ROE,INTEXPY,DEP,"
                "NCLNLSR,NTLNLSR,ELNATRY,EEFFR,NONIXAY,NONIIAY,"
                "LNLSDEPR,IDT1CER,ROAQ,NIMYQ,ROEQ"
            ),
            "sort_by": "REPDTE",
            "sort_order": "DESC",
            "limit": limit,
            "offset": offset,
        }

        response = requests.get(FDIC_BASE_URL, params=params, timeout=30)
        response.raise_for_status()

        payload = response.json()
        batch = payload.get("data", [])

        if not batch:
            break

        all_records.extend(batch)

        if len(batch) < limit:
            break

        offset += limit

    return all_records


def parse_repdte(repdte_str):
    """Convert "20260630" into date(2026, 6, 30)."""
    year = int(repdte_str[0:4])
    month = int(repdte_str[4:6])
    day = int(repdte_str[6:8])
    return date(year, month, day)


def upsert_financials(conn, records):
    """Insert each record, or update it if (cert, repdte) already exists."""
    cur = conn.cursor()

    # NEW: three columns added at the end (roaq, nimyq, roeq), 19 total.
    # Column order in INSERT must match the order of the values tuple.
    upsert_sql = """
        INSERT INTO quarterly_financials (
            cert, repdte, asset, nimy, roa, roe, intexpy, dep,
            ncnlsr, ntlnlsr, elnatry, eeffr, nonixay, noniiay,
            lnlsdepr, idt1cer, roaq, nimyq, roeq
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (cert, repdte)
        DO UPDATE SET
            asset    = EXCLUDED.asset,
            nimy     = EXCLUDED.nimy,
            roa      = EXCLUDED.roa,
            roe      = EXCLUDED.roe,
            intexpy  = EXCLUDED.intexpy,
            dep      = EXCLUDED.dep,
            ncnlsr   = EXCLUDED.ncnlsr,
            ntlnlsr  = EXCLUDED.ntlnlsr,
            elnatry  = EXCLUDED.elnatry,
            eeffr    = EXCLUDED.eeffr,
            nonixay  = EXCLUDED.nonixay,
            noniiay  = EXCLUDED.noniiay,
            lnlsdepr = EXCLUDED.lnlsdepr,
            idt1cer  = EXCLUDED.idt1cer,
            roaq     = EXCLUDED.roaq,
            nimyq    = EXCLUDED.nimyq,
            roeq     = EXCLUDED.roeq;
    """

    for item in records:
        data = item["data"]
        cur.execute(
            upsert_sql,
            (
                data["CERT"],
                parse_repdte(data["REPDTE"]),
                data["ASSET"],
                data["NIMY"],
                data.get("ROA"),
                data.get("ROE"),
                data.get("INTEXPY"),
                data.get("DEP"),
                data["NCLNLSR"],
                data.get("NTLNLSR"),
                data.get("ELNATRY"),
                data.get("EEFFR"),
                data.get("NONIXAY"),
                data.get("NONIIAY"),
                data.get("LNLSDEPR"),
                data.get("IDT1CER"),
                data.get("ROAQ"),   # NEW
                data.get("NIMYQ"),  # NEW
                data.get("ROEQ"),   # NEW
            ),
        )

    conn.commit()
    cur.close()


def check_completeness(conn):
    """
    Post-load sanity check. Raises an error (which turns the GitHub
    Actions run red and triggers GitHub's failure email) if the data
    looks incomplete, instead of letting a bad load pass silently.

    Checks:
      1. Every bank in `banks` has rows in quarterly_financials.
      2. Every bank has the same number of quarters.
      3. Every bank's latest quarter is the same date.
      4. The key fields are not NULL in the latest quarter, including
         the new quarterly columns.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT b.ticker,
               COUNT(qf.repdte) AS quarters,
               MAX(qf.repdte)   AS latest
        FROM banks b
        LEFT JOIN quarterly_financials qf ON qf.cert = b.cert
        GROUP BY b.ticker
        ORDER BY b.ticker;
    """)
    rows = cur.fetchall()

    problems = []
    quarter_counts = {r[1] for r in rows}
    latest_dates = {r[2] for r in rows}

    for ticker, quarters, latest in rows:
        if quarters == 0:
            problems.append(f"{ticker}: no rows loaded")
    if len(quarter_counts) > 1:
        problems.append(f"quarter counts differ by bank: {rows}")
    if len(latest_dates) > 1:
        problems.append(f"latest quarter differs by bank: {rows}")

    # Key fields must be present in the latest quarter for every bank.
    cur.execute("""
        SELECT b.ticker
        FROM quarterly_financials qf
        JOIN banks b ON b.cert = qf.cert
        WHERE qf.repdte = (SELECT MAX(repdte) FROM quarterly_financials)
          AND (qf.roaq IS NULL OR qf.nimyq IS NULL OR qf.roeq IS NULL
               OR qf.ntlnlsr IS NULL OR qf.eeffr IS NULL
               OR qf.idt1cer IS NULL);
    """)
    nulls = [r[0] for r in cur.fetchall()]
    if nulls:
        problems.append(f"NULL key fields in latest quarter for: {nulls}")

    cur.close()

    if problems:
        raise RuntimeError("Completeness check failed: " + "; ".join(problems))
    print("Completeness check passed.")


def main():
    conn = psycopg2.connect(DATABASE_URL)

    certs = get_bank_certs(conn)
    print(f"Found {len(certs)} banks in the banks table.")

    cert_filter = build_cert_filter(certs)
    records = fetch_financials(cert_filter)
    print(f"Pulled {len(records)} quarterly records from the FDIC API.")

    upsert_financials(conn, records)
    print("Upsert complete.")

    check_completeness(conn)

    conn.close()


if __name__ == "__main__":
    main()