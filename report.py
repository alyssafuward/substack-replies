#!/usr/bin/env python3
"""
Generate a self-contained HTML report of Substack replies needing response.

Usage:
  python report.py            # generates report.html and opens it
  python report.py --no-open  # generates report.html without opening
"""

import sys
import json
import sqlite3
import webbrowser
from pathlib import Path
from datetime import datetime

USER_ID = 118913109
DB_PATH = Path(__file__).parent / "replies.db"
OUT_PATH = Path(__file__).parent / "report.html"

# ── Data ──────────────────────────────────────────────────────────────────────

def load_data(conn):
    """Return list of dicts representing replies needing response."""
    results = []

    # 1. Note/comment replies from activity feed
    rows = conn.execute("""
        SELECT a.id, a.type, a.created_at, a.comment_id, a.target_comment_id, a.raw_json
        FROM activity_items a
        WHERE a.type IN ('note_reply', 'comment_reply')
        ORDER BY a.created_at DESC
    """).fetchall()

    for row in rows:
        item_id, item_type, created_at, reply_id, your_id, raw = row
        if not reply_id or not your_id:
            continue

        # Check if you already replied back
        your_reply = conn.execute("""
            SELECT id FROM comments
            WHERE user_id = ? AND ancestor_path LIKE ? AND id > ?
        """, (USER_ID, f"%{reply_id}%", reply_id)).fetchone()
        if your_reply:
            continue

        reply_row = conn.execute(
            "SELECT name, handle, body, post_id, post_url, raw_json FROM comments WHERE id=?", (reply_id,)
        ).fetchone()
        your_row = conn.execute(
            "SELECT body FROM comments WHERE id=?", (your_id,)
        ).fetchone()

        if not reply_row:
            continue

        name = reply_row[0] or reply_row[1] or "Someone"
        reply_handle = reply_row[1] or ""
        reply_body = reply_row[2] or ""
        post_id = reply_row[3]
        post_url = reply_row[4]
        reply_raw = json.loads(reply_row[5] or "{}")
        your_body = your_row[0] if your_row else ""
        label = "replied to your note" if item_type == "note_reply" else "replied to your comment"
        liked = bool(reply_raw.get("reaction"))

        if item_type == "note_reply" and reply_handle:
            link = f"https://substack.com/@{reply_handle}/note/c-{reply_id}"
        elif post_url:
            link = f"{post_url.rstrip('/')}/comment/{reply_id}"
        elif post_id:
            link = f"https://substack.com/p/{post_id}/comment/{reply_id}"
        else:
            link = ""

        results.append({
            "source": "activity",
            "date": (created_at or "")[:10],
            "raw_date": created_at or "",
            "who": name,
            "label": label,
            "your_body": your_body,
            "their_body": reply_body,
            "link": link,
            "comment_id": reply_id,
            "liked": liked,
        })

    # 2. Unresponded comments on own posts
    rows = conn.execute("""
        SELECT c.id, c.name, c.handle, c.body, c.date,
               c.post_title, c.post_url, c.ancestor_path, c.post_id
        FROM comments c
        WHERE c.pub_subdomain IS NOT NULL
          AND c.user_id != ?
          AND c.user_id IS NOT NULL
        ORDER BY c.date DESC
    """, (USER_ID,)).fetchall()

    for row in rows:
        cid, name, handle, body, date, post_title, post_url, ancestor_path, post_id = row

        your_reply = conn.execute("""
            SELECT id FROM comments
            WHERE user_id = ? AND (ancestor_path = ? OR ancestor_path LIKE ?)
        """, (USER_ID, str(cid), f"%.{cid}%")).fetchone()
        if your_reply:
            continue

        if ancestor_path:
            ancestor_ids = [int(x) for x in ancestor_path.split(".") if x]
            if ancestor_ids:
                your_in_thread = conn.execute(
                    f"SELECT id FROM comments WHERE user_id=? AND id IN ({','.join('?'*len(ancestor_ids))})",
                    [USER_ID] + ancestor_ids
                ).fetchone()
                if not your_in_thread:
                    continue

        link = post_url or ""
        if link and cid:
            link = f"{link.rstrip('/')}/comment/{cid}"

        # Check if you liked this comment
        liked_row = conn.execute("SELECT raw_json FROM comments WHERE id=?", (cid,)).fetchone()
        liked_raw = json.loads(liked_row[0] or "{}") if liked_row else {}
        liked = bool(liked_raw.get("reaction"))

        results.append({
            "source": "own_pub",
            "date": (date or "")[:10],
            "raw_date": date or "",
            "who": name or handle or "Anonymous",
            "label": "commented on your post",
            "your_body": post_title or "",
            "their_body": body or "",
            "link": link,
            "comment_id": cid,
            "liked": liked,
        })

    return results


def load_stats(conn):
    activity_count = conn.execute("SELECT COUNT(*) FROM activity_items").fetchone()[0]
    comment_count = conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
    post_count = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    last_sync = conn.execute(
        "SELECT synced_at FROM sync_log ORDER BY synced_at DESC LIMIT 1"
    ).fetchone()
    return {
        "activity_items": activity_count,
        "comments": comment_count,
        "posts": post_count,
        "last_sync": (last_sync[0] or "")[:16].replace("T", " ") if last_sync else "never",
    }

# ── HTML ──────────────────────────────────────────────────────────────────────

def escape(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

def format_date(raw):
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        # Convert to local time
        import time
        offset = -time.timezone if not time.daylight else -time.altzone
        from datetime import timezone, timedelta
        local = dt.astimezone(timezone(timedelta(seconds=offset)))
        return local.strftime("%-m/%-d/%y %-I:%M %p")
    except:
        return raw[:10]

def render_card(item, section="action"):
    date = escape(format_date(item.get("raw_date", item["date"])))
    who = escape(item["who"])
    label = escape(item["label"])
    your = escape(item["your_body"][:120] + ("..." if len(item["your_body"]) > 120 else ""))
    theirs = escape(item["their_body"][:200] + ("..." if len(item["their_body"]) > 200 else ""))
    link = item["link"]
    liked = item.get("liked", False)
    cid = item["comment_id"]
    source_badge = "note" if item["source"] == "activity" and "note" in item["label"] else ("comment" if item["source"] == "activity" else "your post")
    your_label = "Your post:" if item["source"] == "own_pub" else "Your content:"

    liked_badge = '<span class="liked-badge">❤️ liked</span>' if liked else ""
    link_html = f'<a href="{escape(link)}" target="_blank" class="reply-link">Open on Substack →</a>' if link else ""

    return f"""
    <div class="card" data-id="{cid}" data-section="{section}">
      <div class="card-header">
        <div class="card-meta">
          <span class="badge">{source_badge}</span>
          {liked_badge}
          <span class="date">{date}</span>
        </div>
        <div class="card-actions">
          {link_html}
          <button class="done-btn" onclick="markDone({cid})" title="Mark as done">✓ Done</button>
        </div>
      </div>
      <div class="who">{who} <span class="label">{label}</span></div>
      {"<div class='your-content'><span class='field-label'>" + your_label + "</span> " + your + "</div>" if your else ""}
      <div class="their-content"><span class="field-label">Their reply:</span> {theirs}</div>
    </div>
    """

def render_html(items, stats):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    needs_response = [i for i in items if not i.get("liked")]
    reviewed = [i for i in items if i.get("liked")]

    action_cards = "\n".join(render_card(i, "action") for i in needs_response)
    reviewed_cards = "\n".join(render_card(i, "liked") for i in reviewed)

    count = len(needs_response)
    reviewed_count = len(reviewed)
    empty_msg = "" if count else '<div class="empty">🎉 All caught up!</div>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Substack Replies</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f5f4f0; color: #1a1a1a; padding: 24px;
    }}
    .header {{ max-width: 720px; margin: 0 auto 20px; }}
    h1 {{ font-size: 1.6rem; font-weight: 700; margin-bottom: 4px; }}
    .subtitle {{ color: #666; font-size: 0.9rem; }}
    .stats {{ display: flex; gap: 12px; margin-top: 12px; flex-wrap: wrap; }}
    .stat {{
      background: white; border-radius: 8px; padding: 8px 14px;
      font-size: 0.8rem; color: #555; border: 1px solid #e5e5e5;
    }}
    .stat strong {{ color: #1a1a1a; font-size: 1rem; display: block; }}
    .count-banner {{
      max-width: 720px; margin: 0 auto 20px;
      background: #ff3300; color: white;
      border-radius: 8px; padding: 12px 18px;
      font-weight: 600; font-size: 1rem;
    }}
    .count-banner.zero {{ background: #22c55e; }}
    .cards {{ max-width: 720px; margin: 0 auto; display: flex; flex-direction: column; gap: 10px; }}
    .card {{
      background: white; border-radius: 10px; padding: 16px 18px;
      border: 1px solid #e5e5e5; transition: box-shadow 0.15s;
    }}
    .card:hover {{ box-shadow: 0 2px 12px rgba(0,0,0,0.07); }}
    .card.done {{ display: none; }}
    .card-header {{
      display: flex; justify-content: space-between; align-items: center;
      margin-bottom: 10px; gap: 8px;
    }}
    .card-meta {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
    .card-actions {{ display: flex; align-items: center; gap: 10px; flex-shrink: 0; }}
    .badge {{
      background: #fff0ee; color: #cc3300;
      font-size: 0.7rem; font-weight: 700;
      padding: 2px 8px; border-radius: 20px; text-transform: uppercase; letter-spacing: 0.04em;
    }}
    .liked-badge {{
      font-size: 0.75rem; color: #999; background: #f5f5f5;
      padding: 2px 8px; border-radius: 20px; border: 1px solid #e5e5e5;
    }}
    .date {{ font-size: 0.8rem; color: #bbb; }}
    .reply-link {{
      font-size: 0.82rem; color: #cc3300; text-decoration: none; font-weight: 500; white-space: nowrap;
    }}
    .reply-link:hover {{ text-decoration: underline; }}
    .done-btn {{
      font-size: 0.8rem; background: #f0f0f0; border: 1px solid #ddd;
      border-radius: 6px; padding: 3px 10px; cursor: pointer; color: #555;
      white-space: nowrap; font-weight: 500;
    }}
    .done-btn:hover {{ background: #22c55e; color: white; border-color: #22c55e; }}
    .who {{ font-weight: 600; font-size: 0.97rem; margin-bottom: 8px; }}
    .label {{ font-weight: 400; color: #666; }}
    .field-label {{ font-size: 0.72rem; font-weight: 700; color: #bbb; text-transform: uppercase; letter-spacing: 0.05em; margin-right: 4px; }}
    .your-content {{
      font-size: 0.85rem; color: #888; margin-bottom: 8px;
      padding: 7px 11px; background: #fafafa; border-radius: 6px; border-left: 3px solid #e0e0e0;
    }}
    .their-content {{
      font-size: 0.92rem; color: #222;
      padding: 7px 11px; background: #fef8f6; border-radius: 6px; border-left: 3px solid #ff3300;
    }}
    .empty {{ max-width: 720px; margin: 40px auto; text-align: center; font-size: 1.1rem; color: #555; }}
    .toggle-section {{
      max-width: 720px; margin: 28px auto 12px;
    }}
    .toggle-btn {{
      background: none; border: none; cursor: pointer;
      font-size: 0.82rem; font-weight: 700; color: #aaa;
      text-transform: uppercase; letter-spacing: 0.06em; padding: 0;
    }}
    .toggle-btn:hover {{ color: #666; }}
    .liked-section {{ display: none; margin-top: 10px; }}
    .liked-section .card {{ opacity: 0.55; background: #fafafa; }}
    .liked-section .card:hover {{ opacity: 0.8; }}
    .done-section {{ display: none; margin-top: 10px; }}
    .done-section .card {{ opacity: 0.5; background: #fafafa; }}
    .generated {{ max-width: 720px; margin: 28px auto 0; font-size: 0.78rem; color: #bbb; }}
    a {{ color: #bbb; }}
  </style>
</head>
<body>
  <div class="header">
    <h1>Substack Replies</h1>
    <div class="subtitle">Replies needing a response</div>
    <div class="stats">
      <div class="stat"><strong>{stats['activity_items']}</strong>activity synced</div>
      <div class="stat"><strong>{stats['comments']}</strong>comments stored</div>
      <div class="stat"><strong>{stats['last_sync']}</strong>last sync</div>
    </div>
  </div>

  <div class="count-banner {'zero' if count == 0 else ''}" id="banner">
    {"🎉 All caught up!" if count == 0 else f"⚡ <span id='remaining'>{count}</span> {'reply' if count == 1 else 'replies'} need your response"}
  </div>

  <div class="cards" id="action-cards">
    {action_cards}
    {empty_msg}
  </div>

  {"<div class='toggle-section'><button class='toggle-btn' onclick='toggleLiked(this)'>▶ Liked / reviewed (" + str(reviewed_count) + ")</button><div class='liked-section' id='liked-section'><div class='cards'>" + reviewed_cards + "</div></div></div>" if reviewed_count else ""}

  <div class="toggle-section">
    <button class="toggle-btn" onclick="toggleDone(this)">▶ Done (<span id="done-count">0</span>)</button>
    <div class="done-section" id="done-section">
      <div class="cards" id="done-cards"></div>
      <div style="max-width:720px;margin:8px auto 0;text-align:right">
        <a href="javascript:clearDone()" style="font-size:0.78rem;color:#bbb;">Clear all done</a>
      </div>
    </div>
  </div>

  <div class="generated">Generated {now} · <a href="javascript:location.reload()">refresh</a></div>

  <script>
    const DONE_KEY = 'substack_done';

    function getDone() {{
      try {{ return new Set(JSON.parse(localStorage.getItem(DONE_KEY) || '[]')); }}
      catch {{ return new Set(); }}
    }}
    function saveDone(set) {{
      localStorage.setItem(DONE_KEY, JSON.stringify([...set]));
    }}

    function markDone(id) {{
      const card = document.querySelector(`#action-cards [data-id="${{id}}"]`);
      if (!card) return;
      const done = getDone();
      done.add(String(id));
      saveDone(done);
      moveToDone(card, id);
      updateCount();
      updateDoneCount();
    }}

    function undoItem(id) {{
      const card = document.querySelector(`#done-cards [data-id="${{id}}"]`);
      if (!card) return;
      // Remove undo button, restore done button
      const undoBtn = card.querySelector('.undo-btn-inline');
      if (undoBtn) undoBtn.remove();
      const doneBtn = card.querySelector('.done-btn');
      if (doneBtn) {{ doneBtn.style.display = ''; }}
      // Move back to action cards
      document.getElementById('action-cards').prepend(card);
      const done = getDone();
      done.delete(String(id));
      saveDone(done);
      updateCount();
      updateDoneCount();
    }}

    function moveToDone(card, id) {{
      // Hide the done button, add an undo button
      const doneBtn = card.querySelector('.done-btn');
      if (doneBtn) doneBtn.style.display = 'none';
      if (!card.querySelector('.undo-btn-inline')) {{
        const undo = document.createElement('button');
        undo.className = 'done-btn undo-btn-inline';
        undo.textContent = '↩ Restore';
        undo.onclick = () => undoItem(id);
        card.querySelector('.card-actions').appendChild(undo);
      }}
      document.getElementById('done-cards').prepend(card);
    }}

    function updateCount() {{
      const visible = document.querySelectorAll('#action-cards .card').length;
      const el = document.getElementById('remaining');
      if (el) el.textContent = visible;
      const banner = document.getElementById('banner');
      if (banner && visible === 0) {{
        banner.className = 'count-banner zero';
        banner.innerHTML = '🎉 All caught up!';
      }} else if (banner && el) {{
        banner.className = 'count-banner';
      }}
    }}

    function updateDoneCount() {{
      const n = document.querySelectorAll('#done-cards .card').length;
      document.getElementById('done-count').textContent = n;
    }}

    function toggleLiked(btn) {{
      const section = document.getElementById('liked-section');
      const open = section.style.display === 'block';
      section.style.display = open ? 'none' : 'block';
      btn.textContent = btn.textContent.replace(open ? '▼' : '▶', open ? '▶' : '▼');
    }}

    function toggleDone(btn) {{
      const section = document.getElementById('done-section');
      const open = section.style.display === 'block';
      section.style.display = open ? 'none' : 'block';
      btn.firstChild.textContent = open ? '▶ ' : '▼ ';
    }}

    function clearDone() {{
      if (confirm('Move all done items back to your list?')) {{
        const cards = [...document.querySelectorAll('#done-cards .card')];
        cards.forEach(card => {{
          const id = card.dataset.id;
          undoItem(id);
        }});
      }}
    }}

    // Apply saved done state on load
    const done = getDone();
    done.forEach(id => {{
      const card = document.querySelector(`#action-cards [data-id="${{id}}"]`);
      if (card) moveToDone(card, id);
    }});
    updateCount();
    updateDoneCount();
  </script>
</body>
</html>"""

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not DB_PATH.exists():
        print("No database found. Run: python scraper.py sync")
        sys.exit(1)

    with sqlite3.connect(DB_PATH) as conn:
        items = load_data(conn)
        stats = load_stats(conn)

    html = render_html(items, stats)
    OUT_PATH.write_text(html, encoding="utf-8")
    print(f"Report generated: {OUT_PATH}")
    print(f"Found {len(items)} replies needing response.")

    if "--no-open" not in sys.argv:
        webbrowser.open(f"file://{OUT_PATH.resolve()}")

if __name__ == "__main__":
    main()
