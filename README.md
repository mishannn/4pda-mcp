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

## Rate limiting

4PDA fronts the lofi endpoint with Cloudflare; it is uncached, so every request
hits origin and Cloudflare rate-limits it. The limit is not published; measured
empirically (Aug 2026):

| Request rate            | Result                                   |
| ---------------------- | ---------------------------------------- |
| 1 req / 2s             | clean (10/10)                            |
| 1 req / s              | clean (20/20)                            |
| 2 req / s (0.5s gap)   | clean (30/30)                            |
| 5 req / s (0.2s gap)   | **429 on ~20th request, `Retry-After: 3600` (1h block)** |

The server stays well below the trip point by enforcing a minimum interval
between requests (`FOURPDA_MIN_INTERVAL`, default `1.0` — i.e. 1 req/s, a 2x
margin under the confirmed-safe 2 req/s). If a 429 still occurs, the server
records the `Retry-After` cooldown and, **without sending further requests**,
returns a structured `rate_limited` payload from every tool call:

```json
{"rate_limited": true, "retry_after_seconds": 3600,
 "retry_at_utc": "2026-08-24T23:00:00Z",
 "hint": "4PDA is rate-limiting requests. Retry after 3600s."}
```

This is returned as a normal (non-error) result, so the agent can read
`retry_after_seconds` and wait rather than hammering a blocked endpoint. The
cooldown is capped at one hour so an anomalous `Retry-After` can't freeze the
process.