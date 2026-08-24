"""4PDA lofi forum MCP server.

Cloudflare blocks plain HTTP clients; impit (Chrome TLS fingerprint) clears it.
The lofi entry moved off `?index.html` — see README for the live URL format.
"""
from __future__ import annotations

import re
from html import unescape
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import impit

BASE = "https://4pda.to/forum"
LOFI = f"{BASE}/lofiversion/index.php"
FULL_IDX = f"{BASE}/index.php?act=idx"

# Step between lofi topic pages (posts per page).
PAGE_STEP = 20

_client: impit.Client | None = None


def client() -> impit.Client:
    global _client
    if _client is None:
        _client = impit.Client(browser="chrome", follow_redirects=True, timeout=45)
    return _client


def _q(url: str) -> str:
    """Fetch a URL, returning decoded text (impit handles encoding)."""
    r = client().get(url)
    if r.status_code != 200:
        raise RuntimeError(f"4PDA returned {r.status_code} for {url}")
    return r.text


def _strip(text: str) -> str:
    return unescape(text).strip()


# --- link rewriting: push full-version links onto their lofi equivalent ---------
def rewrite_links(html: str) -> str:
    """Rewrite full-version links inside post HTML to lofi where possible.

    showforum=X -> lofi ?fX.html ; showtopic=X -> lofi ?tX.html (page 1, drops
    view= hints which have no lofi equivalent). showuser= / act= left as-is.
    """
    def fix_href(m: re.Match[str]) -> str:
        quote = m.group(1)
        url = m.group(2)
        parts = urlsplit(url)
        if parts.netloc and "4pda.to" not in parts.netloc:
            return m.group(0)
        if "lofiversion" in parts.path:
            return m.group(0)  # already lofi
        qs = parse_qsl(parts.query, keep_blank_values=True)
        if not qs:
            return m.group(0)
        out: list[tuple[str, str]] = []
        rewrote = False
        for k, v in qs:
            if k == "showforum":
                rewrote = True
                out = [("f" + v + ".html", "")]  # lofi uses f{N}.html pseudo-path
                break
            if k == "showtopic":
                rewrote = True
                out = [("t" + v + ".html", "")]
                break
            out.append((k, v))
        if not rewrote:
            return m.group(0)
        # Build a lofi URL: path = lofiversion/index.php, query = "fN.html" / "tN.html"
        new_query = out[0][0]
        # preserve extra params after the first lofi token (rare)
        for k, v in out[1:]:
            new_query += "&" + urlencode([(k, v)])
        new = urlunsplit(("https", "4pda.to", "/forum/lofiversion/index.php", new_query, ""))
        return f'href={quote}{new}{quote}'

    return re.sub(r'href=(["\'])([^"\']+)\1', fix_href, html)


# --- parsers -------------------------------------------------------------------

def parse_categories() -> list[dict]:
    """Top-level categories from the full index (lofi has no root listing)."""
    html = _q(FULL_IDX)
    out: list[dict] = []
    seen: set[int] = set()
    for fid, name in re.findall(
        r'<div class="cat_name"[^>]*>.*?<a href="https://4pda\.to/forum/index\.php\?showforum=(\d+)"[^>]*>([^<]+)</a>',
        html, re.S,
    ):
        n = int(fid)
        if n in seen:
            continue
        seen.add(n)
        out.append({"id": n, "name": _strip(name), "is_category": True})
    return out


def parse_forum(forum_id: int) -> dict:
    """A lofi forum page: subforums (flat) + topics (flat)."""
    html = _q(f"{LOFI}?f{forum_id}.html=")
    # subforums: forumwrap > li > a.f{N}.html (+ optional span.desc count)
    subforums: list[dict] = []
    for m in re.finditer(
        r'<li><a href="https://4pda\.to/forum/lofiversion/index\.php\?f(\d+)\.html">([^<]+)</a>'
        r'(?:\s*<span class="desc">([^<]*)</span>)?',
        html,
    ):
        subforums.append({
            "id": int(m.group(1)),
            "name": _strip(m.group(2)),
            "posts_hint": _strip(m.group(3)) if m.group(3) else None,
        })

    # topics live in <div class="topicwrap"><ol>...</ol>; parse that block only.
    tw = re.search(r'<div class="topicwrap"><ol>(.*?)</ol>', html, re.S)
    topics: list[dict] = []
    if tw:
        for li in re.findall(r"<li>(.*?)</li>", tw.group(1), re.S):
            tm = re.search(
                r'href="https://4pda\.to/forum/lofiversion/index\.php\?t(\d+)\.html">([^<]+)</a>'
                r'(?:\s*<span class="desc">([^<]*)</span>)?',
                li,
            )
            if not tm:
                continue
            replies = None
            if tm.group(3):
                rm = re.search(r"(\d+)", tm.group(3))
                replies = int(rm.group(1)) if rm else None
            topics.append({
                "id": int(tm.group(1)),
                "title": _strip(tm.group(2)),
                "replies": replies,
                "is_important": "(!)" in li,
            })

    # pagination of the topic list (rare); lofi shows offset links f{N}-{st}.html
    pages = set(re.findall(r'\?f%d-(\d+)\.html' % forum_id, html))
    return {
        "forum_id": forum_id,
        "subforums": subforums,
        "topics": topics,
        "topic_page_count": len(pages) + 1 if pages else 1,
    }


def parse_topic(topic_id: int, page: int = 1) -> dict:
    """A lofi topic page: posts + pagination. Drops the pinned header on page>=2."""
    offset = 0 if page <= 1 else (page - 1) * PAGE_STEP
    url = f"{LOFI}?t{topic_id}.html=" if offset == 0 else f"{LOFI}?t{topic_id}-{offset}.html"
    html = _q(url)

    # Split on the post delimiter; each chunk holds one posttopbar+postcontent pair.
    chunks = html.split('<div class="postwrapper">')[1:]
    posts: list[dict] = []
    for ch in chunks:
        author = re.search(r'class="postname">([^<]+)</div>', ch)
        date = re.search(r'class="postdate">([^<]+)</div>', ch)
        # postcontent div closes with </div></div> (inner wrapper + content)
        content = re.search(r'<div class="postcontent">(.*?)</div>\s*</div>', ch, re.S)
        if not (author and content):
            continue
        posts.append({
            "author": _strip(author.group(1)),
            "date": _strip(date.group(1)) if date else None,
            "html": rewrite_links(content.group(1)).strip(),
        })

    # The pinned header (first post of the topic) repeats on every page; drop it on page>=2.
    if page >= 2 and posts:
        posts = posts[1:]

    # total pages: page-nav links use t{topic_id}-{offset}.html, offset = posts per page
    offsets = {int(x) for x in re.findall(r'\?t%d-(\d+)\.html' % topic_id, html)}
    max_off = max(offsets) if offsets else 0
    page_count = max_off // PAGE_STEP + 1 if max_off else 1

    return {
        "topic_id": topic_id,
        "page": page,
        "page_count": page_count,
        "posts": posts,
    }