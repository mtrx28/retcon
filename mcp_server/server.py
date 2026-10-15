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
    executor = _executor_from_env()
    tools_retract.configure(g, executor)
    for fn in (tools_retract.distrust, tools_retract.reinstate, tools_retract.why, tools_retract.recall_list,
               tools_retract.list_remediations, tools_retract.approve_remediation,
               tools_retract.reject_remediation, tools_retract.keystones, tools_retract.contradictions):
        server.add_tool(fn)
    _register_memory_tools(server, g, executor)
    return server


def _executor_from_env():
    """RETCON_SANDBOX_URL (e.g. http://127.0.0.1:8100, `python tasks.py sandbox`) lets approved
    compensations and released actions reach the sandbox bank/inbox. Unset: none."""
    url = os.getenv("RETCON_SANDBOX_URL")
    if not url:
        return None
    from gate.executors import HttpExecutor
    return HttpExecutor(url)


def _register_memory_tools(server, g, executor=None):
    """Lane B tools, only if their dependencies are importable and RETCON_MEMORY != 0."""
    if os.getenv("RETCON_MEMORY", "1") == "0":
        return
    try:
        from core.memory import MemoryService
        from core.retrieve.embed import get_embedder
        from mcp_server import tools_memory
    except ImportError:
        return
    memory = MemoryService(g, get_embedder())
    tools_memory.configure(memory)
    for name in ("remember", "recall", "fragility", "observe", "begin_turn"):
        fn = getattr(tools_memory, name, None)
        if fn is not None:
            server.add_tool(fn)
    # `act` lives in gate/ (Lane A) and shares the memory service's premise capture, so an action
    # is justified by what the agent recalled. Lane B's fragility, once present, feeds the gate.
    from core.actions import ActionService
    from gate import tools as gate_tools
    gate_tools.configure(ActionService(g, memory.capture, executor=executor,
                                       fragility_fn=getattr(tools_memory, "fragility", None)))
    server.add_tool(gate_tools.act)


if __name__ == "__main__":
    build().run("stdio")
