# RAG Pipeline Design — Diet & Exercise Recommendations
**Date:** 2026-05-12  
**Scope:** Haystack-based retrieval pipeline for HealthQuest `get_rag_recommendations` MCP tool

---

## Overview

Add a RAG layer to the existing recommendations flow. A build script scrapes/chunks/embeds two knowledge sources (Harvard Nutrition + NSCA Biomarkers PDF) into a serialized `InMemoryDocumentStore`. At runtime, the MCP tool retrieves relevant chunks and passes them as grounding context to Gemini before generating recommendations.

---

## Architecture

```
BUILD (run once, offline)
  HarvardScraper ──────────────────────────────┐
                                               ▼
  NSCAPDFChunker ──► raw Documents ──► DocumentSplitter (Harvard only)
                                               ▼
                              SentenceTransformersDocumentEmbedder
                                     (BAAI/bge-small-en-v1.5)
                                               ▼
                                   InMemoryDocumentStore
                                               ▼
                                    serialize → corpus/store.json

QUERY (runtime, per MCP tool call)
  agent query string + organ + category
              ▼
  SentenceTransformersTextEmbedder (BAAI/bge-small-en-v1.5)
              ▼
  InMemoryEmbeddingRetriever (metadata pre-filter: organ, category)
              ▼
  top-5 chunks → injected into Gemini prompt as CONTEXT block
              ▼
  JSON recommendations: {diet: [...], exercise: [...], supplements: [...]}
```

---

## File Structure

```
scripts/excercise_diet_reco/
├── build_corpus.py              # indexing pipeline — run once
├── query_pipeline.py            # query pipeline module — imported by recommendations.py
├── corpus/
│   └── store.json               # serialized InMemoryDocumentStore (git-ignored)
└── harvard_nutrition/
    └── scraping_script.py       # existing scraper — imported by build_corpus.py

apps/
└── recommendations.py           # modified: loads store at startup, retrieves before Gemini
```

The NSCA PDF at `scripts/excercise_diet_reco/biomarkers_excercise/biomarkers.pdf` is read directly by `build_corpus.py`.

---

## Dependencies

Add to `pyproject.toml`:
```
haystack-ai>=2.0
sentence-transformers>=3.0
pymupdf>=1.24
beautifulsoup4>=4.12
```

(`httpx` already present for scraping.)

---

## Chunking Strategy

### Harvard pages (~26 HTML pages)
- Source: scraped via existing `scraping_script.py` (PAGES + PAGE_METADATA)
- Chunking: `DocumentSplitter(split_by="sentence", split_length=5, split_overlap=2)`
- ~100–150 words per chunk; child chunks inherit parent metadata

### NSCA PDF (7 manual sections)
- Source: `biomarkers_excercise/biomarkers.pdf` via PyMuPDF
- Chunking: manual page-range extraction, no further splitting (400–800 words each)
- Sections: nutrition_protein_albumin, nutrition_iron_hemoglobin, nutrition_vitamin_d_glucose, hydration_sodium_electrolytes, muscle_status_ck_testosterone_cortisol, endurance_performance_oxygen_transport, inflammation_crp_il6
- **Note:** page numbers in CHUNKS definition must be verified against the actual PDF before running

---

## Metadata Schema

Every `Document.meta` carries:

```python
{
    "source":     "harvard" | "nsca",
    "organ":      "liver" | "heart" | "blood" | "metabolic" | "kidney" | "vitamins" | "all",
    "category":   "diet" | "exercise" | "supplement" | "diet,exercise" | ...,
    "condition":  str,          # free-text, e.g. "elevated SGPT, fatty liver, NAFLD"
    "parameters": list[str],    # biomarker names, e.g. ["SGOT", "SGPT", "GGT"]
    "url":        str,
}
```

---

## Retrieval Filter

Pre-filters candidate set by organ before cosine scoring:

```python
filters = {
    "operator": "OR",
    "conditions": [
        {"field": "meta.organ", "operator": "==", "value": organ},
        {"field": "meta.organ", "operator": "==", "value": "all"},
    ]
}
```

When `category != "all"`, an additional condition filters on `meta.category` containing the requested category string.

`top_k=5` after filtering.

---

## MCP Tool Interface

New tool added alongside the existing `get_recommendations`:

```python
@mcp.tool()
def get_rag_recommendations(query: str, organ: str, category: str = "all") -> str:
    """
    Get RAG-grounded diet/exercise/supplement recommendations.

    The agent constructs `query` from the patient's flagged parameters, e.g.:
    "elevated SGPT SGOT fatty liver diet exercise reduce enzymes"

    - organ: organ name, e.g. "liver", "heart", "blood", "metabolic", "kidney"
    - category: "diet", "exercise", "supplement", or "all" (default)

    Returns JSON: {"diet": [...], "exercise": [...], "supplements": [...]}
    Each item: {"title": str, "description": str, "priority": "high|medium|low"}
    Max 3 items per category.
    """
```

The existing `get_recommendations` tool is kept unchanged for backward compatibility.

---

## `query_pipeline.py` Interface

```python
def load_store(path: str = "scripts/excercise_diet_reco/corpus/store.json") -> None:
    """Load serialized InMemoryDocumentStore into module-level singleton. Call once at startup."""

def retrieve(query: str, organ: str, category: str = "all", top_k: int = 5) -> list[str]:
    """Embed query, apply metadata filter, return list of chunk content strings."""
```

---

## `recommendations.py` Changes

1. On module load: call `load_store()` — store loads once into memory
2. `fetch_recommendations` gains a `use_rag: bool` parameter
3. When `use_rag=True`: call `retrieve(query, organ, category)` → prepend chunks as `CONTEXT:` block in Gemini prompt
4. Updated system prompt: "Use the provided context as grounding. Return ONLY valid JSON."
5. Original path (no context) remains as fallback when store is unavailable

---

## Build Pipeline Flow

```
1. Scrape Harvard pages (import from scraping_script.py)
   → skip 404s (log + continue)
   → produce List[Document] with meta

2. DocumentSplitter on Harvard docs
   → sentence-window chunks, meta inherited

3. Extract NSCA PDF sections (PyMuPDF, manual page ranges)
   → 7 Documents with meta, no splitting

4. SentenceTransformersDocumentEmbedder("BAAI/bge-small-en-v1.5")
   → first run downloads ~130MB model to HF cache

5. InMemoryDocumentStore.write_documents(all_docs)

6. json.dump(store.to_dict(), "corpus/store.json")
```

**CLI flags:**
- `--dry-run`: scrape + chunk, skip embed/serialize, print chunk count per source
- `--force`: overwrite existing `store.json` (default: skip if exists)

---

## Error Handling

| Failure | Behaviour |
|---------|-----------|
| Harvard page 404 | Log + skip, build continues |
| NSCA chunk < 100 chars | Log warning, skip chunk — prompts manual page number check |
| PDF not found | Hard fail with path in error message |
| `store.json` missing at startup | `load_store()` returns silently; `get_rag_recommendations` falls back to non-RAG path |

---

## Testing

- `build_corpus.py --dry-run` smoke test: asserts chunk count > 30
- `tests/test_rag_pipeline.py`: loads serialized store, calls `retrieve("low hemoglobin iron diet", organ="blood")`, asserts top result `meta.organ == "blood"`
