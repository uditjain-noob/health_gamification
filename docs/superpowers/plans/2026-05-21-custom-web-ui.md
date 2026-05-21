# Custom Web UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mount a purpose-built health dashboard web app on the FastMCP HTTP server — one command, one port, four pages.

**Architecture:** `server.py` switches from `mcp.run()` to `mcp.http_app()` + `uvicorn`, adds routes for `/js/app-bridge.js`, `/ui-resource`, `/render`, and `/api/dashboard/{patient_id}`, and mounts `ui/` as StaticFiles at `/ui`. Prefab tool results render inside iframes using the existing `AppBridge` + `PostMessageTransport` protocol from the fastmcp dev server — our `/render?tool=X&args=Y` endpoint generates the host HTML. The native organ grid in `dashboard.html` is powered by a new `/api/dashboard/{patient_id}` REST endpoint that calls `get_dashboard_json()` directly (no MCP protocol in the browser for data fetching).

**Tech Stack:** Python/FastMCP/Starlette/uvicorn, plain HTML+CSS+JS (ES modules, no build step), fastmcp private API `_fetch_app_bridge_bundle_sync` for app-bridge.js.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `apps/dashboard.py` | Add `get_dashboard_json()` helper + `get_dashboard_data` MCP tool |
| Modify | `server.py` | Replace `mcp.run()` with uvicorn + add all UI routes |
| Create | `ui/mcp-client.js` | `loadIntoIframe`, `fetchDashboardData`, `getUrlParam` |
| Create | `ui/index.html` | Patient ID entry form, redirects to dashboard |
| Create | `ui/dashboard.html` | Split-view: native organ grid + organ panel iframe |
| Create | `ui/agent.html` | Full-screen agent runner iframe |
| Create | `ui/goals.html` | Goal readiness + training plan iframes |

---

## Task 1: Add `get_dashboard_json` to `apps/dashboard.py`

**Files:**
- Modify: `apps/dashboard.py`
- Test: `tests/test_get_dashboard_json.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_get_dashboard_json.py`:

```python
from unittest.mock import MagicMock
from apps.dashboard import get_dashboard_json


def _make_store(organ="liver", flagged=False):
    store = MagicMock()
    store.get_organ_summaries.return_value = [{"organ": organ}]
    status = "high" if flagged else "normal"
    store.get_parameters_for_organ.return_value = [
        {
            "name": "ALT",
            "readings": [{"status": status, "value": 30, "ref_min": 7, "ref_max": 56}],
        }
    ]
    store.get_xp_total.return_value = 75
    return store


def _make_mapper():
    mapper = MagicMock()
    mapper.is_critical.return_value = False
    mapper.get_organ_emoji.return_value = "🫁"
    mapper.get_organ_weight.return_value = 1.0
    return mapper


def test_get_dashboard_json_shape():
    data = get_dashboard_json(_make_store(), _make_mapper(), "p1")
    assert isinstance(data["overall"], (int, float))
    assert isinstance(data["rank"], str)
    assert isinstance(data["rank_emoji"], str)
    assert isinstance(data["level"], int)
    assert isinstance(data["xp_total"], int)
    assert isinstance(data["xp_to_next"], int)
    assert isinstance(data["organs"], list)
    assert isinstance(data["total_params"], int)
    assert isinstance(data["total_flagged"], int)


def test_get_dashboard_json_organ_fields():
    data = get_dashboard_json(_make_store(), _make_mapper(), "p1")
    organ = data["organs"][0]
    assert organ["organ"] == "liver"
    assert organ["emoji"] == "🫁"
    assert isinstance(organ["score"], (int, float))
    assert isinstance(organ["rank"], str)
    assert organ["parameter_count"] == 1
    assert organ["flagged_count"] == 0


def test_get_dashboard_json_counts_flagged():
    data = get_dashboard_json(_make_store(flagged=True), _make_mapper(), "p1")
    assert data["organs"][0]["flagged_count"] == 1
    assert data["total_flagged"] == 1


def test_get_dashboard_json_empty_patient():
    store = MagicMock()
    store.get_organ_summaries.return_value = []
    store.get_xp_total.return_value = 0
    data = get_dashboard_json(store, MagicMock(), "nobody")
    assert data["organs"] == []
    assert data["overall"] == 0
    assert data["total_params"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_get_dashboard_json.py -v
```

Expected: `ImportError` or `AttributeError` — `get_dashboard_json` doesn't exist yet.

- [ ] **Step 3: Add `get_dashboard_json` and `get_dashboard_data` tool to `apps/dashboard.py`**

Add after the `_build_organ_summaries` function (before `ShowHealthDashboardInput`):

```python
def get_dashboard_json(store: Store, mapper: OrganMapper, patient_id: str) -> dict:
    from core.scorer import score_overall, get_rank, get_level
    summaries = _build_organ_summaries(store, mapper, patient_id)
    if not summaries:
        xp_total = store.get_xp_total(patient_id)
        return {
            "overall": 0, "rank": "Bronze", "rank_emoji": "🟤",
            "level": 1, "xp_total": xp_total, "xp_to_next": 50,
            "organs": [], "total_params": 0, "total_flagged": 0,
        }
    organ_scores = {s["organ"]: s["score"] for s in summaries}
    organ_weights = {s["organ"]: s["weight"] for s in summaries}
    overall = score_overall(organ_scores, organ_weights)
    rank = get_rank(overall)
    level = get_level(overall)
    xp_total = store.get_xp_total(patient_id)
    xp_to_next = max(0, (level + 1) * 50 - xp_total)
    rank_emoji = {"Bronze": "🟤", "Silver": "⚪", "Gold": "🟡", "Platinum": "🔵", "Diamond": "💎"}.get(rank, "🟤")
    total_params = sum(s["parameter_count"] for s in summaries)
    total_flagged = sum(s["flagged_count"] for s in summaries)
    return {
        "overall": overall,
        "rank": rank,
        "rank_emoji": rank_emoji,
        "level": level,
        "xp_total": xp_total,
        "xp_to_next": xp_to_next,
        "organs": [
            {
                "organ": s["organ"],
                "emoji": s["emoji"],
                "score": s["score"],
                "rank": s["rank"],
                "flagged_count": s["flagged_count"],
                "parameter_count": s["parameter_count"],
            }
            for s in summaries
        ],
        "total_params": total_params,
        "total_flagged": total_flagged,
    }
```

Then inside `register(mcp, get_store, get_mapper)`, after the `show_health_dashboard` tool, add:

```python
    class GetDashboardDataInput(BaseModel):
        patient_id: str

    @mcp.tool()
    def get_dashboard_data(input: GetDashboardDataInput) -> dict:
        """Return dashboard summary as plain JSON (overall score, rank, level, XP, organ list)."""
        return get_dashboard_json(get_store(), get_mapper(), input.patient_id)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_get_dashboard_json.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Run full suite to check for regressions**

```bash
uv run pytest
```

Expected: all existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add apps/dashboard.py tests/test_get_dashboard_json.py
git commit -m "feat: add get_dashboard_json helper and get_dashboard_data MCP tool"
```

---

## Task 2: Modify `server.py` — switch to uvicorn + add UI routes

**Files:**
- Modify: `server.py`

Note: No unit tests for server wiring — integration-tested by running the server.

- [ ] **Step 1: Replace the `if __name__ == "__main__":` block in `server.py`**

The current block is:
```python
if __name__ == "__main__":
    mcp.run()
```

Replace it with:

```python
if __name__ == "__main__":
    import json
    import webbrowser
    import uvicorn
    from starlette.staticfiles import StaticFiles
    from starlette.requests import Request
    from starlette.responses import HTMLResponse, JSONResponse, Response
    from fastmcp.cli.apps_dev import (
        _fetch_app_bridge_bundle_sync,
        _EXT_APPS_VERSION,
        _MCP_SDK_VERSION,
        _HOST_HTML_TEMPLATE,
        _read_mcp_resource,
    )
    from apps.dashboard import get_dashboard_json

    app_bridge_js, import_map_json = _fetch_app_bridge_bundle_sync(
        _EXT_APPS_VERSION, _MCP_SDK_VERSION
    )
    import_map_tag = f'<script type="importmap">{import_map_json}</script>'

    async def serve_bridge(request: Request) -> Response:
        return Response(content=app_bridge_js, media_type="application/javascript")

    async def serve_ui_resource(request: Request) -> Response:
        uri = request.query_params.get("uri", "")
        if not uri:
            return Response("Missing uri", status_code=400)
        html = await _read_mcp_resource("http://127.0.0.1:8000/mcp", uri)
        if html is None:
            return Response("Resource not found", status_code=502)
        return HTMLResponse(html)

    async def render_tool(request: Request) -> Response:
        tool_name = request.query_params.get("tool", "")
        args_json = request.query_params.get("args", "{}")
        try:
            tool_args = json.loads(args_json)
        except json.JSONDecodeError:
            tool_args = {}
        html = _HOST_HTML_TEMPLATE.format(
            tool_name=tool_name,
            import_map_tag=import_map_tag,
            tool_name_json=json.dumps(tool_name),
            tool_args_json=json.dumps(tool_args),
            mcp_sdk_version=_MCP_SDK_VERSION,
        )
        return HTMLResponse(html)

    async def api_dashboard(request: Request) -> Response:
        patient_id = request.path_params["patient_id"]
        store = get_store()
        mapper = get_mapper()
        data = get_dashboard_json(store, mapper, patient_id)
        return JSONResponse(data)

    app = mcp.http_app()
    app.add_route("/js/app-bridge.js", serve_bridge)
    app.add_route("/ui-resource", serve_ui_resource)   # must come before /ui mount
    app.add_route("/render", render_tool)
    app.add_route("/api/dashboard/{patient_id}", api_dashboard)
    app.mount("/ui", StaticFiles(directory="ui", html=True))

    webbrowser.open("http://127.0.0.1:8000/ui/")
    uvicorn.run(app, host="127.0.0.1", port=8000)
```

- [ ] **Step 2: Create the `ui/` directory with a placeholder `index.html` to unblock server startup**

```bash
mkdir -p ui
```

Then create `ui/index.html` with just `<html><body>placeholder</body></html>` (will be replaced in Task 4).

- [ ] **Step 3: Smoke-test the server starts without errors**

```bash
uv run python server.py &
sleep 4
curl -s http://127.0.0.1:8000/ui/ | head -5
curl -s http://127.0.0.1:8000/js/app-bridge.js | head -3
kill %1
```

Expected: `ui/` returns the placeholder HTML; `app-bridge.js` returns JavaScript starting with something like `var ` or `import `.

- [ ] **Step 4: Commit**

```bash
git add server.py ui/index.html
git commit -m "feat: switch server to uvicorn HTTP mode with UI static files and render routes"
```

---

## Task 3: Create `ui/mcp-client.js`

**Files:**
- Create: `ui/mcp-client.js`

- [ ] **Step 1: Create `ui/mcp-client.js`**

```javascript
// Helpers used by all pages.

export function getUrlParam(key) {
    return new URLSearchParams(window.location.search).get(key) ?? "";
}

/**
 * Point an iframe at the /render endpoint, which serves a full AppBridge host
 * page for the given tool.  The iframe handles MCP connection and Prefab
 * rendering internally — no MCP protocol needed on the caller side.
 */
export function loadIntoIframe(iframeEl, toolName, args) {
    const argsJson = JSON.stringify(args);
    iframeEl.src =
        "/render?tool=" +
        encodeURIComponent(toolName) +
        "&args=" +
        encodeURIComponent(argsJson);
}

/**
 * Fetch dashboard JSON data from the REST endpoint.
 * Returns the object from get_dashboard_json() on the server.
 */
export async function fetchDashboardData(patientId) {
    const resp = await fetch("/api/dashboard/" + encodeURIComponent(patientId));
    if (!resp.ok) throw new Error("Dashboard fetch failed: " + resp.status);
    return resp.json();
}
```

- [ ] **Step 2: Commit**

```bash
git add ui/mcp-client.js
git commit -m "feat: add mcp-client.js with loadIntoIframe, fetchDashboardData, getUrlParam"
```

---

## Task 4: Create `ui/index.html`

**Files:**
- Create: `ui/index.html` (replaces placeholder from Task 2)

- [ ] **Step 1: Write `ui/index.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>HealthQuest</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: system-ui, sans-serif;
      background: #f8fafc;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
    }
    .card {
      background: #fff;
      border: 1px solid #e2e8f0;
      border-radius: 12px;
      padding: 2.5rem 2rem;
      width: 360px;
      box-shadow: 0 4px 24px rgba(0,0,0,.07);
      text-align: center;
    }
    h1 { font-size: 1.6rem; margin-bottom: .25rem; }
    p  { color: #64748b; margin-bottom: 1.5rem; font-size: .95rem; }
    input {
      width: 100%; padding: .6rem .9rem;
      border: 1px solid #cbd5e1; border-radius: 6px;
      font-size: 1rem; margin-bottom: .75rem;
      outline: none;
    }
    input:focus { border-color: #3b82f6; box-shadow: 0 0 0 3px rgba(59,130,246,.15); }
    button {
      width: 100%; padding: .65rem;
      background: #3b82f6; color: #fff;
      border: none; border-radius: 6px;
      font-size: 1rem; cursor: pointer;
      font-weight: 500;
    }
    button:hover { background: #2563eb; }
    #err { color: #ef4444; font-size: .85rem; margin-top: .5rem; display: none; }
  </style>
</head>
<body>
  <div class="card">
    <h1>⚕️ HealthQuest</h1>
    <p>Enter your patient ID to view your health dashboard.</p>
    <input id="pid" type="text" placeholder="Patient ID" autofocus>
    <button id="go">View Dashboard →</button>
    <div id="err">Please enter a patient ID.</div>
  </div>
  <script>
    function submit() {
      const pid = document.getElementById("pid").value.trim();
      if (!pid) { document.getElementById("err").style.display = "block"; return; }
      window.location.href = "dashboard.html?patient=" + encodeURIComponent(pid);
    }
    document.getElementById("go").addEventListener("click", submit);
    document.getElementById("pid").addEventListener("keydown", e => {
      if (e.key === "Enter") submit();
    });
  </script>
</body>
</html>
```

- [ ] **Step 2: Smoke-test in browser**

Start the server with `uv run python server.py`, open `http://127.0.0.1:8000/ui/`. Verify:
- Centered card with patient ID input renders
- Submitting empty input shows error message
- Submitting "p1" redirects to `dashboard.html?patient=p1`

- [ ] **Step 3: Commit**

```bash
git add ui/index.html
git commit -m "feat: add index.html patient ID entry page"
```

---

## Task 5: Create `ui/dashboard.html`

**Files:**
- Create: `ui/dashboard.html`

- [ ] **Step 1: Write `ui/dashboard.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>HealthQuest — Dashboard</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: system-ui, sans-serif; background: #f8fafc; height: 100vh; display: flex; flex-direction: column; overflow: hidden; }

    /* Nav */
    nav {
      display: flex; align-items: center; justify-content: space-between;
      padding: .75rem 1.25rem; background: #fff;
      border-bottom: 1px solid #e2e8f0; flex-shrink: 0;
    }
    nav .logo { font-weight: 700; font-size: 1.1rem; }
    nav .patient-badge {
      background: #eff6ff; color: #1d4ed8;
      border: 1px solid #bfdbfe; border-radius: 20px;
      padding: .2rem .75rem; font-size: .85rem;
    }
    nav .nav-links a {
      color: #475569; text-decoration: none; margin-left: 1rem;
      font-size: .9rem;
    }
    nav .nav-links a:hover { color: #3b82f6; }

    /* Layout */
    .layout { display: flex; flex: 1; overflow: hidden; }

    /* Left column */
    .left {
      width: 340px; flex-shrink: 0;
      overflow-y: auto; padding: 1rem;
      border-right: 1px solid #e2e8f0; background: #fff;
    }
    .score-card {
      background: linear-gradient(135deg, #eff6ff, #dbeafe);
      border: 1px solid #bfdbfe; border-radius: 10px;
      padding: 1rem; margin-bottom: 1rem;
    }
    .score-card .rank-row { display: flex; justify-content: space-between; align-items: center; }
    .score-card .rank-name { font-weight: 700; font-size: 1rem; }
    .score-card .level-badge {
      background: #3b82f6; color: #fff;
      border-radius: 20px; padding: .15rem .6rem; font-size: .8rem;
    }
    .score-card .overall { font-size: 1.6rem; font-weight: 800; margin: .3rem 0; }
    .xp-bar { height: 6px; background: #dbeafe; border-radius: 3px; margin: .5rem 0 .25rem; }
    .xp-bar .fill { height: 100%; background: #3b82f6; border-radius: 3px; transition: width .4s; }
    .xp-hint { font-size: .78rem; color: #64748b; }

    .section-label { font-size: .8rem; font-weight: 600; color: #94a3b8; text-transform: uppercase; letter-spacing: .05em; margin: .75rem 0 .5rem; }
    .organ-grid { display: grid; grid-template-columns: 1fr 1fr; gap: .5rem; }
    .organ-card {
      border: 1px solid #e2e8f0; border-radius: 8px; padding: .75rem;
      cursor: pointer; transition: border-color .15s, box-shadow .15s;
      background: #fff;
    }
    .organ-card:hover { border-color: #93c5fd; box-shadow: 0 1px 6px rgba(59,130,246,.12); }
    .organ-card.selected { border-color: #3b82f6; box-shadow: 0 0 0 2px rgba(59,130,246,.2); }
    .organ-card .row { display: flex; justify-content: space-between; align-items: center; margin-bottom: .3rem; }
    .organ-card .name { font-size: .82rem; font-weight: 600; }
    .organ-card .score { font-size: 1.1rem; font-weight: 700; }
    .organ-card .meta { font-size: .72rem; color: #94a3b8; }
    .badge {
      font-size: .7rem; padding: .1rem .45rem; border-radius: 20px; font-weight: 500;
    }
    .badge-optimal  { background: #dcfce7; color: #166534; }
    .badge-good     { background: #f1f5f9; color: #475569; }
    .badge-at-risk  { background: #fef9c3; color: #854d0e; }
    .badge-critical { background: #fee2e2; color: #991b1b; }

    /* Bottom stats */
    .stats-bar {
      display: flex; gap: 1.5rem; padding: .6rem 1.25rem;
      border-top: 1px solid #e2e8f0; background: #fff;
      font-size: .8rem; color: #64748b; flex-shrink: 0;
    }

    /* Right column */
    .right { flex: 1; display: flex; flex-direction: column; overflow: hidden; background: #f8fafc; }
    .right-header {
      display: flex; align-items: center; gap: .75rem;
      padding: .75rem 1.25rem; border-bottom: 1px solid #e2e8f0;
      background: #fff; flex-shrink: 0; font-weight: 600;
    }
    .right-header .loading { font-size: .8rem; color: #94a3b8; font-weight: normal; }
    .organ-iframe { flex: 1; border: none; width: 100%; }
    .placeholder {
      flex: 1; display: flex; align-items: center; justify-content: center;
      color: #94a3b8; font-size: 1rem;
    }
    #loading-spinner { display: none; }
  </style>
</head>
<body>
  <nav>
    <span class="logo">⚕️ HealthQuest</span>
    <span class="patient-badge" id="patient-label">—</span>
    <div class="nav-links">
      <a id="nav-agent" href="#">🤖 Agent Dashboard</a>
      <a id="nav-goals" href="#">🎯 Goals</a>
    </div>
  </nav>

  <div class="layout">
    <div class="left" id="left-col">
      <div class="score-card" id="score-card">
        <div class="rank-row">
          <span class="rank-name" id="rank-name">Loading…</span>
          <span class="level-badge" id="level-badge">—</span>
        </div>
        <div class="overall" id="overall-score">—</div>
        <div class="xp-bar"><div class="fill" id="xp-fill" style="width:0%"></div></div>
        <div class="xp-hint" id="xp-hint"></div>
      </div>
      <div class="section-label">Organ Systems</div>
      <div class="organ-grid" id="organ-grid">
        <div style="grid-column:1/-1;color:#94a3b8;font-size:.85rem;padding:.5rem 0">Loading…</div>
      </div>
    </div>

    <div class="right">
      <div class="right-header" id="right-header">
        <span id="panel-title">Select an organ</span>
        <span class="loading" id="panel-loading" style="display:none">loading…</span>
      </div>
      <div class="placeholder" id="placeholder">← Select an organ to drill in</div>
      <iframe class="organ-iframe" id="organ-iframe" style="display:none"></iframe>
    </div>
  </div>

  <div class="stats-bar" id="stats-bar">
    <span id="stat-total">—</span>
    <span id="stat-flagged">—</span>
    <span id="stat-ok">—</span>
  </div>

  <script type="module">
    import { getUrlParam, loadIntoIframe, fetchDashboardData } from "./mcp-client.js";

    const patientId = getUrlParam("patient");
    if (!patientId) { window.location.href = "index.html"; }

    document.getElementById("patient-label").textContent = "Patient: " + patientId;
    document.getElementById("nav-agent").href = "agent.html?patient=" + encodeURIComponent(patientId);
    document.getElementById("nav-goals").href  = "goals.html?patient="  + encodeURIComponent(patientId);

    const RANK_BADGE = {
      "Optimal": "badge-optimal",
      "Good": "badge-good",
      "At Risk": "badge-at-risk",
      "Critical": "badge-critical",
    };

    let selectedOrgan = null;

    function selectOrgan(organ, iframeEl) {
      selectedOrgan = organ;
      document.querySelectorAll(".organ-card").forEach(c => c.classList.remove("selected"));
      document.querySelector(`[data-organ="${organ}"]`)?.classList.add("selected");

      document.getElementById("panel-title").textContent = organ.charAt(0).toUpperCase() + organ.slice(1);
      document.getElementById("panel-loading").style.display = "inline";
      document.getElementById("placeholder").style.display = "none";
      iframeEl.style.display = "block";

      loadIntoIframe(iframeEl, "show_organ_panel", { patient_id: patientId, organ });

      iframeEl.onload = () => {
        document.getElementById("panel-loading").style.display = "none";
      };
    }

    async function init() {
      let data;
      try {
        data = await fetchDashboardData(patientId);
      } catch (e) {
        document.getElementById("organ-grid").innerHTML =
          `<div style="grid-column:1/-1;color:#ef4444">Error loading data: ${e.message}</div>`;
        return;
      }

      // Score card
      document.getElementById("rank-name").textContent = data.rank_emoji + " " + data.rank + " Health Champion";
      document.getElementById("level-badge").textContent = "Level " + data.level;
      document.getElementById("overall-score").textContent = "Overall Score: " + data.overall + "/1000";
      const xpPct = data.xp_total > 0 ? Math.min(100, ((data.xp_total % 50) / 50) * 100) : 0;
      document.getElementById("xp-fill").style.width = xpPct + "%";
      document.getElementById("xp-hint").textContent = data.xp_to_next + " XP to next level";

      // Stats bar
      document.getElementById("stat-total").textContent   = "📊 " + data.total_params   + " parameters";
      document.getElementById("stat-flagged").textContent = "🚩 " + data.total_flagged   + " flagged";
      document.getElementById("stat-ok").textContent      = "✅ " + (data.total_params - data.total_flagged) + " in range";

      // Organ grid
      const grid = document.getElementById("organ-grid");
      const iframe = document.getElementById("organ-iframe");
      grid.innerHTML = "";
      if (data.organs.length === 0) {
        grid.innerHTML = '<div style="grid-column:1/-1;color:#94a3b8">No organ data found.</div>';
        return;
      }
      for (const s of data.organs) {
        const card = document.createElement("div");
        card.className = "organ-card";
        card.dataset.organ = s.organ;
        const badgeCls = RANK_BADGE[s.rank] ?? "badge-good";
        card.innerHTML = `
          <div class="row">
            <span class="name">${s.emoji} ${s.organ.charAt(0).toUpperCase() + s.organ.slice(1)}</span>
            <span class="badge ${badgeCls}">${s.rank}</span>
          </div>
          <div class="score">${s.score}/100</div>
          <div class="meta">${s.flagged_count} flagged / ${s.parameter_count} total</div>`;
        card.addEventListener("click", () => selectOrgan(s.organ, iframe));
        grid.appendChild(card);
      }

      // Restore organ from URL hash
      const hash = new URLSearchParams(window.location.hash.slice(1));
      const savedOrgan = hash.get("organ");
      if (savedOrgan && data.organs.find(s => s.organ === savedOrgan)) {
        selectOrgan(savedOrgan, iframe);
      }
    }

    init();
  </script>
</body>
</html>
```

- [ ] **Step 2: Smoke-test in browser**

With the server running and a seeded patient (run `python seed.py` to get a patient ID), open `http://127.0.0.1:8000/ui/dashboard.html?patient=<id>`. Verify:
- Score card shows rank/level/XP
- Organ grid renders with cards
- Clicking an organ card loads the organ panel in the right iframe
- Nav links carry the patient ID

- [ ] **Step 3: Commit**

```bash
git add ui/dashboard.html
git commit -m "feat: add dashboard.html with native organ grid and organ panel iframe"
```

---

## Task 6: Create `ui/agent.html`

**Files:**
- Create: `ui/agent.html`

- [ ] **Step 1: Write `ui/agent.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>HealthQuest — Agent Dashboard</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: system-ui, sans-serif; background: #f8fafc; height: 100vh; display: flex; flex-direction: column; overflow: hidden; }

    nav {
      display: flex; align-items: center; gap: 1rem;
      padding: .75rem 1.25rem; background: #fff;
      border-bottom: 1px solid #e2e8f0; flex-shrink: 0;
    }
    nav a { color: #475569; text-decoration: none; font-size: .9rem; }
    nav a:hover { color: #3b82f6; }
    nav .title { font-weight: 700; font-size: 1.05rem; flex: 1; text-align: center; }
    nav .patient-badge {
      background: #eff6ff; color: #1d4ed8;
      border: 1px solid #bfdbfe; border-radius: 20px;
      padding: .2rem .75rem; font-size: .85rem;
    }

    .control-bar {
      display: flex; gap: .75rem; align-items: center;
      padding: .75rem 1.25rem; background: #fff;
      border-bottom: 1px solid #e2e8f0; flex-shrink: 0;
    }
    .control-bar input {
      flex: 1; padding: .55rem .9rem;
      border: 1px solid #cbd5e1; border-radius: 6px;
      font-size: .95rem; outline: none;
    }
    .control-bar input:focus { border-color: #3b82f6; }
    .control-bar button {
      padding: .55rem 1.2rem; background: #3b82f6; color: #fff;
      border: none; border-radius: 6px; cursor: pointer; font-weight: 500; white-space: nowrap;
    }
    .control-bar button:disabled { background: #93c5fd; cursor: not-allowed; }
    .control-bar button:not(:disabled):hover { background: #2563eb; }
    .estimate { font-size: .8rem; color: #94a3b8; white-space: nowrap; }

    .progress-bar {
      height: 3px; background: #dbeafe; flex-shrink: 0;
      display: none;
    }
    .progress-bar .fill {
      height: 100%; background: #3b82f6;
      border-radius: 2px;
      animation: progress-pulse 1.8s ease-in-out infinite;
    }
    @keyframes progress-pulse {
      0%   { width: 10%; }
      50%  { width: 80%; }
      100% { width: 10%; }
    }

    .main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
    .empty-state {
      flex: 1; display: flex; align-items: center; justify-content: center;
      color: #94a3b8; font-size: 1rem;
    }
    iframe { flex: 1; border: none; width: 100%; display: none; }
  </style>
</head>
<body>
  <nav>
    <a id="back-link" href="#">← Dashboard</a>
    <span class="title">🤖 Agent Dashboard</span>
    <span class="patient-badge" id="patient-label">—</span>
  </nav>

  <div class="control-bar">
    <input id="context-input" type="text" placeholder="Optional focus (e.g. 'focus on cardiovascular risk')">
    <button id="run-btn">▶ Run Agent</button>
    <span class="estimate">~30–60s · full analysis</span>
  </div>

  <div class="progress-bar" id="progress-bar"><div class="fill"></div></div>

  <div class="main">
    <div class="empty-state" id="empty-state">Hit ▶ Run Agent to start a full health analysis.</div>
    <iframe id="agent-iframe"></iframe>
  </div>

  <script type="module">
    import { getUrlParam, loadIntoIframe } from "./mcp-client.js";

    const patientId = getUrlParam("patient");
    if (!patientId) { window.location.href = "index.html"; }

    document.getElementById("patient-label").textContent = "Patient: " + patientId;
    document.getElementById("back-link").href = "dashboard.html?patient=" + encodeURIComponent(patientId);

    const runBtn    = document.getElementById("run-btn");
    const iframe    = document.getElementById("agent-iframe");
    const progress  = document.getElementById("progress-bar");
    const emptyState = document.getElementById("empty-state");

    runBtn.addEventListener("click", () => {
      const context = document.getElementById("context-input").value.trim();
      runBtn.disabled = true;
      progress.style.display = "block";
      emptyState.style.display = "none";
      iframe.style.display = "none";

      loadIntoIframe(iframe, "run_health_agent", { patient_id: patientId, context });

      iframe.onload = () => {
        progress.style.display = "none";
        iframe.style.display = "block";
        runBtn.disabled = false;
      };
    });
  </script>
</body>
</html>
```

- [ ] **Step 2: Smoke-test in browser**

Open `http://127.0.0.1:8000/ui/agent.html?patient=<id>`. Verify:
- Page renders with empty state
- Clicking Run Agent shows the progress bar and disables the button
- After ~30-60s the agent result iframe appears

- [ ] **Step 3: Commit**

```bash
git add ui/agent.html
git commit -m "feat: add agent.html full-screen agent runner"
```

---

## Task 7: Create `ui/goals.html`

**Files:**
- Create: `ui/goals.html`

**Note:** `show_goal_view` and `build_goal_plan` MCP tools are not yet implemented in the backend. This page is built to spec — it will display an error state from the `/render` endpoint until those tools exist.

- [ ] **Step 1: Write `ui/goals.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>HealthQuest — Goals</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: system-ui, sans-serif; background: #f8fafc; display: flex; flex-direction: column; min-height: 100vh; }

    nav {
      display: flex; align-items: center; gap: 1rem;
      padding: .75rem 1.25rem; background: #fff;
      border-bottom: 1px solid #e2e8f0;
    }
    nav a { color: #475569; text-decoration: none; font-size: .9rem; }
    nav a:hover { color: #3b82f6; }
    nav .title { font-weight: 700; font-size: 1.05rem; flex: 1; text-align: center; }
    nav .patient-badge {
      background: #eff6ff; color: #1d4ed8;
      border: 1px solid #bfdbfe; border-radius: 20px;
      padding: .2rem .75rem; font-size: .85rem;
    }

    .goal-bar {
      position: sticky; top: 0; z-index: 10;
      display: flex; gap: .75rem; align-items: center;
      padding: .75rem 1.25rem; background: #fff;
      border-bottom: 1px solid #e2e8f0;
    }
    .goal-bar input {
      flex: 1; padding: .55rem .9rem;
      border: 1px solid #cbd5e1; border-radius: 6px;
      font-size: .95rem; outline: none;
    }
    .goal-bar input:focus { border-color: #3b82f6; }
    .goal-bar button {
      padding: .55rem 1.2rem; background: #3b82f6; color: #fff;
      border: none; border-radius: 6px; cursor: pointer; font-weight: 500; white-space: nowrap;
    }
    .goal-bar button:disabled { background: #93c5fd; cursor: not-allowed; }
    .goal-bar button:not(:disabled):hover { background: #2563eb; }

    .content { max-width: 860px; margin: 0 auto; padding: 1.5rem 1.25rem; width: 100%; }

    .section { margin-bottom: 1.5rem; }
    .section-title {
      font-size: .9rem; font-weight: 600; color: #475569;
      text-transform: uppercase; letter-spacing: .05em;
      margin-bottom: .75rem;
    }
    iframe {
      width: 100%; border: 1px solid #e2e8f0; border-radius: 8px;
      min-height: 320px; display: block;
    }

    #plan-trigger { display: none; margin-top: .5rem; }
    #plan-trigger button {
      padding: .55rem 1.4rem; background: #059669; color: #fff;
      border: none; border-radius: 6px; cursor: pointer; font-weight: 500;
    }
    #plan-trigger button:hover { background: #047857; }
    #plan-section { display: none; }
  </style>
</head>
<body>
  <nav>
    <a id="back-link" href="#">← Dashboard</a>
    <span class="title">🎯 Goals</span>
    <span class="patient-badge" id="patient-label">—</span>
  </nav>

  <div class="goal-bar">
    <input id="goal-input" type="text" placeholder="e.g. Run a marathon in 6 months">
    <button id="analyse-btn">Analyse Goal</button>
  </div>

  <div class="content">
    <div class="section" id="readiness-section" style="display:none">
      <div class="section-title">Goal Readiness</div>
      <iframe id="readiness-iframe" title="Goal readiness"></iframe>
    </div>

    <div id="plan-trigger">
      <button id="plan-btn">📋 Build Training Plan</button>
    </div>

    <div class="section" id="plan-section">
      <div class="section-title">Training Plan</div>
      <iframe id="plan-iframe" title="Training plan"></iframe>
    </div>
  </div>

  <script type="module">
    import { getUrlParam, loadIntoIframe } from "./mcp-client.js";

    const patientId = getUrlParam("patient");
    if (!patientId) { window.location.href = "index.html"; }

    document.getElementById("patient-label").textContent = "Patient: " + patientId;
    document.getElementById("back-link").href = "dashboard.html?patient=" + encodeURIComponent(patientId);

    const analyseBtn       = document.getElementById("analyse-btn");
    const readinessSection = document.getElementById("readiness-section");
    const readinessIframe  = document.getElementById("readiness-iframe");
    const planTrigger      = document.getElementById("plan-trigger");
    const planSection      = document.getElementById("plan-section");
    const planIframe       = document.getElementById("plan-iframe");

    analyseBtn.addEventListener("click", () => {
      const goal = document.getElementById("goal-input").value.trim();
      if (!goal) return;

      analyseBtn.disabled = true;
      planTrigger.style.display  = "none";
      planSection.style.display  = "none";
      readinessSection.style.display = "block";

      loadIntoIframe(readinessIframe, "show_goal_view", { patient_id: patientId, goal });

      readinessIframe.onload = () => {
        analyseBtn.disabled = false;
        planTrigger.style.display = "block";
      };
    });

    document.getElementById("plan-btn").addEventListener("click", () => {
      const goal = document.getElementById("goal-input").value.trim();
      if (!goal) return;
      planSection.style.display = "block";
      loadIntoIframe(planIframe, "build_goal_plan", { patient_id: patientId, goal });
    });
  </script>
</body>
</html>
```

- [ ] **Step 2: Smoke-test in browser**

Open `http://127.0.0.1:8000/ui/goals.html?patient=<id>`. Verify:
- Page renders with sticky goal input bar
- Clicking Analyse Goal with empty input does nothing (no submit)
- Clicking with a goal shows the readiness iframe section
- After that loads, "Build Training Plan" button appears (the iframe may show an error since `show_goal_view` isn't implemented yet — that is expected)

- [ ] **Step 3: Commit**

```bash
git add ui/goals.html
git commit -m "feat: add goals.html with goal readiness and training plan sections"
```

---

## Self-Review Notes

**Spec coverage check:**
- ✅ `server.py`: `mcp.http_app()` + StaticFiles + uvicorn + `webbrowser.open`
- ✅ `app-bridge.js` served at `/js/app-bridge.js` via `_fetch_app_bridge_bundle_sync` (private API, Option A)
- ✅ `/ui-resource` proxy (required by `_HOST_HTML_TEMPLATE`'s `frameUrl`)
- ✅ `/render` dynamic host-page (replaces spec's `loadIntoIframe` iframe-via-postMessage complexity)
- ✅ `get_dashboard_data` MCP tool + `get_dashboard_json` helper
- ✅ `index.html`, `dashboard.html`, `agent.html`, `goals.html`, `mcp-client.js`
- ✅ Organ grid is native HTML (clickable, not an iframe)
- ✅ Overall score card with rank/level/XP/progress bar
- ✅ Bottom stats bar (total params, flagged, in range)
- ✅ Nav links carry `?patient=<id>`
- ⚠️ `show_goal_view` and `build_goal_plan` backend tools are not part of this spec — goals.html built to spec, will show error until those tools are added

**Deviation from spec's `mcp-client.js` API:** The spec names `callTool(name, args)` but this plan uses `fetchDashboardData(patientId)` (a direct REST call) because the generic `callTool` would require the full MCP SDK in the browser. `loadIntoIframe` and `getUrlParam` are implemented exactly as specified. The REST endpoint `/api/dashboard/{patient_id}` provides the same data with less complexity.
