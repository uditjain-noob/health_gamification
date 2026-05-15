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


_HARVARD_PAGES_DIR = Path(__file__).parent / "harvard_nutrition" / "pages"

# Browser-like headers to reduce likelihood of 403 blocks
_SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


def _slug(path: str) -> str:
    return path.strip("/").replace("/", "__")


def _load_cached_page(path: str) -> str | None:
    """Load a pre-scraped page from the local pages/ directory, if available."""
    cached = _HARVARD_PAGES_DIR / f"{_slug(path)}.txt"
    if cached.exists():
        text = cached.read_text(encoding="utf-8")
        if len(text) >= 200:
            return text
    return None


def _save_cached_page(path: str, text: str) -> None:
    """Save a successfully scraped page to the local pages/ directory."""
    _HARVARD_PAGES_DIR.mkdir(parents=True, exist_ok=True)
    (_HARVARD_PAGES_DIR / f"{_slug(path)}.txt").write_text(text, encoding="utf-8")


def scrape_harvard_documents() -> list[Document]:
    """Scrape Harvard Nutrition Source pages and return Haystack Documents.

    Falls back to pre-cached pages in harvard_nutrition/pages/ when the live
    site returns 4xx (e.g. 403 rate-limit).  Successfully scraped pages are
    cached there for future runs.  Skips pages that fail everywhere and produce
    < 200 chars of text.
    Sleeps 1.5s between live requests to avoid rate limiting.
    """
    docs: list[Document] = []
    for path in PAGES:
        url = _HARVARD_BASE + path
        text: str | None = None

        # 1. Try the local cache first (fast, always works offline)
        cached = _load_cached_page(path)
        if cached:
            text = cached

        # 2. Fall back to live HTTP request
        if text is None:
            try:
                r = httpx.get(url, headers=_SCRAPE_HEADERS, timeout=15, follow_redirects=True)
                r.raise_for_status()
                text = extract_text(r.text)
                if len(text) >= 200:
                    _save_cached_page(path, text)
                time.sleep(1.5)
            except Exception as e:
                print(f"  ERROR {path}: {e}")
                continue

        if text is None or len(text) < 200:
            print(f"  WARN too short ({len(text) if text else 0} chars): {path}")
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
    return docs


def chunk_harvard_documents(docs: list[Document]) -> list[Document]:
    """Split Harvard documents into sentence-window chunks, inheriting parent metadata."""
    from haystack.components.preprocessors import DocumentSplitter
    splitter = DocumentSplitter(split_by="sentence", split_length=5, split_overlap=2)
    result = splitter.run(documents=docs)
    return result["documents"]


def build(
    force: bool = False,
    dry_run: bool = False,
    pdf_path: str = "scripts/excercise_diet_reco/biomarkers_excercise/biomarkers.pdf",
    out_path: str = "scripts/excercise_diet_reco/corpus/store.json",
) -> None:
    """Scrape Harvard pages + extract NSCA PDF → embed → serialize InMemoryDocumentStore.

    --dry-run: scrape + chunk only, skip embed/serialize, print chunk count
    --force: overwrite existing store.json
    """
    if not Path(pdf_path).exists():
        raise FileNotFoundError(f"NSCA PDF not found: {pdf_path}")

    out = Path(out_path)
    if out.exists() and not force and not dry_run:
        print(f"Store already exists at {out}. Use --force to rebuild.")
        return

    print("Scraping Harvard pages...")
    harvard_docs = scrape_harvard_documents()
    harvard_chunks = chunk_harvard_documents(harvard_docs)
    print(f"  {len(harvard_docs)} pages → {len(harvard_chunks)} chunks")

    print("Extracting NSCA sections...")
    nsca_docs = extract_nsca_documents(pdf_path)
    print(f"  {len(nsca_docs)} sections")

    all_docs = harvard_chunks + nsca_docs
    print(f"Total: {len(all_docs)} documents")

    if dry_run:
        print("Dry run complete — skipping embed and serialize.")
        return

    print("Embedding (first run downloads ~130MB model)...")
    from haystack.components.embedders import SentenceTransformersDocumentEmbedder
    from haystack.document_stores.in_memory import InMemoryDocumentStore

    embedder = SentenceTransformersDocumentEmbedder(model="BAAI/bge-small-en-v1.5")
    embedder.warm_up()
    embedded_docs = embedder.run(documents=all_docs)["documents"]

    store = InMemoryDocumentStore()
    store.write_documents(embedded_docs)

    out.parent.mkdir(parents=True, exist_ok=True)
    # Serialize documents manually — InMemoryDocumentStore.to_dict() only saves
    # component config (not document data).  We save the full document list so
    # rag_retriever.py can reconstruct the store with embeddings intact.
    serialized = {
        "store_config": store.to_dict(),
        "documents": [doc.to_dict() for doc in store.filter_documents()],
    }
    out.write_text(json.dumps(serialized))
    print(f"Store saved → {out} ({store.count_documents()} documents)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build HealthQuest RAG corpus")
    parser.add_argument("--force", action="store_true", help="Overwrite existing store.json")
    parser.add_argument("--dry-run", action="store_true", help="Scrape + chunk only, skip embed")
    args = parser.parse_args()
    build(force=args.force, dry_run=args.dry_run)
