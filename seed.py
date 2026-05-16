"""
Seed script — loads real data from sample_organ_data.json into a local SQLite file.
Run with: python3.12 seed.py

Outputs:
  - healthquest_seed.db  (upload this to Turso)
  - prints patient_id for use in testing
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(__file__))

from db.store import Store
from core.organs import OrganMapper
from core.parser import Parser
from apps.ingest import ingest_report

DB_FILE = "healthquest_seed.db"

if os.path.exists(DB_FILE):
    os.remove(DB_FILE)

# Also clean up WAL files from previous run
for ext in ["-wal", "-shm"]:
    if os.path.exists(DB_FILE + ext):
        os.remove(DB_FILE + ext)

store = Store(db_path=DB_FILE)
store.initialize()
mapper = OrganMapper()
parser = Parser(llm_client=None)

PATIENT_NAME = "Udit Jain"

# Load actual lab data
with open("sample_organ_data.json") as f:
    raw = json.load(f)

def is_valid(item):
    """Skip entries with no range or qualitative -1.0 values."""
    if not item.get("range", "").strip():
        return False
    # Skip non-standard range formats like "> 90.0" — parser can't handle them
    range_str = item["range"].strip()
    if range_str.startswith(">") or range_str.startswith("<"):
        return False
    # Skip qualitative absent results (-1.0 means "not detected" / negative)
    for pv in item.get("parameterValues", []):
        try:
            if float(pv["value"]) == -1.0:
                return False
        except (ValueError, KeyError):
            return False
    return True

# Map source organ keys → Phase 1 organ buckets we care about
# (others will still be ingested but land in "other" organ bucket)
ORGAN_ORDER = ["Liver", "Kidney", "Blood", "Pancreas", "Heart", "Thyroid", "Nutrition", "Vitamins", "Bone", "Minerals"]

print(f"Seeding database: {DB_FILE}")
print(f"Patient: {PATIENT_NAME}")
print()

patient_id = None

for organ_key in ORGAN_ORDER:
    params = raw.get(organ_key, [])
    if not params:
        continue

    valid = [p for p in params if is_valid(p)]
    if not valid:
        print(f"  {organ_key}: skipped (no valid parameters)")
        continue

    result = ingest_report(
        store=store, parser=parser, mapper=mapper,
        patient_id=patient_id, patient_name=PATIENT_NAME if patient_id is None else None,
        file_path=None, data=valid,
    )

    # Extract patient_id from first successful ingest
    if patient_id is None:
        patient_id = result.split("patient_id=")[1].split(" ")[0].rstrip("|").strip()

    print(f"  {organ_key:12s}: {result}")

# Set WAL mode so Turso can import the file
import sqlite3 as _sqlite3
conn = _sqlite3.connect(DB_FILE)
conn.execute("PRAGMA journal_mode = WAL;")
conn.commit()
conn.close()

print()
print("━" * 70)
print(f"patient_id : {patient_id}")
print(f"DB file    : {DB_FILE}  ({os.path.getsize(DB_FILE) // 1024}KB, WAL mode ✓)")
print()
print("Next steps:")
print("  1. Upload healthquest_seed.db to Turso (website → Create DB → Import file)")
print("  2. Copy your Database URL and create a Token in the Turso dashboard")
print("  3. Add to your environment:")
print("       TURSO_URL=libsql://your-db.turso.io")
print("       TURSO_AUTH_TOKEN=your-token")
print("       GOOGLE_API_KEY=your-gemini-key")
print(f"  4. Run: fastmcp dev server.py")
print(f"  5. Use patient_id={patient_id} in all tool calls")
print("━" * 70)
