# RAG Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Haystack RAG pipeline over Harvard Nutrition pages and the NSCA Biomarkers PDF, and wire it into a new `get_rag_recommendations` MCP tool in `apps/recommendations.py`.

**Architecture:** A build script (`scripts/excercise_diet_reco/build_corpus.py`) scrapes/chunks/embeds both sources into a serialized `InMemoryDocumentStore`. A runtime module (`apps/rag_retriever.py`) loads the store at server startup and exposes `retrieve()`. `apps/recommendations.py` calls `retrieve()` before Gemini for the new `get_rag_recommendations` tool.

**Tech Stack:** `haystack-ai>=2.0`, `sentence-transformers>=3.0` (`BAAI/bge-small-en-v1.5`), `pymupdf>=1.24`, `beautifulsoup4>=4.12`, existing `httpx` + `google-genai`.

> **Structural note:** The spec placed `query_pipeline.py` under `scripts/`. Moved to `apps/rag_retriever.py` because `scripts/` is not in `pyproject.toml` packages and cannot be imported at runtime.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `pyproject.toml` | Add 4 new dependencies |
| Modify | `.gitignore` | Ignore `corpus/store.json` |
| Create | `apps/rag_retriever.py` | Runtime: load store, expose `retrieve()` |
| Create | `scripts/excercise_diet_reco/build_corpus.py` | Offline: scrape → chunk → embed → serialize |
| Create | `tests/test_rag_retriever.py` | Tests for `rag_retriever` |
| Create | `tests/test_build_corpus.py` | Tests for build helpers |
| Modify | `apps/recommendations.py` | Add `get_rag_recommendations` MCP tool |

---

## Task 1: Add Dependencies and .gitignore

**Files:**
- Modify: `pyproject.toml`
- Modify: `.gitignore`

- [ ] **Step 1: Add dependencies to pyproject.toml**

In `pyproject.toml`, replace the `dependencies` list with:

```toml
dependencies = [
    "fastmcp[apps]>=3.2",
    "prefab-ui>=0.19.1",
    "pdfplumber>=0.11",
    "google-genai>=1.0",
    "pydantic>=2.0",
    "httpx>=0.27",
    "python-dotenv>=1.0",
    "haystack-ai>=2.0",
    "sentence-transformers>=3.0",
    "pymupdf>=1.24",
    "beautifulsoup4>=4.12",
]
```

- [ ] **Step 2: Install dependencies**

```bash
uv sync
```

Expected: resolves without errors, lockfile updated.

- [ ] **Step 3: Verify imports work**

```bash
python -c "import haystack; import sentence_transformers; import fitz; import bs4; print('all imports OK')"
```

Expected: `all imports OK`

- [ ] **Step 4: Add corpus output to .gitignore**

Add this line to `.gitignore`:

```
scripts/excercise_diet_reco/corpus/
```

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock .gitignore
git commit -m "chore: add haystack, sentence-transformers, pymupdf, beautifulsoup4 deps"
```

---

## Task 2: Inspect NSCA PDF Page Numbers

**Files:**
- Read: `scripts/excercise_diet_reco/biomarkers_excercise/biomarkers.pdf`

The CHUNKS page ranges in the spec are estimates. Verify them before coding the chunker.

- [ ] **Step 1: Run page inspection script**

```bash
python - <<'EOF'
import fitz
doc = fitz.open("scripts/excercise_diet_reco/biomarkers_excercise/biomarkers.pdf")
print(f"Total pages: {len(doc)}")
for i, page in enumerate(doc):
    first_line = page.get_text().strip()[:120].replace("\n", " ")
    print(f"  page {i:2d}: {first_line}")
doc.close()
EOF
```

- [ ] **Step 2: Record actual page ranges**

From the output, note the 0-indexed page where each section starts and ends. The 7 sections to map:

| Section | Expected start | Actual start | Actual end |
|---------|---------------|--------------|------------|
| nutrition_protein_albumin | 3 | ___ | ___ |
| nutrition_iron_hemoglobin | 5 | ___ | ___ |
| nutrition_vitamin_d_glucose | 7 | ___ | ___ |
| hydration_sodium_electrolytes | 8 | ___ | ___ |
| muscle_status_ck_testosterone_cortisol | 9 | ___ | ___ |
| endurance_performance_oxygen_transport | 12 | ___ | ___ |
| inflammation_crp_il6 | 14 | ___ | ___ |

Keep these values — you'll use them in Task 4.

---

## Task 3: Create `apps/rag_retriever.py`

**Files:**
- Create: `apps/rag_retriever.py`
- Create: `tests/test_rag_retriever.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_rag_retriever.py`:

```python
import pytest
import apps.rag_retriever as rag


def setup_function():
    rag._store = None
    rag._retriever = None
    rag._text_embedder = None


def test_retrieve_returns_empty_when_store_not_loaded():
    result = rag.retrieve("elevated SGPT liver diet", organ="liver")
    assert result == []


def test_load_store_missing_file_does_not_raise(tmp_path):
    rag.load_store(str(tmp_path / "nonexistent.json"))
    assert rag._store is None


def test_retrieve_returns_empty_after_missing_load(tmp_path):
    rag.load_store(str(tmp_path / "nonexistent.json"))
    result = rag.retrieve("cholesterol diet", organ="heart")
    assert result == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_rag_retriever.py -v
```

Expected: `ImportError` or `AttributeError` — module does not exist yet.

- [ ] **Step 3: Create `apps/rag_retriever.py`**

```python
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger("healthquest.rag")

_store: Any = None
_retriever: Any = None
_text_embedder: Any = None

_DEFAULT_STORE_PATH = "scripts/excercise_diet_reco/corpus/store.json"


def load_store(path: str = _DEFAULT_STORE_PATH) -> None:
    global _store, _retriever, _text_embedder
    p = Path(path)
    if not p.exists():
        log.warning("RAG store not found at %s — get_rag_recommendations will return empty results", path)
        return
    try:
        from haystack.document_stores.in_memory import InMemoryDocumentStore
        from haystack.components.retrievers.in_memory import InMemoryEmbeddingRetriever
        from haystack.components.embedders import SentenceTransformersTextEmbedder

        data = json.loads(p.read_text())
        _store = InMemoryDocumentStore.from_dict(data)
        _retriever = InMemoryEmbeddingRetriever(document_store=_store)
        _text_embedder = SentenceTransformersTextEmbedder(model="BAAI/bge-small-en-v1.5")
        _text_embedder.warm_up()
        log.info("RAG store loaded: %d documents", _store.count_documents())
    except Exception as e:
        log.error("Failed to load RAG store: %s", e)
        _store = None
        _retriever = None
        _text_embedder = None


def retrieve(query: str, organ: str, category: str = "all", top_k: int = 5) -> list[str]:
    if _store is None or _retriever is None or _text_embedder is None:
        return []

    filters: dict = {
        "operator": "OR",
        "conditions": [
            {"field": "meta.organ", "operator": "==", "value": organ},
            {"field": "meta.organ", "operator": "==", "value": "all"},
        ],
    }

    result = _text_embedder.run(text=query)
    query_embedding = result["embedding"]

    docs = _retriever.run(
        query_embedding=query_embedding,
        filters=filters,
        top_k=top_k * 2,  # over-fetch before optional category post-filter
    )["documents"]

    if category != "all":
        docs = [d for d in docs if category in (d.meta.get("category") or "")]

    return [doc.content for doc in docs[:top_k]]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_rag_retriever.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/rag_retriever.py tests/test_rag_retriever.py
git commit -m "feat: add rag_retriever with load_store and retrieve"
```

---

## Task 4: Build Corpus — NSCA PDF Extraction

**Files:**
- Create: `scripts/excercise_diet_reco/build_corpus.py`
- Create: `tests/test_build_corpus.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_build_corpus.py`:

```python
import pytest
from pathlib import Path

PDF_PATH = "scripts/excercise_diet_reco/biomarkers_excercise/biomarkers.pdf"


@pytest.mark.skipif(not Path(PDF_PATH).exists(), reason="NSCA PDF not present")
def test_extract_nsca_documents_returns_seven_sections():
    from scripts.excercise_diet_reco.build_corpus import extract_nsca_documents
    docs = extract_nsca_documents(PDF_PATH)
    assert len(docs) == 7


@pytest.mark.skipif(not Path(PDF_PATH).exists(), reason="NSCA PDF not present")
def test_extract_nsca_documents_meta_schema():
    from scripts.excercise_diet_reco.build_corpus import extract_nsca_documents
    docs = extract_nsca_documents(PDF_PATH)
    for doc in docs:
        assert doc.meta["source"] == "nsca"
        assert "organ" in doc.meta
        assert "category" in doc.meta
        assert "parameters" in doc.meta
        assert isinstance(doc.meta["parameters"], list)
        assert len(doc.content) > 100
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_build_corpus.py -v
```

Expected: `ImportError` — module does not exist yet.

- [ ] **Step 3: Create `scripts/excercise_diet_reco/__init__.py`** (makes it importable in tests)

```bash
touch scripts/excercise_diet_reco/__init__.py
touch scripts/__init__.py
```

- [ ] **Step 4: Create `scripts/excercise_diet_reco/build_corpus.py` with NSCA extraction**

Use the actual page ranges you recorded in Task 2 — replace the `"pages"` tuples below with your verified values.

```python
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

# ── NSCA chunk definitions ────────────────────────────────────────────────────
# UPDATE "pages" tuples with values from Task 2 page inspection.
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
        "pages": (5, 7),
        "organ": "blood",
        "condition": "low iron, low hemoglobin, iron deficiency anemia, sports anemia",
        "parameters": ["Iron", "Hemoglobin", "Hematocrit", "Ferritin", "Transferrin"],
        "category": "exercise,supplement",
    },
    {
        "name": "nutrition_vitamin_d_glucose",
        "pages": (7, 8),
        "organ": "vitamins,metabolic",
        "condition": "low vitamin D, high blood glucose, insulin resistance",
        "parameters": ["Vitamin D", "Glucose", "HbA1c", "Insulin"],
        "category": "exercise,supplement",
    },
    {
        "name": "hydration_sodium_electrolytes",
        "pages": (8, 9),
        "organ": "kidney",
        "condition": "dehydration, electrolyte imbalance",
        "parameters": ["Sodium", "Potassium", "Osmolality", "Creatinine"],
        "category": "exercise",
    },
    {
        "name": "muscle_status_ck_testosterone_cortisol",
        "pages": (9, 12),
        "organ": "hormones,muscle",
        "condition": "muscle damage, overtraining, low testosterone, high cortisol",
        "parameters": ["CK", "Myoglobin", "Testosterone", "Cortisol", "DHEA-S"],
        "category": "exercise",
    },
    {
        "name": "endurance_performance_oxygen_transport",
        "pages": (12, 14),
        "organ": "blood,heart",
        "condition": "low hemoglobin, low hematocrit, poor cardiovascular fitness",
        "parameters": ["Hemoglobin", "Hematocrit", "RBC", "VO2max", "Lactate"],
        "category": "exercise",
    },
    {
        "name": "inflammation_crp_il6",
        "pages": (14, 17),
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
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_build_corpus.py -v
```

Expected: both nsca tests pass (or skip with clear message if PDF absent).

- [ ] **Step 6: Commit**

```bash
git add scripts/__init__.py scripts/excercise_diet_reco/__init__.py \
        scripts/excercise_diet_reco/build_corpus.py tests/test_build_corpus.py
git commit -m "feat: build_corpus NSCA PDF extraction"
```

---

## Task 5: Build Corpus — Harvard Scraping

**Files:**
- Modify: `scripts/excercise_diet_reco/build_corpus.py`
- Modify: `tests/test_build_corpus.py`

- [ ] **Step 1: Write failing tests**

Add `from unittest.mock import MagicMock, patch` to the top of `tests/test_build_corpus.py` (after the existing imports), then add these test functions:

```python
def test_scrape_harvard_documents_skips_http_errors():
    import httpx
    from scripts.excercise_diet_reco.build_corpus import scrape_harvard_documents

    def mock_get(url, **kwargs):
        raise httpx.HTTPError("connection refused")

    with patch("httpx.get", side_effect=mock_get):
        docs = scrape_harvard_documents()
    assert docs == []


def test_scrape_harvard_documents_skips_short_content():
    from scripts.excercise_diet_reco.build_corpus import scrape_harvard_documents

    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.text = "<html><body><article>short</article></body></html>"

    with patch("httpx.get", return_value=mock_response):
        docs = scrape_harvard_documents()
    assert docs == []


def test_scrape_harvard_documents_meta_schema():
    from scripts.excercise_diet_reco.build_corpus import scrape_harvard_documents

    long_text = "This is a sentence. " * 30
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.text = f"<html><body><article>{long_text}</article></body></html>"

    with patch("httpx.get", return_value=mock_response):
        with patch("time.sleep"):  # don't actually sleep during tests
            docs = scrape_harvard_documents()

    assert len(docs) > 0
    for doc in docs:
        assert doc.meta["source"] == "harvard"
        assert "organ" in doc.meta
        assert "category" in doc.meta
        assert isinstance(doc.meta["parameters"], list)
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_build_corpus.py::test_scrape_harvard_documents_skips_http_errors \
       tests/test_build_corpus.py::test_scrape_harvard_documents_skips_short_content \
       tests/test_build_corpus.py::test_scrape_harvard_documents_meta_schema -v
```

Expected: `ImportError` — `scrape_harvard_documents` not defined yet.

- [ ] **Step 3: Add Harvard scraping to `build_corpus.py`**

Add these imports and constants at the top of `build_corpus.py` (after the existing imports):

```python
# ── Harvard scraping ──────────────────────────────────────────────────────────
_HARVARD_BASE = "https://nutritionsource.hsph.harvard.edu"

# Import page list and metadata from the existing scraping script
sys.path.insert(0, str(Path(__file__).parent))
from harvard_nutrition.scraping_script import PAGES, PAGE_METADATA, extract_text  # noqa: E402
```

Then add this function to `build_corpus.py`:

```python
def scrape_harvard_documents() -> list[Document]:
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_build_corpus.py -v
```

Expected: all 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/excercise_diet_reco/build_corpus.py tests/test_build_corpus.py
git commit -m "feat: build_corpus Harvard scraping"
```

---

## Task 6: Build Corpus — Chunking, Embedding, and CLI

**Files:**
- Modify: `scripts/excercise_diet_reco/build_corpus.py`
- Modify: `tests/test_build_corpus.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_build_corpus.py`:

```python
def test_chunk_harvard_documents_inherits_meta():
    from scripts.excercise_diet_reco.build_corpus import chunk_harvard_documents
    from haystack import Document

    docs = [Document(
        content=(
            "Eating fiber reduces cholesterol. "
            "Soluble fiber binds bile acids. "
            "This lowers LDL levels significantly. "
            "Oats and beans are excellent sources. "
            "Aim for 25 grams daily. "
            "Insoluble fiber aids digestion. "
            "Both types improve metabolic health."
        ),
        meta={
            "source": "harvard",
            "organ": "heart",
            "category": "diet",
            "condition": "high LDL",
            "parameters": ["LDL"],
            "url": "http://example.com",
        },
    )]
    chunks = chunk_harvard_documents(docs)
    assert len(chunks) >= 1
    assert all(c.meta["organ"] == "heart" for c in chunks)
    assert all(c.meta["source"] == "harvard" for c in chunks)


def test_build_dry_run_prints_counts(capsys):
    from unittest.mock import patch
    from scripts.excercise_diet_reco.build_corpus import build

    dummy_doc = Document(
        content="Sentence one. Sentence two. Sentence three. Sentence four. Sentence five. Sentence six.",
        meta={"source": "harvard", "organ": "heart", "category": "diet",
              "condition": "", "parameters": [], "url": "http://x.com"},
    )

    with patch("scripts.excercise_diet_reco.build_corpus.scrape_harvard_documents", return_value=[dummy_doc]):
        with patch("scripts.excercise_diet_reco.build_corpus.extract_nsca_documents", return_value=[]):
            build(dry_run=True)

    captured = capsys.readouterr()
    assert "chunk" in captured.out.lower() or "total" in captured.out.lower()
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_build_corpus.py::test_chunk_harvard_documents_inherits_meta \
       tests/test_build_corpus.py::test_build_dry_run_prints_counts -v
```

Expected: `ImportError` — functions not defined yet.

- [ ] **Step 3: Add `chunk_harvard_documents` and `build` to `build_corpus.py`**

```python
def chunk_harvard_documents(docs: list[Document]) -> list[Document]:
    from haystack.components.preprocessors import DocumentSplitter
    splitter = DocumentSplitter(split_by="sentence", split_length=5, split_overlap=2)
    result = splitter.run(documents=docs)
    return result["documents"]


def build(force: bool = False, dry_run: bool = False) -> None:
    out_path = Path("scripts/excercise_diet_reco/corpus/store.json")
    pdf_path = "scripts/excercise_diet_reco/biomarkers_excercise/biomarkers.pdf"

    if not Path(pdf_path).exists():
        raise FileNotFoundError(f"NSCA PDF not found: {pdf_path}")

    if out_path.exists() and not force and not dry_run:
        print(f"Store already exists at {out_path}. Use --force to rebuild.")
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

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(store.to_dict()))
    print(f"Store saved → {out_path} ({store.count_documents()} documents)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build HealthQuest RAG corpus")
    parser.add_argument("--force", action="store_true", help="Overwrite existing store.json")
    parser.add_argument("--dry-run", action="store_true", help="Scrape + chunk only, skip embed")
    args = parser.parse_args()
    build(force=args.force, dry_run=args.dry_run)
```

- [ ] **Step 4: Run all build_corpus tests**

```bash
pytest tests/test_build_corpus.py -v
```

Expected: all 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/excercise_diet_reco/build_corpus.py tests/test_build_corpus.py
git commit -m "feat: build_corpus chunking, embedding, and CLI"
```

---

## Task 7: Wire RAG into `apps/recommendations.py`

**Files:**
- Modify: `apps/recommendations.py`
- Modify: `tests/test_rag_retriever.py`

- [ ] **Step 1: Write failing tests**

Add `import json` and `from unittest.mock import MagicMock` to the top of `tests/test_rag_retriever.py` (after the existing imports), then add these test functions:

```python


def test_fetch_rag_recommendations_returns_empty_when_no_context():
    from apps.recommendations import fetch_rag_recommendations
    mock_client = MagicMock()
    result = fetch_rag_recommendations(mock_client, organ="liver", query="elevated SGPT", context_chunks=[])
    assert result == {"diet": [], "exercise": [], "supplements": []}
    mock_client.complete.assert_not_called()


def test_fetch_rag_recommendations_calls_gemini_with_context():
    from apps.recommendations import fetch_rag_recommendations
    mock_client = MagicMock()
    mock_client.complete.return_value = json.dumps({
        "diet": [{"title": "Eat greens", "description": "Helps liver", "priority": "high"}],
        "exercise": [],
        "supplements": [],
    })
    result = fetch_rag_recommendations(
        mock_client,
        organ="liver",
        query="elevated SGPT liver",
        context_chunks=["Leafy greens reduce liver inflammation according to studies."],
    )
    assert result["diet"][0]["title"] == "Eat greens"
    mock_client.complete.assert_called_once()
    call_kwargs = mock_client.complete.call_args
    assert "Leafy greens" in call_kwargs.kwargs.get("user", "") or \
           "Leafy greens" in str(call_kwargs)


def test_fetch_rag_recommendations_raises_on_bad_json():
    from apps.recommendations import fetch_rag_recommendations
    mock_client = MagicMock()
    mock_client.complete.return_value = "not valid json"
    with pytest.raises(ValueError, match="invalid JSON"):
        fetch_rag_recommendations(
            mock_client,
            organ="liver",
            query="elevated SGPT",
            context_chunks=["some context here"],
        )
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_rag_retriever.py -v
```

Expected: `ImportError` — `fetch_rag_recommendations` not defined yet.

- [ ] **Step 3: Update `apps/recommendations.py`**

Replace the full file with:

```python
import json

from apps.rag_retriever import load_store, retrieve as rag_retrieve

load_store()

_cache: dict[tuple, dict] = {}

_REC_SYSTEM = "You are a health optimization assistant. Return ONLY valid JSON, no explanation."

_REC_PROMPT = """A patient's {organ} lab results show these flagged parameters:
{flagged}

Generate evidence-based recommendations in exactly this JSON format:
{{
  "diet": [{{"title": str, "description": str, "priority": "high|medium|low"}}],
  "exercise": [{{"title": str, "description": str, "priority": "high|medium|low"}}],
  "supplements": [{{"title": str, "description": str, "priority": "high|medium|low"}}]
}}
Max 3 items per category. Be specific and practical.
Note: These are general wellness suggestions, not medical advice."""

_RAG_SYSTEM = (
    "You are a health optimization assistant. "
    "Use the provided context as grounding. Return ONLY valid JSON, no explanation."
)

_RAG_PROMPT = """Context from medical literature:
{context}

---
Based on the above context, generate evidence-based recommendations for a patient with:
Organ: {organ}
Concern: {query}

Return exactly this JSON format:
{{
  "diet": [{{"title": str, "description": str, "priority": "high|medium|low"}}],
  "exercise": [{{"title": str, "description": str, "priority": "high|medium|low"}}],
  "supplements": [{{"title": str, "description": str, "priority": "high|medium|low"}}]
}}
Max 3 items per category. Be specific and practical.
Note: These are general wellness suggestions, not medical advice."""


def fetch_recommendations(client, organ: str, flagged_params: list[dict], patient_id: str = "") -> dict:
    cache_key = (patient_id, organ, tuple(sorted(p["name"] for p in flagged_params)))
    if cache_key in _cache:
        return _cache[cache_key]

    if not flagged_params:
        return {"diet": [], "exercise": [], "supplements": []}

    flagged_text = "\n".join(
        f"- {p['name']}: {p['readings'][0]['value']} {p['unit']} "
        f"(normal: {p['ref_min']}–{p['ref_max']})"
        for p in flagged_params if p.get("readings")
    )
    raw = client.complete(
        system=_REC_SYSTEM,
        user=_REC_PROMPT.format(organ=organ, flagged=flagged_text),
    )
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM returned invalid JSON for recommendations: {e}") from e
    _cache[cache_key] = result
    return result


def fetch_rag_recommendations(client, organ: str, query: str, context_chunks: list[str]) -> dict:
    if not context_chunks:
        return {"diet": [], "exercise": [], "supplements": []}

    context = "\n\n---\n\n".join(context_chunks)
    raw = client.complete(
        system=_RAG_SYSTEM,
        user=_RAG_PROMPT.format(context=context, organ=organ, query=query),
    )
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM returned invalid JSON for RAG recommendations: {e}") from e


def register(mcp, get_store, get_client):
    @mcp.tool()
    def get_recommendations(patient_id: str, organ: str) -> str:
        """
        Get AI-generated, evidence-based recommendations for improving an organ's flagged parameters.

        Returns a JSON string with three categories — diet, exercise, supplements — each containing
        up to 3 actionable items with title, description, and priority (high/medium/low).
        Only generates recommendations for out-of-range parameters; returns empty lists if all are normal.
        Results are cached per (patient_id, organ) so repeat calls are free.
        Use this when a user asks "what should I do about my liver?" or "how can I improve my cholesterol?".
        For a visual version with the same content embedded in a panel, use show_organ_panel instead.

        Parameters:
        - patient_id: the patient's ID
        - organ: organ name (e.g. "liver", "heart") — case-insensitive
        """
        store = get_store()
        client = get_client()
        params = store.get_parameters_for_organ(patient_id, organ)
        flagged = [p for p in params if p["readings"] and p["readings"][0]["status"] != "normal"]
        recs = fetch_recommendations(client, organ, flagged, patient_id)
        return json.dumps(recs, indent=2)

    @mcp.tool()
    def get_rag_recommendations(query: str, organ: str, category: str = "all") -> str:
        """
        Get RAG-grounded diet/exercise/supplement recommendations backed by medical literature.

        Construct `query` from the patient's flagged parameters and condition, e.g.:
        "elevated SGPT SGOT fatty liver diet exercise reduce enzymes"

        Parameters:
        - query: free-text description of the patient's concern — the agent composes this
        - organ: organ system, e.g. "liver", "heart", "blood", "metabolic", "kidney", "vitamins"
        - category: narrow results to "diet", "exercise", or "supplement"; default "all"

        Returns JSON: {"diet": [...], "exercise": [...], "supplements": [...]}
        Each item: {"title": str, "description": str, "priority": "high|medium|low"}
        Max 3 items per category.
        """
        client = get_client()
        context_chunks = rag_retrieve(query, organ, category, top_k=5)
        recs = fetch_rag_recommendations(client, organ, query, context_chunks)
        return json.dumps(recs, indent=2)
```

- [ ] **Step 4: Run all tests**

```bash
pytest tests/test_rag_retriever.py tests/test_build_corpus.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Run the full test suite to check for regressions**

```bash
pytest -v
```

Expected: all existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add apps/recommendations.py tests/test_rag_retriever.py
git commit -m "feat: add get_rag_recommendations MCP tool with RAG grounding"
```

---

## Task 8: Build the Corpus (End-to-End)

**Files:**
- Run: `scripts/excercise_diet_reco/build_corpus.py`

- [ ] **Step 1: Dry run to verify chunk counts**

```bash
python scripts/excercise_diet_reco/build_corpus.py --dry-run
```

Expected output (approximate):
```
Scraping Harvard pages...
  26 pages → 80+ chunks
Extracting NSCA sections...
  7 sections
Total: 87+ documents
Dry run complete — skipping embed and serialize.
```

If any Harvard pages 404, they are logged and skipped — that's expected.
If any NSCA sections show "WARN too short", go back to Task 2 and fix the page ranges in `NSCA_CHUNKS`.

- [ ] **Step 2: Build the store**

```bash
python scripts/excercise_diet_reco/build_corpus.py
```

Expected: completes without error, prints `Store saved → scripts/excercise_diet_reco/corpus/store.json (N documents)`.

This downloads `BAAI/bge-small-en-v1.5` (~130MB) on first run.

- [ ] **Step 3: Smoke-test retrieval**

```bash
python - <<'EOF'
from apps.rag_retriever import load_store, retrieve
load_store()
results = retrieve("low hemoglobin iron diet anemia", organ="blood", top_k=3)
print(f"Got {len(results)} results")
for i, r in enumerate(results):
    print(f"\n--- Result {i+1} (first 200 chars) ---")
    print(r[:200])
EOF
```

Expected: 3 results, each starting with content about iron/blood/hemoglobin.

- [ ] **Step 4: Commit (store.json is git-ignored, nothing to stage)**

```bash
git status
```

Expected: `scripts/excercise_diet_reco/corpus/` does not appear — it is git-ignored.

---

## Post-Build Verification

After completing all tasks, run the full suite one final time:

```bash
pytest -v
```

Then verify the new MCP tool is registered:

```bash
python - <<'EOF'
import server
# server.py calls mcp.tool() registrations at import time — check no ImportError
print("server imported OK")
EOF
```
