"""
Seed script — creates a local SQLite file with one patient and data for all 4 organs.
Run with: python3.12 seed.py

Outputs:
  - healthquest_seed.db  (upload this to Turso)
  - prints patient_id for use in testing
"""

import os
import sys

# Ensure we're running from the repo root
sys.path.insert(0, os.path.dirname(__file__))

from db.store import Store
from core.organs import OrganMapper
from core.parser import Parser
from apps.ingest import ingest_report

DB_FILE = "healthquest_seed.db"

# Remove existing seed DB if present
if os.path.exists(DB_FILE):
    os.remove(DB_FILE)

store = Store(db_path=DB_FILE)
store.initialize()

mapper = OrganMapper()
parser = Parser(llm_client=None)  # No LLM needed — all data is in "sample" format

PATIENT_NAME = "Udit Jain"

# ──────────────────────────────────────────────
# LIVER data (from your real sample_organ_data.json, all normal)
# ──────────────────────────────────────────────
liver_data = [
    {
        "parameter": "ASPARTATE AMINOTRANSFERASE (SGOT )",
        "range": "Range 0.0 - 31.0 U/L",
        "parameterValues": [{"resultDate": "2025-10-15T00:00:00Z", "value": "27.76"}],
    },
    {
        "parameter": "SGOT / SGPT RATIO",
        "range": "Range 0.0 - 2.0 Ratio",
        "parameterValues": [{"resultDate": "2025-10-15T00:00:00Z", "value": "1.05"}],
    },
    {
        "parameter": "GAMMA GLUTAMYL TRANSFERASE (GGT)",
        "range": "Range 0.0 - 38.0 U/L",
        "parameterValues": [{"resultDate": "2025-10-15T00:00:00Z", "value": "11.9"}],
    },
    {
        "parameter": "SERUM GLOBULIN",
        "range": "Range 2.5 - 3.4 gm/dL",
        "parameterValues": [{"resultDate": "2025-10-15T00:00:00Z", "value": "2.93"}],
    },
    {
        "parameter": "PROTEIN - TOTAL",
        "range": "Range 5.7 - 8.2 gm/dL",
        "parameterValues": [{"resultDate": "2025-10-15T00:00:00Z", "value": "6.74"}],
    },
    {
        "parameter": "ALBUMIN - SERUM",
        "range": "Range 3.2 - 4.8 gm/dL",
        "parameterValues": [{"resultDate": "2025-10-15T00:00:00Z", "value": "3.81"}],
    },
    {
        "parameter": "BILIRUBIN - TOTAL",
        "range": "Range 0.3 - 1.2 mg/dL",
        "parameterValues": [{"resultDate": "2025-10-15T00:00:00Z", "value": "0.67"}],
    },
    {
        "parameter": "BILIRUBIN (INDIRECT)",
        "range": "Range 0.0 - 0.9 mg/dL",
        "parameterValues": [{"resultDate": "2025-10-15T00:00:00Z", "value": "0.54"}],
    },
    {
        "parameter": "BILIRUBIN -DIRECT",
        "range": "Range 0.0 - 0.3 mg/dL",
        "parameterValues": [{"resultDate": "2025-10-15T00:00:00Z", "value": "0.13"}],
    },
    {
        "parameter": "ALKALINE PHOSPHATASE",
        "range": "Range 45.0 - 129.0 U/L",
        "parameterValues": [{"resultDate": "2025-10-15T00:00:00Z", "value": "61.4"}],
    },
    {
        "parameter": "ALANINE TRANSAMINASE (SGPT)",
        "range": "Range 0.0 - 34.0 U/L",
        "parameterValues": [{"resultDate": "2025-10-15T00:00:00Z", "value": "26.36"}],
    },
    {
        "parameter": "SERUM ALB/GLOBULIN RATIO",
        "range": "Range 0.9 - 2.0 Ratio",
        "parameterValues": [{"resultDate": "2025-10-15T00:00:00Z", "value": "1.3"}],
    },
]

# ──────────────────────────────────────────────
# KIDNEY data (creatinine slightly high, uric acid high)
# ──────────────────────────────────────────────
kidney_data = [
    {
        "parameter": "CREATININE",
        "range": "Range 0.7 - 1.2 mg/dL",
        "parameterValues": [{"resultDate": "2025-10-15T00:00:00Z", "value": "1.31"}],
    },
    {
        "parameter": "BLOOD UREA NITROGEN (BUN)",
        "range": "Range 7.0 - 20.0 mg/dL",
        "parameterValues": [{"resultDate": "2025-10-15T00:00:00Z", "value": "14.5"}],
    },
    {
        "parameter": "URIC ACID",
        "range": "Range 3.5 - 7.2 mg/dL",
        "parameterValues": [{"resultDate": "2025-10-15T00:00:00Z", "value": "8.4"}],
    },
    {
        "parameter": "SODIUM",
        "range": "Range 136.0 - 145.0 mEq/L",
        "parameterValues": [{"resultDate": "2025-10-15T00:00:00Z", "value": "140.0"}],
    },
    {
        "parameter": "POTASSIUM",
        "range": "Range 3.5 - 5.1 mEq/L",
        "parameterValues": [{"resultDate": "2025-10-15T00:00:00Z", "value": "4.2"}],
    },
    {
        "parameter": "CHLORIDE",
        "range": "Range 98.0 - 107.0 mEq/L",
        "parameterValues": [{"resultDate": "2025-10-15T00:00:00Z", "value": "102.0"}],
    },
]

# ──────────────────────────────────────────────
# BLOOD (CBC) data (hemoglobin borderline low, platelets normal)
# ──────────────────────────────────────────────
blood_data = [
    {
        "parameter": "HEMOGLOBIN",
        "range": "Range 13.0 - 17.0 g/dL",
        "parameterValues": [{"resultDate": "2025-10-15T00:00:00Z", "value": "12.3"}],
    },
    {
        "parameter": "HEMATOCRIT (PCV)",
        "range": "Range 40.0 - 52.0 %",
        "parameterValues": [{"resultDate": "2025-10-15T00:00:00Z", "value": "38.5"}],
    },
    {
        "parameter": "WHITE BLOOD CELL COUNT (WBC)",
        "range": "Range 4.0 - 11.0 10^3/uL",
        "parameterValues": [{"resultDate": "2025-10-15T00:00:00Z", "value": "7.2"}],
    },
    {
        "parameter": "RED BLOOD CELL COUNT (RBC)",
        "range": "Range 4.5 - 5.9 10^6/uL",
        "parameterValues": [{"resultDate": "2025-10-15T00:00:00Z", "value": "4.8"}],
    },
    {
        "parameter": "PLATELET COUNT",
        "range": "Range 150.0 - 400.0 10^3/uL",
        "parameterValues": [{"resultDate": "2025-10-15T00:00:00Z", "value": "245.0"}],
    },
    {
        "parameter": "MCV",
        "range": "Range 80.0 - 100.0 fL",
        "parameterValues": [{"resultDate": "2025-10-15T00:00:00Z", "value": "76.0"}],
    },
    {
        "parameter": "MCH",
        "range": "Range 27.0 - 33.0 pg",
        "parameterValues": [{"resultDate": "2025-10-15T00:00:00Z", "value": "25.5"}],
    },
    {
        "parameter": "MCHC",
        "range": "Range 32.0 - 36.0 g/dL",
        "parameterValues": [{"resultDate": "2025-10-15T00:00:00Z", "value": "33.5"}],
    },
    {
        "parameter": "NEUTROPHILS",
        "range": "Range 40.0 - 75.0 %",
        "parameterValues": [{"resultDate": "2025-10-15T00:00:00Z", "value": "58.0"}],
    },
    {
        "parameter": "LYMPHOCYTES",
        "range": "Range 20.0 - 45.0 %",
        "parameterValues": [{"resultDate": "2025-10-15T00:00:00Z", "value": "33.0"}],
    },
    {
        "parameter": "EOSINOPHILS",
        "range": "Range 1.0 - 6.0 %",
        "parameterValues": [{"resultDate": "2025-10-15T00:00:00Z", "value": "7.5"}],
    },
    {
        "parameter": "MONOCYTES",
        "range": "Range 2.0 - 10.0 %",
        "parameterValues": [{"resultDate": "2025-10-15T00:00:00Z", "value": "6.0"}],
    },
]

# ──────────────────────────────────────────────
# METABOLIC data (fasting glucose borderline high, HbA1c slightly elevated)
# ──────────────────────────────────────────────
metabolic_data = [
    {
        "parameter": "FASTING BLOOD GLUCOSE",
        "range": "Range 70.0 - 100.0 mg/dL",
        "parameterValues": [{"resultDate": "2025-10-15T00:00:00Z", "value": "108.0"}],
    },
    {
        "parameter": "HBA1C (GLYCATED HEMOGLOBIN)",
        "range": "Range 4.0 - 5.6 %",
        "parameterValues": [{"resultDate": "2025-10-15T00:00:00Z", "value": "5.9"}],
    },
    {
        "parameter": "INSULIN - FASTING",
        "range": "Range 2.6 - 24.9 uIU/mL",
        "parameterValues": [{"resultDate": "2025-10-15T00:00:00Z", "value": "11.5"}],
    },
]

# ──────────────────────────────────────────────
# Ingest all reports for the same patient
# ──────────────────────────────────────────────
print(f"Seeding database: {DB_FILE}")
print(f"Patient: {PATIENT_NAME}")
print()

# First report creates the patient
result = ingest_report(
    store=store, parser=parser, mapper=mapper,
    patient_id=None, patient_name=PATIENT_NAME,
    file_path=None, data=liver_data,
)
print(f"Liver:    {result}")

# Extract patient_id from the summary string
patient_id = result.split("patient_id=")[1].split(" ")[0].rstrip("|").strip()

# Subsequent reports reuse the same patient_id
result = ingest_report(
    store=store, parser=parser, mapper=mapper,
    patient_id=patient_id, patient_name=None,
    file_path=None, data=kidney_data,
)
print(f"Kidney:   {result}")

result = ingest_report(
    store=store, parser=parser, mapper=mapper,
    patient_id=patient_id, patient_name=None,
    file_path=None, data=blood_data,
)
print(f"Blood:    {result}")

result = ingest_report(
    store=store, parser=parser, mapper=mapper,
    patient_id=patient_id, patient_name=None,
    file_path=None, data=metabolic_data,
)
print(f"Metabolic:{result}")

print()
print("━" * 60)
print(f"patient_id: {patient_id}")
print(f"DB file:    {DB_FILE}")
print()
print("Next steps:")
print("  1. Upload healthquest_seed.db to Turso")
print("  2. Set TURSO_URL and TURSO_AUTH_TOKEN in your environment")
print("  3. Run: fastmcp dev server.py")
print(f"  4. Use patient_id={patient_id} in all tool calls")
print("━" * 60)
