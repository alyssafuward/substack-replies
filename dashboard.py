"""
Data loading and HTML rendering for the Substack Replies Flask app.
"""

import sys
import json
import sqlite3
from pathlib import Path
from datetime import datetime

try:
    from config import USER_ID, OWN_PUBS
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
        f"SELECT id, name, body, post_url, handle FROM comments WHERE id IN ({placeholders})", ancestor_ids
    ).fetchall()
    by_id = {r[0]: r for r in rows}
    result = []
    for i in ancestor_ids:
        if i not in by_id:
            continue
        _, name, body, post_url, handle = by_id[i]
        if post_url:
            link = f"{post_url.rstrip('/')}/comment/{i}"
        elif handle:
            link = f"https://substack.com/@{handle}/note/c-{i}"
        else:
            link = None
        result.append({"id": i, "name": name or "?", "body": body or "", "link": link})
    return result


def load_data(conn):
    """Return list of dicts representing replies needing response."""
    results = []

    # 1. Note/comment replies from activity feed
    rows = conn.execute("""
        SELECT a.id, a.type, a.created_at, a.comment_id, a.target_comment_id, a.raw_json, a.is_responded
        FROM activity_items a
        WHERE a.type IN ('note_reply', 'comment_reply')
          AND (a.is_archived IS NULL OR a.is_archived = 0)
        ORDER BY a.created_at DESC
    """).fetchall()

    for row in rows:
        item_id, item_type, created_at, reply_id, your_id, raw, is_responded = row
        if not reply_id or not your_id:
            continue

        # Check if you already replied back (recheck flag or response comment in DB)
        if is_responded:
            continue
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
        guest_post = bool(post_url) and not any(f"{sub}.substack.com" in post_url for sub in OWN_PUBS)

        results.append({
            "source": "activity",
            "date": (created_at or "")[:10],
            "raw_date": created_at or "",
            "who": name,
            "handle": reply_handle,
            "label": label,
            "your_body": your_body,
            "their_body": reply_body,
            "link": link,
            "comment_id": reply_id,
            "liked": liked,
            "thread": thread,
            "guest_post": guest_post,
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
            "handle": handle or "",
            "label": "commented on your post",
            "your_body": post_title or "",
            "their_body": body or "",
            "link": link,
            "comment_id": cid,
            "liked": liked,
            "thread": thread,
        })

    return results


def load_responded_data(conn):
    """Return activity reply items where you have responded."""
    results = []
    rows = conn.execute("""
        SELECT a.id, a.type, a.created_at, a.comment_id, a.target_comment_id, a.raw_json
        FROM activity_items a
        WHERE a.type IN ('note_reply', 'comment_reply')
          AND a.is_responded = 1
        ORDER BY a.created_at DESC
    """).fetchall()

    for row in rows:
        item_id, item_type, created_at, reply_id, your_id, raw = row
        if not reply_id or not your_id:
            continue

        reply_row = conn.execute(
            "SELECT name, handle, body, post_id, post_url, raw_json FROM comments WHERE id=?", (reply_id,)
        ).fetchone()
        your_row = conn.execute("SELECT body FROM comments WHERE id=?", (your_id,)).fetchone()

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
            "handle": reply_handle,
            "label": label,
            "your_body": your_body,
            "their_body": reply_body,
            "link": link,
            "comment_id": reply_id,
            "liked": bool(reply_raw.get("reaction")),
            "thread": thread,
        })

    return results


def load_archived_data(conn):
    """Return activity reply items that have been archived."""
    results = []
    rows = conn.execute("""
        SELECT a.id, a.type, a.created_at, a.comment_id, a.target_comment_id, a.raw_json
        FROM activity_items a
        WHERE a.type IN ('note_reply', 'comment_reply')
          AND a.is_archived = 1
        ORDER BY a.created_at DESC
    """).fetchall()

    for row in rows:
        item_id, item_type, created_at, reply_id, your_id, raw = row
        if not reply_id or not your_id:
            continue

        reply_row = conn.execute(
            "SELECT name, handle, body, post_id, post_url, raw_json FROM comments WHERE id=?", (reply_id,)
        ).fetchone()
        your_row = conn.execute("SELECT body FROM comments WHERE id=?", (your_id,)).fetchone()

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
            "handle": reply_handle,
            "label": label,
            "your_body": your_body,
            "their_body": reply_body,
            "link": link,
            "comment_id": reply_id,
            "liked": bool(reply_raw.get("reaction")),
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

    # Gap detection: find the largest silent stretch between consecutive activity items.
    # If any gap > 14 days exists in a DB with 100+ items, warn the user.
    gap_warning = None
    if activity_count >= 100:
        rows = conn.execute(
            "SELECT updated_at FROM activity_items WHERE updated_at IS NOT NULL ORDER BY updated_at"
        ).fetchall()
        max_gap_days = 0
        gap_start = gap_end = None
        for i in range(1, len(rows)):
            try:
                from datetime import datetime, timezone
                a = datetime.fromisoformat(rows[i-1][0].replace("Z", "+00:00"))
                b = datetime.fromisoformat(rows[i][0].replace("Z", "+00:00"))
                days = (b - a).total_seconds() / 86400
                if days > max_gap_days:
                    max_gap_days = days
                    gap_start = rows[i-1][0][:10]
                    gap_end = rows[i][0][:10]
            except Exception:
                pass
        if max_gap_days > 14:
            gap_warning = f"Data gap detected: {int(max_gap_days)} days missing between {gap_start} and {gap_end}. History may be incomplete — consider a full resync."

    return {
        "activity_items": activity_count,
        "comments": comment_count,
        "posts": post_count,
        "synced_up_to": _format_sync_time(synced_up_to[0]) if synced_up_to else "never",
        "gap_warning": gap_warning,
    }

def load_post_comments_data(conn, pub_subdomain):
    """Return loaded posts with their unanswered/liked comments for Tab 2."""
    if not pub_subdomain:
        return []

    posts = conn.execute("""
        SELECT id, title, canonical_url, post_date
        FROM posts WHERE pub_subdomain=?
        ORDER BY post_date DESC
    """, (pub_subdomain,)).fetchall()

    result = []
    for post_id, title, url, post_date in posts:
        comment_rows = conn.execute("""
            SELECT c.id, c.name, c.handle, c.body, c.date, c.raw_json
            FROM comments c
            WHERE c.post_id=? AND c.user_id != ? AND c.user_id IS NOT NULL
            ORDER BY c.date DESC
        """, (post_id, USER_ID)).fetchall()

        unanswered = []
        liked_list = []

        for cid, name, handle, body, date, raw_json_str in comment_rows:
            your_reply = conn.execute("""
                SELECT id FROM comments
                WHERE user_id=? AND (ancestor_path=? OR ancestor_path LIKE ?)
            """, (USER_ID, str(cid), f"%.{cid}%")).fetchone()
            if your_reply:
                continue

            raw = json.loads(raw_json_str or "{}")
            is_liked = bool(raw.get("reaction"))
            link = f"{url.rstrip('/')}/comment/{cid}" if url else ""

            c = {
                "id": cid,
                "who": name or handle or "Anonymous",
                "body": body or "",
                "date": (date or "")[:10],
                "raw_date": date or "",
                "link": link,
                "liked": is_liked,
            }
            if is_liked:
                liked_list.append(c)
            else:
                unanswered.append(c)

        result.append({
            "id": post_id,
            "title": title or f"Post {post_id}",
            "url": url or "",
            "post_date": (post_date or "")[:10],
            "unanswered": unanswered,
            "liked": liked_list,
        })

    return result


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
    link = m.get('link')
    name_text = escape(m['name'])
    name_html = f'<a class="thread-name-link" href="{link}" target="_blank">{name_text}</a>' if link else f'<span class="thread-name">{name_text}</span>'
    body = m['body']
    LIMIT = 120
    if len(body) <= LIMIT:
        return f"""<div class="thread-msg">
      {name_html}
      <span class="thread-body">{escape(body)}</span>
    </div>"""
    short = escape(body[:LIMIT])
    full = escape(body)
    return f"""<div class="thread-msg">
      {name_html}
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

    handle = item.get("handle", "")
    who_html = f'<a href="https://substack.com/@{escape(handle)}" target="_blank" class="who-link">{who}</a>' if handle else who

    liked_badge = '<span class="liked-badge">❤️ liked</span>' if liked else ""
    link_html = f'<a href="{escape(link)}" target="_blank" class="reply-link">Open on Substack →</a>' if link else ""
    archive_btn = f'<button class="archive-btn" onclick="archiveCard(this, {cid})">Archive</button>' if section not in ("responded", "archived") else ""
    thread_html = render_thread(thread)

    who_key = escape((item["who"] + " " + item.get("handle", "")).strip().lower())
    return f"""
    <div class="card" data-id="{cid}" data-section="{section}" data-who="{who_key}">
      <div class="card-header">
        <div class="card-meta">
          <span class="badge">{source_badge}</span>
          {liked_badge}
          <span class="date">{date}</span>
        </div>
        <div class="card-actions">
          {archive_btn}
          {link_html}
        </div>
      </div>
      <div class="who">{who_html} <span class="label">{label}</span></div>
      {"<div class='your-content'><span class='field-label'>" + your_label + "</span> " + your + "</div>" if your and not thread_html else ""}
      {thread_html}
      <div class="their-content"><span class="field-label">Their reply:</span> {theirs}</div>
    </div>
    """

def render_post_comment_card(c):
    who = escape(c["who"])
    date = escape(format_date(c.get("raw_date", c["date"])))
    body = escape(c["body"][:200] + ("..." if len(c["body"]) > 200 else ""))
    link = c.get("link", "")
    liked = c.get("liked", False)

    liked_badge = '<span class="liked-badge">❤️ liked</span>' if liked else ""
    link_html = f'<a href="{escape(link)}" target="_blank" class="reply-link">Open →</a>' if link else ""

    return f"""    <div class="post-comment-card">
      <div class="card-header">
        <div class="card-meta">{liked_badge}<span class="date">{date}</span></div>
        <div class="card-actions">{link_html}</div>
      </div>
      <div class="who">{who}</div>
      <div class="their-content">{body}</div>
    </div>"""


def render_post_section(post):
    title = escape(post["title"])
    url = post["url"]
    post_date = escape(post["post_date"])
    unanswered = post["unanswered"]
    liked = post["liked"]

    title_link = f'<a href="{escape(url)}" target="_blank">{title}</a>' if url else title
    header = f'<div class="post-header"><span class="post-title">{title_link}</span><span class="post-date">{post_date}</span></div>'

    if not unanswered and not liked:
        body = '<div class="post-empty">No unanswered comments</div>'
    else:
        body = "\n".join(render_post_comment_card(c) for c in unanswered)
        if liked:
            liked_html = "\n".join(render_post_comment_card(c) for c in liked)
            body += f"""
      <div class="toggle-section" style="margin-top:8px;">
        <button class="toggle-btn" onclick="toggleSection(this)">▶ Show liked comments ({len(liked)})</button>
        <div class="liked-section" style="display:none;">{liked_html}</div>
      </div>"""

    return f'<div class="post-section">{header}{body}</div>'


def render_post_comments_tab(posts_data, pub_subdomain):
    total = sum(len(p["unanswered"]) for p in posts_data)
    posts_html = "\n".join(render_post_section(p) for p in posts_data)
    pub_esc = escape(pub_subdomain)

    if not posts_data:
        banner_html = ""
    elif total == 0:
        banner_html = '<div class="count-banner zero" style="margin-bottom:16px;">🎉 All caught up!</div>'
    else:
        banner_html = f'<div class="count-banner" style="margin-bottom:16px;">⚡ <span>{total}</span> {"comment" if total == 1 else "comments"} need your response</div>'

    empty_html = "" if posts_data else '<div class="empty" style="margin-top:40px;">No posts loaded yet — click <strong>Load more posts</strong> to get started.</div>'

    return f"""  <div class="posts-controls">
    <div class="sync-row">
      <label style="font-size:0.82rem; color:#666;">Load until:</label>
      <select id="load-count-{pub_esc}" style="font-size:0.82rem; padding:4px 6px; border-radius:4px; border:1px solid #ccc;">
        <option value="10">10 unanswered</option>
        <option value="25" selected>25 unanswered</option>
        <option value="50">50 unanswered</option>
        <option value="100">100 unanswered</option>
      </select>
      <button class="load-more-link" id="load-btn-{pub_esc}" onclick="startLoadPosts(this, '{pub_esc}')">Load posts</button>
      <button class="sync-btn" id="posts-sync-btn-{pub_esc}" onclick="startPostsSync('{pub_esc}')">Sync</button>
      <button class="sync-btn" id="load-stop-btn-{pub_esc}" onclick="stopPostsLoad('{pub_esc}')" style="display:none; background:#888;">Stop</button>
      <button class="sync-btn" id="posts-stop-btn-{pub_esc}" onclick="stopPostsSync('{pub_esc}')" style="display:none; background:#888;">Stop</button>
      <span class="sync-status" id="posts-sync-status-{pub_esc}"></span>
    </div>
    <pre class="sync-log" id="posts-sync-log-{pub_esc}" style="display:none"></pre>
    <div id="last-posts-sync-log-wrap-{pub_esc}" style="display:none; margin-top:6px;">
      <button onclick="toggleLastPostsLog(this, '{pub_esc}')" style="background:none; border:none; cursor:pointer; font-size:0.8rem; color:#888; padding:0;">▶ Last sync log</button>
      <pre class="sync-log" id="last-posts-sync-log-{pub_esc}" style="display:none; margin-top:4px;"></pre>
    </div>
  </div>
  {banner_html}
  {posts_html}
  {empty_html}"""


def render_html(items, stats, all_posts_data=None, active_tab="replies", all_pubs=None, responded_items=None, archived_items=None):
    all_posts_data = all_posts_data or {}
    all_pubs = all_pubs or []
    responded_items = responded_items or []
    archived_items = archived_items or []

    needs_response = [i for i in items if not i.get("liked")]
    reviewed = [i for i in items if i.get("liked")]

    direct_items = [i for i in needs_response if not i.get("guest_post")]
    guest_items = [i for i in needs_response if i.get("guest_post")]

    action_cards = "\n".join(render_card(i, "action") for i in direct_items)
    guest_cards = "\n".join(render_card(i, "guest") for i in guest_items)
    reviewed_cards = "\n".join(render_card(i, "liked") for i in reviewed)
    responded_cards = "\n".join(render_card(i, "responded") for i in responded_items)
    archived_cards = "\n".join(render_card(i, "archived") for i in archived_items)

    count = len(direct_items)
    guest_count = len(guest_items)
    reviewed_count = len(reviewed)
    responded_count = len(responded_items)
    archived_count = len(archived_items)
    empty_msg = "" if count else '<div class="empty">🎉 All caught up!</div>'

    pub_tabs_html = "\n".join(
        f'<button class="tab-btn" id="tab-btn-{escape(p)}" onclick="switchTab(\'{escape(p)}\')">{escape(p)}</button>'
        for p in all_pubs
    )
    pub_contents_html = "\n".join(
        f'<div id="tab-content-{escape(p)}" style="display:none">{render_post_comments_tab(all_posts_data.get(p, []), p)}</div>'
        for p in all_pubs
    )

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
    .header {{ max-width: 720px; margin: 0 auto 16px; }}
    h1 {{ font-size: 1.6rem; font-weight: 700; margin-bottom: 4px; }}
    .subtitle {{ color: #666; font-size: 0.9rem; }}
    .stats {{ display: flex; gap: 12px; margin-top: 12px; flex-wrap: wrap; }}
    .stat {{
      background: white; border-radius: 8px; padding: 8px 14px;
      font-size: 0.8rem; color: #555; border: 1px solid #e5e5e5;
    }}
    .stat strong {{ color: #1a1a1a; font-size: 1rem; display: block; }}
    .stat-link {{
      text-decoration: none; color: #cc3300;
      border-color: #ffd5cc; background: #fff8f7;
    }}
    .stat-link strong {{ color: #cc3300; font-size: 1rem; }}
    .stat-link:hover {{ background: #fff0ee; border-color: #ff3300; }}
    .gap-warning {{
      max-width: 720px; margin: 10px auto 0;
      background: #fffbe6; border: 1px solid #f0c040; border-radius: 6px;
      padding: 8px 14px; font-size: 0.82rem; color: #7a5c00;
    }}
    .tab-nav {{
      max-width: 720px; margin: 0 auto 20px;
      border-bottom: 2px solid #e5e5e5; display: flex;
    }}
    .tab-btn {{
      background: none; border: none; cursor: pointer;
      font-size: 0.9rem; font-weight: 600; color: #aaa;
      padding: 8px 18px; border-bottom: 2px solid transparent; margin-bottom: -2px;
    }}
    .tab-btn.active {{ color: #1a1a1a; border-bottom-color: #ff3300; }}
    .tab-btn:hover:not(.active) {{ color: #666; }}
    .sync-row {{ display: flex; align-items: center; gap: 10px; margin-top: 14px; flex-wrap: wrap; }}
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
    .load-more-link {{
      font-size: 0.85rem; font-weight: 600; color: #1a1a1a;
      background: white; border: 1px solid #ccc; border-radius: 6px;
      padding: 5px 14px; text-decoration: none; white-space: nowrap;
    }}
    .load-more-link:hover {{ background: #f5f5f5; color: #1a1a1a; }}
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
    .archive-btn {{
      background: none; border: 1px solid #ccc; border-radius: 4px;
      font-size: 0.78rem; color: #999; cursor: pointer; padding: 2px 8px;
    }}
    .archive-btn:hover {{ background: #f5f5f5; color: #555; border-color: #aaa; }}
    .who {{ font-weight: 600; font-size: 0.97rem; margin-bottom: 8px; }}
    .who-link {{ font-weight: 600; color: inherit; text-decoration: none; }}
    .who-link:hover {{ color: #cc3300; text-decoration: underline; }}
    .label {{ font-weight: 400; color: #666; }}
    .field-label {{ font-size: 0.72rem; font-weight: 700; color: #bbb; text-transform: uppercase; letter-spacing: 0.05em; margin-right: 4px; }}
    .your-content {{
      font-size: 0.85rem; color: #888; margin-bottom: 8px;
      padding: 7px 11px; background: #fafafa; border-radius: 6px; border-left: 3px solid #e0e0e0;
    }}
    .thread-context {{ margin-bottom: 8px; }}
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
    .thread-name-link {{ font-weight: 600; color: #888; margin-right: 6px; text-decoration: none; }}
    .thread-name-link:hover {{ color: #cc3300; text-decoration: underline; }}
    .thread-body {{ color: #aaa; }}
    .thread-more {{ background: none; border: none; cursor: pointer; color: #bbb; font-size: 0.78rem; padding: 0; }}
    .thread-more:hover {{ color: #888; }}
    .their-content {{
      font-size: 0.92rem; color: #222;
      padding: 7px 11px; background: #fef8f6; border-radius: 6px; border-left: 3px solid #ff3300;
    }}
    .empty {{ max-width: 720px; margin: 40px auto; text-align: center; font-size: 1.1rem; color: #555; }}
    .toggle-section {{ max-width: 720px; margin: 16px auto 0; }}
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
    .post-section {{
      background: white; border-radius: 10px; padding: 16px 18px;
      border: 1px solid #e5e5e5; margin-bottom: 12px;
      max-width: 720px; margin-left: auto; margin-right: auto;
    }}
    .post-header {{
      display: flex; justify-content: space-between; align-items: baseline;
      margin-bottom: 12px; padding-bottom: 10px; border-bottom: 1px solid #f0f0f0;
    }}
    .post-title {{ font-weight: 700; font-size: 1rem; }}
    .post-title a {{ color: #1a1a1a; text-decoration: none; }}
    .post-title a:hover {{ text-decoration: underline; }}
    .post-date {{ font-size: 0.8rem; color: #bbb; flex-shrink: 0; margin-left: 12px; }}
    .post-empty {{ font-size: 0.85rem; color: #aaa; padding: 4px 0; }}
    .post-comment-card {{
      padding: 10px 0; border-bottom: 1px solid #f5f5f5;
    }}
    .post-comment-card:last-child {{ border-bottom: none; }}
    .posts-controls {{ max-width: 720px; margin: 0 auto 20px; }}
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
      <!-- insights link hidden: <a href="/insights" target="_blank" class="stat stat-link"><strong>Insights</strong>Dashboard →</a> -->
    </div>
    {f'<div class="gap-warning">⚠️ {stats["gap_warning"]}</div>' if stats.get("gap_warning") else ""}
  </div>

  <div class="intro">
    Track and respond to comments across your Substack publications. <strong>Replies</strong> shows activity from your notes and comments. Each publication tab shows unanswered comments on your posts — load posts to build up the list, sync to refresh.
    <button class="how-it-works-toggle" onclick="toggleHowItWorks(this)">How it works ▾</button>
    <div class="how-it-works" id="how-it-works">
      <h3>Replies tab</h3>
      Shows notes and comments across Substack where someone replied to you and you haven't responded yet.
      <h3>Publication tabs</h3>
      Shows unanswered comments on your own posts. Click <strong>Load posts</strong> to fetch posts (newest first) until you hit your target count of unanswered comments. <strong>Sync</strong> refreshes already-loaded posts with the latest comments.
      <h3>Liked = acknowledged</h3>
      If you've liked a comment on Substack, it's treated as acknowledged and moved to a collapsed section rather than shown as needing a response.
      <h3>Keeping data fresh</h3>
      Data lives in a local database and persists across page refreshes. Use Sync to update it.
    </div>
  </div>

  <div id="sync-busy-banner" style="display:none; max-width:720px; margin:0 auto 16px; background:#fff3cd; border:1px solid #ffc107; border-radius:8px; padding:10px 16px; font-size:0.88rem; color:#856404;">
    A sync is already in progress. Please wait for it to finish before starting another.
  </div>

  <div class="tab-nav">
    <button class="tab-btn" id="tab-btn-replies" onclick="switchTab('replies')">Replies</button>
    {pub_tabs_html}
  </div>

  <div id="tab-replies">
    <div style="max-width:720px; margin:0 auto;">
      <div style="margin-bottom:14px;">
        <input type="text" id="commenter-search" placeholder="Filter by name or @handle…" oninput="filterByName(this.value)"
               style="width:100%; padding:8px 12px; border:1px solid #ddd; border-radius:6px; font-size:0.9rem; background:white;">
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

    <div class="count-banner {'zero' if count == 0 else ''}" id="banner">
      {"🎉 All caught up!" if count == 0 else f"⚡ <span id='remaining'>{count}</span> {'reply' if count == 1 else 'replies'} need your response"}
    </div>

    <div class="cards" id="action-cards">
      {action_cards}
      {empty_msg}
    </div>

    {"<div class='toggle-section' id='guest-toggle-wrap'><button class='toggle-btn' onclick='toggleGuest(this)'>▶ Co-authored &amp; guest posts (<span id='guest-count'>" + str(guest_count) + "</span>)</button><div class='liked-section' id='guest-section'><div class='cards' id='guest-cards'>" + guest_cards + "</div></div></div>" if guest_count else ""}
    {"<div class='toggle-section' id='liked-toggle-wrap'><button class='toggle-btn' onclick='toggleLiked(this)'>▶ Liked only — no reply (<span id='liked-count'>" + str(reviewed_count) + "</span>)</button><div class='liked-section' id='liked-section'><div class='cards' id='liked-cards'>" + reviewed_cards + "</div></div></div>" if reviewed_count else ""}
    {"<div class='toggle-section' id='responded-toggle-wrap'><button class='toggle-btn' onclick='toggleResponded(this)'>▶ Responded (<span id='responded-count'>" + str(responded_count) + "</span>)</button><div class='liked-section' id='responded-section'><div class='cards' id='responded-cards'>" + responded_cards + "</div></div></div>" if responded_count else ""}
    {"<div class='toggle-section' id='archived-toggle-wrap'><button class='toggle-btn' onclick='toggleArchived(this)'>▶ Archived (<span id='archived-count'>" + str(archived_count) + "</span>)</button><div class='liked-section' id='archived-section'><div class='cards' id='archived-cards'>" + archived_cards + "</div></div></div>" if archived_count else ""}
  </div>

  {pub_contents_html}

  <script>
    const initTab = "{active_tab}";

    const allPubs = {json.dumps(all_pubs)};

    function switchTab(tab) {{
      // Hide all tabs
      document.getElementById('tab-replies').style.display = 'none';
      allPubs.forEach(p => {{
        const el = document.getElementById('tab-content-' + p);
        if (el) el.style.display = 'none';
        const btn = document.getElementById('tab-btn-' + p);
        if (btn) btn.classList.remove('active');
      }});
      document.getElementById('tab-btn-replies').classList.remove('active');

      // Show active tab
      if (tab === 'replies') {{
        document.getElementById('tab-replies').style.display = '';
        document.getElementById('tab-btn-replies').classList.add('active');
      }} else {{
        const el = document.getElementById('tab-content-' + tab);
        if (el) el.style.display = '';
        const btn = document.getElementById('tab-btn-' + tab);
        if (btn) btn.classList.add('active');
      }}

      localStorage.setItem('activeTab', tab);
      const url = new URL(window.location);
      url.searchParams.set('tab', tab);
      history.replaceState({{}}, '', url);
    }}

    let _loadEs = null;

    function startLoadPosts(btn, pub) {{
      const count = document.getElementById('load-count-' + pub).value;
      const stopBtn = document.getElementById('load-stop-btn-' + pub);
      const status = document.getElementById('posts-sync-status-' + pub);
      const log = document.getElementById('posts-sync-log-' + pub);
      btn.style.display = 'none';
      stopBtn.style.display = '';
      status.textContent = 'Loading…';
      // Don't clear the log until we know the sync actually started
      log.style.display = 'block';

      _loadEs = new EventSource('/posts/load?pub=' + encodeURIComponent(pub) + '&count=' + count);
      _loadEs.onmessage = function(e) {{
        if (e.data === '__done__') {{
          _loadEs.close(); _loadEs = null;
          localStorage.setItem('lastPostsSyncLog_' + pub, log.textContent);
          status.textContent = 'Done — reloading…';
          setTimeout(() => window.location.href = '/?tab=' + encodeURIComponent(pub), 1500);
          return;
        }}
        if (e.data === '__error__') {{
          _loadEs.close(); _loadEs = null;
          btn.style.display = ''; stopBtn.style.display = 'none';
          log.style.display = 'none';
          status.textContent = 'Sync already in progress — try again when it finishes.';
          return;
        }}
        if (!log.dataset.started) {{
          log.textContent = '';
          log.dataset.started = '1';
        }}
        log.textContent += e.data + '\\n';
        log.scrollTop = log.scrollHeight;
        status.textContent = e.data;
        localStorage.setItem('lastPostsSyncLog_' + pub, log.textContent);
      }};
      _loadEs.onerror = function() {{
        _loadEs.close(); _loadEs = null;
        fetch('/sync/status').then(r => r.json()).then(data => {{
          if (data.running) {{
            btn.style.display = 'none'; stopBtn.style.display = '';
            status.textContent = 'Connection lost — sync still running in background…';
            var poll = setInterval(() => {{
              fetch('/sync/status').then(r => r.json()).then(d => {{
                if (!d.running) {{ clearInterval(poll); status.textContent = 'Done — reloading…'; setTimeout(() => window.location.reload(), 1500); }}
              }});
            }}, 5000);
          }} else {{
            btn.style.display = ''; stopBtn.style.display = 'none';
            status.textContent = 'Connection lost — reloading…';
            setTimeout(() => window.location.reload(), 2000);
          }}
        }}).catch(() => {{ btn.style.display = ''; stopBtn.style.display = 'none'; status.textContent = 'Connection lost.'; }});
      }};
    }}

    function stopPostsLoad(pub) {{
      if (_loadEs) {{ _loadEs.close(); _loadEs = null; }}
      fetch('/sync/stop', {{method: 'POST'}});
      document.getElementById('load-btn-' + pub).style.display = '';
      document.getElementById('load-stop-btn-' + pub).style.display = 'none';
      document.getElementById('posts-sync-status-' + pub).textContent = 'Stopped.';
    }}

    function toggleSection(btn) {{
      const section = btn.nextElementSibling;
      const open = section.style.display === 'block';
      section.style.display = open ? 'none' : 'block';
      btn.textContent = open
        ? btn.textContent.replace('▼', '▶').replace('Hide', 'Show')
        : btn.textContent.replace('▶', '▼').replace('Show', 'Hide');
    }}

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

    function toggleGuest(btn) {{
      const section = document.getElementById('guest-section');
      const open = section.style.display === 'block';
      section.style.display = open ? 'none' : 'block';
      const count = document.getElementById('guest-count');
      btn.innerHTML = (open ? '▶ Co-authored &amp; guest posts' : '▼ Co-authored &amp; guest posts') + ' (<span id="guest-count">' + (count ? count.textContent : '') + '</span>)';
    }}

    function toggleLiked(btn) {{
      const section = document.getElementById('liked-section');
      const open = section.style.display === 'block';
      section.style.display = open ? 'none' : 'block';
      const count = document.getElementById('liked-count');
      const label = count ? ' (' + count.textContent + ')' : '';
      btn.innerHTML = (open ? '▶ Liked only — no reply' : '▼ Liked only — no reply') + ' (<span id="liked-count">' + (count ? count.textContent : '') + '</span>)';
    }}

    function toggleResponded(btn) {{
      const section = document.getElementById('responded-section');
      const open = section.style.display === 'block';
      section.style.display = open ? 'none' : 'block';
      const count = document.getElementById('responded-count');
      btn.innerHTML = (open ? '▶ Responded' : '▼ Responded') + ' (<span id="responded-count">' + (count ? count.textContent : '') + '</span>)';
    }}

    function toggleArchived(btn) {{
      const section = document.getElementById('archived-section');
      const open = section.style.display === 'block';
      section.style.display = open ? 'none' : 'block';
      const count = document.getElementById('archived-count');
      btn.innerHTML = (open ? '▶ Archived' : '▼ Archived') + ' (<span id="archived-count">' + (count ? count.textContent : '') + '</span>)';
    }}

    function archiveCard(btn, commentId) {{
      fetch('/archive', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{comment_id: commentId}})
      }}).then(r => r.json()).then(data => {{
        if (data.ok) {{
          const card = btn.closest('.card');
          card.style.display = 'none';
          const remaining = document.getElementById('remaining');
          if (remaining) remaining.textContent = Math.max(0, parseInt(remaining.textContent) - 1);
        }}
      }});
    }}

    function filterByName(q) {{
      q = q.toLowerCase().trim();

      // Helper: filter cards in a container, return visible count
      function filterCards(containerId, q) {{
        const cards = document.querySelectorAll('#' + containerId + ' .card');
        let visible = 0;
        cards.forEach(card => {{
          const who = (card.dataset.who || '').toLowerCase();
          const show = !q || who.includes(q);
          card.style.display = show ? '' : 'none';
          if (show) visible++;
        }});
        return visible;
      }}

      // Unanswered — also clear show-more hiding when filtering
      const actionCards = document.querySelectorAll('#action-cards .card');
      let visibleAction = 0;
      actionCards.forEach(card => {{
        const who = (card.dataset.who || '').toLowerCase();
        const show = !q || who.includes(q);
        card.style.display = show ? '' : 'none';
        if (show) visibleAction++;
      }});
      // Remove show-more button when filtering
      const showMoreWrap = document.getElementById('show-more-btn');
      if (showMoreWrap) showMoreWrap.closest('.toggle-section').style.display = q ? 'none' : '';
      const remaining = document.getElementById('remaining');
      if (remaining) remaining.textContent = visibleAction;

      // Guest / co-authored
      const visibleGuest = filterCards('guest-cards', q);
      const guestCount = document.getElementById('guest-count');
      if (guestCount) guestCount.textContent = visibleGuest;
      const guestWrap = document.getElementById('guest-toggle-wrap');
      if (guestWrap) {{
        guestWrap.style.display = (!q || visibleGuest > 0) ? '' : 'none';
      }}

      // Liked
      const visibleLiked = filterCards('liked-cards', q);
      const likedCount = document.getElementById('liked-count');
      if (likedCount) likedCount.textContent = visibleLiked;
      const likedWrap = document.getElementById('liked-toggle-wrap');
      if (likedWrap) {{
        likedWrap.style.display = (!q || visibleLiked > 0) ? '' : 'none';
      }}

      // Responded
      const visibleResponded = filterCards('responded-cards', q);
      const respondedCount = document.getElementById('responded-count');
      if (respondedCount) respondedCount.textContent = visibleResponded;
      const respondedWrap = document.getElementById('responded-toggle-wrap');
      if (respondedWrap) {{
        respondedWrap.style.display = (!q || visibleResponded > 0) ? '' : 'none';
      }}

      // Archived
      const visibleArchived = filterCards('archived-cards', q);
      const archivedCount = document.getElementById('archived-count');
      if (archivedCount) archivedCount.textContent = visibleArchived;
      const archivedWrap = document.getElementById('archived-toggle-wrap');
      if (archivedWrap) {{
        archivedWrap.style.display = (!q || visibleArchived > 0) ? '' : 'none';
      }}
    }}

    (function initShowMore() {{
      const SHOW = 10;
      const cards = document.querySelectorAll('#action-cards .card');
      if (cards.length <= SHOW) return;
      for (let i = SHOW; i < cards.length; i++) {{
        cards[i].classList.add('hidden-card');
        cards[i].style.display = 'none';
      }}
      const btn = document.createElement('div');
      btn.className = 'toggle-section';
      btn.innerHTML = '<button class="toggle-btn" id="show-more-btn" onclick="showMoreCards(this)">▶ Show ' + (cards.length - SHOW) + ' more replies</button>';
      document.getElementById('action-cards').after(btn);
    }})();

    function showMoreCards(btn) {{
      document.querySelectorAll('#action-cards .hidden-card').forEach(c => c.style.display = '');
      btn.closest('.toggle-section').remove();
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
      allPubs.forEach(p => {{
        const savedPosts = localStorage.getItem('lastPostsSyncLog_' + p);
        if (savedPosts) {{
          const wrap = document.getElementById('last-posts-sync-log-wrap-' + p);
          const pre = document.getElementById('last-posts-sync-log-' + p);
          if (wrap && pre) {{ pre.textContent = savedPosts; wrap.style.display = ''; }}
        }}
      }});
    }})();

    function toggleLastLog(btn) {{
      const pre = document.getElementById('last-sync-log');
      const open = pre.style.display === 'block';
      pre.style.display = open ? 'none' : 'block';
      btn.textContent = open ? '▶ Last sync log' : '▼ Last sync log';
    }}

    function toggleLastPostsLog(btn, pub) {{
      const pre = document.getElementById('last-posts-sync-log-' + pub);
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
          _es.close(); _es = null;
          localStorage.setItem('lastSyncLog', log.textContent);
          status.textContent = 'Done — reloading…';
          setTimeout(() => window.location.href = '/?tab=replies', 1500);
          return;
        }}
        if (e.data === '__error__') {{
          _es.close(); _es = null;
          btn.style.display = ''; stopBtn.style.display = 'none';
          status.textContent = 'Could not start sync.';
          return;
        }}
        log.textContent += e.data + '\\n';
        log.scrollTop = log.scrollHeight;
        status.textContent = e.data;
        localStorage.setItem('lastSyncLog', log.textContent);
      }};
      _es.onerror = function() {{
        _es.close(); _es = null;
        fetch('/sync/status').then(r => r.json()).then(data => {{
          if (data.running) {{
            btn.style.display = 'none'; stopBtn.style.display = '';
            status.textContent = 'Connection lost (computer may have slept) — sync is still running in background…';
            _pollUntilDone();
          }} else {{
            btn.style.display = ''; stopBtn.style.display = 'none';
            status.textContent = 'Connection lost — sync may have completed. Reloading…';
            setTimeout(() => window.location.reload(), 2000);
          }}
        }}).catch(() => {{
          btn.style.display = ''; stopBtn.style.display = 'none';
          status.textContent = 'Connection lost — reload to check status.';
        }});
      }};
      function _pollUntilDone() {{
        setTimeout(() => {{
          fetch('/sync/status').then(r => r.json()).then(data => {{
            if (data.running) {{
              status.textContent = 'Sync still running in background… (reload to see progress)';
              _pollUntilDone();
            }} else {{
              status.textContent = 'Sync complete — reloading…';
              setTimeout(() => window.location.reload(), 1500);
            }}
          }}).catch(() => _pollUntilDone());
        }}, 5000);
      }}
    }}

    function stopSync() {{
      if (_es) {{ _es.close(); _es = null; }}
      fetch('/sync/stop', {{method: 'POST'}});
      document.getElementById('sync-btn').style.display = '';
      document.getElementById('stop-btn').style.display = 'none';
      document.getElementById('sync-status').textContent = 'Stopped.';
    }}

    let _postsEs = null;

    function startPostsSync(pub) {{
      const btn = document.getElementById('posts-sync-btn-' + pub);
      const stopBtn = document.getElementById('posts-stop-btn-' + pub);
      const status = document.getElementById('posts-sync-status-' + pub);
      const log = document.getElementById('posts-sync-log-' + pub);
      btn.style.display = 'none';
      stopBtn.style.display = '';
      status.textContent = 'Starting…';
      log.style.display = 'block';

      _postsEs = new EventSource('/posts/sync?pub=' + encodeURIComponent(pub));
      _postsEs.onmessage = function(e) {{
        if (e.data === '__done__') {{
          _postsEs.close(); _postsEs = null;
          localStorage.setItem('lastPostsSyncLog_' + pub, log.textContent);
          status.textContent = 'Done — reloading…';
          setTimeout(() => window.location.href = '/?tab=' + encodeURIComponent(pub), 1500);
          return;
        }}
        if (e.data === '__error__') {{
          _postsEs.close(); _postsEs = null;
          btn.style.display = ''; stopBtn.style.display = 'none';
          log.style.display = 'none';
          status.textContent = 'Sync already in progress — try again when it finishes.';
          return;
        }}
        if (!log.dataset.started) {{
          log.textContent = '';
          log.dataset.started = '1';
        }}
        log.textContent += e.data + '\\n';
        log.scrollTop = log.scrollHeight;
        status.textContent = e.data;
        localStorage.setItem('lastPostsSyncLog_' + pub, log.textContent);
      }};
      _postsEs.onerror = function() {{
        _postsEs.close(); _postsEs = null;
        fetch('/sync/status').then(r => r.json()).then(data => {{
          if (data.running) {{
            btn.style.display = 'none'; stopBtn.style.display = '';
            status.textContent = 'Connection lost — sync still running in background…';
            var poll = setInterval(() => {{
              fetch('/sync/status').then(r => r.json()).then(d => {{
                if (!d.running) {{ clearInterval(poll); status.textContent = 'Done — reloading…'; setTimeout(() => window.location.reload(), 1500); }}
              }});
            }}, 5000);
          }} else {{
            btn.style.display = ''; stopBtn.style.display = 'none';
            status.textContent = 'Connection lost — reloading…';
            setTimeout(() => window.location.reload(), 2000);
          }}
        }}).catch(() => {{ btn.style.display = ''; stopBtn.style.display = 'none'; status.textContent = 'Connection lost.'; }});
      }};
    }}

    function stopPostsSync(pub) {{
      if (_postsEs) {{ _postsEs.close(); _postsEs = null; }}
      fetch('/sync/stop', {{method: 'POST'}});
      document.getElementById('posts-sync-btn-' + pub).style.display = '';
      document.getElementById('posts-stop-btn-' + pub).style.display = 'none';
      document.getElementById('posts-sync-status-' + pub).textContent = 'Stopped.';
    }}

    // Initialize tab from server-side value or localStorage
    (function() {{
      const tab = initTab || localStorage.getItem('activeTab') || 'replies';
      switchTab(tab);
    }})();

    // Check if a sync is already running (another user may have started one)
    fetch('/sync/status')
      .then(r => r.json())
      .then(data => {{
        if (data.running) {{
          document.getElementById('sync-busy-banner').style.display = '';
        }}
      }})
      .catch(() => {{}});
  </script>
</body>
</html>"""

