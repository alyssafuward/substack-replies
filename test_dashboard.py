"""
Tests for dashboard.py classification logic.
All tests use in-memory SQLite — no live DB or API calls.
"""
import json
import sqlite3
import unittest

import config
import dashboard

MY = config.USER_ID
OTHER = MY + 1
OWN_PUB = list(config.OWN_PUBS.keys())[0]
OWN_URL = f"https://{OWN_PUB}.substack.com/p/test-post"
GUEST_URL = "https://someoneelse.substack.com/p/their-post"


# ── DB helpers ────────────────────────────────────────────────────────────────

def make_db():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE activity_items (
            id TEXT PRIMARY KEY, type TEXT, created_at TEXT, updated_at TEXT,
            comment_id INTEGER, target_comment_id INTEGER, target_post_id INTEGER,
            is_new INTEGER, is_responded INTEGER DEFAULT 0, raw_json TEXT,
            is_archived INTEGER DEFAULT 0
        );
        CREATE TABLE comments (
            id INTEGER PRIMARY KEY, pub_subdomain TEXT, post_id INTEGER,
            post_title TEXT, post_url TEXT, parent_id INTEGER, ancestor_path TEXT,
            user_id INTEGER, handle TEXT, name TEXT, body TEXT, date TEXT, raw_json TEXT
        );
        CREATE TABLE posts (
            id INTEGER PRIMARY KEY, pub_subdomain TEXT, title TEXT, slug TEXT,
            canonical_url TEXT, post_date TEXT, comment_count INTEGER
        );
        CREATE TABLE sync_state (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE sync_log (synced_at TEXT, type TEXT, items_fetched INTEGER);
    """)
    return conn

def add_activity(conn, item_id, item_type, reply_id, your_id,
                 is_responded=0, is_archived=0, created_at="2026-01-01T00:00:00Z"):
    conn.execute(
        "INSERT INTO activity_items (id, type, created_at, comment_id, target_comment_id, "
        "is_responded, is_archived, raw_json) VALUES (?,?,?,?,?,?,?,?)",
        (item_id, item_type, created_at, reply_id, your_id, is_responded, is_archived, "{}")
    )

def add_comment(conn, cid, user_id, body="hello", post_url=None, post_id=None,
                ancestor_path=None, pub_subdomain=None, raw_json=None, handle=None, name=None):
    conn.execute(
        "INSERT INTO comments (id, user_id, body, post_url, post_id, ancestor_path, "
        "pub_subdomain, raw_json, handle, name) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (cid, user_id, body, post_url, post_id, ancestor_path,
         pub_subdomain, raw_json or "{}", handle, name)
    )

def add_post(conn, post_id, pub_subdomain, title="Test Post", url=None, comment_count=0):
    conn.execute(
        "INSERT INTO posts (id, pub_subdomain, title, canonical_url, comment_count) VALUES (?,?,?,?,?)",
        (post_id, pub_subdomain, title, url or f"https://{pub_subdomain}.substack.com/p/{post_id}", comment_count)
    )


# ── _comment_link ─────────────────────────────────────────────────────────────

class TestCommentLink(unittest.TestCase):

    def test_normal_post_url(self):
        url = "https://example.substack.com/p/my-post"
        self.assertEqual(
            dashboard._comment_link(url, 123),
            "https://example.substack.com/p/my-post/comment/123"
        )

    def test_home_post_url_returned_as_is(self):
        """home/post URLs don't support /comment/{id} appending."""
        url = "https://substack.com/home/post/12345"
        self.assertEqual(dashboard._comment_link(url, 999), url)

    def test_trailing_slash_stripped(self):
        url = "https://example.substack.com/p/my-post/"
        self.assertEqual(
            dashboard._comment_link(url, 123),
            "https://example.substack.com/p/my-post/comment/123"
        )

    def test_no_url_returns_none(self):
        self.assertIsNone(dashboard._comment_link(None, 123))
        self.assertIsNone(dashboard._comment_link("", 123))


# ── load_data: activity feed items ────────────────────────────────────────────

class TestLoadDataActivity(unittest.TestCase):

    def test_unresponded_item_appears(self):
        conn = make_db()
        add_comment(conn, 10, OTHER, body="hey!", post_url=OWN_URL)  # their reply
        add_comment(conn, 20, MY, body="my original note")           # your comment
        add_activity(conn, "a1", "note_reply", reply_id=10, your_id=20)

        items = dashboard.load_data(conn)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["comment_id"], 10)
        self.assertEqual(items[0]["their_body"], "hey!")

    def test_is_responded_flag_excludes_item(self):
        conn = make_db()
        add_comment(conn, 10, OTHER, body="hey!")
        add_comment(conn, 20, MY, body="my note")
        add_activity(conn, "a1", "note_reply", reply_id=10, your_id=20, is_responded=1)

        items = dashboard.load_data(conn)
        self.assertEqual(len(items), 0)

    def test_reply_in_db_excludes_item(self):
        """If a reply comment exists in DB after the reply, item is excluded."""
        conn = make_db()
        add_comment(conn, 10, OTHER, body="hey!")
        add_comment(conn, 20, MY, body="my note")
        # Your reply back (id > reply_id=10, ancestor_path contains 10)
        add_comment(conn, 30, MY, body="my reply back", ancestor_path="10")
        add_activity(conn, "a1", "note_reply", reply_id=10, your_id=20)

        items = dashboard.load_data(conn)
        self.assertEqual(len(items), 0)

    def test_archived_item_excluded(self):
        conn = make_db()
        add_comment(conn, 10, OTHER, body="hey!")
        add_comment(conn, 20, MY, body="my note")
        add_activity(conn, "a1", "note_reply", reply_id=10, your_id=20, is_archived=1)

        items = dashboard.load_data(conn)
        self.assertEqual(len(items), 0)

    def test_guest_post_flagged_correctly(self):
        conn = make_db()
        add_comment(conn, 10, OTHER, body="nice post", post_url=GUEST_URL)
        add_comment(conn, 20, MY, body="my comment")
        add_activity(conn, "a1", "comment_reply", reply_id=10, your_id=20)

        items = dashboard.load_data(conn)
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["guest_post"])

    def test_own_pub_post_not_flagged_as_guest(self):
        conn = make_db()
        add_comment(conn, 10, OTHER, body="nice post", post_url=OWN_URL)
        add_comment(conn, 20, MY, body="my comment")
        add_activity(conn, "a1", "comment_reply", reply_id=10, your_id=20)

        items = dashboard.load_data(conn)
        self.assertEqual(len(items), 1)
        self.assertFalse(items[0]["guest_post"])

    def test_missing_reply_comment_skipped(self):
        """Activity item where reply comment row doesn't exist in comments table."""
        conn = make_db()
        add_comment(conn, 20, MY, body="my note")
        add_activity(conn, "a1", "note_reply", reply_id=10, your_id=20)  # 10 doesn't exist

        items = dashboard.load_data(conn)
        self.assertEqual(len(items), 0)

    def test_liked_reply_still_appears_with_liked_flag(self):
        """Liked items still show in load_data — render_html filters them into 'reviewed'."""
        conn = make_db()
        add_comment(conn, 10, OTHER, body="hey!", raw_json=json.dumps({"reaction": "❤"}))
        add_comment(conn, 20, MY, body="my note")
        add_activity(conn, "a1", "note_reply", reply_id=10, your_id=20)

        items = dashboard.load_data(conn)
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["liked"])

    def test_note_reply_label(self):
        conn = make_db()
        add_comment(conn, 10, OTHER, handle="alice")
        add_comment(conn, 20, MY)
        add_activity(conn, "a1", "note_reply", reply_id=10, your_id=20)

        items = dashboard.load_data(conn)
        self.assertEqual(items[0]["label"], "replied to your note")

    def test_comment_reply_label(self):
        conn = make_db()
        add_comment(conn, 10, OTHER, post_url=OWN_URL)
        add_comment(conn, 20, MY)
        add_activity(conn, "a1", "comment_reply", reply_id=10, your_id=20)

        items = dashboard.load_data(conn)
        self.assertEqual(items[0]["label"], "replied to your comment")


# ── load_data: own pub comments (section 2) ───────────────────────────────────

class TestLoadDataOwnPub(unittest.TestCase):

    def test_own_pub_comment_in_thread_appears(self):
        """Comment on own post where user is in ancestor thread."""
        conn = make_db()
        # User's comment (id=100), other person's reply (id=101, ancestor=100)
        add_comment(conn, 100, MY, pub_subdomain=OWN_PUB, post_url=OWN_URL)
        add_comment(conn, 101, OTHER, body="nice!", pub_subdomain=OWN_PUB,
                    post_url=OWN_URL, ancestor_path="100")

        items = dashboard.load_data(conn)
        own_pub = [i for i in items if i["source"] == "own_pub"]
        self.assertEqual(len(own_pub), 1)
        self.assertEqual(own_pub[0]["comment_id"], 101)

    def test_own_pub_top_level_comment_included(self):
        """Top-level comment (no ancestor) on own pub is included — direct commenter."""
        conn = make_db()
        add_comment(conn, 101, OTHER, body="great post!", pub_subdomain=OWN_PUB,
                    post_url=OWN_URL, ancestor_path=None)

        items = dashboard.load_data(conn)
        own_pub = [i for i in items if i["source"] == "own_pub"]
        self.assertEqual(len(own_pub), 1)

    def test_own_pub_already_replied_excluded(self):
        conn = make_db()
        add_comment(conn, 100, MY, pub_subdomain=OWN_PUB, post_url=OWN_URL)
        add_comment(conn, 101, OTHER, body="nice!", pub_subdomain=OWN_PUB,
                    post_url=OWN_URL, ancestor_path="100")
        # User replied to 101
        add_comment(conn, 102, MY, pub_subdomain=OWN_PUB, post_url=OWN_URL,
                    ancestor_path="100.101")

        items = dashboard.load_data(conn)
        own_pub = [i for i in items if i["source"] == "own_pub"]
        self.assertEqual(len(own_pub), 0)

    def test_own_pub_source_label(self):
        conn = make_db()
        add_comment(conn, 100, MY, pub_subdomain=OWN_PUB, post_url=OWN_URL)
        add_comment(conn, 101, OTHER, body="hi", pub_subdomain=OWN_PUB,
                    post_url=OWN_URL, ancestor_path="100")

        items = dashboard.load_data(conn)
        own_pub = [i for i in items if i["source"] == "own_pub"]
        self.assertEqual(own_pub[0]["label"], "commented on your post")


# ── load_post_comments_data ───────────────────────────────────────────────────

class TestLoadPostCommentsData(unittest.TestCase):

    def setUp(self):
        self.conn = make_db()
        add_post(self.conn, 1, OWN_PUB, title="Test Post", url=OWN_URL)

    def test_unanswered_comment_appears(self):
        add_comment(self.conn, 101, OTHER, body="great post", post_id=1, pub_subdomain=OWN_PUB)

        data = dashboard.load_post_comments_data(self.conn, OWN_PUB)
        post = data[0]
        self.assertEqual(len(post["unanswered"]), 1)
        self.assertEqual(post["unanswered"][0]["body"], "great post")

    def test_responded_comment_in_responded_not_unanswered(self):
        add_comment(self.conn, 101, OTHER, body="great post", post_id=1, pub_subdomain=OWN_PUB)
        # User's reply to 101
        add_comment(self.conn, 102, MY, body="thanks!", post_id=1,
                    pub_subdomain=OWN_PUB, ancestor_path="101")

        data = dashboard.load_post_comments_data(self.conn, OWN_PUB)
        post = data[0]
        self.assertEqual(len(post["unanswered"]), 0)
        self.assertEqual(len(post["responded"]), 1)
        self.assertEqual(post["responded"][0]["body"], "great post")
        self.assertEqual(post["responded"][0]["your_reply"], "thanks!")

    def test_liked_comment_in_liked_not_unanswered(self):
        add_comment(self.conn, 101, OTHER, body="cool", post_id=1,
                    pub_subdomain=OWN_PUB, raw_json=json.dumps({"reaction": "❤"}))

        data = dashboard.load_post_comments_data(self.conn, OWN_PUB)
        post = data[0]
        self.assertEqual(len(post["unanswered"]), 0)
        self.assertEqual(len(post["liked"]), 1)

    def test_user_own_comments_excluded(self):
        """The user's own comments should never appear."""
        add_comment(self.conn, 101, MY, body="my own comment", post_id=1, pub_subdomain=OWN_PUB)

        data = dashboard.load_post_comments_data(self.conn, OWN_PUB)
        post = data[0]
        self.assertEqual(len(post["unanswered"]), 0)
        self.assertEqual(len(post["responded"]), 0)
        self.assertEqual(len(post["liked"]), 0)

    def test_multiple_comments_classified_correctly(self):
        add_comment(self.conn, 101, OTHER, body="unanswered", post_id=1, pub_subdomain=OWN_PUB)
        add_comment(self.conn, 102, OTHER, body="liked one", post_id=1,
                    pub_subdomain=OWN_PUB, raw_json=json.dumps({"reaction": "❤"}))
        add_comment(self.conn, 103, OTHER, body="responded one", post_id=1, pub_subdomain=OWN_PUB)
        add_comment(self.conn, 104, MY, body="my reply", post_id=1,
                    pub_subdomain=OWN_PUB, ancestor_path="103")

        data = dashboard.load_post_comments_data(self.conn, OWN_PUB)
        post = data[0]
        self.assertEqual(len(post["unanswered"]), 1)
        self.assertEqual(len(post["liked"]), 1)
        self.assertEqual(len(post["responded"]), 1)

    def test_no_pub_subdomain_returns_empty(self):
        data = dashboard.load_post_comments_data(self.conn, "")
        self.assertEqual(data, [])


# ── render helpers ────────────────────────────────────────────────────────────

class TestRenderCard(unittest.TestCase):

    BASE_ITEM = {
        "source": "activity", "date": "2026-01-01", "raw_date": "2026-01-01T00:00:00Z",
        "who": "Alice", "handle": "alice", "label": "replied to your note",
        "your_body": "my note", "their_body": "their reply", "your_reply_back": "",
        "link": "https://substack.com/@alice/note/c-1", "comment_id": 1,
        "liked": False, "thread": [], "guest_post": False,
    }

    def test_archive_btn_in_action_section(self):
        html = dashboard.render_card(dict(self.BASE_ITEM), section="action")
        self.assertIn("archiveCard", html)
        self.assertNotIn("unarchiveCard", html)

    def test_unarchive_btn_in_archived_section(self):
        html = dashboard.render_card(dict(self.BASE_ITEM), section="archived")
        self.assertIn("unarchiveCard", html)
        self.assertNotIn("onclick=\"archiveCard", html)

    def test_no_archive_btn_in_responded_section(self):
        html = dashboard.render_card(dict(self.BASE_ITEM), section="responded")
        self.assertNotIn("archiveCard", html)
        self.assertNotIn("unarchiveCard", html)

    def test_long_body_gets_expand_button(self):
        item = dict(self.BASE_ITEM)
        item["their_body"] = "x" * 300
        html = dashboard.render_card(item)
        self.assertIn("expandThread", html)
        self.assertIn("thread-full", html)

    def test_short_body_no_expand_button(self):
        item = dict(self.BASE_ITEM)
        item["their_body"] = "short"
        html = dashboard.render_card(item)
        self.assertNotIn("expandThread", html)

    def test_reply_back_shown(self):
        item = dict(self.BASE_ITEM)
        item["your_reply_back"] = "thanks for the kind words!"
        html = dashboard.render_card(item)
        self.assertIn("thanks for the kind words!", html)
        self.assertIn("your-reply-preview", html)

    def test_data_who_contains_name_and_handle(self):
        html = dashboard.render_card(dict(self.BASE_ITEM))
        self.assertIn('data-who="alice alice"', html)


class TestRenderPostCommentCard(unittest.TestCase):

    BASE = {
        "who": "Bob", "date": "2026-01-01", "raw_date": "2026-01-01T00:00:00",
        "body": "nice post", "link": "https://example.com/p/1/comment/99",
        "liked": False,
    }

    def test_short_body_no_expand(self):
        html = dashboard.render_post_comment_card(dict(self.BASE))
        self.assertNotIn("expandThread", html)

    def test_long_body_gets_expand(self):
        card = dict(self.BASE)
        card["body"] = "y" * 300
        html = dashboard.render_post_comment_card(card)
        self.assertIn("expandThread", html)

    def test_your_reply_shown(self):
        card = dict(self.BASE)
        card["your_reply"] = "my reply to bob"
        html = dashboard.render_post_comment_card(card)
        self.assertIn("my reply to bob", html)
        self.assertIn("your-reply-preview", html)

    def test_liked_badge(self):
        card = dict(self.BASE)
        card["liked"] = True
        html = dashboard.render_post_comment_card(card)
        self.assertIn("liked-badge", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
