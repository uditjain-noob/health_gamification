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
    mcp.run()
