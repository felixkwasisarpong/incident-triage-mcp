from __future__ import annotations

import os
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Incident Triage MCP", json_response=True)

@mcp.tool()
def ping(message: str = "hello") -> dict:
    return {"ok": True, "message": message}

def main() -> None:
    # stdio by default; for HTTP:
    # MCP_TRANSPORT=streamable-http python -m incident_triage_mcp.server
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    mcp.run(transport=transport)

if __name__ == "__main__":
    main()