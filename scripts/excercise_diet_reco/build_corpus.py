"""
Build script: scrape Harvard Nutrition pages + chunk NSCA PDF → embed → serialize InMemoryDocumentStore.

Usage:
    python scripts/excercise_diet_reco/build_corpus.py [--force] [--dry-run]

Output: scripts/excercise_diet_reco/corpus/store.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import fitz
import httpx
from bs4 import BeautifulSoup
from haystack import Document

# ── Harvard scraping ──────────────────────────────────────────────────────────
_HARVARD_BASE = "https://nutritionsource.hsph.harvard.edu"

# Import page list and metadata from the existing scraping script
sys.path.insert(0, str(Path(__file__).parent))
from harvard_nutrition.scraping_script import PAGES, PAGE_METADATA, extract_text  # noqa: E402

# ── NSCA chunk definitions ────────────────────────────────────────────────────
# Page ranges are 0-indexed and verified against the actual PDF.
NSCA_CHUNKS = [
    {
        "name": "nutrition_protein_albumin",
        "pages": (3, 5),
        "organ": "liver,blood",
        "condition": "low albumin, low total protein, protein deficiency",
        "parameters": ["Albumin", "Total Protein", "Globulin", "BUN"],
        "category": "exercise",
    },
    {
        "name": "nutrition_iron_hemoglobin",
        "pages": (4, 10),
        "organ": "blood",
        "condition": "low iron, low hemoglobin, iron deficiency anemia, sports anemia",
        "parameters": ["Iron", "Hemoglobin", "Hematocrit", "Ferritin", "Transferrin"],
        "category": "exercise,supplement",
    },
    {
        "name": "nutrition_vitamin_d_glucose",
        "pages": (3, 5),
        "organ": "vitamins,metabolic",
        "condition": "low vitamin D, high blood glucose, insulin resistance",
        "parameters": ["Vitamin D", "Glucose", "HbA1c", "Insulin"],
        "category": "exercise,supplement",
    },
    {
        "name": "hydration_sodium_electrolytes",
        "pages": (5, 6),
        "organ": "kidney",
        "condition": "dehydration, electrolyte imbalance",
        "parameters": ["Sodium", "Potassium", "Osmolality", "Creatinine"],
        "category": "exercise",
    },
    {
        "name": "muscle_status_ck_testosterone_cortisol",
        "pages": (7, 9),
        "organ": "hormones,muscle",
        "condition": "muscle damage, overtraining, low testosterone, high cortisol",
        "parameters": ["CK", "Myoglobin", "Testosterone", "Cortisol", "DHEA-S"],
        "category": "exercise",
    },
    {
        "name": "endurance_performance_oxygen_transport",
        "pages": (9, 11),
        "organ": "blood,heart",
        "condition": "low hemoglobin, low hematocrit, poor cardiovascular fitness",
        "parameters": ["Hemoglobin", "Hematocrit", "RBC", "VO2max", "Lactate"],
        "category": "exercise",
    },
    {
        "name": "inflammation_crp_il6",
        "pages": (11, 13),
        "organ": "heart,liver,general",
        "condition": "chronic inflammation, high CRP, elevated liver enzymes",
        "parameters": ["Hs-CRP", "IL-6", "TNF-alpha", "SGOT", "SGPT"],
        "category": "exercise",
    },
]

NSCA_URL = (
    "https://vtechworks.lib.vt.edu/server/api/core/bitstreams/"
    "9fdf4ecc-c70f-4fce-befd-d8b5689ef405/content"
)


def extract_nsca_documents(pdf_path: str) -> list[Document]:
    """Extract NSCA_CHUNKS from the PDF as Haystack Documents.

    Raises FileNotFoundError (via fitz) if pdf_path is missing.
    Chunks shorter than 100 chars are skipped with a printed warning — check NSCA_CHUNKS page ranges.
    """
    fitz_doc = fitz.open(pdf_path)
    results: list[Document] = []
    for chunk in NSCA_CHUNKS:
        start, end = chunk["pages"]
        text_parts = []
        for page_num in range(start, min(end + 1, len(fitz_doc))):
            text_parts.append(fitz_doc[page_num].get_text())
        text = "\n".join(text_parts)
        text = re.sub(r"-\n(\w)", r"\1", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if len(text) < 100:
            print(f"  WARN too short ({len(text)} chars): {chunk['name']} — check page ranges")
            continue
        results.append(Document(
            content=text,
            meta={
                "source": "nsca",
                "organ": chunk["organ"],
                "category": chunk["category"],
                "condition": chunk["condition"],
                "parameters": chunk["parameters"],
                "url": NSCA_URL,
            },
        ))
    fitz_doc.close()
    return results


def scrape_harvard_documents() -> list[Document]:
    """Scrape Harvard Nutrition Source pages and return Haystack Documents.

    Skips pages that fail HTTP requests or produce < 200 chars of text.
    Sleeps 1.5s between requests to avoid rate limiting.
    """
    headers = {"User-Agent": "HealthQuest RAG Builder/1.0 (educational use)"}
    docs: list[Document] = []
    for path in PAGES:
        url = _HARVARD_BASE + path
        try:
            r = httpx.get(url, headers=headers, timeout=15, follow_redirects=True)
            r.raise_for_status()
        except Exception as e:
            print(f"  ERROR {path}: {e}")
            continue

        text = extract_text(r.text)
        if len(text) < 200:
            print(f"  WARN too short ({len(text)} chars): {path}")
            continue

        meta = PAGE_METADATA.get(
            path,
            {"organ": "general", "condition": "", "parameters": [], "category": ""},
        )
        docs.append(Document(
            content=text,
            meta={
                "source": "harvard",
                "organ": meta["organ"],
                "category": meta["category"],
                "condition": meta["condition"],
                "parameters": meta["parameters"],
                "url": url,
            },
        ))
        time.sleep(1.5)
    return docs
