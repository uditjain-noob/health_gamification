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
    "/vitamins/"
    # Exercise
    "/staying-active/",
    
    "/disease-prevention/cardiovascular-disease/",
    "/what-should-you-eat/vegetables-and-fruits/",
    "/sleep/",
    "/stress-and-health/",


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
    "/what-should-you-eat/vegetables-and-fruits/":
        {"organ": "all", "condition": "general nutrition, micronutrient deficiency, inflammation",
         "parameters": ["Folate", "Vitamin C", "Potassium", "Fiber"],
         "category": "diet"},
    "/sleep/":
        {"organ": "all", "condition": "sleep deprivation, metabolic health, insulin resistance",
         "parameters": ["Glucose", "Cortisol", "HbA1c"],
         "category": "lifestyle"},
    "/stress-and-health/":
        {"organ": "all", "condition": "chronic stress, elevated cortisol, inflammation",
         "parameters": ["Cortisol", "Hs-CRP", "Glucose"],
         "category": "lifestyle"},
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