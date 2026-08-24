"""MCP server: 4PDA lofi forum tools (stdio transport)."""
from __future__ import annotations

import json

import mcp.types as types
from mcp.server.lowlevel import Server

from . import forum

server = Server("4pda-mcp")


async def _list_tools(ctx, params):
    return types.ListToolsResult(tools=[
        types.Tool(
            name="list_forums",
            description=(
                "List 4PDA forum categories/subforums. With no forum_id, returns the "
                "top-level categories (the forum tree roots). With a forum_id, returns "
                "that forum's subforums and a summary of its topics. IDs are 4PDA forum IDs.\n\n"
                "On rate limit, returns a 'rate_limited' payload with retry_after_seconds "
                "and retry_at_utc instead of an error — wait that long before calling again."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "forum_id": {
                        "type": "integer",
                        "description": "Forum ID. Omit to list top-level categories.",
                    }
                },
            },
        ),
        types.Tool(
            name="list_topics",
            description=(
                "List topics in a 4PDA forum (lofi version): id, title, reply count, "
                "is_important (pinned/important topics are prefixed with (!) on the site).\n\n"
                "On rate limit, returns a 'rate_limited' payload with retry_after_seconds "
                "and retry_at_utc instead of an error — wait that long before calling again."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "forum_id": {"type": "integer", "description": "4PDA forum ID."},
                },
                "required": ["forum_id"],
            },
        ),
        types.Tool(
            name="list_posts",
            description=(
                "List posts on a page of a 4PDA topic (lofi version), with author, date and "
                "HTML body. Internal links to the full version are rewritten to their lofi "
                "equivalent where one exists. The pinned header post repeats on every page "
                "on the site; it is dropped on page >= 2. Pages are 1-indexed; each page has "
                "20 posts.\n\n"
                "On rate limit, returns a 'rate_limited' payload with retry_after_seconds "
                "and retry_at_utc instead of an error — wait that long before calling again."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "topic_id": {"type": "integer", "description": "4PDA topic ID."},
                    "page": {
                        "type": "integer",
                        "description": "1-indexed page number (default 1).",
                        "default": 1,
                    },
                },
                "required": ["topic_id"],
            },
        ),
    ])


async def _call_tool(ctx, params):
    name = params.name
    args = params.arguments or {}

    try:
        if name == "list_forums":
            fid = args.get("forum_id")
            result = forum.parse_categories() if fid is None else forum.parse_forum(int(fid))
        elif name == "list_topics":
            fid = int(args["forum_id"])
            result = forum.parse_forum(fid)["topics"]
        elif name == "list_posts":
            tid = int(args["topic_id"])
            page = int(args.get("page", 1))
            result = forum.parse_topic(tid, page)
        else:
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=f"Unknown tool: {name}")],
                isError=True,
            )
    except forum.RateLimited as rl:
        # Not an error: tell the agent when to retry instead of hammering.
        payload = forum.cooldown_payload(rl.retry_after)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))],
        )

    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))],
    )


server.add_request_handler("tools/list", types.PaginatedRequestParams, _list_tools)
server.add_request_handler("tools/call", types.CallToolRequestParams, _call_tool)


def main() -> None:
    import asyncio
    from mcp.server.stdio import stdio_server

    async def run():
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(run())


if __name__ == "__main__":
    main()