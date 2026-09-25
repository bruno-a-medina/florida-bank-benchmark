"""
fetch_financials.py

Pulls quarterly financial data from the FDIC BankFind API for every bank
currently listed in the `banks` table, and upserts it into
`quarterly_financials` in Neon Postgres.

Run manually for now: python fetch_financials.py
Later: this gets called on a schedule by GitHub Actions.
"""

import os
import requests
import psycopg2
from datetime import date
from dotenv import load_dotenv

# load_dotenv() reads the .env file and makes DATABASE_URL available
# via os.getenv(). Without this, os.getenv('DATABASE_URL') returns None.
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
FDIC_BASE_URL = "https://api.fdic.gov/banks/financials"


def get_bank_certs(conn):
    """
    Query Postgres for every CERT currently in the banks table.
    This is what lets the bank list grow later just by adding a row
    to `banks`, nothing in this script needs to change.
    """
    # conn.cursor() opens a "cursor," the object you use to run SQL
    # and read results back, similar to how DBeaver runs a query.
    cur = conn.cursor()
    cur.execute("SELECT cert FROM banks;")

    # fetchall() returns a list of tuples, like [(33555,), (58979,), ...]
    # even though each row only has one column. The [0] below unpacks
    # each tuple down to just the number.
    rows = cur.fetchall()
    cur.close()
    return [row[0] for row in rows]


def build_cert_filter(cert_list):
    """
    Turns [33555, 58979, 131] into:
    CERT:(33555 OR 58979 OR 131)

    This is Elasticsearch's grouped-OR syntax, the FDIC API's stand-in
    for a SQL-style IN clause (there isn't a literal IN in this API).
    """
    # " OR ".join(...) takes a list of strings and glues them together
    # with " OR " in between each one. The f"{c}" part converts each
    # integer CERT into a string so it can be joined with text.
    cert_values = " OR ".join([f"{c}" for c in cert_list])
    return f"CERT:({cert_values})"


def fetch_financials(cert_filter):
    """
    Calls the FDIC API for all quarters from 2019 onward, for the
    banks named in cert_filter. Handles pagination since one call
    can return at most 10,000 rows (we won't hit that limit here,
    but the pattern matters for when the bank list grows).
    """
    all_records = []
    offset = 0
    limit = 200

    # REPDTE:[2019-01-01 TO *] is the FDIC's range syntax:
    # [] means inclusive range, * means open-ended (no upper bound).
    date_filter = "REPDTE:[2019-01-01 TO *]"

    # Parentheses group the CERT OR-list separately from the date
    # filter, so AND combines "any of these banks" with "this date
    # range" correctly, instead of AND/OR combining in the wrong order.
    full_filter = f"({cert_filter}) AND {date_filter}"

    while True:
        params = {
            "filters": full_filter,
            "fields": "CERT,REPDTE,ASSET,ROA,NIMY,NCLNLSR",
            "sort_by": "REPDTE",
            "sort_order": "DESC",
            "limit": limit,
            "offset": offset,
        }

        # requests.get with a params dict handles URL-encoding for you,
        # this is the same query you tested by hand in the browser,
        # just built and encoded automatically here.
        response = requests.get(FDIC_BASE_URL, params=params, timeout=30)

        # raise_for_status() throws an error if the API returned a
        # 4xx or 5xx response, instead of silently continuing with
        # bad or empty data. This is the error handling the Steam
        # tracker was missing.
        response.raise_for_status()

        payload = response.json()
        batch = payload.get("data", [])

        if not batch:
            break

        all_records.extend(batch)

        # If this batch came back smaller than our limit, there's
        # nothing left to page through.
        if len(batch) < limit:
            break

        offset += limit

    return all_records


def parse_repdte(repdte_str):
    """
    Converts the FDIC's date string "20260630" into a real Python
    date object: date(2026, 6, 30).

    Slicing a string with [start:end] pulls out a substring.
    "20260630"[0:4] -> "2026"
    "20260630"[4:6] -> "06"
    "20260630"[6:8] -> "30"
    int(...) converts each piece from text to a number.
    """
    year = int(repdte_str[0:4])
    month = int(repdte_str[4:6])
    day = int(repdte_str[6:8])
    return date(year, month, day)


def upsert_financials(conn, records):
    """
    Inserts each record into quarterly_financials. If a row with the
    same (cert, repdte) already exists, ON CONFLICT tells Postgres to
    update it instead of throwing a duplicate-key error, this is what
    makes reruns safe.
    """
    cur = conn.cursor()

    upsert_sql = """
        INSERT INTO quarterly_financials (cert, repdte, asset, roa, nimy, ncnlsr)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (cert, repdte)
        DO UPDATE SET
            asset = EXCLUDED.asset,
            roa = EXCLUDED.roa,
            nimy = EXCLUDED.nimy,
            ncnlsr = EXCLUDED.ncnlsr;
    """
    # %s are placeholders, psycopg2 safely substitutes real values in,
    # this prevents SQL injection and handles quoting automatically,
    # never build SQL by pasting values directly into a string.

    # EXCLUDED refers to the row that *tried* to insert but conflicted.
    # So "asset = EXCLUDED.asset" means "overwrite the stored asset
    # value with whatever this new API pull just returned."

    for item in records:
        data = item["data"]
        cur.execute(
            upsert_sql,
            (
                data["CERT"],
                parse_repdte(data["REPDTE"]),
                data["ASSET"],
                data["ROA"],
                data["NIMY"],
                data["NCLNLSR"],
            ),
        )

    # commit() actually saves the changes. Without it, everything
    # above happens only in a temporary transaction and gets thrown
    # away when the connection closes.
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


# This if-block only runs when the file is executed directly
# (python fetch_financials.py), not if it's ever imported by
# another script later. Standard Python pattern.
if __name__ == "__main__":
    main()