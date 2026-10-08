"""SQL verification suite: run each check, compare with the expected value, log PASS/FAIL.

Usage: python src/verify.py out/projects.db out/summary.json out/verification_clean.json
"""
import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd

CHECKS = [
    ("V01", "Row count: projects",
     "SELECT COUNT(*) FROM projects", "eq", "projects_out"),
    ("V02", "Row count: metrics",
     "SELECT COUNT(*) FROM metrics", "eq", "events_out"),
    ("V03", "Duplicate project ids",
     "SELECT COUNT(*) FROM (SELECT project_id FROM projects GROUP BY project_id HAVING COUNT(*) > 1)", "zero", None),
    ("V04", "Duplicate metric rows",
     "SELECT COUNT(*) FROM (SELECT project_id, last_synced, record_count FROM metrics "
     "GROUP BY project_id, last_synced, record_count HAVING COUNT(*) > 1)", "zero", None),
    ("V05", "Orphan metrics (no parent project)",
     "SELECT COUNT(*) FROM metrics m LEFT JOIN projects p ON p.project_id = m.project_id "
     "WHERE p.project_id IS NULL", "zero", None),
    ("V06", "Missing or invalid status",
     "SELECT COUNT(*) FROM projects WHERE status IS NULL OR status NOT IN ('Active','Review','Done')", "zero", None),
    ("V07", "Negative record counts",
     "SELECT (SELECT COUNT(*) FROM projects WHERE record_count < 0) + "
     "(SELECT COUNT(*) FROM metrics WHERE record_count < 0)", "zero", None),
    ("V08", "Metric synced before project creation",
     "SELECT COUNT(*) FROM metrics m JOIN projects p ON p.project_id = m.project_id "
     "WHERE substr(m.last_synced, 1, 10) < p.created_at", "zero", None),
    ("V09", "Total records: projects vs pipeline",
     "SELECT COALESCE(SUM(record_count), 0) FROM projects", "eq", "total_records"),
    ("V10", "Total records: metrics vs pipeline",
     "SELECT COALESCE(SUM(record_count), 0) FROM metrics", "eq", "metrics_total"),
]

INFO = ("I01", "Projects with no metrics (information only)",
        "SELECT COUNT(*) FROM projects p WHERE NOT EXISTS (SELECT 1 FROM metrics m WHERE m.project_id = p.project_id)")

TOP5 = """SELECT p.project_id, p.name, COUNT(m.metric_id) AS syncs, SUM(m.record_count) AS total_records
FROM projects p JOIN metrics m ON m.project_id = p.project_id
GROUP BY p.project_id, p.name
ORDER BY total_records DESC LIMIT 5"""


def run(db, summary_path, out_path):
    stats = json.loads(Path(summary_path).read_text())
    stats["metrics_total"] = int(pd.read_csv("out/clean_metrics.csv").record_count.sum())
    con = sqlite3.connect(db)
    results = []
    for cid, name, sql, mode, key in CHECKS:
        value = con.execute(sql).fetchone()[0]
        expected = 0 if mode == "zero" else stats[key]
        status = "PASS" if value == expected else "FAIL"
        results.append({"id": cid, "name": name, "value": value, "expected": expected, "status": status})
        con.execute("INSERT INTO logs(event_type, payload_status, message, timestamp) VALUES (?,?,?,?)",
                    ("VERIFY", "OK" if status == "PASS" else "ERROR", f"{cid} {name}: {value} (expected {expected})", "2026-07-15T12:00:00Z"))
    info = {"id": INFO[0], "name": INFO[1], "value": con.execute(INFO[2]).fetchone()[0]}
    top5 = [list(r) for r in con.execute(TOP5)]
    con.commit()
    con.close()
    out = {"results": results, "info": info, "top5": top5,
           "passed": sum(r["status"] == "PASS" for r in results), "failed": sum(r["status"] == "FAIL" for r in results)}
    Path(out_path).write_text(json.dumps(out, indent=1))
    for r in results:
        print(f"{r['id']}  {r['name']:<40} value={r['value']:<9} expected={r['expected']:<9} {r['status']}")
    print(f"{info['id']}  {info['name']:<40} value={info['value']}")
    print(f"SUMMARY: {out['passed']} passed, {out['failed']} failed")
    return out


if __name__ == "__main__":
    run(*sys.argv[1:4])
