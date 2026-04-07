"""
Tests for refresh_post_comments smart sync logic.
Mocks fetch_all_posts and fetch_post_comments — no real API calls.
"""
import sqlite3
import unittest
from unittest.mock import patch
from io import StringIO
import sys

# We need config values before importing scraper
import config
import scraper

def make_db():
    """Create an in-memory DB with the required schema."""
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE posts (
            id INTEGER PRIMARY KEY,
            pub_subdomain TEXT,
            title TEXT,
            slug TEXT,
            canonical_url TEXT,
            post_date TEXT,
            comment_count INTEGER
        );
        CREATE TABLE comments (
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
    """)
    return conn

def seed_post(conn, post_id, title, comment_count):
    conn.execute(
        "INSERT INTO posts (id, pub_subdomain, title, canonical_url, comment_count) VALUES (?,?,?,?,?)",
        (post_id, "testpub", title, f"https://testpub.substack.com/p/{post_id}", comment_count)
    )

def seed_comment(conn, comment_id, post_id, user_id, body="hello"):
    conn.execute(
        "INSERT INTO comments (id, user_id, body, post_id, pub_subdomain, raw_json) VALUES (?,?,?,?,?,?)",
        (comment_id, user_id, body, post_id, "testpub", "{}")
    )

def capture_output(fn):
    """Run fn() and return stdout as a string."""
    buf = StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        fn()
    finally:
        sys.stdout = old
    return buf.getvalue()

OTHER_USER = 99999
MY_USER = config.USER_ID

class TestSmartSync(unittest.TestCase):

    def test_no_changes(self):
        """All comment counts match — nothing should be fetched."""
        conn = make_db()
        seed_post(conn, 1, "Post One", 3)

        fresh_posts = [{"id": 1, "comment_count": 3}]
        with patch.object(scraper, "fetch_all_posts", return_value=fresh_posts):
            output = capture_output(lambda: scraper.refresh_post_comments(conn, "testpub"))

        self.assertIn("All up to date", output)
        # fetch_post_comments should never have been called
        self.assertNotIn("new comment", output)

    def test_new_comment_from_other(self):
        """Count increased, new comment is from someone else."""
        conn = make_db()
        seed_post(conn, 1, "Post One", 2)
        seed_comment(conn, 101, 1, OTHER_USER, "old comment")

        fresh_posts = [{"id": 1, "comment_count": 3}]
        # New comment (id=102) from another user, not in DB yet
        fresh_comments = [
            {"id": 101, "user_id": OTHER_USER, "body": "old comment", "name": "Alice",
             "handle": "alice", "date": "2026-01-01", "ancestor_path": None},
            {"id": 102, "user_id": OTHER_USER, "body": "brand new!", "name": "Bob",
             "handle": "bob", "date": "2026-04-07", "ancestor_path": None},
        ]
        with patch.object(scraper, "fetch_all_posts", return_value=fresh_posts), \
             patch.object(scraper, "fetch_post_comments", return_value=fresh_comments), \
             patch.object(scraper, "flatten_comments", return_value=fresh_comments):
            output = capture_output(lambda: scraper.refresh_post_comments(conn, "testpub"))

        self.assertIn("1 new comment(s) from others", output)
        self.assertIn("Sync complete", output)
        # Stored count updated
        new_count = conn.execute("SELECT comment_count FROM posts WHERE id=1").fetchone()[0]
        self.assertEqual(new_count, 3)

    def test_count_changed_by_own_reply(self):
        """Count increased, but new comment is from the user themselves."""
        conn = make_db()
        seed_post(conn, 1, "Post One", 2)
        seed_comment(conn, 101, 1, OTHER_USER, "their comment")

        fresh_posts = [{"id": 1, "comment_count": 3}]
        fresh_comments = [
            {"id": 101, "user_id": OTHER_USER, "body": "their comment", "name": "Alice",
             "handle": "alice", "date": "2026-01-01", "ancestor_path": None},
            {"id": 102, "user_id": MY_USER, "body": "my reply", "name": "Alyssa",
             "handle": "alyssa", "date": "2026-04-07", "ancestor_path": None},
        ]
        with patch.object(scraper, "fetch_all_posts", return_value=fresh_posts), \
             patch.object(scraper, "fetch_post_comments", return_value=fresh_comments), \
             patch.object(scraper, "flatten_comments", return_value=fresh_comments):
            output = capture_output(lambda: scraper.refresh_post_comments(conn, "testpub"))

        self.assertIn("your own reply or edit", output)
        self.assertNotIn("new comment(s) from others", output)

    def test_multiple_posts_mixed(self):
        """One post unchanged, one with new comment, one with own reply."""
        conn = make_db()
        seed_post(conn, 1, "Unchanged", 5)
        seed_post(conn, 2, "New Comment", 2)
        seed_post(conn, 3, "Own Reply", 2)

        fresh_posts = [
            {"id": 1, "comment_count": 5},  # unchanged
            {"id": 2, "comment_count": 3},  # new comment from other
            {"id": 3, "comment_count": 3},  # own reply
        ]
        comments_post2 = [
            {"id": 201, "user_id": OTHER_USER, "body": "new!", "name": "X",
             "handle": "x", "date": "2026-04-07", "ancestor_path": None},
        ]
        comments_post3 = [
            {"id": 301, "user_id": MY_USER, "body": "my reply", "name": "Alyssa",
             "handle": "alyssa", "date": "2026-04-07", "ancestor_path": None},
        ]

        def mock_fetch_posts(subdomain):
            return fresh_posts

        def mock_fetch_comments(subdomain, post_id):
            return comments_post2 if post_id == 2 else comments_post3

        def mock_flatten(comments):
            return comments

        with patch.object(scraper, "fetch_all_posts", side_effect=mock_fetch_posts), \
             patch.object(scraper, "fetch_post_comments", side_effect=mock_fetch_comments), \
             patch.object(scraper, "flatten_comments", side_effect=mock_flatten):
            output = capture_output(lambda: scraper.refresh_post_comments(conn, "testpub"))

        self.assertIn("2 post(s) have new activity", output)
        self.assertIn("1 new comment(s) from others", output)
        self.assertIn("your own reply or edit", output)

    def test_no_posts_loaded(self):
        """DB has no posts — should say so and return."""
        conn = make_db()
        output = capture_output(lambda: scraper.refresh_post_comments(conn, "testpub"))
        self.assertIn("No posts loaded", output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
