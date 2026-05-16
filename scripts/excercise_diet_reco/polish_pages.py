"""
Polish raw scraped pages into structured RAG-optimised text using Gemini 2.5 Pro.

Usage:
    python scripts/excercise_diet_reco/polish_pages.py [--force] [--dry-run] [--file <slug>]

Input:  scripts/excercise_diet_reco/harvard_nutrition/pages/*.txt
Output: scripts/excercise_diet_reco/harvard_nutrition/pages_polished/*.txt

--force:    overwrite existing polished files (default: skip existing)
--dry-run:  print the prompt for the first file only, don't call Gemini
--file:     polish a single file by slug (e.g. vitamins__iron)
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

_PAGES_DIR = Path("scripts/excercise_diet_reco/harvard_nutrition/pages")
_OUT_DIR = Path("scripts/excercise_diet_reco/harvard_nutrition/pages_polished")
_MODEL = "gemini-2.5-pro"

_SYSTEM = "You are a medical content editor. Output only the structured schema — no preamble, no explanation, no markdown fences."

_PROMPT = """\
You are a medical content editor improving RAG corpus quality for a health app.

Below is raw text scraped from a medical reference page about nutrition, vitamins, or disease prevention.
It contains navigation boilerplate, link lists, review metadata, and useful clinical information mixed together.

Your job: extract and rewrite ONLY the medically useful content into this exact schema.
Do not add information not present in the source. Do not invent numbers or food names.

---

CONDITION: [the specific health condition or biomarker abnormality this page addresses, e.g. "Iron deficiency anemia, low hemoglobin, low ferritin"]
BIOMARKERS: [comma-separated lab test names most relevant to this page, e.g. "Hemoglobin, Iron, Ferritin, Transferrin, MCV"]
ORGAN: [single value from: liver | blood | heart | metabolic | kidney | vitamins | all]
CATEGORY: [one or more from: diet | exercise | supplement | lifestyle — comma-separated]

---

MECHANISM:
[2-3 sentences: what the condition is and WHY the recommendations below work at a biological level. Include specific numbers or ranges where the source mentions them.]

DIETARY RECOMMENDATIONS:
[Bullet list of specific, actionable dietary advice. Include:
- Specific food names with quantities where mentioned
- Foods/drinks/substances to reduce or avoid, with reason
- Timing or preparation tips if mentioned (e.g. "take iron with vitamin C to improve absorption")
- Skip vague advice like "eat a balanced diet" — only include specific guidance]

EXERCISE RECOMMENDATIONS:
[Bullet list of specific exercise advice: type, duration, frequency, intensity where mentioned.
If the page has no exercise content, write exactly: General moderate exercise (150 min/week aerobic + 2x strength training) is recommended for overall metabolic health.]

SUPPLEMENT RECOMMENDATIONS:
[Bullet list: supplement name, typical dose range, form available, absorption notes.
If the page has no supplement content, write exactly: N/A]

WARNINGS:
[2-3 bullet points of clinical red flags that require medical attention, e.g. symptoms of severe deficiency or dangerous excess. Skip generic "consult your doctor" advice — only specific warning signs.]

---

Strip: navigation menus, "On this page", "Also called", link lists, "Find an Expert", "Clinical Trials",
"Also in Spanish", author credits, review dates, disclaimers, "Related Health Topics" link sections.

Keep: specific numbers (mg, IU, g, %, mmol/L, mg/dL, minutes/week), specific food names,
specific biomarker names, normal/target ranges where mentioned, supplement forms and doses.

SOURCE TEXT:
{text}
"""


def polish_file(path: Path, client: genai.Client, dry_run: bool = False) -> str:
    text = path.read_text(encoding="utf-8")
    prompt = _PROMPT.format(text=text)

    if dry_run:
        print(f"\n{'='*60}")
        print(f"FILE: {path.name}")
        print(f"{'='*60}")
        print(prompt[:2000])
        print("... [dry run — not calling Gemini]")
        return ""

    response = client.models.generate_content(
        model=_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM,
            thinking_config=types.ThinkingConfig(thinking_budget=5000),
        ),
    )
    return response.text


def build(force: bool = False, dry_run: bool = False, single_file: str | None = None) -> None:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise EnvironmentError("GOOGLE_API_KEY not set in environment / .env")

    client = genai.Client(api_key=api_key)
    _OUT_DIR.mkdir(parents=True, exist_ok=True)

    if single_file:
        files = [_PAGES_DIR / f"{single_file}.txt"]
        if not files[0].exists():
            raise FileNotFoundError(f"Page not found: {files[0]}")
    else:
        files = sorted(_PAGES_DIR.glob("*.txt"))

    print(f"Polishing {len(files)} page(s) → {_OUT_DIR}")

    for i, src in enumerate(files, 1):
        out = _OUT_DIR / src.name
        if out.exists() and not force and not dry_run:
            print(f"  [{i:02d}/{len(files)}] skip (exists): {src.name}")
            continue

        print(f"  [{i:02d}/{len(files)}] polishing: {src.name} ...", end=" ", flush=True)
        try:
            result = polish_file(src, client, dry_run=dry_run)
            if not dry_run:
                out.write_text(result, encoding="utf-8")
                print(f"done ({len(result)} chars)")
            # Rate-limit: Gemini 2.5 Pro has lower RPM quota
            if not dry_run and i < len(files):
                time.sleep(4)
        except Exception as e:
            print(f"ERROR: {e}")

    if not dry_run:
        print(f"\nDone. Polished files in {_OUT_DIR}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Polish RAG corpus pages with Gemini 2.5 Pro")
    parser.add_argument("--force", action="store_true", help="Overwrite existing polished files")
    parser.add_argument("--dry-run", action="store_true", help="Print prompt for first file, skip Gemini calls")
    parser.add_argument("--file", metavar="SLUG", help="Polish a single file by slug (e.g. vitamins__iron)")
    args = parser.parse_args()
    build(force=args.force, dry_run=args.dry_run, single_file=args.file)
