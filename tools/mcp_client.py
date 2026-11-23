"""Kleiner MCP-Testclient: startet den Server per stdio und ruft ein Tool auf.
Nutzung: uv run python tools/mcp_client.py [tool] ['{"arg": 1}']"""
import asyncio, json, sys, os
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    params = StdioServerParameters(command="uv", args=["run", "--directory", os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ki-bridge"], env=dict(os.environ))
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            if len(sys.argv) < 2:
                tools = await s.list_tools()
                for t in tools.tools:
                    print("-", t.name)
                return
            args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
            res = await s.call_tool(sys.argv[1], args)
            for c in res.content:
                print(getattr(c, "text", c))
asyncio.run(main())
