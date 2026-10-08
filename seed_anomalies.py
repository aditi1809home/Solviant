"""Copy the clean database and inject five known anomalies to prove the checks can catch them."""
import shutil
import sqlite3
import sys

src, dst = sys.argv[1:3]
shutil.copy(src, dst)
con = sqlite3.connect(dst)
cur = con.cursor()

# 1. duplicate metric row (re-loaded batch)
cur.execute("INSERT INTO metrics(project_id, record_count, last_synced, source) "
            "SELECT project_id, record_count, last_synced, source FROM metrics WHERE metric_id = 10")
# 2. orphan metric: project 9999 does not exist
cur.execute("INSERT INTO metrics(project_id, record_count, last_synced, source) VALUES (9999, 120, '2026-07-05T08:00:00Z', 'api')")
# 3. missing status on a project
cur.execute("UPDATE projects SET status = NULL WHERE project_id = 1010")
# 4. negative record count on a metric
cur.execute("UPDATE metrics SET record_count = -250 WHERE metric_id = 20")
# 5. metric synced before its project was created
cur.execute("UPDATE metrics SET last_synced = '2026-01-01T00:00:00Z' WHERE metric_id = 30 AND project_id IN (SELECT project_id FROM projects WHERE created_at > '2026-01-01')")
con.commit()
print("seeded rows changed:", cur.execute("SELECT changes()").fetchone()[0])
con.close()
