#!/usr/bin/env python3
"""
Substack Reply Tracker
Fetches replies to your comments/notes across all of Substack and surfaces ones you haven't responded to.

Usage:
  export SUBSTACK_SID="your-cookie-value"
  python scraper.py sync     # fetch new data
  python scraper.py report   # show what needs responses
  python scraper.py sync report  # do both
"""

import os
import sys
import json
import sqlite3
import time
import requests
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.parse import unquote

# ── Config ────────────────────────────────────────────────────────────────────

try:
    from config import USER_ID, HANDLE, OWN_PUBS
except ImportError:
    print("Error: config.py not found. Copy config.example.py to config.py and fill in your values.")
    sys.exit(1)

DB_PATH = Path(__file__).parent / "replies.db"

REPLY_TYPES = {"note_reply", "comment_reply", "new_comment"}

# ── HTTP ──────────────────────────────────────────────────────────────────────

def get_headers():
    sid = os.environ.get("SUBSTACK_SID", "")
    if not sid:
        print("ERROR: Set SUBSTACK_SID environment variable.")
        sys.exit(1)
    cookie = unquote(sid)
    return {
        "Cookie": f"substack.sid={cookie}",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json",
    }

def get(url, params=None, retries=4):
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=get_headers(), params=params, timeout=15)
        except requests.exceptions.RequestException as e:
            if attempt == retries - 1:
                raise
            time.sleep(5)
            continue
        if resp.status_code == 429:
            wait = 60 * (attempt + 1)
            print(f"  Rate limited, waiting {wait}s...")
            time.sleep(wait)
            continue
        if resp.status_code >= 500:
            if attempt == retries - 1:
                resp.raise_for_status()
            time.sleep(5 * (attempt + 1))
            continue
        resp.raise_for_status()
        return resp.json()
    raise Exception(f"Failed after {retries} retries: {url}")

# ── DB ────────────────────────────────────────────────────────────────────────

def init_db(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS activity_items (
            id TEXT PRIMARY KEY,
            type TEXT,
            created_at TEXT,
            updated_at TEXT,
            comment_id INTEGER,        -- the reply comment (by someone else)
            target_comment_id INTEGER, -- your comment that was replied to
            target_post_id INTEGER,
            is_new INTEGER,
            raw_json TEXT
        );

        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY,
            pub_subdomain TEXT,
            post_id INTEGER,
            post_title TEXT,
            post_url TEXT,
            parent_id INTEGER,
            ancestor_path TEXT,
            user_id INTEGER,
            handle TEXT,
            name TEXT,
            body TEXT,
            date TEXT,
            raw_json TEXT
        );

        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY,
            pub_subdomain TEXT,
            title TEXT,
            slug TEXT,
            canonical_url TEXT,
            post_date TEXT,
            comment_count INTEGER
        );

        CREATE TABLE IF NOT EXISTS sync_log (
            synced_at TEXT,
            type TEXT,
            items_fetched INTEGER
        );

        CREATE TABLE IF NOT EXISTS sync_state (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    conn.commit()

# ── Activity Feed Sync ────────────────────────────────────────────────────────

def sync_activity_feed(conn, days=60, target=100):
    """Paginate through activity-feed-web and store all items up to `days` old."""
    url = "https://substack.com/api/v1/activity-feed-web"
    after = None
    total = 0
    pages = 0
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    while True:
        params = {"limit": 10}
        if after:
            params["after"] = after

        data = get(url, params)
        items = data.get("activityItems", [])

        if not items:
            break

        print(f"  [activity] page {pages+1}: fetched {len(items)} items (total stored: {total})", flush=True)
        new_this_page = 0
        for item in items:
            # Stop if older than cutoff
            item_ts = item.get("updated_at") or item.get("created_at") or ""
            if item_ts and item_ts < cutoff:
                conn.commit()
                unanswered = count_unanswered_activity(conn)
                print(f"  Activity feed: {total} new items ({pages+1} pages, reached {days}-day cutoff), {unanswered} unanswered")
                return unanswered

            existing = conn.execute(
                "SELECT id FROM activity_items WHERE id=?", (item["id"],)
            ).fetchone()
            if existing:
                continue

            conn.execute("""
                INSERT OR IGNORE INTO activity_items
                (id, type, created_at, updated_at, comment_id, target_comment_id,
                 target_post_id, is_new, raw_json)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                item["id"],
                item.get("type"),
                item.get("created_at"),
                item.get("updated_at"),
                item.get("comment_id"),
                item.get("target_comment_id"),
                item.get("target_post_id"),
                1 if item.get("isNew") else 0,
                json.dumps(item),
            ))

            # Store feed item comments (the full thread context)
            for fic in data.get("feedItemComments", []):
                post = fic.get("post") or {}
                post_url = post.get("canonical_url")
                post_title = post.get("title")
                post_id_fic = post.get("id")
                c = fic.get("comment")
                if c:
                    _store_comment(conn, c, pub_subdomain=None, post_id=post_id_fic or c.get("post_id"), post_title=post_title, post_url=post_url)
                for pc in fic.get("parentComments", []):
                    _store_comment(conn, pc, pub_subdomain=None, post_id=post_id_fic or pc.get("post_id"), post_title=post_title, post_url=post_url)

            new_this_page += 1

        total += new_this_page
        pages += 1

        if not data.get("more"):
            break

        conn.commit()  # save progress after each page

        unanswered = count_unanswered_activity(conn)
        print(f"    {unanswered} unanswered activity replies so far", flush=True)
        if unanswered >= target:
            print(f"  Reached target of {target} unanswered activity replies — stopping feed sync")
            return unanswered

        time.sleep(2)  # be polite

        # Pagination: use min(updated_at) - 1ms
        updated_ats = [item.get("updated_at") or item.get("created_at") for item in items if item.get("updated_at") or item.get("created_at")]
        if not updated_ats:
            break
        min_ts = min(updated_ats)
        # Subtract 1ms
        dt = datetime.fromisoformat(min_ts.replace("Z", "+00:00"))
        after = (dt - timedelta(milliseconds=1)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    conn.commit()
    unanswered = count_unanswered_activity(conn)
    print(f"  Activity feed: {total} new items ({pages} pages), {unanswered} unanswered")
    return unanswered


def _store_comment(conn, c, pub_subdomain, post_id, post_title, post_url):
    if not c or not c.get("id"):
        return
    conn.execute("""
        INSERT OR IGNORE INTO comments
        (id, pub_subdomain, post_id, post_title, post_url,
         parent_id, ancestor_path, user_id, handle, name, body, date, raw_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        c["id"],
        pub_subdomain,
        post_id or c.get("post_id"),
        post_title,
        post_url,
        _parent_id(c.get("ancestor_path", "")),
        c.get("ancestor_path", ""),
        c.get("user_id"),
        c.get("handle"),
        c.get("name"),
        c.get("body", ""),
        c.get("date"),
        json.dumps(c),
    ))

def _parent_id(ancestor_path):
    if not ancestor_path:
        return None
    parts = ancestor_path.split(".")
    return int(parts[-1]) if parts[-1] else None

# ── Own Publication Sync ──────────────────────────────────────────────────────

def count_unanswered_activity(conn):
    """Count unanswered replies from the activity feed."""
    return conn.execute("""
        SELECT COUNT(*) FROM activity_items a
        WHERE a.type IN ('note_reply', 'comment_reply')
          AND a.comment_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM comments r
              WHERE r.user_id = ?
                AND r.ancestor_path LIKE '%' || a.comment_id || '%'
                AND r.id > a.comment_id
          )
    """, (USER_ID,)).fetchone()[0]


def count_unanswered_own(conn):
    """Approximate count of unanswered comments on own pub posts."""
    return conn.execute("""
        SELECT COUNT(*) FROM comments c
        WHERE c.pub_subdomain IS NOT NULL
          AND c.user_id != ?
          AND c.user_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM comments r
              WHERE r.user_id = ?
                AND (r.ancestor_path = CAST(c.id AS TEXT)
                     OR r.ancestor_path LIKE '%.' || c.id
                     OR r.ancestor_path LIKE '%.' || c.id || '.%')
          )
    """, (USER_ID, USER_ID)).fetchone()[0]


def sync_own_pubs(conn, target=100, already_found=0):
    """Scrape comments on posts from own publications.

    Fetches newest posts first. Skips posts whose comment_count hasn't changed
    since the last sync. Stops extending into older posts once the total number of
    unanswered replies (activity + own pubs) reaches `target`.
    """
    total_comments = 0

    for subdomain in OWN_PUBS:
        print(f"  Syncing {subdomain}...")

        # Load watermark: how many posts deep we've previously synced
        row = conn.execute(
            "SELECT value FROM sync_state WHERE key=?",
            (f"own_pubs_{subdomain}_depth",)
        ).fetchone()
        prev_depth = int(row[0]) if row else 0
        new_depth = prev_depth

        print(f"  Fetching post list for {subdomain}...", flush=True)
        all_posts = fetch_all_posts(subdomain)
        print(f"  {len(all_posts)} posts found", flush=True)
        fetched_this_run = 0

        for i, post in enumerate(all_posts):
            post_id = post["id"]
            api_count = post.get("comment_count", 0)
            post_title = post.get("title", "")
            post_url = post.get("canonical_url", f"https://{subdomain}.substack.com/p/{post.get('slug','')}")

            # Check old state before upserting
            old_row = conn.execute(
                "SELECT comment_count FROM posts WHERE id=?", (post_id,)
            ).fetchone()
            already_synced = old_row is not None and i < prev_depth
            count_unchanged = old_row is not None and old_row[0] == api_count

            # Always update post metadata
            conn.execute("""
                INSERT OR REPLACE INTO posts (id, pub_subdomain, title, slug, canonical_url, post_date, comment_count)
                VALUES (?,?,?,?,?,?,?)
            """, (post_id, subdomain, post_title, post.get("slug"), post_url, post.get("post_date"), api_count))

            # Skip posts we've already synced where nothing changed
            if already_synced and count_unchanged:
                print(f"    [{i+1}/{len(all_posts)}] skip (unchanged): {post_title[:60]}", flush=True)
                continue

            # Skip posts with no comments — nothing to fetch
            if api_count == 0:
                print(f"    [{i+1}/{len(all_posts)}] skip (0 comments): {post_title[:60]}", flush=True)
                continue

            # For posts beyond our previous watermark, check if target is reached
            if i >= prev_depth:
                unanswered = already_found + count_unanswered_own(conn)
                if unanswered >= target:
                    print(f"    Reached target of {target} unanswered — stopping at post {i + 1}/{len(all_posts)}")
                    break
                new_depth = i + 1

            # Fetch comments for this post
            print(f"    [{i+1}/{len(all_posts)}] fetching: {post_title[:60]} ({api_count} comments)", flush=True)
            time.sleep(1)
            comments = fetch_post_comments(subdomain, post_id)
            for c in flatten_comments(comments):
                _store_comment(conn, c, pub_subdomain=subdomain, post_id=post_id, post_title=post_title, post_url=post_url)
                total_comments += 1
            fetched_this_run += 1

        # Save updated watermark
        conn.execute(
            "INSERT OR REPLACE INTO sync_state (key, value) VALUES (?,?)",
            (f"own_pubs_{subdomain}_depth", str(new_depth))
        )
        conn.commit()
        print(f"    {subdomain}: {new_depth}/{len(all_posts)} posts synced depth, {fetched_this_run} refreshed this run")

    return total_comments


def backfill_post_urls(conn):
    """Fetch canonical URLs for comments that have a post_id but no post_url."""
    rows = conn.execute("""
        SELECT DISTINCT post_id FROM comments
        WHERE post_id IS NOT NULL AND post_url IS NULL
    """).fetchall()

    if not rows:
        print("  No missing post URLs to backfill.")
        return

    print(f"  Backfilling URLs for {len(rows)} posts...")
    for (post_id,) in rows:
        try:
            data = get(f"https://substack.com/api/v1/posts/by-id/{post_id}")
            post = data.get("post", {})
            url = post.get("canonical_url")
            title = post.get("title")
            if url:
                conn.execute("""
                    UPDATE comments SET post_url=?, post_title=?
                    WHERE post_id=? AND post_url IS NULL
                """, (url, title, post_id))
            time.sleep(0.5)
        except Exception as e:
            print(f"    Warning: couldn't fetch post {post_id}: {e}")
    conn.commit()
    print("  Backfill complete.")


def fetch_all_posts(subdomain, limit=50):
    """Fetch all posts for a publication."""
    url = f"https://{subdomain}.substack.com/api/v1/posts"
    posts = []
    offset = 0
    while True:
        batch = get(url, {"limit": limit, "offset": offset})
        if not batch:
            break
        posts.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    return posts


def fetch_post_comments(subdomain, post_id):
    """Fetch all comments for a post."""
    url = f"https://{subdomain}.substack.com/api/v1/post/{post_id}/comments"
    try:
        data = get(url)
        return data.get("comments", [])
    except Exception as e:
        print(f"    Warning: couldn't fetch comments for post {post_id}: {e}")
        return []


def flatten_comments(comments):
    """Recursively flatten nested comment children."""
    result = []
    for c in comments:
        result.append(c)
        for child in c.get("children", []):
            result.extend(flatten_comments([child]))
    return result

# ── Report ────────────────────────────────────────────────────────────────────

def report(conn):
    print(f"\n{'='*65}")
    print(f"  SUBSTACK REPLIES NEEDING RESPONSE")
    print(f"{'='*65}\n")

    found = 0

    # 1. Replies to your notes/comments from the activity feed
    found += report_activity_replies(conn)

    # 2. Unresponded comments on your own posts
    found += report_own_pub_comments(conn)

    if found == 0:
        print("All caught up! No unresponded replies found.\n")


def report_activity_replies(conn):
    """Show activity feed items where someone replied to you and you haven't replied back."""
    # Get all note_reply and comment_reply type items
    rows = conn.execute("""
        SELECT a.id, a.type, a.created_at, a.comment_id, a.target_comment_id
        FROM activity_items a
        WHERE a.type IN ('note_reply', 'comment_reply')
        ORDER BY a.created_at DESC
    """).fetchall()

    found = 0
    for row in rows:
        item_id, item_type, created_at, reply_comment_id, your_comment_id = row

        if not reply_comment_id or not your_comment_id:
            continue

        # Check if you have a comment AFTER the reply in the same thread
        # (i.e., you replied back)
        your_reply = conn.execute("""
            SELECT id FROM comments
            WHERE user_id = ?
              AND ancestor_path LIKE ?
              AND id > ?
        """, (USER_ID, f"%{reply_comment_id}%", reply_comment_id)).fetchone()

        if your_reply:
            continue  # you already responded

        # Get the reply comment details
        reply = conn.execute(
            "SELECT name, handle, body, post_id FROM comments WHERE id=?", (reply_comment_id,)
        ).fetchone()

        # Get your original comment
        yours = conn.execute(
            "SELECT body, post_id FROM comments WHERE id=?", (your_comment_id,)
        ).fetchone()

        if not reply:
            # We have the activity item but not the comment body stored
            raw = conn.execute("SELECT raw_json FROM activity_items WHERE id=?", (item_id,)).fetchone()
            data = json.loads(raw[0]) if raw else {}
            name = "Someone"
            body = "(comment body not fetched)"
            post_id = data.get("target_post_id")
        else:
            name = reply[0] or reply[1] or "Someone"
            body = (reply[2] or "")[:120]
            post_id = reply[3]

        your_body = (yours[1] if yours else "") or ""

        date_str = created_at[:10] if created_at else ""
        type_label = "replied to your note" if item_type == "note_reply" else "replied to your comment"

        print(f"[{date_str}] {name} {type_label}")
        if your_body:
            print(f"  Your comment: \"{your_body[:80]}{'...' if len(your_body)>80 else ''}\"")
        print(f"  Their reply:  \"{body[:100]}{'...' if len(body)>100 else ''}\"")
        # Build a best-effort link
        if post_id:
            print(f"  Link: https://substack.com/p/{post_id}/comment/{reply_comment_id}")
        print()
        found += 1

    return found


def report_own_pub_comments(conn):
    """Show comments on your own posts that you haven't replied to."""
    found = 0

    # Get all top-level and reply comments on your posts that are NOT by you
    # and where you have no child comment after them
    rows = conn.execute("""
        SELECT c.id, c.name, c.handle, c.body, c.date, c.post_title, c.post_url, c.ancestor_path, c.post_id
        FROM comments c
        WHERE c.pub_subdomain IS NOT NULL
          AND c.user_id != ?
          AND c.user_id IS NOT NULL
        ORDER BY c.date DESC
    """, (USER_ID,)).fetchall()

    for row in rows:
        cid, name, handle, body, date, post_title, post_url, ancestor_path, post_id = row

        # Check if you have a reply to this comment
        your_reply = conn.execute("""
            SELECT id FROM comments
            WHERE user_id = ?
              AND (ancestor_path = ? OR ancestor_path LIKE ?)
        """, (USER_ID, str(cid), f"%.{cid}%")).fetchone()

        if your_reply:
            continue

        # Only show if the comment is addressed to you somehow or is a reply in a thread you started
        # For top-level comments (ancestor_path=""), always show
        # For replies, only show if you're an ancestor in the thread
        if ancestor_path:
            # Check if you're in the ancestor chain
            ancestor_ids = [int(x) for x in ancestor_path.split(".") if x]
            your_in_thread = conn.execute(
                f"SELECT id FROM comments WHERE user_id=? AND id IN ({','.join('?'*len(ancestor_ids))})",
                [USER_ID] + ancestor_ids
            ).fetchone() if ancestor_ids else None
            if not your_in_thread:
                continue

        date_str = (date or "")[:10]
        author = name or handle or "Anonymous"
        body_short = (body or "")[:120]
        post_label = post_title or f"post {post_id}"
        link = post_url or ""
        if link and cid:
            link = f"{link.rstrip('/')}/comment/{cid}"

        print(f"[{date_str}] {author} commented on your post")
        print(f"  Post:    \"{post_label[:60]}\"")
        print(f"  Comment: \"{body_short}{'...' if len(body or '')>120 else ''}\"")
        if link:
            print(f"  Link:    {link}")
        print()
        found += 1

    return found

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    args = set(sys.argv[1:])
    if not args:
        print("Usage: python scraper.py [sync] [report]")
        sys.exit(0)

    with sqlite3.connect(DB_PATH) as conn:
        init_db(conn)

        # Parse --days N (default 60) and --target N (default 100)
        days = 60
        target = 100
        for i, arg in enumerate(sys.argv[1:]):
            if arg == "--days" and i + 2 < len(sys.argv):
                days = int(sys.argv[i + 2])
            if arg == "--target" and i + 2 < len(sys.argv):
                target = int(sys.argv[i + 2])

        if "sync" in args:
            print(f"Syncing (last {days} days, target {target} unanswered)...")
            activity_unanswered = sync_activity_feed(conn, days=days, target=target)
            sync_own_pubs(conn, target=target, already_found=activity_unanswered)
            backfill_post_urls(conn)
            conn.execute("INSERT INTO sync_log VALUES (?,?,?)",
                         (datetime.now(timezone.utc).isoformat(), "full", 0))
            conn.commit()
            print("Sync complete.\n")

        if "report" in args:
            report(conn)

if __name__ == "__main__":
    main()
