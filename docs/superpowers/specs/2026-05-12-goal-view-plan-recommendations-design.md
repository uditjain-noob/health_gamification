# Goal View, Training Plan & Recommendations Design
**Date:** 2026-05-12

---

## Overview

Three connected features:
1. **Goal-Based Parameter View** — user expresses a goal (e.g. "run a marathon"), LLM picks all relevant parameters from the patient's full list, shows a readiness score + status card grid.
2. **Training Plan Generator** — LLM generates a 3-phase phased roadmap with embedded quests and XP per quest based on flagged goal-relevant parameters.
3. **Recommendations Refactor** — split into diet (LLM), exercise (LLM), supplements (stub API), all returning concise bullet-point items.

---

## 1. Goal-Based Parameter View

### Goal Resolution — pure LLM, no templates

**No keyword matching, no templates.** Every goal goes through a single LLM call.

`resolve_goal(client, goal: str, patient_params: list[str]) -> list[str]`
1. Fetch full patient parameter name list
2. One LLM call: give it the goal + full parameter name list
3. LLM returns a JSON array of relevant parameter names drawn from that list
4. Filter to names that actually exist in the patient's data (exact match)
5. Return matched parameter names

Prompt instructs the LLM to reason about clinical relevance: which parameters actually affect the user's ability to achieve this goal.

### New MCP Tool — `show_goal_view(patient_id, goal)`

**File:** `apps/goals.py`
**Decorator:** `@mcp.tool(app=True)`

Flow:
1. Fetch all patient parameters via `store.get_all_parameters(patient_id)`
2. Call `resolve_goal(client, goal, param_names)` to get relevant param names
3. Filter params to matched set; compute per-param scores via `score_parameter`
4. Compute **readiness score** = average score of all matched params (0–100), weighted so flagged params count double
5. Sort: flagged params first (by deviation), then normal params (dimmed)
6. Render Prefab UI:
   - Header card: goal name, readiness score badge, `"{N} parameters across {K} organs"`
   - Flat 3-col grid of status cards:
     - Each card: organ label (small, top-left), status badge (HIGH/LOW/NORMAL), parameter name, current value + unit, sparkline of score history
     - Flagged cards: colored border (red/yellow), dark tinted background
     - Normal cards: muted/dimmed
   - Footer `Muted`: "Ready to act? Ask me to build a training plan for {goal}"

---

## 2. Training Plan Generator

### New MCP Tool — `build_goal_plan(patient_id, goal)`

**File:** `apps/goals.py` (same file as `show_goal_view`)
**Decorator:** `@mcp.tool(app=True)`

Flow:
1. Re-run `resolve_goal` to get relevant params; filter to flagged only
2. Build flagged param summaries: name, current value, unit, ref range, target value (midpoint)
3. Single LLM call with structured prompt:
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
4. Parse JSON; log XP award via `store.log_xp` for plan creation event
5. Render Prefab UI:
   - Header: plan title, readiness score → projected score
   - 3-segment progress bar (Phase 1 active, 2 & 3 locked)
   - Phase 1 expanded: phase name + duration, parameter target chips (`current → target`), quest cards (type emoji, frequency, XP badge)
   - Phases 2 & 3: collapsed, "🔒 Unlocks after Phase N"
   - Disclaimer footer

**No persistence** — plan regenerated on each call; DB persistence is future work.

---

## 3. Recommendations Refactor

### Refactored `apps/recommendations.py`

Split into three focused functions, all returning **concise bullet-point items** — short actionable pointers, no verbose paragraphs.

```python
def fetch_diet_recs(client, organ: str, flagged: list[dict]) -> list[dict]
def fetch_exercise_recs(client, organ: str, flagged: list[dict]) -> list[dict]
def fetch_supplement_recs(flagged_param_names: list[str]) -> list[dict]  # stub → []
```

**Return schema for diet + exercise:**
```json
[{"title": str, "description": str, "priority": "high|medium|low"}]
```
`description` must be one sentence max — a concrete action pointer, not an explanation.

**Prompt instruction added to both diet + exercise calls:**
> "Each item must be one sentence. Be specific and actionable. No background explanation."

`fetch_supplement_recs`:
- Takes `list[str]` of flagged parameter names
- Returns `[]` until the supplements API is provided
- Marked with `# TODO(supplements-api): replace with API call` comment

`fetch_recommendations` (existing public wrapper) unchanged — calls all three and merges. No callers change.

---

## New Files

| File | Purpose |
|---|---|
| `apps/goals.py` | `show_goal_view` + `build_goal_plan` MCP tools + `resolve_goal` helper |

## Modified Files

| File | Change |
|---|---|
| `apps/recommendations.py` | Split into 3 focused functions; tighten prompts for concise output |
| `server.py` | Register `apps/goals` module |

## No DB Schema Changes

Plans generated on-the-fly. `xp_log` handles XP. No new tables.

---

## Out of Scope

- Persisting generated plans to DB
- RAG-based recommendations (PDF ingestion pipeline)
- Supplements API integration (stub interface ready)
- Marking quests complete within plan view
