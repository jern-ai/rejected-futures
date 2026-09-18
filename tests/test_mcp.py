"""The MCP server answers a real stdio client: list tools, record, recall, retire."""
import asyncio
import os
import sys
import tempfile


def test_mcp_roundtrip():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    home = tempfile.mkdtemp()
    env = dict(os.environ, RF_HOME=home)

    async def go():
        params = StdioServerParameters(command=sys.executable, args=["-m", "rejected_futures.mcp_server"], env=env, cwd=tempfile.mkdtemp())
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                names = {t.name for t in (await s.list_tools()).tools}
                assert {"recall", "record", "candidates", "resolve", "claims", "retire"} <= names
                out = await s.call_tool("record", dict(statement="Temperatures keep two decimals; never round to integers.",
                                                       kind="invariant", scope="personal", quote="two decimals"))
                text = out.content[0].text
                assert text.startswith("recorded ")
                cid = text.split()[1]
                out = await s.call_tool("recall", dict(query="round the temperature readings to whole numbers"))
                assert "two decimals" in out.content[0].text and cid in out.content[0].text
                out = await s.call_tool("retire", dict(claim_id=cid))
                assert "retired" in out.content[0].text
                out = await s.call_tool("recall", dict(query="round the temperature readings"))
                assert "No claims" in out.content[0].text
                out = await s.call_tool("candidates", dict())
                assert "No open candidates" in out.content[0].text

    asyncio.run(go())
