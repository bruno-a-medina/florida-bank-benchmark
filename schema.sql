CREATE TABLE banks (
    cert         INTEGER PRIMARY KEY,
    namehcr      TEXT,
    namefull     TEXT NOT NULL,
    ticker       TEXT,
    is_peer      BOOLEAN NOT NULL DEFAULT FALSE,
    is_benchmark BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE quarterly_financials (
    cert         INTEGER NOT NULL REFERENCES banks(cert),
    repdte       DATE NOT NULL,
    asset        NUMERIC NOT NULL,
    roa          NUMERIC NOT NULL,
    nimy         NUMERIC NOT NULL,
    ncnlsr       NUMERIC NOT NULL,
    PRIMARY KEY (cert, repdte)
);
