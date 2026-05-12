# Goal View, Training Plan & Recommendations Design
**Date:** 2026-05-12

---

## Overview

Three connected features:
1. **Goal-Based Parameter View** — user expresses a goal (e.g. "run a marathon"), system fetches all health parameters relevant to that goal across organs and shows a readiness score + status card grid.
2. **Training Plan Generator** — from the goal view, user clicks "Build Training Plan" to get a 3-phase phased roadmap with embedded quests and XP per quest.
3. **Recommendations Refactor** — split the single LLM call into separate diet (LLM), exercise (LLM), and supplements (stub API interface) functions.

---

## 1. Goal-Based Parameter View

### Goal Template System — `core/goals.py`

A dict mapping normalized goal keywords to lists of canonical parameter name substrings. Matching is case-insensitive substring on the parameter name.

**Initial templates:**

| Goal key | Canonical parameter substrings |
|---|---|
| `marathon` | hemoglobin, iron, ferritin, ESR, triglycerides, cholesterol, HbA1c, fasting blood sugar, vitamin B-12, vitamin D |
| `weight_loss` | HbA1c, fasting blood sugar, triglycerides, cholesterol, TSH, insulin |
| `heart_health` | total cholesterol, LDL, HDL, triglycerides, blood pressure, ESR |
| `sleep` | TSH, vitamin D, vitamin B-12, iron, ferritin, cortisol |
| `energy` | hemoglobin, iron, ferritin, vitamin B-12, vitamin D, fasting blood sugar, HbA1c |

**Matching function:** `resolve_goal(goal: str, patient_params: list[str]) -> list[str]`
1. Lowercase + strip the user's goal string
2. Try substring match against template keys (e.g. "marathon training" → `marathon`)
3. If no match: one LLM call with the goal + the patient's full parameter name list → LLM returns a JSON list of relevant parameter names
4. Filter result to only names that actually exist in the patient's data
5. Return matched parameter names

### New MCP Tool — `show_goal_view(patient_id, goal)`

**File:** `apps/goals.py`
**Decorator:** `@mcp.tool(app=True)`

Flow:
1. Fetch all patient parameters via `store.get_all_parameters(patient_id)`
2. Call `resolve_goal(goal, param_names)` to get relevant param names
3. Filter to matched params; compute per-param scores via `score_parameter`
4. Compute **readiness score** = average score of all matched params (0–100), weighted so flagged params count double
5. Sort: flagged params first (by deviation), then normal params (dimmed)
6. Render Prefab UI:
   - Header card: goal emoji + name, readiness score badge, `"{N} parameters across {K} organs"`
   - Flat 3-col grid of status cards (same style as organ view Option A):
     - Each card: organ label (small, top-left), status badge (HIGH/LOW/NORMAL), parameter name, current value + unit, sparkline of score history (flat list of scores)
     - Flagged cards: colored border (red/yellow), dark tinted background
     - Normal cards: muted/dimmed
   - A `Muted` footer line: "Ready to act? Ask me to **build_goal_plan** for {goal}" — since Prefab UI has no cross-tool button handler, this is a plain text prompt to the user/LLM to invoke the next tool

---

## 2. Training Plan Generator

### New MCP Tool — `build_goal_plan(patient_id, goal)`

**File:** `apps/goals.py` (same file as `show_goal_view`)
**Decorator:** `@mcp.tool(app=True)`

Flow:
1. Re-run `resolve_goal` to get relevant params; filter to flagged only
2. Build a summary of flagged params: name, current value, unit, ref range, target value (midpoint of range)
3. Single LLM call (`client.complete`) with structured prompt:
   - Input: goal, flagged param summaries, patient readiness score
   - System: "Return ONLY valid JSON matching this schema"
   - Output schema:
     ```json
     {
       "plan_title": str,
       "phases": [
         {
           "name": str,
           "duration_weeks": int,
           "focus": str,
           "parameter_targets": [{"name": str, "current": float, "target": float, "unit": str}],
           "quests": [{"title": str, "type": "diet|exercise|supplement", "frequency": str, "xp": int}]
         }
       ]
     }
     ```
   - Max 3 phases, max 3 quests per phase
4. Parse JSON; log XP events for quest completion stubs via `store.log_xp`
5. Render Prefab UI:
   - Header: plan title, readiness score → projected score after plan completion
   - 3-segment progress bar (one segment per phase; Phase 1 active, 2 & 3 locked)
   - Phase 1 fully expanded:
     - Phase name + duration
     - Parameter target chips: `current → target` per flagged param
     - Quest cards with type emoji (🥗 diet / 🏃 exercise / 💊 supplement), frequency, XP badge
   - Phases 2 & 3: collapsed row showing name only, "🔒 Unlocks after Phase 1"
   - Disclaimer footer

**No persistence of plan JSON** — plan is regenerated each call. This keeps the DB schema simple; persistence can be added later.

---

## 3. Recommendations Refactor

### Refactored `apps/recommendations.py`

Split `fetch_recommendations` into three independent functions:

```python
def fetch_diet_recs(client, organ: str, flagged: list[dict]) -> list[dict]
def fetch_exercise_recs(client, organ: str, flagged: list[dict]) -> list[dict]
def fetch_supplement_recs(flagged_param_names: list[str]) -> list[dict]  # stub
```

Each `fetch_diet_recs` / `fetch_exercise_recs` makes its own focused LLM call:
- Prompt scoped to just that category (diet or exercise)
- Returns `[{title, description, priority}]`
- Separate prompts allow future RAG replacement per-category without touching the other

`fetch_supplement_recs`:
- Signature: takes `list[str]` of flagged parameter names
- Currently returns `[]`
- Placeholder comment marks the API integration point
- When the supplements API is provided: one function swap, no callers change

`fetch_recommendations` (existing public function) is kept as a thin wrapper calling all three and merging results — so `show_organ_panel` and `get_recommendations` require zero changes.

---

## New Files

| File | Purpose |
|---|---|
| `core/goals.py` | Goal templates dict + `resolve_goal()` function |
| `apps/goals.py` | `show_goal_view` + `build_goal_plan` MCP tools |

## Modified Files

| File | Change |
|---|---|
| `apps/recommendations.py` | Split `fetch_recommendations` into 3 functions; keep wrapper |
| `server.py` | Register `apps/goals` module |

## No DB Schema Changes

Goal plans are generated on-the-fly. The existing `xp_log` table handles XP. No new tables needed.

---

## Out of Scope

- Persisting generated plans to DB (future)
- RAG-based diet/exercise recommendations (future — PDF ingestion pipeline)
- Supplements API integration (future — stub interface ready)
- Editing or marking quests complete within the plan view (future)
