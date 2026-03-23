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
from urllib.parse import unquote, urlparse

# ── Config ────────────────────────────────────────────────────────────────────

try:
    from config import USER_ID, HANDLE, OWN_PUBS
except ImportError:
    print("Error: config.py not found. Copy config.example.py to config.py and fill in your values.")
    sys.exit(1)

DB_PATH = Path(__file__).parent / "replies.db"

REPLY_TYPES = {"note_reply", "comment_reply", "new_comment"}
UNRESPONDED_TARGET = 250

# ── HTTP ──────────────────────────────────────────────────────────────────────

def ts():
    return datetime.now().strftime("[%H:%M:%S]")

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
            is_responded INTEGER DEFAULT 0,
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

    # Migrate existing DB: add is_responded if it doesn't exist yet
    try:
        conn.execute("ALTER TABLE activity_items ADD COLUMN is_responded INTEGER DEFAULT 0")
    except Exception:
        pass  # column already exists

    conn.commit()

def get_state(conn, key):
    row = conn.execute("SELECT value FROM sync_state WHERE key=?", (key,)).fetchone()
    return row[0] if row else None

def set_state(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO sync_state (key, value) VALUES (?,?)", (key, value))

# ── Sync: Recheck Unresponded ─────────────────────────────────────────────────

def _user_replied_in_thread(comments, target_comment_id, user_id):
    """
    Search the nested comment tree for target_comment_id, then check if
    any of its descendants were written by user_id.
    Returns True if the user has replied to that comment.
    """
    for c in comments:
        if str(c.get("id")) == str(target_comment_id):
            return _has_descendant_by_user(c.get("children", []), user_id)
        if _user_replied_in_thread(c.get("children", []), target_comment_id, user_id):
            return True
    return False


def _has_descendant_by_user(comments, user_id):
    for c in comments:
        if c.get("user_id") == user_id:
            return True
        if _has_descendant_by_user(c.get("children", []), user_id):
            return True
    return False


def recheck_note_replies(conn):
    """
    For each unresponded note_reply, fetch the thread via the reader API and check if:
    - the user liked the reply (reaction on rootComment) → acknowledged
    - the user replied back (commentBranch by USER_ID) → responded
    Updates is_responded and refreshes stored raw_json with fresh reaction data.
    Returns count still unresponded.
    """
    rows = conn.execute("""
        SELECT a.id, a.comment_id
        FROM activity_items a
        LEFT JOIN comments c ON c.id = a.comment_id
        WHERE a.is_responded = 0
          AND a.type = 'note_reply'
          AND a.comment_id IS NOT NULL
          AND (c.raw_json IS NULL OR json_extract(c.raw_json, '$.reaction') IS NULL)
        ORDER BY a.updated_at DESC
        LIMIT ?
    """, (UNRESPONDED_TARGET * 2,)).fetchall()

    if not rows:
        print(f"{ts()} Note recheck: nothing to check.")
        return 0

    print(f"{ts()} Rechecking {len(rows)} note replies...")
    newly_responded = 0
    still_unresponded = 0

    for item_id, comment_id in rows:
        try:
            url = f"https://substack.com/api/v1/reader/comment/{comment_id}/replies?comment_id={comment_id}"
            data = get(url)

            responded = False

            # Check if user liked the reply
            root = data.get("rootComment", {})
            if root.get("reaction"):
                conn.execute("UPDATE comments SET raw_json=? WHERE id=?",
                             (json.dumps(root), comment_id))
                responded = True

            # Check if user replied back
            if not responded:
                for branch in data.get("commentBranches", []):
                    c = branch.get("comment", {})
                    if c.get("user_id") == USER_ID:
                        _store_comment(conn, c, pub_subdomain=None,
                                       post_id=c.get("post_id"),
                                       post_title=None, post_url=None)
                        responded = True
                        break

            if responded:
                conn.execute("UPDATE activity_items SET is_responded=1 WHERE id=?", (item_id,))
                newly_responded += 1
            else:
                still_unresponded += 1

            time.sleep(0.5)

        except Exception as e:
            print(f"{ts()}   warning: couldn't recheck note {comment_id}: {e}")
            still_unresponded += 1

    conn.commit()
    print(f"{ts()} Note recheck done: {newly_responded} newly responded, {still_unresponded} still unresponded")
    return still_unresponded


def recheck_unresponded(conn):
    """
    For each unresponded comment_reply, re-fetch its post thread and check if
    the user has since replied. Updates is_responded in the DB.
    Returns count of items still unresponded after checking.
    """
    rows = conn.execute("""
        SELECT a.id, a.comment_id, a.target_post_id
        FROM activity_items a
        LEFT JOIN comments c ON c.id = a.comment_id
        WHERE a.is_responded = 0
          AND a.type = 'comment_reply'
          AND a.comment_id IS NOT NULL
          AND (c.raw_json IS NULL OR json_extract(c.raw_json, '$.reaction') IS NULL)  -- liked = acknowledged, skip recheck
        ORDER BY a.updated_at DESC
        LIMIT ?
    """, (UNRESPONDED_TARGET * 2,)).fetchall()

    if not rows:
        print(f"{ts()} Recheck: nothing to check.")
        return 0

    # Group items by (subdomain, post_id) to fetch each post's comments only once
    groups = {}  # (subdomain, post_id) -> [(item_id, comment_id), ...]
    skip_count = 0

    for item_id, comment_id, post_id in rows:
        row = conn.execute(
            "SELECT post_url FROM comments WHERE id=?", (comment_id,)
        ).fetchone()

        if not row or not row[0] or not post_id:
            skip_count += 1
            continue

        post_url = row[0]
        parsed = urlparse(post_url)
        host = parsed.netloc

        if not host.endswith(".substack.com"):
            skip_count += 1
            continue

        subdomain = host.replace(".substack.com", "")
        key = (subdomain, post_id)
        groups.setdefault(key, []).append((item_id, comment_id))

    print(f"{ts()} Rechecking {len(rows)} comment replies...")
    still_unresponded = skip_count
    newly_responded = 0

    for (subdomain, post_id), items in groups.items():
        try:
            comments = fetch_post_comments(subdomain, post_id)

            for item_id, comment_id in items:
                if _user_replied_in_thread(comments, comment_id, USER_ID):
                    conn.execute(
                        "UPDATE activity_items SET is_responded=1 WHERE id=?", (item_id,)
                    )
                    newly_responded += 1
                    print(f"{ts()}   responded: {item_id}")
                else:
                    still_unresponded += 1

        except Exception as e:
            print(f"{ts()}   warning: couldn't recheck post {post_id}: {e}")
            still_unresponded += len(items)

        time.sleep(1)

    conn.commit()
    print(f"{ts()} Recheck done: {newly_responded} newly responded, {still_unresponded} still unresponded")
    return still_unresponded

# ── Sync: Activity Feed ───────────────────────────────────────────────────────

def sync_activity_feed(conn, target=UNRESPONDED_TARGET, after_cursor=None, set_last_synced=None):
    """
    Fetch activity feed newest-first, storing items until `target` new
    unresponded items are found or the feed is exhausted / last sync point reached.

    target:          how many new unresponded items to collect before stopping
    after_cursor:    pagination cursor — set to oldest_fetched_at for backfill/load-more;
                     also used with --as-of to jump to a specific date
    set_last_synced: override whether last_synced_at is updated (default: True when after_cursor is None)

    Returns (new_items, new_unresponded, oldest_ts_seen).
    """
    url = "https://substack.com/api/v1/activity-feed-web"
    last_synced_at = get_state(conn, "last_synced_at")

    after = after_cursor
    new_items = 0
    new_unresponded = 0
    pages = 0
    newest_ts = None
    oldest_ts = None
    done = False

    print(f"{ts()} Fetching activity feed (need {target} more replies)...")

    while not done:
        params = {"limit": 10}
        if after:
            params["after"] = after

        data = get(url, params)
        items = data.get("activityItems", [])

        if not items:
            print(f"{ts()}   Feed exhausted.")
            break

        pages += 1
        new_this_page = 0

        # Store thread context for this page first
        for fic in data.get("feedItemComments", []):
            post = fic.get("post") or {}
            post_url = post.get("canonical_url")
            post_title = post.get("title")
            post_id_fic = post.get("id")
            c = fic.get("comment")
            if c:
                _store_comment(conn, c, pub_subdomain=None,
                               post_id=post_id_fic or c.get("post_id"),
                               post_title=post_title, post_url=post_url)
            for pc in fic.get("parentComments", []):
                _store_comment(conn, pc, pub_subdomain=None,
                               post_id=post_id_fic or pc.get("post_id"),
                               post_title=post_title, post_url=post_url)

        for item in items:
            item_ts = item.get("updated_at") or item.get("created_at") or ""

            # Track timestamp range seen this run
            if item_ts:
                if newest_ts is None or item_ts > newest_ts:
                    newest_ts = item_ts
                if oldest_ts is None or item_ts < oldest_ts:
                    oldest_ts = item_ts

            # Stop when we reach already-synced territory (forward fetches only, not backfill)
            if after_cursor is None and last_synced_at and item_ts and item_ts <= last_synced_at:
                print(f"{ts()}   Reached last sync point.")
                done = True
                break

            # Skip duplicates
            if conn.execute("SELECT 1 FROM activity_items WHERE id=?", (item["id"],)).fetchone():
                continue

            item_type = item.get("type")
            comment_id = item.get("comment_id")

            conn.execute("""
                INSERT OR IGNORE INTO activity_items
                (id, type, created_at, updated_at, comment_id, target_comment_id,
                 target_post_id, is_new, is_responded, raw_json)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (
                item["id"],
                item_type,
                item.get("created_at"),
                item.get("updated_at"),
                comment_id,
                item.get("target_comment_id"),
                item.get("target_post_id"),
                1 if item.get("isNew") else 0,
                0,
                json.dumps(item),
            ))
            new_this_page += 1

            # Count toward target if it's a reply type and not already responded
            if item_type in REPLY_TYPES and comment_id:
                your_reply = conn.execute("""
                    SELECT id FROM comments
                    WHERE user_id=? AND ancestor_path LIKE ? AND id > ?
                """, (USER_ID, f"%{comment_id}%", comment_id)).fetchone()

                if your_reply:
                    conn.execute(
                        "UPDATE activity_items SET is_responded=1 WHERE id=?", (item["id"],)
                    )
                elif new_unresponded < target:
                    new_unresponded += 1
                    if new_unresponded >= target:
                        print(f"{ts()}   Hit target of {target} replies.")
                        done = True
                        break

        new_items += new_this_page
        conn.commit()

        print(f"{ts()}   Page {pages} — {new_this_page} stored | {new_unresponded}/{target} replies")

        if not done and not data.get("more"):
            print(f"{ts()}   No more pages.")
            done = True
            break

        if not done:
            time.sleep(1)
            updated_ats = [
                item.get("updated_at") or item.get("created_at")
                for item in items
                if item.get("updated_at") or item.get("created_at")
            ]
            if not updated_ats:
                break
            min_ts = min(updated_ats)
            dt = datetime.fromisoformat(min_ts.replace("Z", "+00:00"))
            after = (dt - timedelta(milliseconds=1)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    # Update watermarks
    should_update_last_synced = set_last_synced if set_last_synced is not None else (after_cursor is None)
    if newest_ts and should_update_last_synced:
        set_state(conn, "last_synced_at", newest_ts)
    if oldest_ts:
        current_oldest = get_state(conn, "oldest_fetched_at")
        if not current_oldest or oldest_ts < current_oldest:
            set_state(conn, "oldest_fetched_at", oldest_ts)
    conn.commit()

    print(f"{ts()} Activity feed done: {new_items} new items, {new_unresponded} replies counted ({pages} pages)")
    return new_items, new_unresponded, oldest_ts


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

def sync_own_pubs(conn):
    """Scrape comments on all posts from own publications."""
    total_comments = 0

    for subdomain in OWN_PUBS:
        print(f"{ts()}  Syncing {subdomain}...")
        posts = fetch_all_posts(subdomain)

        for post in posts:
            post_id = post["id"]
            post_title = post.get("title", "")
            post_url = post.get("canonical_url", f"https://{subdomain}.substack.com/p/{post.get('slug','')}")

            # Store post
            conn.execute("""
                INSERT OR REPLACE INTO posts (id, pub_subdomain, title, slug, canonical_url, post_date, comment_count)
                VALUES (?,?,?,?,?,?,?)
            """, (post_id, subdomain, post_title, post.get("slug"), post_url, post.get("post_date"), post.get("comment_count", 0)))

            time.sleep(1)
            # Fetch and store comments
            comments = fetch_post_comments(subdomain, post_id)
            for c in flatten_comments(comments):
                _store_comment(conn, c, pub_subdomain=subdomain, post_id=post_id, post_title=post_title, post_url=post_url)
                total_comments += 1

        conn.commit()
        print(f"{ts()}    {subdomain}: {len(posts)} posts, {total_comments} total comments")

    return total_comments


def backfill_post_urls(conn):
    """Fetch canonical URLs for comments that have a post_id but no post_url."""
    rows = conn.execute("""
        SELECT DISTINCT post_id FROM comments
        WHERE post_id IS NOT NULL AND post_url IS NULL
    """).fetchall()

    if not rows:
        print(f"{ts()}  No missing post URLs to backfill.")
        return

    print(f"{ts()}  Backfilling URLs for {len(rows)} posts...")
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
    print(f"{ts()}  Backfill complete.")


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
    argv = sys.argv[1:]
    args = set(argv)

    # Parse --count N (how many replies to fetch, overrides UNRESPONDED_TARGET)
    count = UNRESPONDED_TARGET
    if "--count" in argv:
        idx = argv.index("--count")
        if idx + 1 < len(argv):
            count = int(argv[idx + 1])
            args.discard("--count")
            args.discard(argv[idx + 1])

    # Parse --as-of YYYY-MM-DD (simulate syncing as of a past date)
    as_of_date = None
    as_of_cursor = None
    if "--as-of" in argv:
        idx = argv.index("--as-of")
        if idx + 1 < len(argv):
            as_of_date = argv[idx + 1]
            # Jump to end of that day: fetch items older than midnight of the next day
            as_of_dt = datetime.strptime(as_of_date, "%Y-%m-%d") + timedelta(days=1)
            as_of_cursor = as_of_dt.strftime("%Y-%m-%dT00:00:00.000Z")
            args.discard("--as-of")
            args.discard(as_of_date)

    if not args:
        print("Usage: python scraper.py [sync] [report] [--as-of YYYY-MM-DD]")
        sys.exit(0)

    with sqlite3.connect(DB_PATH) as conn:
        init_db(conn)

        if "sync" in args:
            if as_of_date:
                print(f"{ts()} Starting sync (--as-of {as_of_date})...")
            else:
                print(f"{ts()} Starting sync...")

            # Step 1: recheck items already in DB
            still_unresponded = recheck_unresponded(conn)
            still_unresponded += recheck_note_replies(conn)

            # Step 2: always fetch a full target of new replies from new activity
            new_items, new_unresponded = 0, 0
            oldest_ts = None
            new_items, new_unresponded, oldest_ts = sync_activity_feed(
                conn, target=count,
                after_cursor=as_of_cursor,   # None for normal sync; date cursor for --as-of
                set_last_synced=True,
            )

            # Step 3: backfill if new period ran out before hitting target
            if new_unresponded < count:
                remaining = count - new_unresponded
                oldest_cursor = get_state(conn, "oldest_fetched_at")
                if oldest_cursor:
                    print(f"{ts()} Backfilling — need {remaining} more replies...")
                    sync_activity_feed(conn, target=remaining, after_cursor=oldest_cursor,
                                       set_last_synced=False)

            conn.execute("INSERT INTO sync_log VALUES (?,?,?)",
                         (datetime.now(timezone.utc).isoformat(), "activity_feed", new_items))
            conn.commit()
            print(f"{ts()} Sync complete.\n")

        if "report" in args:
            report(conn)

if __name__ == "__main__":
    main()
