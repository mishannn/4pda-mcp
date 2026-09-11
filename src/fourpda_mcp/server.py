"""MCP server: 4PDA lofi forum tools (stdio and streamable HTTP transports).

HTTP mode (``4pda-mcp --http``) serves stateless JSON-mode MCP at ``/mcp``.
Set ``FOURPDA_API_KEY`` to require ``Authorization: Bearer <key>`` on every
request; without it the HTTP endpoint is unauthenticated.
"""
from __future__ import annotations

import contextlib
import hmac
import json
import os

import mcp.types as types
from mcp.server.lowlevel import Server

from . import forum

server = Server("4pda-mcp")

API_KEY = os.environ.get("FOURPDA_API_KEY", "").strip() or None


class _BearerAuthMiddleware:
    """ASGI middleware: reject requests whose bearer token is not the env key.

    Installed only when FOURPDA_API_KEY is set; stdio is trusted as before.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                   for k, v in scope.get("headers", [])}
        auth = headers.get("authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else None
        if token is None or not hmac.compare_digest(token.encode(), API_KEY.encode()):
            await self._unauthorized(send)
            return
        await self.app(scope, receive, send)

    @staticmethod
    async def _unauthorized(send):
        body = json.dumps({
            "jsonrpc": "2.0", "id": None, "error": {
                "code": -32000, "message": "Unauthorized: missing or invalid bearer token.",
            },
        }).encode()
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"www-authenticate", b'Bearer realm="4pda-mcp"'),
            ],
        })
        await send({"type": "http.response.body", "body": body})


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


def _serve_http(host: str, port: int) -> None:
    import uvicorn
    from starlette.applications import Starlette
    from starlette.routing import Route
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    manager = StreamableHTTPSessionManager(
        app=server, json_response=True, stateless=True,
    )

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with manager.run():
            yield

    class McpEndpoint:
        async def __call__(self, scope, receive, send):
            await manager.handle_request(scope, receive, send)

    endpoint = McpEndpoint()
    if API_KEY:
        endpoint = _BearerAuthMiddleware(endpoint)  # type: ignore[assignment]

    app = Starlette(
        routes=[Route("/mcp", endpoint=endpoint, methods=["GET", "POST", "PUT", "DELETE"])],
        lifespan=lifespan,
    )

    config = uvicorn.Config(app, host=host, port=port, lifespan="on")
    uvicorn.Server(config).run()


def main() -> None:
    import argparse
    import asyncio
    from mcp.server.stdio import stdio_server

    parser = argparse.ArgumentParser(
        prog="4pda-mcp",
        description="4PDA lofi MCP server. Default transport is stdio; pass --http for streamable HTTP.",
    )
    parser.add_argument("--http", action="store_true",
                        help="serve via streamable HTTP instead of stdio")
    parser.add_argument("--host", default="127.0.0.1",
                        help="HTTP bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000,
                        help="HTTP bind port (default: 8000)")
    args = parser.parse_args()

    if args.http:
        _serve_http(args.host, args.port)
        return

    async def run():
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(run())


if __name__ == "__main__":
    main()