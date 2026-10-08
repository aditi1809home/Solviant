"""Create deterministic, deliberately messy sample exports for the pipeline.

The data is synthetic. It imitates the problems seen in real CSV/JSON exports:
duplicates, blanks, inconsistent spelling, mixed date formats and bad numbers.
"""
import csv
import json
import random
from pathlib import Path

random.seed(2026)
OUT = Path("data")
OUT.mkdir(exist_ok=True)

CATEGORIES = ["Billing", "CPQ", "Data Quality", "AI Testing", "Integration"]
STATUS_CLEAN = ["Active", "Active", "Active", "Review", "Done"]
NAME_A = ["Quote", "Billing", "Contract", "Invoice", "Pricing", "Usage", "Renewal", "Catalog", "Order", "Tax", "Credit", "Proposal", "Account", "Payment", "Bundle", "Discount"]
NAME_B = ["Pilot", "Validation", "Audit", "Reconciliation", "Review", "Sync", "Migration", "Tracker", "Verification", "Cleanup", "Report", "Portal", "Check", "Test", "Export", "Flow"]

# ---- 1. 200 genuine projects ------------------------------------------------
projects = []
used = set()
pid = 1001
while len(projects) < 200:
    name = f"{random.choice(NAME_A)} {random.choice(NAME_B)}"
    if name in used:
        name = f"{name} {random.randint(2, 9)}"
    if name in used:
        continue
    used.add(name)
    projects.append({
        "project_id": pid,
        "name": name,
        "category": random.choice(CATEGORIES),
        "status": random.choice(STATUS_CLEAN),
        "record_count": random.randint(300, 20000),
        "created_at": f"2026-0{random.randint(1, 6)}-{random.randint(1, 28):02d}",
    })
    pid += 1

# ---- 2. turn them into messy raw rows --------------------------------------
STATUS_VARIANTS = {"Active": ["Active", "active", "ACTIVE ", "In Progress", "Active"], "Review": ["Review", "under review", "REVIEW"], "Done": ["Done", "done", "Completed", "complete"]}
MONTHS = ["January", "February", "March", "April", "May", "June", "July"]

def messy_date(iso):
    y, m, d = iso.split("-")
    kind = random.random()
    if kind < 0.70:
        return iso
    if kind < 0.88:
        return f"{d}/{m}/{y}"
    return f"{MONTHS[int(m) - 1]} {int(d)}, {y}"

def messy_records(n):
    kind = random.random()
    if kind < 0.80:
        return str(n)
    if kind < 0.93:
        return f"{n:,}"
    return f"{n} "

raw = []
for p in projects:
    raw.append({
        "project_id": str(p["project_id"]),
        "name": random.choice([p["name"], p["name"], p["name"], "  " + p["name"].lower() + " ", p["name"].upper()]),
        "category": random.choice([p["category"], p["category"], p["category"].lower(), " " + p["category"]]),
        "status": random.choice(STATUS_VARIANTS[p["status"]]),
        "record_count": messy_records(p["record_count"]),
        "created_at": messy_date(p["created_at"]),
    })

# exact duplicate rows (re-exported lines)
for row in random.sample(raw, 28):
    raw.append(dict(row))

# same project exported again with a newer record count (superseded rows)
for row in random.sample(raw[:200], 12):
    newer = dict(row)
    newer["record_count"] = str(int(str(row["record_count"]).replace(",", "").strip()) + random.randint(50, 900))
    raw.append(newer)

# ---- 3. invalid rows ------------------------------------------------------
bad = []
for i in range(7):   # missing id
    r = dict(random.choice(raw[:200])); r["project_id"] = random.choice(["", " ", "N/A"]); bad.append(r)
for i in range(9):   # unknown status
    r = dict(random.choice(raw[:200])); r["project_id"] = str(2000 + i); r["status"] = random.choice(["On hold?", "unknown", "TBD"]); bad.append(r)
for i in range(8):   # bad record count
    r = dict(random.choice(raw[:200])); r["project_id"] = str(2100 + i); r["record_count"] = random.choice(["-120", "abc", "", "12.5k", "-1"]); bad.append(r)
for i in range(6):   # bad date
    r = dict(random.choice(raw[:200])); r["project_id"] = str(2200 + i); r["created_at"] = random.choice(["N/A", "31/02/2026", "2026-13-40", "", "yesterday"]); bad.append(r)
for i in range(4):   # empty name
    r = dict(random.choice(raw[:200])); r["project_id"] = str(2300 + i); r["name"] = random.choice(["", "  "]); bad.append(r)
raw.extend(bad)
random.shuffle(raw)

with open(OUT / "raw_projects.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["project_id", "name", "category", "status", "record_count", "created_at"])
    w.writeheader()
    w.writerows(raw)

# ---- 4. nested JSON sync events ------------------------------------------
events = []
for p in projects:
    for k in range(random.randint(1, 3)):
        m = random.randint(int(p["created_at"][5:7]), 7)
        day = random.randint(1, 28)
        if m == int(p["created_at"][5:7]):
            day = max(day, int(p["created_at"][8:10]) + 1) if int(p["created_at"][8:10]) < 28 else 28
        events.append({
            "project_id": p["project_id"],
            "synced_at": f"2026-{m:02d}-{min(day, 28):02d}T{random.randint(0, 23):02d}:{random.choice(['00', '15', '30', '45'])}:00Z",
            "records": random.randint(40, 900),
            "source": random.choice(["api", "batch", "manual"]),
        })
dups = [dict(e) for e in random.sample(events, 15)]
events.extend(dups)
orph = [{"project_id": 9000 + i, "synced_at": "2026-07-01T10:00:00Z", "records": 100 + i, "source": "api"} for i in range(5)]
neg = [{"project_id": random.choice(projects)["project_id"], "synced_at": "2026-07-02T09:30:00Z", "records": -r, "source": "batch"} for r in (30, 75, 410)]
nofield = [{"project_id": random.choice(projects)["project_id"], "synced_at": "2026-07-03T09:30:00Z", "source": "api"} for _ in range(4)]
baddate = [{"project_id": random.choice(projects)["project_id"], "synced_at": "not-a-date", "records": 55, "source": "api"} for _ in range(3)]
events.extend(orph + neg + nofield + baddate)
random.shuffle(events)
json.dump({"export": "sync-events", "version": 2, "data": {"metrics": events}}, open(OUT / "raw_sync_events.json", "w"), indent=1)
print(f"raw_projects.csv rows: {len(raw)}   raw_sync_events.json events: {len(events)}")
