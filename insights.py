"""
Data loading and HTML rendering for the Insights dashboard page.
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime

try:
    from config import USER_ID
except ImportError:
    USER_ID = 0


DB_PATH = Path(__file__).parent / "replies.db"


# ── Data queries ──────────────────────────────────────────────────────────────

def _escape(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def load_response_rate(conn):
    """Return response rate stats across all activity replies."""
    rows = conn.execute(
        "SELECT id, comment_id, is_responded FROM activity_items WHERE type IN ('note_reply','comment_reply')"
    ).fetchall()

    total = 0
    replied = 0
    liked_only = 0

    for _, reply_id, is_responded in rows:
        if not reply_id:
            continue
        total += 1

        # Check if you responded: is_responded flag (set by recheck) OR response comment in DB
        has_response = bool(is_responded)
        if not has_response:
            has_response = bool(conn.execute(
                "SELECT id FROM comments WHERE user_id=? AND ancestor_path LIKE ? AND id > ?",
                (USER_ID, f"%{reply_id}%", reply_id)
            ).fetchone())

        if has_response:
            replied += 1
            continue

        # Only liked, no response
        raw = conn.execute("SELECT raw_json FROM comments WHERE id=?", (reply_id,)).fetchone()
        if raw:
            data = json.loads(raw[0] or "{}")
            if data.get("reaction"):
                liked_only += 1

    unanswered = total - replied - liked_only
    return {
        "total": total,
        "replied": replied,
        "liked_only": liked_only,
        "unanswered": unanswered,
        "reply_rate": round(replied / total * 100) if total else 0,
    }


def load_monthly_engagement(conn, months=8):
    """Return monthly counts for replies, likes, restacks, follows."""
    rows = conn.execute("""
        SELECT substr(created_at,1,7) as mo,
               SUM(CASE WHEN type IN ('note_reply','comment_reply') THEN 1 ELSE 0 END) as replies,
               SUM(CASE WHEN type = 'note_like' THEN 1 ELSE 0 END) as likes,
               SUM(CASE WHEN type IN ('restack','restack_quote') THEN 1 ELSE 0 END) as restacks,
               SUM(CASE WHEN type IN ('follow','free_subscription','paid_subscription') THEN 1 ELSE 0 END) as follows
        FROM activity_items
        WHERE mo IS NOT NULL
        GROUP BY mo
        ORDER BY mo DESC
        LIMIT ?
    """, (months,)).fetchall()

    result = []
    for mo, replies, likes, restacks, follows in reversed(rows):
        try:
            label = datetime.strptime(mo, "%Y-%m").strftime("%b %Y")
        except Exception:
            label = mo
        result.append({
            "month": mo,
            "label": label,
            "replies": replies or 0,
            "likes": likes or 0,
            "restacks": restacks or 0,
            "follows": follows or 0,
        })
    return result


def load_top_commenters(conn, limit=10):
    """Return top commenters by volume (excluding yourself)."""
    rows = conn.execute("""
        SELECT name, handle, COUNT(*) as n
        FROM comments
        WHERE user_id != ? AND user_id IS NOT NULL
        GROUP BY user_id
        ORDER BY n DESC
        LIMIT ?
    """, (USER_ID, limit)).fetchall()
    return [{"name": r[0] or r[1] or "Anonymous", "handle": r[1] or "", "count": r[2]} for r in rows]


def load_top_posts(conn, limit=8):
    """Return posts with the most comments."""
    rows = conn.execute("""
        SELECT p.title, p.canonical_url, p.pub_subdomain,
               COUNT(c.id) as comment_count
        FROM posts p
        LEFT JOIN comments c ON c.post_id = p.id
            AND c.user_id != ? AND c.user_id IS NOT NULL
        GROUP BY p.id
        ORDER BY comment_count DESC
        LIMIT ?
    """, (USER_ID, limit)).fetchall()
    return [
        {
            "title": r[0] or "(untitled)",
            "url": r[1] or "",
            "pub": r[2] or "",
            "count": r[3],
        }
        for r in rows
        if r[3] > 0
    ]


def load_engagement_breakdown(conn):
    """Return a breakdown of engagement type totals."""
    rows = conn.execute("""
        SELECT type, COUNT(*) as n
        FROM activity_items
        GROUP BY type
        ORDER BY n DESC
    """).fetchall()

    type_labels = {
        "note_reply": "Note replies",
        "comment_reply": "Comment replies",
        "note_like": "Note likes",
        "restack": "Restacks",
        "restack_quote": "Restack quotes",
        "follow": "New follows",
        "free_subscription": "Free subscriptions",
        "paid_subscription": "Paid subscriptions",
        "post_reply": "Post replies",
        "post_like": "Post likes",
        "comment_mention": "Comment mentions",
        "post_mention": "Post mentions",
        "naked_restack_reaction": "Restack reactions",
    }
    result = []
    for type_key, count in rows:
        label = type_labels.get(type_key)
        if label:
            result.append({"type": type_key, "label": label, "count": count})
    return result


def load_all(conn):
    return {
        "response_rate": load_response_rate(conn),
        "monthly": load_monthly_engagement(conn),
        "top_commenters": load_top_commenters(conn),
        "top_posts": load_top_posts(conn),
        "engagement": load_engagement_breakdown(conn),
    }


# ── HTML rendering ────────────────────────────────────────────────────────────

def _bar(value, max_value, color="#ff3300", height="10px"):
    pct = round(value / max_value * 100) if max_value else 0
    return f'<div style="background:{color}; height:{height}; width:{pct}%; border-radius:3px; min-width:{"2px" if pct > 0 else "0"};"></div>'


def render_response_rate(data):
    total = data["total"]
    replied = data["replied"]
    liked = data["liked_only"]
    unanswered = data["unanswered"]
    rate = data["reply_rate"]

    replied_pct = round(replied / total * 100) if total else 0
    liked_pct = round(liked / total * 100) if total else 0
    unanswered_pct = max(0, 100 - replied_pct - liked_pct)

    return f"""
    <div class="card">
      <div class="card-title">Response Rate</div>
      <div class="rate-row">
        <div class="rate-number">{rate}%</div>
        <div class="rate-label">of replies directly responded to</div>
      </div>
      <div class="stack-bar">
        <div class="stack-seg" style="width:{replied_pct}%; background:#22c55e;" title="Responded: {replied}"></div>
        <div class="stack-seg" style="width:{liked_pct}%; background:#f59e0b;" title="Liked only (no reply): {liked}"></div>
        <div class="stack-seg" style="width:{unanswered_pct}%; background:#e5e5e5;" title="Unanswered: {unanswered}"></div>
      </div>
      <div class="stack-legend">
        <span class="legend-dot" style="background:#22c55e;"></span> Responded ({replied})
        <span class="legend-dot" style="background:#f59e0b; margin-left:12px;"></span> Liked only — no reply ({liked})
        <span class="legend-dot" style="background:#ccc; margin-left:12px;"></span> Unanswered ({unanswered})
      </div>
      <div class="rate-sub">Based on {total} note and comment replies in your activity feed</div>
    </div>"""


def render_monthly_chart(monthly):
    if not monthly:
        return ""

    # Show replies + restacks + follows in grouped bars
    max_replies = max((m["replies"] for m in monthly), default=1) or 1
    max_likes = max((m["likes"] for m in monthly), default=1) or 1
    max_restacks = max((m["restacks"] for m in monthly), default=1) or 1

    rows = ""
    for m in monthly:
        label = _escape(m["label"])
        replies_bar = _bar(m["replies"], max_replies, "#ff3300", "8px")
        likes_bar = _bar(m["likes"], max_likes, "#f59e0b", "8px")
        restacks_bar = _bar(m["restacks"], max_restacks, "#6366f1", "8px")
        rows += f"""
        <div class="chart-row">
          <div class="chart-label">{label}</div>
          <div class="chart-bars">
            <div class="bar-group">
              <div class="bar-track">{replies_bar}</div>
              <div class="bar-val">{m["replies"]}</div>
            </div>
            <div class="bar-group">
              <div class="bar-track">{likes_bar}</div>
              <div class="bar-val">{m["likes"]}</div>
            </div>
            <div class="bar-group">
              <div class="bar-track">{restacks_bar}</div>
              <div class="bar-val">{m["restacks"]}</div>
            </div>
          </div>
        </div>"""

    return f"""
    <div class="card">
      <div class="card-title">Monthly Engagement</div>
      <div class="chart-legend">
        <span class="legend-dot" style="background:#ff3300;"></span> Replies
        <span class="legend-dot" style="background:#f59e0b; margin-left:12px;"></span> Likes
        <span class="legend-dot" style="background:#6366f1; margin-left:12px;"></span> Restacks
      </div>
      <div class="chart">{rows}</div>
    </div>"""


def render_top_commenters(commenters):
    if not commenters:
        return ""
    max_count = commenters[0]["count"] if commenters else 1
    rows = ""
    for i, c in enumerate(commenters):
        bar = _bar(c["count"], max_count, "#ff3300", "6px")
        name = _escape(c["name"])
        rows += f"""
        <div class="list-row">
          <div class="list-rank">{i+1}</div>
          <div class="list-name">{name}</div>
          <div class="list-bar">{bar}</div>
          <div class="list-count">{c["count"]}</div>
        </div>"""

    return f"""
    <div class="card">
      <div class="card-title">Top Commenters</div>
      <div class="list">{rows}</div>
    </div>"""


def render_top_posts(posts):
    if not posts:
        return ""
    max_count = posts[0]["count"] if posts else 1
    rows = ""
    for p in posts:
        bar = _bar(p["count"], max_count, "#ff3300", "6px")
        title = _escape(p["title"])
        url = _escape(p["url"])
        link = f'<a href="{url}" target="_blank" class="post-link">{title}</a>' if url else f'<span>{title}</span>'
        rows += f"""
        <div class="list-row">
          <div class="list-name post-title-cell">{link}</div>
          <div class="list-bar">{bar}</div>
          <div class="list-count">{p["count"]}</div>
        </div>"""

    return f"""
    <div class="card">
      <div class="card-title">Most Commented Posts</div>
      <div class="list">{rows}</div>
    </div>"""


def render_engagement_breakdown(engagement):
    if not engagement:
        return ""
    max_count = engagement[0]["count"] if engagement else 1
    rows = ""
    for e in engagement:
        bar = _bar(e["count"], max_count, "#6366f1", "6px")
        rows += f"""
        <div class="list-row">
          <div class="list-name">{_escape(e["label"])}</div>
          <div class="list-bar">{bar}</div>
          <div class="list-count">{e["count"]}</div>
        </div>"""

    return f"""
    <div class="card">
      <div class="card-title">All Engagement Types</div>
      <div class="list">{rows}</div>
    </div>"""


def render_insights_html(data):
    response_rate_html = render_response_rate(data["response_rate"])
    monthly_html = render_monthly_chart(data["monthly"])
    commenters_html = render_top_commenters(data["top_commenters"])
    posts_html = render_top_posts(data["top_posts"])
    engagement_html = render_engagement_breakdown(data["engagement"])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Insights — Substack Replies</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f5f4f0; color: #1a1a1a; padding: 24px;
    }}
    .header {{ max-width: 720px; margin: 0 auto 24px; }}
    .back-link {{
      display: inline-block; margin-bottom: 12px;
      font-size: 0.82rem; color: #aaa; text-decoration: none;
    }}
    .back-link:hover {{ color: #666; }}
    h1 {{ font-size: 1.6rem; font-weight: 700; margin-bottom: 4px; }}
    .subtitle {{ color: #666; font-size: 0.9rem; }}

    .grid {{ max-width: 720px; margin: 0 auto; display: flex; flex-direction: column; gap: 14px; }}

    .card {{
      background: white; border-radius: 10px; padding: 20px 22px;
      border: 1px solid #e5e5e5;
    }}
    .card-title {{
      font-size: 0.72rem; font-weight: 700; color: #bbb;
      text-transform: uppercase; letter-spacing: 0.06em;
      margin-bottom: 14px;
    }}

    /* Response rate */
    .rate-row {{ display: flex; align-items: baseline; gap: 8px; margin-bottom: 14px; }}
    .rate-number {{ font-size: 2.4rem; font-weight: 700; color: #22c55e; line-height: 1; }}
    .rate-label {{ font-size: 0.9rem; color: #555; }}
    .stack-bar {{
      height: 12px; border-radius: 6px; overflow: hidden;
      display: flex; gap: 2px; background: #f0f0f0; margin-bottom: 10px;
    }}
    .stack-seg {{ height: 100%; transition: width 0.3s; min-width: 2px; }}
    .stack-legend {{ font-size: 0.78rem; color: #888; display: flex; align-items: center; flex-wrap: wrap; gap: 4px; margin-bottom: 8px; }}
    .legend-dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; }}
    .rate-sub {{ font-size: 0.78rem; color: #bbb; }}

    /* Chart */
    .chart-legend {{ font-size: 0.78rem; color: #888; display: flex; align-items: center; flex-wrap: wrap; gap: 4px; margin-bottom: 14px; }}
    .chart {{ display: flex; flex-direction: column; gap: 10px; }}
    .chart-row {{ display: flex; align-items: center; gap: 12px; }}
    .chart-label {{ font-size: 0.78rem; color: #888; width: 72px; flex-shrink: 0; text-align: right; }}
    .chart-bars {{ flex: 1; display: flex; flex-direction: column; gap: 3px; }}
    .bar-group {{ display: flex; align-items: center; gap: 6px; }}
    .bar-track {{ flex: 1; background: #f5f5f5; border-radius: 3px; height: 8px; overflow: hidden; }}
    .bar-val {{ font-size: 0.72rem; color: #bbb; width: 32px; text-align: right; flex-shrink: 0; }}

    /* Lists */
    .list {{ display: flex; flex-direction: column; gap: 8px; }}
    .list-row {{ display: flex; align-items: center; gap: 10px; }}
    .list-rank {{ font-size: 0.75rem; color: #ccc; width: 16px; flex-shrink: 0; text-align: right; }}
    .list-name {{ font-size: 0.85rem; color: #333; width: 160px; flex-shrink: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .post-title-cell {{ width: 240px; }}
    .list-bar {{ flex: 1; background: #f5f5f5; border-radius: 3px; height: 6px; overflow: hidden; }}
    .list-count {{ font-size: 0.78rem; color: #999; width: 36px; text-align: right; flex-shrink: 0; }}
    .post-link {{ color: #cc3300; text-decoration: none; font-size: 0.85rem; }}
    .post-link:hover {{ text-decoration: underline; }}

    a {{ color: #bbb; }}
  </style>
</head>
<body>
  <div class="header">
    <a href="/" class="back-link">← Back to Replies</a>
    <h1>Insights</h1>
    <div class="subtitle">A snapshot of your Substack engagement</div>
  </div>

  <div class="grid">
    {response_rate_html}
    {monthly_html}
    {commenters_html}
    {posts_html}
    {engagement_html}
  </div>
</body>
</html>"""
