"""
Data loading and HTML rendering for the Substack Replies Flask app.
"""

import sys
import json
import sqlite3
from pathlib import Path
from datetime import datetime

try:
    from config import USER_ID
except ImportError:
    print("Error: config.py not found. Copy config.example.py to config.py and fill in your values.")
    sys.exit(1)

DB_PATH = Path(__file__).parent / "replies.db"

# ── Data ──────────────────────────────────────────────────────────────────────

def load_thread(conn, reply_id):
    """Return ancestor comments in order (oldest first), excluding the reply itself."""
    row = conn.execute("SELECT ancestor_path FROM comments WHERE id=?", (reply_id,)).fetchone()
    if not row or not row[0]:
        return []
    ancestor_ids = [int(x) for x in row[0].split(".") if x]
    if not ancestor_ids:
        return []
    placeholders = ",".join("?" * len(ancestor_ids))
    rows = conn.execute(
        f"SELECT id, name, body FROM comments WHERE id IN ({placeholders})", ancestor_ids
    ).fetchall()
    by_id = {r[0]: r for r in rows}
    return [{"name": by_id[i][1] or "?", "body": by_id[i][2] or ""} for i in ancestor_ids if i in by_id]


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

        thread = load_thread(conn, reply_id)

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
            "thread": thread,
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

        thread = load_thread(conn, cid)

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
            "thread": thread,
        })

    return results


def _format_sync_time(iso_str):
    if not iso_str:
        return "never"
    try:
        from datetime import timezone
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        local = dt.astimezone()
        return local.strftime("%-m/%-d at %-I:%M %p")
    except Exception:
        return iso_str[:16].replace("T", " ")


def load_stats(conn):
    activity_count = conn.execute("SELECT COUNT(*) FROM activity_items").fetchone()[0]
    comment_count = conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
    post_count = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    synced_up_to = conn.execute(
        "SELECT value FROM sync_state WHERE key='last_synced_at'"
    ).fetchone()
    return {
        "activity_items": activity_count,
        "comments": comment_count,
        "posts": post_count,
        "synced_up_to": _format_sync_time(synced_up_to[0]) if synced_up_to else "never",
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

def render_thread_msg(m):
    name = escape(m['name'])
    body = m['body']
    LIMIT = 120
    if len(body) <= LIMIT:
        return f"""<div class="thread-msg">
      <span class="thread-name">{name}</span>
      <span class="thread-body">{escape(body)}</span>
    </div>"""
    short = escape(body[:LIMIT])
    full = escape(body)
    return f"""<div class="thread-msg">
      <span class="thread-name">{name}</span>
      <span class="thread-body"><span class="thread-short">{short}<button class="thread-more" onclick="expandThread(this)">… more</button></span><span class="thread-full" style="display:none">{full}<button class="thread-more" onclick="collapseThread(this)"> less</button></span></span>
    </div>"""


def render_thread(thread):
    """Render ancestor thread. Show last message, hide rest behind toggle."""
    if not thread:
        return ""

    last = thread[-1]
    last_html = render_thread_msg(last)

    if len(thread) <= 1:
        return f'<div class="thread-context">{last_html}</div>'

    older = thread[:-1]
    older_html = "".join(render_thread_msg(m) for m in older)

    count = len(older)
    plural = "s" if count > 1 else ""
    return f"""<div class="thread-context">
      <button class="thread-toggle" onclick="toggleThread(this)">▶ {count} earlier message{plural}</button>
      <div class="thread-older" style="display:none">{older_html}</div>
      {last_html}
    </div>"""


def render_card(item, section="action"):
    date = escape(format_date(item.get("raw_date", item["date"])))
    who = escape(item["who"])
    label = escape(item["label"])
    your = escape(item["your_body"][:120] + ("..." if len(item["your_body"]) > 120 else ""))
    theirs = escape(item["their_body"][:200] + ("..." if len(item["their_body"]) > 200 else ""))
    link = item["link"]
    liked = item.get("liked", False)
    cid = item["comment_id"]
    thread = item.get("thread", [])
    source_badge = "note" if item["source"] == "activity" and "note" in item["label"] else ("comment" if item["source"] == "activity" else "your post")
    your_label = "Your post:" if item["source"] == "own_pub" else "Your content:"

    liked_badge = '<span class="liked-badge">❤️ liked</span>' if liked else ""
    link_html = f'<a href="{escape(link)}" target="_blank" class="reply-link">Open on Substack →</a>' if link else ""
    thread_html = render_thread(thread)

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
        </div>
      </div>
      <div class="who">{who} <span class="label">{label}</span></div>
      {"<div class='your-content'><span class='field-label'>" + your_label + "</span> " + your + "</div>" if your and not thread_html else ""}
      {thread_html}
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
    .sync-row {{ display: flex; align-items: center; gap: 10px; margin-top: 14px; }}
    .sync-btn {{
      background: #ff3300; color: white; border: none; border-radius: 6px;
      padding: 6px 16px; font-size: 0.85rem; font-weight: 600; cursor: pointer;
    }}
    .sync-btn:disabled {{ background: #ccc; cursor: default; }}
    .sync-btn:hover:not(:disabled) {{ background: #cc2900; }}
    .sync-status {{ font-size: 0.82rem; color: #888; }}
    .sync-log {{
      margin-top: 10px; padding: 10px; background: #1a1a1a; color: #ccc;
      font-size: 0.75rem; border-radius: 6px; max-height: 200px; overflow-y: auto;
      white-space: pre-wrap; word-break: break-all;
    }}
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

    .who {{ font-weight: 600; font-size: 0.97rem; margin-bottom: 8px; }}
    .label {{ font-weight: 400; color: #666; }}
    .field-label {{ font-size: 0.72rem; font-weight: 700; color: #bbb; text-transform: uppercase; letter-spacing: 0.05em; margin-right: 4px; }}
    .your-content {{
      font-size: 0.85rem; color: #888; margin-bottom: 8px;
      padding: 7px 11px; background: #fafafa; border-radius: 6px; border-left: 3px solid #e0e0e0;
    }}
    .thread-context {{
      margin-bottom: 8px;
    }}
    .thread-toggle {{
      background: none; border: none; cursor: pointer;
      font-size: 0.75rem; color: #bbb; padding: 0 0 4px 0;
    }}
    .thread-toggle:hover {{ color: #888; }}
    .thread-msg {{
      font-size: 0.82rem; color: #999;
      padding: 5px 10px; background: #f7f7f7; border-radius: 6px;
      border-left: 3px solid #e0e0e0; margin-bottom: 4px;
    }}
    .thread-name {{ font-weight: 600; color: #888; margin-right: 6px; }}
    .thread-body {{ color: #aaa; }}
    .thread-more {{ background: none; border: none; cursor: pointer; color: #bbb; font-size: 0.78rem; padding: 0; }}
    .thread-more:hover {{ color: #888; }}
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
    .intro {{ max-width: 720px; margin: 0 auto 16px; font-size: 0.88rem; color: #666; line-height: 1.5; }}
    .how-it-works-toggle {{
      background: none; border: none; cursor: pointer;
      font-size: 0.8rem; color: #bbb; padding: 0; margin-top: 6px;
      display: block; text-decoration: underline; text-underline-offset: 2px;
    }}
    .how-it-works-toggle:hover {{ color: #888; }}
    .how-it-works {{
      display: none; margin-top: 12px; padding: 14px 16px;
      background: white; border-radius: 8px; border: 1px solid #e5e5e5;
      font-size: 0.84rem; color: #555; line-height: 1.6;
    }}
    .how-it-works h3 {{ font-size: 0.78rem; font-weight: 700; color: #aaa; text-transform: uppercase; letter-spacing: 0.05em; margin: 12px 0 4px; }}
    .how-it-works h3:first-child {{ margin-top: 0; }}
    .liked-section {{ display: none; margin-top: 10px; }}
    .liked-section .card {{ opacity: 0.55; background: #fafafa; }}
    .liked-section .card:hover {{ opacity: 0.8; }}

    a {{ color: #bbb; }}
  </style>
</head>
<body>
  <div class="header">
    <h1>Substack Replies</h1>
    <div class="subtitle">Synced up to {stats['synced_up_to']}</div>
    <div class="stats">
      <div class="stat"><strong>{stats['activity_items']}</strong>activity synced</div>
      <div class="stat"><strong>{stats['comments']}</strong>comments stored</div>
    </div>
    <div class="sync-row">
      <label style="font-size:0.82rem; color:#666;">New replies to sync:</label>
      <select id="sync-count" style="font-size:0.82rem; padding:4px 6px; border-radius:4px; border:1px solid #ccc;">
        <option value="25" selected>25</option>
        <option value="50">50</option>
        <option value="100">100</option>
        <option value="200">200</option>
        <option value="250">250</option>
      </select>
      <button class="sync-btn" id="sync-btn" onclick="startSync()">Sync</button>
      <button class="sync-btn" id="stop-btn" onclick="stopSync()" style="display:none; background:#888;">Stop</button>
      <span class="sync-status" id="sync-status"></span>
    </div>
    <pre class="sync-log" id="sync-log" style="display:none"></pre>
    <div id="last-sync-log-wrap" style="display:none; margin-top:6px;">
      <button onclick="toggleLastLog(this)" style="background:none; border:none; cursor:pointer; font-size:0.8rem; color:#888; padding:0;">▶ Last sync log</button>
      <pre class="sync-log" id="last-sync-log" style="display:none; margin-top:4px;"></pre>
    </div>
  </div>

  <div class="intro">
    Never miss a reply across your Substack publications. Substack Replies collects comments and replies waiting for your response and surfaces them in one place — no more digging through your inbox.
    <button class="how-it-works-toggle" onclick="toggleHowItWorks(this)">How it works ▾</button>
    <div class="how-it-works" id="how-it-works">
      <h3>What you're seeing</h3>
      This list shows comments and replies across your publications that haven't been addressed yet. Click <strong>Open on Substack →</strong> to jump directly to a comment and respond.
      <h3>Liked comments</h3>
      By default, if you've liked a comment on Substack, Substack Replies takes that as a signal the comment has been acknowledged and hides it from your list. To show all unanswered replies regardless of likes, toggle <strong>Show liked comments</strong> below.
      <h3>Keeping your data fresh</h3>
      Use the <strong>Sync</strong> button above to pull in the latest replies and recheck which ones you've responded to or liked.
    </div>
  </div>

  <div class="count-banner {'zero' if count == 0 else ''}" id="banner">
    {"🎉 All caught up!" if count == 0 else f"⚡ <span id='remaining'>{count}</span> {'reply' if count == 1 else 'replies'} need your response"}
  </div>

  <div class="cards" id="action-cards">
    {action_cards}
    {empty_msg}
  </div>

  {"<div class='toggle-section'><button class='toggle-btn' onclick='toggleLiked(this)'>▶ Show liked comments (" + str(reviewed_count) + ")</button><div class='liked-section' id='liked-section'><div class='cards'>" + reviewed_cards + "</div></div></div>" if reviewed_count else ""}


  <script>

    function expandThread(btn) {{
      const msg = btn.closest('.thread-msg');
      msg.querySelector('.thread-short').style.display = 'none';
      msg.querySelector('.thread-full').style.display = '';
    }}
    function collapseThread(btn) {{
      const msg = btn.closest('.thread-msg');
      msg.querySelector('.thread-short').style.display = '';
      msg.querySelector('.thread-full').style.display = 'none';
    }}
    function toggleThread(btn) {{
      const older = btn.nextElementSibling;
      const open = older.style.display === 'block';
      older.style.display = open ? 'none' : 'block';
      btn.textContent = open ? btn.textContent.replace('▲', '▶') : btn.textContent.replace('▶', '▲');
    }}

    function toggleHowItWorks(btn) {{
      const el = document.getElementById('how-it-works');
      const open = el.style.display === 'block';
      el.style.display = open ? 'none' : 'block';
      btn.textContent = open ? 'How it works ▾' : 'How it works ▴';
    }}

    function toggleLiked(btn) {{
      const section = document.getElementById('liked-section');
      const open = section.style.display === 'block';
      section.style.display = open ? 'none' : 'block';
      btn.textContent = open ? '▶ Show liked comments' : '▼ Hide liked comments';
    }}


    // Restore last sync log if present
    (function() {{
      const saved = localStorage.getItem('lastSyncLog');
      if (saved) {{
        const wrap = document.getElementById('last-sync-log-wrap');
        const pre = document.getElementById('last-sync-log');
        pre.textContent = saved;
        wrap.style.display = '';
      }}
    }})();

    function toggleLastLog(btn) {{
      const pre = document.getElementById('last-sync-log');
      const open = pre.style.display === 'block';
      pre.style.display = open ? 'none' : 'block';
      btn.textContent = open ? '▶ Last sync log' : '▼ Last sync log';
    }}

    let _es = null;

    function startSync() {{
      const btn = document.getElementById('sync-btn');
      const stopBtn = document.getElementById('stop-btn');
      const count = document.getElementById('sync-count').value;
      const status = document.getElementById('sync-status');
      const log = document.getElementById('sync-log');
      btn.style.display = 'none';
      stopBtn.style.display = '';
      status.textContent = 'Starting…';
      log.textContent = '';
      log.style.display = 'block';

      _es = new EventSource('/sync?count=' + count);
      _es.onmessage = function(e) {{
        if (e.data === '__done__') {{
          _es.close();
          _es = null;
          localStorage.setItem('lastSyncLog', log.textContent);
          status.textContent = 'Done — reloading…';
          setTimeout(() => window.location.reload(), 1500);
          return;
        }}
        log.textContent += e.data + '\\n';
        log.scrollTop = log.scrollHeight;
        status.textContent = e.data;
      }};
      _es.onerror = function() {{
        _es.close();
        _es = null;
        btn.style.display = '';
        stopBtn.style.display = 'none';
        status.textContent = 'Error — check terminal';
      }};
    }}

    function stopSync() {{
      if (_es) {{ _es.close(); _es = null; }}
      fetch('/sync/stop', {{method: 'POST'}});
      document.getElementById('sync-btn').style.display = '';
      document.getElementById('stop-btn').style.display = 'none';
      document.getElementById('sync-status').textContent = 'Stopped.';
    }}
  </script>
</body>
</html>"""

