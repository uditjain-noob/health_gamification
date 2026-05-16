# RAG Corpus Plan
## HealthQuest — Diet & Exercise Knowledge Base

**Goal:** A condition/parameter-searchable corpus that answers:
> "Given that [parameter] is [high/low], what diet, exercise, or supplements help?"

Not perfectly chunked, not academic-paper granular. Practical, retrievable, good enough.

---

## Source Overview

| | Source 2 | Source 3 |
|---|---|---|
| **Name** | Harvard T.H. Chan — The Nutrition Source | NSCA Biomarkers in Sports & Exercise (Lee et al., 2017) |
| **URL** | nutritionsource.hsph.harvard.edu | vtechworks.lib.vt.edu (open-access PDF) |
| **License** | Free, educational use | Open-access CC BY-NC-ND 4.0 |
| **Coverage** | Diet + specific nutrients/conditions | Exercise physiology + biomarker response to training |
| **Format** | ~40 individual HTML pages | Single 18-page PDF |
| **Chunking approach** | Scrape → one doc per page | Parse PDF → one chunk per biomarker section |

---

## Source 2 — Harvard Nutrition Source: Scraping Plan

### Why scrape instead of using the annual PDF
The annual PDF (Healthy Living Guide 2023/2024) is too general — it covers mindful eating and Zumba, not "what to eat when your SGPT is elevated." The website has dedicated pages per nutrient and condition that are far more useful. Each page is self-contained, 800–2000 words, and maps cleanly to a single topic.

### Target Pages

These are all the pages worth scraping, grouped by how they map to your organ systems:

**Lipids / Heart (Triglycerides, Cholesterol, LDL, HDL)**
```
/what-should-you-eat/fats-and-cholesterol/cholesterol/
/what-should-you-eat/fats-and-cholesterol/types-of-fat/
/what-should-you-eat/fats-and-cholesterol/dietary-fat-and-disease/
/carbohydrates/carbohydrates-and-blood-sugar/
/carbohydrates/fiber/
/carbohydrates/added-sugar-in-the-diet/
```

**Metabolic / Blood Sugar (HbA1c, Glucose, Insulin)**
```
/disease-prevention/diabetes-prevention/
/disease-prevention/diabetes-prevention/preventing-diabetes-problems/
/healthy-weight/best-diet-quality-counts/
```

**Blood / Anemia (Iron, Hemoglobin, Ferritin)**
```
/vitamins/iron/                          ← confirmed exists, rich content
/vitamins/vitamin-c/                     ← vitamin C enhances iron absorption
/vitamins/vitamin-b12/
/vitamins/folate-folic-acid/
```

**Liver (SGOT, SGPT, GGT, Alkaline Phosphatase)**
```
/disease-prevention/liver-disease/
/healthy-drinks/drinks-to-consume-in-moderation/   ← alcohol + liver
/what-should-you-eat/protein/
```

**Kidney (Creatinine, BUN, Uric Acid)**
```
/disease-prevention/kidney-disease/
/salt-and-sodium/
/healthy-drinks/water/
```

**Vitamins & General**
```
/vitamins/vitamin-d/
/vitamins/magnesium/
/vitamins/zinc/
/vitamins/calcium/
/vitamins/omega-3-fatty-acids/
```

**Exercise (used as cross-reference for all organs)**
```
/staying-active/
/staying-active/active-communities/
/disease-prevention/cardiovascular-disease/
```

**Total pages:** ~30 pages, each 800–2000 words = ~40,000–60,000 tokens total. Comfortable for embedding.

---

### Scraping Script

```python
# scrape_harvard.py
# Usage: python scrape_harvard.py
# Output: corpus/harvard/{slug}.txt — one file per page

import httpx
from bs4 import BeautifulSoup
import time
import re
from pathlib import Path

BASE = "https://nutritionsource.hsph.harvard.edu"

PAGES = [
    # Lipids
    "/what-should-you-eat/fats-and-cholesterol/cholesterol/",
    "/what-should-you-eat/fats-and-cholesterol/types-of-fat/",
    "/what-should-you-eat/fats-and-cholesterol/dietary-fat-and-disease/",
    "/carbohydrates/carbohydrates-and-blood-sugar/",
    "/carbohydrates/fiber/",
    "/carbohydrates/added-sugar-in-the-diet/",
    # Metabolic
    "/disease-prevention/diabetes-prevention/",
    "/disease-prevention/diabetes-prevention/preventing-diabetes-problems/",
    "/healthy-weight/best-diet-quality-counts/",
    # Blood / Anemia
    "/vitamins/iron/",
    "/vitamins/vitamin-c/",
    "/vitamins/vitamin-b12/",
    "/vitamins/folate-folic-acid/",
    # Liver
    "/disease-prevention/liver-disease/",
    "/healthy-drinks/drinks-to-consume-in-moderation/",
    "/what-should-you-eat/protein/",
    # Kidney
    "/disease-prevention/kidney-disease/",
    "/salt-and-sodium/",
    "/healthy-drinks/water/",
    # Vitamins
    "/vitamins/vitamin-d/",
    "/vitamins/magnesium/",
    "/vitamins/zinc/",
    "/vitamins/calcium/",
    "/vitamins/omega-3-fatty-acids/",
    # Exercise
    "/staying-active/",
    "/disease-prevention/cardiovascular-disease/",
]

# Metadata to attach to each scraped page
# Used for filtering during retrieval: organ, category
PAGE_METADATA = {
    "/what-should-you-eat/fats-and-cholesterol/cholesterol/":
        {"organ": "heart", "condition": "high cholesterol, high LDL, low HDL",
         "parameters": ["Total Cholesterol", "LDL", "HDL", "VLDL"],
         "category": "diet"},
    "/what-should-you-eat/fats-and-cholesterol/types-of-fat/":
        {"organ": "heart", "condition": "high triglycerides, high LDL",
         "parameters": ["Triglycerides", "LDL", "HDL"],
         "category": "diet"},
    "/what-should-you-eat/fats-and-cholesterol/dietary-fat-and-disease/":
        {"organ": "heart", "condition": "cardiovascular risk, lipid panel",
         "parameters": ["Total Cholesterol", "LDL", "HDL", "Triglycerides"],
         "category": "diet"},
    "/carbohydrates/carbohydrates-and-blood-sugar/":
        {"organ": "metabolic", "condition": "high blood sugar, high HbA1c",
         "parameters": ["Glucose", "HbA1c", "Insulin"],
         "category": "diet"},
    "/carbohydrates/fiber/":
        {"organ": "metabolic", "condition": "high triglycerides, high blood sugar",
         "parameters": ["Triglycerides", "Glucose", "LDL"],
         "category": "diet"},
    "/carbohydrates/added-sugar-in-the-diet/":
        {"organ": "metabolic", "condition": "high triglycerides, high blood sugar",
         "parameters": ["Triglycerides", "Glucose", "HbA1c"],
         "category": "diet"},
    "/disease-prevention/diabetes-prevention/":
        {"organ": "metabolic", "condition": "pre-diabetes, high HbA1c, insulin resistance",
         "parameters": ["HbA1c", "Glucose", "Insulin", "HOMA-IR"],
         "category": "diet,exercise"},
    "/disease-prevention/diabetes-prevention/preventing-diabetes-problems/":
        {"organ": "metabolic", "condition": "diabetes management",
         "parameters": ["HbA1c", "Glucose"],
         "category": "diet,exercise"},
    "/healthy-weight/best-diet-quality-counts/":
        {"organ": "metabolic", "condition": "metabolic syndrome, weight management",
         "parameters": ["Glucose", "Triglycerides", "HbA1c"],
         "category": "diet"},
    "/vitamins/iron/":
        {"organ": "blood", "condition": "low iron, iron deficiency anemia",
         "parameters": ["Iron", "Ferritin", "Hemoglobin", "Transferrin"],
         "category": "diet,supplement"},
    "/vitamins/vitamin-c/":
        {"organ": "blood", "condition": "low iron absorption, immune support",
         "parameters": ["Iron", "Hemoglobin"],
         "category": "diet,supplement"},
    "/vitamins/vitamin-b12/":
        {"organ": "blood", "condition": "low B12, macrocytic anemia",
         "parameters": ["Vitamin B12", "Hemoglobin", "MCV"],
         "category": "diet,supplement"},
    "/vitamins/folate-folic-acid/":
        {"organ": "blood", "condition": "low folate, macrocytic anemia",
         "parameters": ["Folate", "Hemoglobin", "MCV"],
         "category": "diet,supplement"},
    "/disease-prevention/liver-disease/":
        {"organ": "liver", "condition": "elevated liver enzymes, fatty liver, NAFLD",
         "parameters": ["SGOT", "SGPT", "GGT", "Alkaline Phosphatase", "Bilirubin"],
         "category": "diet,exercise"},
    "/healthy-drinks/drinks-to-consume-in-moderation/":
        {"organ": "liver", "condition": "elevated liver enzymes, alcohol-related",
         "parameters": ["GGT", "SGOT", "SGPT"],
         "category": "diet"},
    "/what-should-you-eat/protein/":
        {"organ": "liver,blood", "condition": "low albumin, low total protein",
         "parameters": ["Albumin", "Total Protein", "Globulin"],
         "category": "diet"},
    "/disease-prevention/kidney-disease/":
        {"organ": "kidney", "condition": "elevated creatinine, low eGFR",
         "parameters": ["Creatinine", "BUN", "eGFR", "Uric Acid"],
         "category": "diet,exercise"},
    "/salt-and-sodium/":
        {"organ": "kidney", "condition": "high blood pressure, kidney stress",
         "parameters": ["Sodium", "Creatinine"],
         "category": "diet"},
    "/healthy-drinks/water/":
        {"organ": "kidney", "condition": "dehydration, kidney function",
         "parameters": ["Creatinine", "BUN", "Uric Acid"],
         "category": "diet"},
    "/vitamins/vitamin-d/":
        {"organ": "vitamins", "condition": "low vitamin D",
         "parameters": ["Vitamin D"],
         "category": "diet,supplement"},
    "/vitamins/magnesium/":
        {"organ": "vitamins,metabolic", "condition": "low magnesium, insulin resistance",
         "parameters": ["Magnesium", "Glucose"],
         "category": "diet,supplement"},
    "/vitamins/zinc/":
        {"organ": "vitamins,immune", "condition": "low zinc",
         "parameters": ["Zinc"],
         "category": "diet,supplement"},
    "/vitamins/calcium/":
        {"organ": "vitamins,bone", "condition": "low calcium",
         "parameters": ["Calcium"],
         "category": "diet,supplement"},
    "/vitamins/omega-3-fatty-acids/":
        {"organ": "heart", "condition": "high triglycerides, inflammation",
         "parameters": ["Triglycerides", "HDL", "Hs-CRP"],
         "category": "diet,supplement"},
    "/staying-active/":
        {"organ": "all", "condition": "general exercise guidelines",
         "parameters": [],
         "category": "exercise"},
    "/disease-prevention/cardiovascular-disease/":
        {"organ": "heart", "condition": "cardiovascular risk, high LDL",
         "parameters": ["LDL", "HDL", "Triglycerides", "Hs-CRP"],
         "category": "diet,exercise"},
}

def slug(path: str) -> str:
    return path.strip("/").replace("/", "__")

def extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    # Remove nav, header, footer, sidebar — keep only article content
    for tag in soup.select("nav, header, footer, .sidebar, script, style, .menu"):
        tag.decompose()
    # Harvard Nutrition Source wraps content in <article> or <div class="entry-content">
    content = soup.select_one("article") or soup.select_one(".entry-content") or soup.body
    if not content:
        return ""
    text = content.get_text(separator="\n", strip=True)
    # Collapse excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def prepend_metadata(text: str, meta: dict, url: str) -> str:
    """
    Prepend a structured header to each doc.
    This is what gets embedded — the metadata makes semantic search
    work even for vague queries like 'liver enzymes diet'.
    """
    header = f"""SOURCE: Harvard T.H. Chan School of Public Health — The Nutrition Source
URL: {url}
ORGAN SYSTEM: {meta.get('organ', 'general')}
CONDITION: {meta.get('condition', '')}
RELATED PARAMETERS: {', '.join(meta.get('parameters', []))}
CATEGORY: {meta.get('category', '')}
---
"""
    return header + text

def scrape():
    out = Path("corpus/harvard")
    out.mkdir(parents=True, exist_ok=True)

    headers = {"User-Agent": "HealthQuest RAG Builder/1.0 (educational use)"}

    for path in PAGES:
        url = BASE + path
        filename = out / f"{slug(path)}.txt"

        if filename.exists():
            print(f"  skip (exists): {path}")
            continue

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

        meta = PAGE_METADATA.get(path, {"organ": "general", "condition": "", "parameters": [], "category": ""})
        doc = prepend_metadata(text, meta, url)

        filename.write_text(doc, encoding="utf-8")
        print(f"  OK  {path}  ({len(text)} chars)")
        time.sleep(1.5)   # be a polite scraper

if __name__ == "__main__":
    scrape()
```

**Output:** `corpus/harvard/` — one `.txt` file per page, ~30 files.

---

## Source 3 — NSCA Biomarkers Paper: Chunking Plan

### Paper Structure (from inspection)
The paper (Lee et al., 2017, JSCR) is 18 pages covering 6 biomarker categories:
1. Nutrition & Metabolic Health — protein/albumin, iron, vitamin D, glucose
2. Hydration Status — sodium, osmolality
3. Muscle Status — CK, myoglobin, testosterone, cortisol
4. Endurance Performance — hemoglobin, hematocrit, VO2max markers
5. Injury Status & Risk — inflammatory markers, bone density markers
6. Inflammation — CRP, IL-6, TNF-alpha

For your use case, categories 1, 3, 4, and 6 are relevant. Category 2 and 5 are lower priority but keep them for completeness.

### Chunking Strategy

**NOT** splitting at every sentence or paragraph. Split at **biomarker-group level** — each chunk covers one biomarker or a tight cluster (e.g. "iron + hemoglobin" together, since they're always discussed together in the paper).

Target chunk size: 400–800 words. At that size, each chunk is semantically cohesive and won't confuse the retriever with mixed signals.

### Chunking Script

```python
# chunk_nsca.py
# Usage: python chunk_nsca.py
# Requires: pip install pymupdf (fitz)
# Input:  source/nsca_biomarkers_2017.pdf
# Output: corpus/nsca/{chunk_name}.txt

import fitz   # PyMuPDF
import re
from pathlib import Path

PDF_PATH = "source/nsca_biomarkers_2017.pdf"

# Manual chunk boundaries — defined by the paper's own section headings.
# Each entry: (start_page, end_page, chunk_name, metadata)
# Pages are 0-indexed from the PDF.
# You'll verify these page numbers after downloading the PDF.

CHUNKS = [
    {
        "name": "nutrition_protein_albumin",
        "pages": (3, 5),          # adjust after inspection
        "organ": "liver,blood",
        "condition": "low albumin, low total protein, protein deficiency",
        "parameters": ["Albumin", "Total Protein", "Globulin", "BUN"],
        "category": "exercise",
        "summary": "How exercise training affects protein status, albumin, BUN. "
                   "How protein intake and dietary adequacy are reflected in these markers.",
    },
    {
        "name": "nutrition_iron_hemoglobin",
        "pages": (5, 7),
        "organ": "blood",
        "condition": "low iron, low hemoglobin, iron deficiency anemia, sports anemia",
        "parameters": ["Iron", "Hemoglobin", "Hematocrit", "Ferritin", "Transferrin"],
        "category": "exercise,supplement",
        "summary": "How endurance exercise affects iron stores and hemoglobin. "
                   "Sports anemia vs true anemia. Iron supplementation protocols for athletes.",
    },
    {
        "name": "nutrition_vitamin_d_glucose",
        "pages": (7, 8),
        "organ": "vitamins,metabolic",
        "condition": "low vitamin D, high blood glucose, insulin resistance",
        "parameters": ["Vitamin D", "Glucose", "HbA1c", "Insulin"],
        "category": "exercise,supplement",
        "summary": "Exercise effects on vitamin D status and glucose regulation. "
                   "Supplementation evidence.",
    },
    {
        "name": "hydration_sodium_electrolytes",
        "pages": (8, 9),
        "organ": "kidney",
        "condition": "dehydration, electrolyte imbalance",
        "parameters": ["Sodium", "Potassium", "Osmolality", "Creatinine"],
        "category": "exercise",
        "summary": "Hydration biomarkers during exercise. Sodium and electrolyte balance.",
    },
    {
        "name": "muscle_status_ck_testosterone_cortisol",
        "pages": (9, 12),
        "organ": "hormones,muscle",
        "condition": "muscle damage, overtraining, low testosterone, high cortisol",
        "parameters": ["CK", "Myoglobin", "Testosterone", "Cortisol", "DHEA-S"],
        "category": "exercise",
        "summary": "Creatine kinase as muscle damage marker. Testosterone:Cortisol ratio "
                   "as overtraining indicator. How training intensity affects hormonal biomarkers.",
    },
    {
        "name": "endurance_performance_oxygen_transport",
        "pages": (12, 14),
        "organ": "blood,heart",
        "condition": "low hemoglobin, low hematocrit, poor cardiovascular fitness",
        "parameters": ["Hemoglobin", "Hematocrit", "RBC", "VO2max", "Lactate"],
        "category": "exercise",
        "summary": "Hemoglobin and hematocrit as oxygen transport markers. "
                   "How aerobic training improves RBC mass and VO2max. Zone 2 training effects.",
    },
    {
        "name": "inflammation_crp_il6",
        "pages": (14, 17),
        "organ": "heart,liver,general",
        "condition": "chronic inflammation, high CRP, elevated liver enzymes",
        "parameters": ["Hs-CRP", "IL-6", "TNF-alpha", "SGOT", "SGPT"],
        "category": "exercise",
        "summary": "How exercise reduces systemic inflammation. CRP as cardiovascular "
                   "risk marker. Anti-inflammatory effects of aerobic vs resistance training.",
    },
]

SOURCE_META = """SOURCE: Lee EC et al. (2017) Biomarkers in Sports and Exercise: Tracking Health, Performance, and Recovery in Athletes. Journal of Strength and Conditioning Research, 31(10):2920-2937.
LICENSE: CC BY-NC-ND 4.0 (open access)
URL: https://vtechworks.lib.vt.edu/server/api/core/bitstreams/9fdf4ecc-c70f-4fce-befd-d8b5689ef405/content
"""

def extract_pages(pdf_path: str, start: int, end: int) -> str:
    doc = fitz.open(pdf_path)
    text_parts = []
    for page_num in range(start, min(end + 1, len(doc))):
        page = doc[page_num]
        text_parts.append(page.get_text())
    doc.close()
    text = "\n".join(text_parts)
    # Clean up hyphenated line breaks common in PDF extraction
    text = re.sub(r"-\n(\w)", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def prepend_metadata(text: str, chunk: dict) -> str:
    header = f"""{SOURCE_META}
CHUNK: {chunk['name']}
ORGAN SYSTEM: {chunk['organ']}
CONDITION: {chunk['condition']}
RELATED PARAMETERS: {', '.join(chunk['parameters'])}
CATEGORY: {chunk['category']}
SUMMARY: {chunk['summary']}
---
"""
    return header + text

def chunk_pdf():
    out = Path("corpus/nsca")
    out.mkdir(parents=True, exist_ok=True)

    for chunk in CHUNKS:
        start, end = chunk["pages"]
        text = extract_pages(PDF_PATH, start, end)

        if len(text) < 100:
            print(f"  WARN too short: {chunk['name']}")
            continue

        doc = prepend_metadata(text, chunk)
        out_path = out / f"{chunk['name']}.txt"
        out_path.write_text(doc, encoding="utf-8")
        print(f"  OK  {chunk['name']}  ({len(text)} chars)")

if __name__ == "__main__":
    chunk_pdf()
```

---

## Corpus Structure After Running Both Scripts

```
corpus/
├── harvard/                              # ~30 files, one per page
│   ├── vitamins__iron.txt                # organ=blood, params=[Iron, Hemoglobin, Ferritin]
│   ├── disease-prevention__liver-disease.txt
│   ├── what-should-you-eat__fats-and-cholesterol__cholesterol.txt
│   └── ...
└── nsca/                                 # 7 files, one per biomarker section
    ├── nutrition_iron_hemoglobin.txt
    ├── endurance_performance_oxygen_transport.txt
    ├── inflammation_crp_il6.txt
    └── ...
```

**Total corpus size:** ~37 documents, ~50,000–70,000 words.

---

## Embedding & Retrieval Plan

### Embedding
```python
# embed.py — run once after scraping/chunking
from pathlib import Path
from sentence_transformers import SentenceTransformer
import json, numpy as np

model = SentenceTransformer("BAAI/bge-small-en-v1.5")  # lightweight, fast, good

docs = []
for f in Path("corpus").rglob("*.txt"):
    text = f.read_text()
    docs.append({"id": f.stem, "source": f.parent.name, "text": text, "path": str(f)})

texts = [d["text"] for d in docs]
embeddings = model.encode(texts, batch_size=8, show_progress_bar=True)

np.save("corpus/embeddings.npy", embeddings)
with open("corpus/docs_index.json", "w") as f:
    json.dump(docs, f, indent=2)
```

### Retrieval (used inside `get_recommendations_for_case`)
```python
# retrieval.py
import numpy as np, json
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("BAAI/bge-small-en-v1.5")
embeddings = np.load("corpus/embeddings.npy")
with open("corpus/docs_index.json") as f:
    docs = json.load(f)

def search(
    query: str,
    top_k: int = 4,
    filter_category: str | None = None,    # "diet", "exercise", "supplement"
    filter_organ: str | None = None,       # "liver", "blood", "heart", etc.
) -> list[dict]:
    q_emb = model.encode([query])
    scores = (embeddings @ q_emb.T).squeeze()

    results = []
    for i, score in enumerate(scores):
        doc = docs[i]
        # Simple metadata filter from the prepended header
        if filter_category and filter_category not in doc["text"][:500]:
            continue
        if filter_organ and filter_organ not in doc["text"][:500]:
            continue
        results.append({"score": float(score), **doc})

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]
```

### Query Patterns from the Agent

The agent's `get_recommendations_for_case` tool will call `search()` three times per organ, combining results:

```python
# Example: Liver organ with SGPT elevated, user goal = "weight loss"
diet_docs    = search("elevated SGPT fatty liver diet foods avoid",   filter_category="diet",     filter_organ="liver")
exercise_docs = search("liver enzymes exercise aerobic resistance",   filter_category="exercise", filter_organ="liver")
supplement_docs = search("SGPT SGOT liver supplements reduce",        filter_category="supplement")

# Pass top 2 from each (6 docs total) as context to Claude API
# in get_recommendations_for_case prompt
```

---

## Quick Setup (Sequence)

```bash
# 1. Install deps
pip install httpx beautifulsoup4 pymupdf sentence-transformers numpy

# 2. Download NSCA PDF
mkdir -p source
curl -L "https://vtechworks.lib.vt.edu/server/api/core/bitstreams/9fdf4ecc-c70f-4fce-befd-d8b5689ef405/content" \
     -o source/nsca_biomarkers_2017.pdf

# 3. Scrape Harvard pages
python scrape_harvard.py

# 4. Chunk NSCA PDF
#    First: open the PDF and verify page numbers in CHUNKS[], then:
python chunk_nsca.py

# 5. Embed everything
python embed.py

# 6. Test retrieval
python -c "
from retrieval import search
for r in search('low hemoglobin iron diet', top_k=3):
    print(r['id'], round(r['score'], 3))
"
```

---

## Notes

**Page number verification for NSCA PDF:**
Before running `chunk_nsca.py`, open the PDF and check the actual page numbers where each section starts. The `CHUNKS` list above has approximate estimates based on the paper's structure. Adjust `"pages"` tuples accordingly.

**If a Harvard page returns 404:**
The site occasionally reorganizes URLs. Check the sitemap at `nutritionsource.hsph.harvard.edu/sitemap.xml` or search for the topic directly. The scraper skips and logs failed pages cleanly.

**Re-embedding after adding pages:**
Just re-run `embed.py` — it re-reads all files in `corpus/`. No incremental embedding needed at this scale.

**Corpus updates:**
Harvard updates their pages occasionally. Re-scrape every 6 months. Delete the `.txt` file for that page (or all files) and re-run — the scraper checks for existing files and skips them.