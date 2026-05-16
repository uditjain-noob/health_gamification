# Custom Web UI Design
**Date:** 2026-05-16

---

## Overview

Replace the `fastmcp dev` inspector UI with a purpose-built health dashboard web app. The app mounts directly onto the FastMCP HTTP server — one command, one port, no separate process. Four files: a patient ID entry page (redirect only) and three main pages — dashboard (split view), agent (full-screen), goals (readiness + plan).

---

## Architecture

### Entry point

```bash
uv run python server.py   # was: fastmcp dev server.py
# Serves UI at:  http://localhost:8000/ui/
# MCP at:        http://localhost:8000/mcp
```

### How it works

`server.py` runs FastMCP in HTTP mode via `mcp.http_app()`, which returns a Starlette ASGI app. A `StaticFiles` mount is added at `/ui` pointing to a new `ui/` directory. The browser opens automatically. No subprocess management, no separate server, no CORS issues.

```python
# Bottom of server.py — replaces mcp.run()
from starlette.staticfiles import StaticFiles
import webbrowser, uvicorn

if __name__ == "__main__":
    app = mcp.http_app()
    app.mount("/ui", StaticFiles(directory="ui", html=True))
    webbrowser.open("http://localhost:8000/ui/")
    uvicorn.run(app, port=8000)
```

### Prefab rendering

Tool results (PrefabApp objects) are rendered in `<iframe>` elements using `app-bridge.js` from the `@modelcontextprotocol/ext-apps` npm package — the same bridge FastMCP's dev server uses internally. `server.py` exposes this JS file at `/ui/app-bridge.js` by adding an HTTP route that reads the bundled file from the installed FastMCP package (found at `fastmcp/apps/static/app-bridge.js` or equivalent). `mcp-client.js` handles the JSON-RPC call, receives the Prefab payload, and loads it into the iframe via `postMessage`.

### Dashboard organ grid

The organ grid in `dashboard.html` must be native interactive HTML (not a Prefab iframe) so organ cards are clickable. A new `get_dashboard_data(patient_id)` tool is added to `apps/dashboard.py` — it returns the same organ summaries that `show_health_dashboard` computes, but as plain JSON instead of a PrefabApp. The existing `show_health_dashboard` tool is unchanged.

---

## New Files

```
ui/
├── index.html        ← patient ID input; redirects to dashboard.html?patient=<id>
├── dashboard.html    ← main split-view dashboard
├── agent.html        ← full-screen agent dashboard
├── goals.html        ← goal readiness + training plan
└── mcp-client.js     ← shared: MCP JSON-RPC helper + iframe loader
```

### `mcp-client.js` responsibilities
- `callTool(name, args)` — sends a JSON-RPC `tools/call` request to `/mcp`, returns the result
- `loadIntoIframe(iframeEl, toolName, args)` — calls the tool, extracts the PrefabApp payload, loads it into the given iframe element via app-bridge
- `getUrlParam(key)` — URL param helper used by all pages to read `patient` and `organ`

---

## Pages

### Page 1: `index.html`
Simple centered form. Single input for patient ID, a submit button. On submit, redirects to `dashboard.html?patient=<id>`. No MCP calls.

### Page 2: `dashboard.html`

**URL:** `dashboard.html?patient=<id>`

**Layout:** Fixed top nav + two-column split (no scroll on outer container).

**Top nav:**
- Left: ⚕️ HealthQuest logo
- Center: patient ID badge (read from URL param)
- Right: nav links → Agent Dashboard, Goals (both carry `?patient=<id>`)

**Left column (340px fixed, scrollable):**
- Overall score card: rank emoji, rank name, score/1000, XP progress bar, level badge
- Section label "Organ Systems"
- 2-column organ grid: each card shows organ emoji + name, score/100, rank badge, flagged/total count
- On page load: calls `show_health_dashboard(patient_id)` via `callTool`, builds the organ grid from the JSON result (not via iframe — the grid is native HTML for interactivity)
- Selected organ card gets a blue border highlight

**Right column (flex, fills remaining width):**
- Sub-header: selected organ name + rank badge + "loading…" indicator
- Full-height iframe: loads `show_organ_panel(patient_id, organ)` result via `loadIntoIframe`
- Default state (no organ selected): placeholder with "← Select an organ to drill in"
- On organ card click: updates URL hash (`#organ=heart`), swaps iframe content

**Bottom stats bar:**
- Total parameters, total flagged, total in range — derived from dashboard tool result

### Page 3: `agent.html`

**URL:** `agent.html?patient=<id>`

**Layout:** Full-screen, minimal chrome.

**Top nav:** Back arrow → dashboard, page title "🤖 Agent Dashboard", patient ID badge.

**Control bar (below nav):**
- Free-text input: optional context (e.g. "focus on cardiovascular risk")
- "▶ Run Agent" button
- Estimated time label: "~30–60s · full analysis"

**Main area:**
- Before run: empty state with prompt to hit Run Agent
- While running: progress indicator bar showing current agent step
- After run: full-width iframe with `run_health_agent(patient_id, context)` result

Patient ID read from URL param. Carried from dashboard via nav link.

### Page 4: `goals.html`

**URL:** `goals.html?patient=<id>`

**Layout:** Scrollable single column.

**Top nav:** Back arrow → dashboard, page title "🎯 Goals", patient ID badge.

**Goal input bar (sticky):**
- Goal text input (e.g. "Run a marathon in 6 months")
- "Analyse Goal" button

**Results (appear sequentially after Analyse Goal is clicked):**
1. **Goal Readiness section** — iframe loads `show_goal_view(patient_id, goal)`; appears immediately after button click
2. **"Build Training Plan" button** — appears after goal view iframe finishes loading
3. **Training Plan section** — iframe loads `build_goal_plan(patient_id, goal)` after button click

Patient ID read from URL param.

---

## Modified Files

| File | Change |
|------|--------|
| `server.py` | Replace `mcp.run()` with `mcp.http_app()` + `StaticFiles` mount + app-bridge route + `uvicorn.run()` |
| `apps/dashboard.py` | Add `get_dashboard_data(patient_id)` tool — returns organ summaries as JSON for native HTML grid |

---

## Data Flow

```
User opens /ui/
  → index.html: enters patient_id → redirects to dashboard.html?patient=<id>
  → dashboard.html: callTool("show_health_dashboard", {patient_id})
      → builds organ grid from JSON result (native HTML)
  → user clicks organ card
      → loadIntoIframe(iframe, "show_organ_panel", {patient_id, organ})
  → user clicks "Agent Dashboard" nav link
      → agent.html?patient=<id>
      → user hits Run Agent → loadIntoIframe(iframe, "run_health_agent", {patient_id, context})
  → user clicks "Goals" nav link
      → goals.html?patient=<id>
      → user enters goal → loadIntoIframe(iframe1, "show_goal_view", {patient_id, goal})
      → user clicks Build Training Plan → loadIntoIframe(iframe2, "build_goal_plan", {patient_id, goal})
```

---

## Out of Scope

- Authentication / multi-user session management
- Persisting selected organ or goal across page refreshes (URL params are sufficient)
- Mobile / responsive layout
- Dark/light theme toggle
- Upload report flow in the new UI (still accessible via MCP clients)
- React or build tooling (pure HTML/JS only)
