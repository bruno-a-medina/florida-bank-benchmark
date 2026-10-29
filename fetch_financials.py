"""
fetch_financials.py

Pulls quarterly financial data from the FDIC BankFind API for every bank
in the `banks` table and upserts it into `quarterly_financials` in Neon.

Fields pulled:
  - Income engine: ASSET, NIMY, ROA, ROE, INTEXPY, DEP
  - Credit risk: NCLNLSR (noncurrent loans / loans, an early-warning
    signal), NTLNLSR (net charge-offs / loans, realized losses),
    ELNATRY (provision rate, expected losses)
  - Operating leverage: EEFFR, NONIXAY, NONIIAY
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
            # NEW: NTLNLSR added right after NCLNLSR. NTLNLSR is the
            # true net charge-off rate. NCLNLSR is the noncurrent loan
            # ratio (loans 90+ days past due or not accruing interest).
            "fields": (
                "CERT,REPDTE,ASSET,NIMY,ROA,ROE,INTEXPY,DEP,"
                "NCLNLSR,NTLNLSR,ELNATRY,EEFFR,NONIXAY,NONIIAY,"
                "LNLSDEPR,IDT1CER"
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

    # NEW: ntlnlsr added to the column list, one more %s (16 total),
    # and one more line in DO UPDATE. The column order in INSERT must
    # match the order of the values in the tuple below. Note that the
    # ncnlsr column holds NCLNLSR (the noncurrent loan ratio).
    upsert_sql = """
        INSERT INTO quarterly_financials (
            cert, repdte, asset, nimy, roa, roe, intexpy, dep,
            ncnlsr, ntlnlsr, elnatry, eeffr, nonixay, noniiay,
            lnlsdepr, idt1cer
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s)
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
            idt1cer  = EXCLUDED.idt1cer;
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
                data.get("NTLNLSR"),  # NEW
                data.get("ELNATRY"),
                data.get("EEFFR"),
                data.get("NONIXAY"),
                data.get("NONIIAY"),
                data.get("LNLSDEPR"),
                data.get("IDT1CER"),
            ),
        )

    conn.commit()
    cur.close()


def main():
    conn = psycopg2.connect(DATABASE_URL)

    certs = get_bank_certs(conn)
    print(f"Found {len(certs)} banks in the banks table.")

    cert_filter = build_cert_filter(certs)
    records = fetch_financials(cert_filter)
    print(f"Pulled {len(records)} quarterly records from the FDIC API.")

    upsert_financials(conn, records)
    print("Upsert complete.")

    conn.close()


if __name__ == "__main__":
    main()