"""RETCON MCP server (stdio). One process per tenant graph.

    python -m mcp_server.server            # tenant from RETCON_TENANT (default northwind)

Registers Lane A's tools (distrust, reinstate, why, recall_list) always, and Lane B's memory
tools (remember, recall) when a MemoryService can be built. Tool modules are looked up lazily so
either lane can land first. Claude Code config snippet: docs/MCP_CLIENT.md (task A13).
"""
import os

from mcp.server.mcpserver import MCPServer

from core.db import tenant_graph
from mcp_server import tools_retract


def build(graph=None, tenant=None) -> MCPServer:
    g = graph if graph is not None else tenant_graph(tenant)
    server = MCPServer("retcon")
    tools_retract.configure(g)
    for fn in (tools_retract.distrust, tools_retract.reinstate, tools_retract.why, tools_retract.recall_list):
        server.add_tool(fn)
    _register_memory_tools(server, g)
    return server


def _register_memory_tools(server, g):
    """Lane B tools, only if their dependencies are importable and RETCON_MEMORY != 0."""
    if os.getenv("RETCON_MEMORY", "1") == "0":
        return
    try:
        from core.memory import MemoryService
        from core.retrieve.embed import get_embedder
        from mcp_server import tools_memory
    except ImportError:
        return
    tools_memory.configure(MemoryService(g, get_embedder()))
    for name in ("remember", "recall", "act", "fragility"):
        fn = getattr(tools_memory, name, None)
        if fn is not None:
            server.add_tool(fn)


if __name__ == "__main__":
    build().run("stdio")
