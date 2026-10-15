"""How agents reach tools (task B3). Every call goes through a Toolbox and lands in the ToolCallLog,
so the same transcript exists whether the agents run in-process or over a real MCP connection.

    LocalToolbox   direct calls into the tool modules (fast; what most tests use)
    McpToolbox     a real in-process MCP client talking to mcp_server.server.build(...)

Both return the tool's payload (dict, or list for list-valued tools). Failures are the contract
{"error": {...}} payload, never an exception, so a policy can branch on `"error" in result`.
"""
import asyncio
import concurrent.futures
import json
import threading

# tools whose signature takes the calling agent
AGENT_TOOLS = {"remember", "recall", "act", "observe", "begin_turn"}
# tools that return a list (MCP delivers one content item per element; empty list = no content)
LIST_TOOLS = {"recall", "recall_list", "list_remediations"}


# wall-clock values: real, but not part of the deterministic transcript
VOLATILE_KEYS = {"latency_ms", "executed_at", "profile"}   # profile: GRAPH.PROFILE timings (A6)


def _scrub(x):
    if isinstance(x, dict):
        return {k: _scrub(v) for k, v in x.items() if k not in VOLATILE_KEYS}
    if isinstance(x, list):
        return [_scrub(v) for v in x]
    return x


class ToolCallLog:
    """Deterministic transcript: sequence numbers, no wall clock."""

    def __init__(self):
        self.entries = []

    def add(self, agent, tool, args, result):
        result = _scrub(result)
        e = {"seq": len(self.entries) + 1, "agent": agent, "tool": tool, "args": args, "result": result}
        self.entries.append(e)
        return e

    def by_agent(self, agent):
        return [e for e in self.entries if e["agent"] == agent]

    def tools_used(self, agent=None):
        return [e["tool"] for e in self.entries if agent is None or e["agent"] == agent]

    def to_jsonl(self):
        return "\n".join(json.dumps(e, sort_keys=True, default=str) for e in self.entries)

    def render(self, width=110):
        out = []
        for e in self.entries:
            r = e["result"]
            if isinstance(r, dict) and "error" in r:
                brief = f"ERROR {r['error']['code']}: {r['error']['message']}"
            else:
                brief = json.dumps(r, default=str)
            args = json.dumps(e["args"], default=str)
            line = f"{e['seq']:>3} {e['agent']:<10} {e['tool']:<10} {args} -> {brief}"
            out.append(line if len(line) <= width * 2 else line[: width * 2 - 1] + "…")
        return "\n".join(out)


class _Base:
    def __init__(self, log=None):
        self.log = log or ToolCallLog()

    def call(self, agent, tool, args):
        args = dict(args)
        if tool in AGENT_TOOLS:
            args.setdefault("agent", agent)
        result = self._invoke(tool, args)
        self.log.add(agent, tool, {k: v for k, v in args.items() if k != "agent"}, result)
        return result


class LocalToolbox(_Base):
    def __init__(self, graph, memory, actions, executor=None, log=None):
        super().__init__(log)
        from gate import tools as gate_tools
        from mcp_server import tools_memory, tools_retract
        tools_memory.configure(memory)
        gate_tools.configure(actions)
        tools_retract.configure(graph, executor)
        self._fns = {n: getattr(tools_memory, n) for n in
                     ("remember", "recall", "fragility", "observe", "begin_turn")}
        self._fns["act"] = gate_tools.act
        for n in ("distrust", "reinstate", "why", "recall_list", "list_remediations",
                  "approve_remediation", "reject_remediation"):
            self._fns[n] = getattr(tools_retract, n)

    def _invoke(self, tool, args):
        if tool not in self._fns:
            return {"error": {"code": "NOT_FOUND", "message": f"unknown tool {tool!r}", "details": {}}}
        try:
            return self._fns[tool](**args)
        except TypeError as e:  # wrong arguments from a brain: report, do not crash the loop
            return {"error": {"code": "INVALID_ARGUMENT", "message": str(e), "details": {"tool": tool}}}


class McpToolbox(_Base):
    """One long-lived in-process MCP client on a background event loop (the client's task group
    must be entered and exited from the same task, so all calls are served by one coroutine)."""

    def __init__(self, server, log=None):
        super().__init__(log)
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._startup_error = None
        self._thread = threading.Thread(target=self._run, args=(server,), daemon=True)
        self._thread.start()
        self._ready.wait(timeout=30)
        if self._startup_error:
            raise self._startup_error

    def _run(self, server):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._main(server))

    async def _main(self, server):
        from mcp.client.client import Client
        self._queue = asyncio.Queue()
        try:
            async with Client(server) as client:
                self._ready.set()
                while True:
                    item = await self._queue.get()
                    if item is None:
                        return
                    tool, args, fut = item
                    try:
                        fut.set_result(await client.call_tool(tool, args))
                    except Exception as e:  # noqa: BLE001
                        fut.set_exception(e)
        except Exception as e:  # noqa: BLE001
            self._startup_error = e
            self._ready.set()

    def _invoke(self, tool, args):
        fut = concurrent.futures.Future()
        self._loop.call_soon_threadsafe(self._queue.put_nowait, (tool, args, fut))
        try:
            res = fut.result(timeout=120)
        except Exception as e:  # noqa: BLE001
            return {"error": {"code": "TOOL_ERROR", "message": str(e), "details": {"tool": tool}}}
        items = []
        for c in res.content:
            try:
                items.append(json.loads(c.text))
            except ValueError:
                items.append({"error": {"code": "TOOL_ERROR", "message": c.text, "details": {"tool": tool}}})
        if tool in LIST_TOOLS and not (items and isinstance(items[0], dict) and "error" in items[0]):
            return items
        return items[0] if items else {}

    def close(self):
        self._loop.call_soon_threadsafe(self._queue.put_nowait, None)
        self._thread.join(timeout=10)
