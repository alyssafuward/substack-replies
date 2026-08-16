"""Subscriber list tracker — separate DB from replies.db (see issue #67).

Two ways data comes in:
  - Full CSV export from Substack (Settings -> Subscribers -> export): email,
    active_subscription, expiry, plan, email_disabled, created_at, first_payment_at.
    No display name.
  - Screenshot of the Substack subscriber dashboard, read by Claude: email,
    plan tag (Free / Yearly Paid / Monthly Paid), star rating, signup date.
    Partial — no expiry/first_payment_at.

Upserts merge fields rather than overwrite, so a partial screenshot row never
blows away richer data from a CSV import, and a later CSV re-import never
erases a star rating that only ever came from a screenshot.
"""

import csv
import sqlite3
from datetime import datetime, timezone

DB_PATH = "subscribers.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS subscribers (
    email TEXT PRIMARY KEY,
    name TEXT,
    active_subscription TEXT,
    expiry TEXT,
    plan TEXT,
    email_disabled TEXT,
    created_at TEXT,
    first_payment_at TEXT,
    quality_stars INTEGER,
    source TEXT,
    first_seen_at TEXT,
    last_updated_at TEXT
);
"""

FIELDS = [
    "name", "active_subscription", "expiry", "plan", "email_disabled",
    "created_at", "first_payment_at", "quality_stars",
]


def get_conn(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.execute(SCHEMA)
    return conn


def upsert(conn, email, source, **fields):
    """Insert or merge a subscriber row. Only non-None fields overwrite existing values."""
    email = email.strip().lower()
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute("SELECT * FROM subscribers WHERE email = ?", (email,))
    existing = cur.fetchone()
    col_names = [d[0] for d in cur.description] if existing else None

    if existing is None:
        row = {f: fields.get(f) for f in FIELDS}
        conn.execute(
            f"""INSERT INTO subscribers
                (email, {", ".join(FIELDS)}, source, first_seen_at, last_updated_at)
                VALUES (?, {", ".join("?" for _ in FIELDS)}, ?, ?, ?)""",
            (email, *[row[f] for f in FIELDS], source, now, now),
        )
        return "inserted"

    existing_dict = dict(zip(col_names, existing))
    changed = False
    for f in FIELDS:
        new_val = fields.get(f)
        if new_val is not None and new_val != "" and str(new_val) != str(existing_dict.get(f)):
            existing_dict[f] = new_val
            changed = True
    if changed:
        existing_dict["source"] = source
        existing_dict["last_updated_at"] = now
        conn.execute(
            f"""UPDATE subscribers SET {", ".join(f"{f} = ?" for f in FIELDS)},
                source = ?, last_updated_at = ? WHERE email = ?""",
            (*[existing_dict[f] for f in FIELDS], source, now, email),
        )
        return "updated"
    return "unchanged"


def import_csv(conn, csv_path, source="csv_export"):
    counts = {"inserted": 0, "updated": 0, "unchanged": 0}
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            result = upsert(
                conn,
                row["email"],
                source,
                active_subscription=row.get("active_subscription"),
                expiry=row.get("expiry"),
                plan=row.get("plan"),
                email_disabled=row.get("email_disabled"),
                created_at=row.get("created_at"),
                first_payment_at=row.get("first_payment_at"),
            )
            counts[result] += 1
    conn.commit()
    return counts


def import_screenshot_rows(conn, rows, source="screenshot"):
    """rows: list of dicts with at least 'email'; optional plan, quality_stars, created_at, name."""
    counts = {"inserted": 0, "updated": 0, "unchanged": 0}
    for row in rows:
        result = upsert(
            conn,
            row["email"],
            source,
            name=row.get("name"),
            plan=row.get("plan"),
            quality_stars=row.get("quality_stars"),
            created_at=row.get("created_at"),
        )
        counts[result] += 1
    conn.commit()
    return counts


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python subscribers.py <path-to-email_list-csv>")
        sys.exit(1)
    conn = get_conn()
    counts = import_csv(conn, sys.argv[1])
    total = conn.execute("SELECT COUNT(*) FROM subscribers").fetchone()[0]
    print(f"{counts} — total subscribers in db: {total}")
