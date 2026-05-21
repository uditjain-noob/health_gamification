from fastmcp import FastMCP
import config
from core.parser import Parser
from core.organs import OrganMapper

mcp = FastMCP("HealthQuest", instructions="Health gamification server. Start with upload_report.")

# Lazy dependency factories
def get_store():
    return config.get_store()

def get_client():
    return config.get_client()

def get_mapper():
    if not hasattr(get_mapper, "_instance"):
        get_mapper._instance = OrganMapper()
    return get_mapper._instance

def get_parser():
    if not hasattr(get_parser, "_instance"):
        get_parser._instance = Parser(llm_client=get_client())
    return get_parser._instance

# Register all tools
import apps.ingest as ingest_app
import apps.dashboard as dashboard_app
import apps.organ_panel as organ_panel_app
import apps.charts as charts_app
import apps.recommendations as recs_app
import apps.quests as quests_app
import apps.inspector as inspector_app
import apps.query as query_app
import agent.runner as agent_app
import agent.mcp_tools as agent_mcp_app

ingest_app.register(mcp, get_store, get_parser, get_mapper)
dashboard_app.register(mcp, get_store, get_mapper)
organ_panel_app.register(mcp, get_store, get_mapper, get_client)
charts_app.register(mcp, get_store, get_mapper)
recs_app.register(mcp, get_store, get_client)
quests_app.register(mcp, get_store, get_mapper)
inspector_app.register(mcp, get_store, get_mapper)
query_app.register(mcp, get_store, get_mapper)
agent_app.register(mcp, get_store, get_mapper, get_client)
agent_mcp_app.register(mcp, get_store, get_mapper, get_client)

if __name__ == "__main__":
    import json
    import threading
    import time
    import webbrowser
    import uvicorn
    from pathlib import Path
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
        try:
            html = await _read_mcp_resource("http://127.0.0.1:8000/mcp", uri)
        except Exception:
            return Response("Resource fetch error", status_code=502)
        if html is None:
            return Response("Resource not found", status_code=502)
        return HTMLResponse(html)

    async def render_tool(request: Request) -> Response:
        import html as html_mod
        tool_name = request.query_params.get("tool", "")
        args_json = request.query_params.get("args", "{}")
        try:
            tool_args = json.loads(args_json)
        except json.JSONDecodeError:
            tool_args = {}
        tool_name_safe = html_mod.escape(tool_name)
        html_content = _HOST_HTML_TEMPLATE.format(
            tool_name=tool_name_safe,
            import_map_tag=import_map_tag,
            tool_name_json=json.dumps(tool_name),
            tool_args_json=json.dumps(tool_args),
            mcp_sdk_version=_MCP_SDK_VERSION,
        )
        return HTMLResponse(html_content)

    async def api_dashboard(request: Request) -> Response:
        patient_id = request.path_params["patient_id"]
        try:
            store = get_store()
            mapper = get_mapper()
            data = get_dashboard_json(store, mapper, patient_id)
            return JSONResponse(data)
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

    app = mcp.http_app()
    app.add_route("/js/app-bridge.js", serve_bridge)
    app.add_route("/ui-resource", serve_ui_resource)   # must come before /ui mount
    app.add_route("/render", render_tool)
    app.add_route("/api/dashboard/{patient_id}", api_dashboard)
    app.mount("/ui", StaticFiles(directory=Path(__file__).parent / "ui", html=True))

    def _run_server():
        uvicorn.run(app, host="127.0.0.1", port=8000)

    t = threading.Thread(target=_run_server, daemon=False)
    t.start()
    time.sleep(1.5)
    webbrowser.open("http://127.0.0.1:8000/ui/")
    t.join()
