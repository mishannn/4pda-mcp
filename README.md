# 4PDA MCP

MCP server exposing the [4PDA](https://4pda.to) forum **lofi (text) version** without a
browser. Uses [`impit`](https://github.com/zimmski/impit) to pass Cloudflare's TLS
challenge.

## Why lofi?

The lofi/text version is ~50x smaller than the full page and has stable, simple
markup — ideal for LLM consumption. The full version (`?act=idx`, `?showforum=`,
`?showtopic=`) is JS-heavy and Cloudflare-gated.

## URL conventions (discovered)

4PDA changed the lofi entry. `lofiversion/index.php?index.html` now 404s. The
live format is:

- `lofiversion/index.php?f{forum_id}.html` — a forum page (subforums + topics list)
- `lofiversion/index.php?t{topic_id}.html` — topic page 1
- `lofiversion/index.php?t{topic_id}-{offset}.html` — topic page N, step **20**
- `index.php?act=idx` — full index, used only to enumerate top categories

The pinned header post repeats on every topic page; this server drops it on page ≥ 2.

## Tools

- `list_forums(forum_id?)` — top categories when `forum_id` omitted, else the subforums
  (and topics summary) of a forum as a flat list. Returns a tree the client can nest.
- `list_topics(forum_id)` — topics in a forum: id, title, replies, is_important.
- `list_posts(topic_id, page=1)` — posts on a page: author, date, html (with internal
  links rewritten to lofi where possible). Header post dropped on page ≥ 2.

## Run

```bash
pip install -e .
4pda-mcp            # stdio MCP server
# or: mcp run src/fourpda_mcp/server.py
```

No browser, no auth needed (read-only public content). impit impersonates Chrome to
clear Cloudflare.