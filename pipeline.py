"""Data automation pipeline: ingest -> normalise -> validate -> de-duplicate -> transform -> report.

Usage:  python src/pipeline.py --projects data/raw_projects.csv --events data/raw_sync_events.json --out out
"""
import argparse
import json
import logging
import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd

log = logging.getLogger("pipeline")

STATUS_MAP = {
    "active": "Active", "in progress": "Active",
    "review": "Review", "under review": "Review",
    "done": "Done", "completed": "Done", "complete": "Done",
}
CATEGORY_MAP = {c.lower(): c for c in ["Billing", "CPQ", "Data Quality", "AI Testing", "Integration"]}
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%B %d, %Y")
RUN_DATE = date(2026, 7, 15)          # rows dated after this are rejected


# --------------------------------------------------------------------- ingest
def ingest_projects(path):
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    log.info("INGEST projects: %d rows, columns=%s", len(df), list(df.columns))
    return df


def ingest_events(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    df = pd.json_normalize(payload["data"]["metrics"])
    if df.empty:                                   # no events in the export
        df = pd.DataFrame(columns=["project_id", "synced_at", "records", "source"])
    log.info("INGEST sync events: %d records (export v%s)", len(df), payload.get("version"))
    return df


# ------------------------------------------------------------------ normalise
def parse_date(text):
    text = str(text).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_int(text):
    cleaned = str(text).replace(",", "").strip()
    return int(cleaned) if re.fullmatch(r"-?\d+", cleaned) else None


def normalise_projects(df):
    out = pd.DataFrame()
    out["project_id"] = df["project_id"].str.strip()
    out["name"] = df["name"].str.strip().str.replace(r"\s+", " ", regex=True).str.title()
    out["category"] = df["category"].str.strip().str.lower().map(CATEGORY_MAP)
    out["status"] = df["status"].str.strip().str.lower().map(STATUS_MAP)
    out["record_count"] = df["record_count"].map(parse_int)
    out["created_at"] = df["created_at"].map(parse_date)
    return out


# ------------------------------------------------------------------- validate
def reasons_for(row):
    problems = []
    if not re.fullmatch(r"\d+", str(row.project_id)):
        problems.append("missing_id")
    if not row["name"]:
        problems.append("empty_name")
    if pd.isna(row.category):
        problems.append("bad_category")
    if pd.isna(row.status):
        problems.append("bad_status")
    if pd.isna(row.record_count) or row.record_count < 0:
        problems.append("bad_records")
    if row.created_at is None or row.created_at > RUN_DATE:
        problems.append("bad_date")
    return ";".join(problems)


def validate_projects(df):
    df = df.copy()
    if df.empty:                                   # header-only export: nothing to validate
        df["reject_reason"] = pd.Series(dtype=str)
    else:
        df["reject_reason"] = df.apply(reasons_for, axis=1)
    return df[df.reject_reason == ""].drop(columns="reject_reason"), df[df.reject_reason != ""]


# ---------------------------------------------------------------- de-duplicate
def deduplicate_projects(df):
    before = len(df)
    df = df.drop_duplicates()
    exact = before - len(df)
    df = df.sort_values(["project_id", "record_count"]).drop_duplicates("project_id", keep="last")
    superseded = before - exact - len(df)
    return df, exact, superseded


# ------------------------------------------------------------------- transform
def size_band(n):
    return "Small" if n < 1000 else "Medium" if n < 5000 else "Large"


def transform_projects(df):
    df = df.copy()
    df["project_id"] = df["project_id"].astype(int)
    df["record_count"] = df["record_count"].astype(int)
    df["size_band"] = df["record_count"].map(size_band)
    df["created_at"] = df["created_at"].map(lambda d: d.isoformat())
    return df.sort_values("project_id").reset_index(drop=True)


# ------------------------------------------------------------ metrics pipeline
def clean_events(events, valid_ids, created):
    ev = events.copy()
    ev["synced_ts"] = pd.to_datetime(ev["synced_at"], errors="coerce", utc=True)
    reasons = []
    for _, r in ev.iterrows():
        p = []
        if pd.isna(r.get("records")):
            p.append("missing_records")
        elif r["records"] < 0:
            p.append("negative_records")
        if pd.isna(r["synced_ts"]):
            p.append("bad_timestamp")
        if int(r["project_id"]) not in valid_ids:
            p.append("orphan_project")
        elif not pd.isna(r["synced_ts"]) and r["synced_ts"].date().isoformat() < created[int(r["project_id"])]:
            p.append("before_creation")
        reasons.append(";".join(p))
    ev["reject_reason"] = reasons
    rejected = ev[ev.reject_reason != ""]
    ok = ev[ev.reject_reason == ""].drop(columns=["reject_reason", "synced_ts"])
    before = len(ok)
    ok = ok.drop_duplicates(subset=["project_id", "synced_at", "records", "source"])
    dup = before - len(ok)
    ok = ok.rename(columns={"records": "record_count", "synced_at": "last_synced"})
    ok["project_id"] = ok["project_id"].astype(int)
    ok["record_count"] = ok["record_count"].astype(int)
    return ok.sort_values(["project_id", "last_synced"]).reset_index(drop=True), rejected, dup


# ---------------------------------------------------------------------- report
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--projects", required=True)
    ap.add_argument("--events", required=True)
    ap.add_argument("--out", default="out")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s %(message)s",
                        datefmt="%H:%M:%S", handlers=[logging.FileHandler(out / "pipeline.log", mode="w"), logging.StreamHandler()])
    stats = {}
    try:
        raw = ingest_projects(args.projects)
        stats["projects_in"] = len(raw)
        norm = normalise_projects(raw)
        good, rejected = validate_projects(norm)
        reason_counts = {}
        for text in rejected.reject_reason:
            for r in text.split(";"):
                reason_counts[r] = reason_counts.get(r, 0) + 1
        stats["projects_rejected"] = len(rejected)
        stats["reject_reasons"] = reason_counts
        log.info("VALIDATE projects: %d valid, %d rejected %s", len(good), len(rejected), reason_counts)
        good, exact, superseded = deduplicate_projects(good)
        stats["exact_duplicates"], stats["superseded"] = exact, superseded
        log.info("DEDUPE projects: %d exact duplicates, %d superseded rows removed", exact, superseded)
        clean = transform_projects(good)
        stats["projects_out"] = len(clean)

        ev = ingest_events(args.events)
        stats["events_in"] = len(ev)
        created = dict(zip(clean.project_id, clean.created_at))
        cev, rej_ev, dup_ev = clean_events(ev, set(clean.project_id), created)
        ev_reasons = {}
        for text in rej_ev.reject_reason:
            for r in text.split(";"):
                ev_reasons[r] = ev_reasons.get(r, 0) + 1
        stats.update(events_rejected=len(rej_ev), event_reject_reasons=ev_reasons, event_duplicates=dup_ev, events_out=len(cev))
        log.info("VALIDATE events: %d rejected %s, %d duplicates removed, %d kept", len(rej_ev), ev_reasons, dup_ev, len(cev))

        clean.to_csv(out / "clean_projects.csv", index=False)
        rejected.drop(columns=[]).to_csv(out / "rejected_projects.csv", index=False)
        cev.to_csv(out / "clean_metrics.csv", index=False)
        rej_ev.drop(columns=["synced_ts"]).to_csv(out / "rejected_events.csv", index=False)

        summary = (clean.groupby("category")
                   .agg(projects=("project_id", "count"), records=("record_count", "sum"), avg_records=("record_count", "mean"))
                   .round(0).astype(int).reset_index())
        status = clean.groupby("status").size().to_dict()
        summary.to_csv(out / "summary_by_category.csv", index=False)
        stats.update(total_records=int(clean.record_count.sum()), by_status=status,
                     by_band=clean.groupby("size_band").size().to_dict())
        (out / "summary.json").write_text(json.dumps(stats, indent=2, default=int))
        log.info("REPORT written: %d projects, %d records, summary_by_category.csv, summary.json", len(clean), stats["total_records"])
    except Exception as exc:                      # never crash silently
        log.error("PIPELINE FAILED: %s", exc)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
