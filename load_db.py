"""Load pipeline output into a SQLite staging database (PRIMARY KEY only, no other constraints).

A staging schema is deliberately loose, as in a bulk load, which is why the SQL verification
suite is needed to prove the data is sound.
"""
import re
import sqlite3
import sys
from pathlib import Path

import pandas as pd

SCHEMA = """
DROP TABLE IF EXISTS projects; DROP TABLE IF EXISTS metrics; DROP TABLE IF EXISTS logs;
CREATE TABLE projects (
    project_id   INTEGER PRIMARY KEY,
    name         TEXT,
    category     TEXT,
    status       TEXT,
    record_count INTEGER,
    created_at   TEXT
);
CREATE TABLE metrics (
    metric_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id   INTEGER,
    record_count INTEGER,
    last_synced  TEXT,
    source       TEXT
);
CREATE TABLE logs (
    log_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type     TEXT,
    payload_status TEXT,
    message        TEXT,
    timestamp      TEXT
);
"""


def load(out_dir, db_path):
    out = Path(out_dir)
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    proj = pd.read_csv(out / "clean_projects.csv")[["project_id", "name", "category", "status", "record_count", "created_at"]]
    met = pd.read_csv(out / "clean_metrics.csv")[["project_id", "record_count", "last_synced", "source"]]
    proj.to_sql("projects", con, if_exists="append", index=False)
    met.to_sql("metrics", con, if_exists="append", index=False)
    rows = []
    for line in (out / "pipeline.log").read_text().splitlines():
        m = re.match(r"(\d\d:\d\d:\d\d) (\w+)\s+(\w+)\s+(.*)", line)
        if m:
            t, level, event, msg = m.groups()
            rows.append((event, "OK" if level == "INFO" else "ERROR", msg, f"2026-07-15T{t}Z"))
    con.executemany("INSERT INTO logs(event_type, payload_status, message, timestamp) VALUES (?,?,?,?)", rows)
    con.commit()
    n = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("projects", "metrics", "logs")}
    con.close()
    return n


if __name__ == "__main__":
    print(load(sys.argv[1], sys.argv[2]))
