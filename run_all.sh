#!/bin/bash
set -e
cd "$(dirname "$0")"
python3 src/generate_data.py
( time python3 src/pipeline.py --projects data/raw_projects.csv --events data/raw_sync_events.json --out out ) > out/run_pipeline.txt 2>&1
python3 src/load_db.py out out/projects.db > out/run_load.txt
python3 src/verify.py out/projects.db out/summary.json out/verification_clean.json > out/run_verify_clean.txt
python3 src/seed_anomalies.py out/projects.db out/projects_seeded.db > /dev/null
python3 src/verify.py out/projects_seeded.db out/summary.json out/verification_seeded.json > out/run_verify_seeded.txt
python3 src/run_guardrail.py > out/run_guardrail.txt
echo done
