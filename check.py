#!/usr/bin/env python3
"""
Sanity checks for substack-replies.
Run after any code changes to verify nothing is broken.

Usage:
  python check.py
"""

import sys
import sqlite3
import traceback
from pathlib import Path

PASS = "✓"
FAIL = "✗"
results = []

def check(label, fn):
    try:
        msg = fn()
        results.append((True, label, msg or ""))
    except Exception as e:
        results.append((False, label, str(e)))

# ── 1. Config ─────────────────────────────────────────────────────────────────

def check_config():
    from config import USER_ID, HANDLE, OWN_PUBS
    assert USER_ID != 0, "USER_ID is 0 — fill in config.py"
    assert HANDLE != "", "HANDLE is empty — fill in config.py"
    assert OWN_PUBS, "OWN_PUBS is empty — fill in config.py"
    return f"USER_ID={USER_ID}, {len(OWN_PUBS)} publication(s)"

check("config.py exists and is filled in", check_config)

# ── 2. Database ───────────────────────────────────────────────────────────────

DB_PATH = Path(__file__).parent / "replies.db"

def check_db_exists():
    assert DB_PATH.exists(), "replies.db not found — run: python scraper.py sync"
    return f"{DB_PATH.stat().st_size // 1024} KB"

def check_db_tables():
    with sqlite3.connect(DB_PATH) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        required = {"activity_items", "comments", "posts", "sync_log"}
        missing = required - tables
        assert not missing, f"Missing tables: {missing}"
        return f"tables: {', '.join(sorted(tables))}"

def check_db_has_data():
    with sqlite3.connect(DB_PATH) as conn:
        activity = conn.execute("SELECT COUNT(*) FROM activity_items").fetchone()[0]
        comments = conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
        posts = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        last_sync = conn.execute("SELECT synced_at FROM sync_log ORDER BY synced_at DESC LIMIT 1").fetchone()
        assert activity > 0 or comments > 0, "Database is empty — run: python scraper.py sync"
        sync_str = last_sync[0][:16] if last_sync else "never"
        return f"{activity} activity items, {comments} comments, {posts} posts, last sync: {sync_str}"

check("replies.db exists", check_db_exists)
check("database tables present", check_db_tables)
check("database has data", check_db_has_data)

# ── 3. Scraper imports ────────────────────────────────────────────────────────

def check_scraper_imports():
    import scraper
    assert hasattr(scraper, "sync_activity_feed"), "sync_activity_feed missing"
    assert hasattr(scraper, "sync_own_pubs"), "sync_own_pubs missing"
    assert hasattr(scraper, "init_db"), "init_db missing"
    assert hasattr(scraper, "load_next_post"), "load_next_post missing"
    assert hasattr(scraper, "refresh_post_comments"), "refresh_post_comments missing"
    return "all expected functions present"

check("scraper.py imports cleanly", check_scraper_imports)

# ── 4. Dashboard imports and data loading ─────────────────────────────────────

def check_dashboard_imports():
    import dashboard
    assert hasattr(dashboard, "load_data"), "load_data missing"
    assert hasattr(dashboard, "load_stats"), "load_stats missing"
    assert hasattr(dashboard, "load_post_comments_data"), "load_post_comments_data missing"
    assert hasattr(dashboard, "render_html"), "render_html missing"
    return "all expected functions present"

def check_dashboard_loads_data():
    import dashboard
    with sqlite3.connect(DB_PATH) as conn:
        items = dashboard.load_data(conn)
        stats = dashboard.load_stats(conn)
    assert isinstance(items, list), "load_data did not return a list"
    assert "activity_items" in stats, "load_stats missing activity_items"
    assert "synced_up_to" in stats, "load_stats missing synced_up_to"
    return f"{len(items)} items needing response"

def check_dashboard_renders():
    import dashboard
    with sqlite3.connect(DB_PATH) as conn:
        items = dashboard.load_data(conn)
        stats = dashboard.load_stats(conn)
    html = dashboard.render_html(items, stats)
    assert len(html) > 500, "rendered HTML suspiciously short"
    assert "<html" in html, "rendered HTML missing <html> tag"
    assert "Substack Replies" in html, "rendered HTML missing expected title"
    return f"{len(html) // 1024} KB of HTML"

check("dashboard.py imports cleanly", check_dashboard_imports)
check("dashboard loads data from DB", check_dashboard_loads_data)
check("dashboard renders HTML", check_dashboard_renders)

# ── 5. Reply logic sanity check ───────────────────────────────────────────────

def check_reply_logic():
    """Verify the 'already replied' filter isn't hiding everything or nothing."""
    import dashboard
    with sqlite3.connect(DB_PATH) as conn:
        items = dashboard.load_data(conn)
        total_activity = conn.execute(
            "SELECT COUNT(*) FROM activity_items WHERE type IN ('note_reply','comment_reply')"
        ).fetchone()[0]
        total_comments = conn.execute(
            "SELECT COUNT(*) FROM comments WHERE pub_subdomain IS NOT NULL AND user_id != ? AND user_id IS NOT NULL",
            (dashboard.USER_ID,)
        ).fetchone()[0]
    total_candidates = total_activity + total_comments
    assert total_candidates > 0, "No candidate items found — database may be empty"
    # If 100% of candidates show up as needing response, the filter might be broken
    if total_candidates > 10:
        assert len(items) < total_candidates, \
            f"All {total_candidates} candidates marked as needing response — 'already replied' filter may be broken"
    return f"{len(items)} needing response out of {total_candidates} total candidates"

check("reply filter logic is working", check_reply_logic)

# ── Results ───────────────────────────────────────────────────────────────────

print()
print("Substack Replies — checks")
print("─" * 50)
passed = 0
failed = 0
for ok, label, detail in results:
    icon = PASS if ok else FAIL
    print(f"  {icon} {label}")
    if detail:
        print(f"      {detail}")
    if ok:
        passed += 1
    else:
        failed += 1

print("─" * 50)
if failed == 0:
    print(f"  All {passed} checks passed.")
else:
    print(f"  {passed} passed, {failed} failed.")
print()

sys.exit(0 if failed == 0 else 1)
