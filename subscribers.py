"""Subscriber list tracker across all publications — separate DB from replies.db (see issue #67).

Alyssa runs three Substacks (alyssafuward, thehartstudio, createwithalyssa) with
overlapping subscribers. This tracks each publication's list and lets you see
the deduped total and per-pair overlap.

Two ways data comes in:
  - Full CSV export from Substack (Settings -> Subscribers -> export), named
    email_list.<publication>.csv: email, active_subscription, expiry, plan,
    email_disabled, created_at, first_payment_at. No display name.
  - Screenshot of the Substack subscriber dashboard, read by Claude: email,
    plan tag (Free / Yearly Paid / Monthly Paid), star rating, signup date.
    Partial — no expiry/first_payment_at.

A person subscribed to multiple publications gets one row per (email,
publication) pair. Upserts merge fields rather than overwrite, so a partial
screenshot row never blows away richer data from a CSV import, and a later
CSV re-import never erases a star rating that only ever came from a screenshot.
"""

import csv
import re
import sqlite3
from datetime import datetime, timezone
from itertools import combinations

DB_PATH = "subscribers.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS subscribers (
    email TEXT NOT NULL,
    publication TEXT NOT NULL,
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
    last_updated_at TEXT,
    PRIMARY KEY (email, publication)
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


def upsert(conn, email, publication, source, **fields):
    """Insert or merge a subscriber row. Only non-None/non-empty fields overwrite existing values."""
    email = email.strip().lower()
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "SELECT * FROM subscribers WHERE email = ? AND publication = ?", (email, publication)
    )
    existing = cur.fetchone()
    col_names = [d[0] for d in cur.description] if existing else None

    if existing is None:
        row = {f: fields.get(f) for f in FIELDS}
        conn.execute(
            f"""INSERT INTO subscribers
                (email, publication, {", ".join(FIELDS)}, source, first_seen_at, last_updated_at)
                VALUES (?, ?, {", ".join("?" for _ in FIELDS)}, ?, ?, ?)""",
            (email, publication, *[row[f] for f in FIELDS], source, now, now),
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
                source = ?, last_updated_at = ? WHERE email = ? AND publication = ?""",
            (*[existing_dict[f] for f in FIELDS], source, now, email, publication),
        )
        return "updated"
    return "unchanged"


def publication_from_filename(csv_path):
    """email_list.<publication>.csv -> <publication>"""
    m = re.search(r"email_list\.([^.]+)\.csv$", csv_path)
    if not m:
        raise ValueError(
            f"Can't infer publication from {csv_path!r} — pass publication= explicitly"
        )
    return m.group(1)


def import_csv(conn, csv_path, publication=None, source="csv_export"):
    publication = publication or publication_from_filename(csv_path)
    counts = {"inserted": 0, "updated": 0, "unchanged": 0}
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            result = upsert(
                conn,
                row["email"],
                publication,
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
    return publication, counts


def import_screenshot_rows(conn, rows, publication, source="screenshot"):
    """rows: list of dicts with at least 'email'; optional plan, quality_stars, created_at, name."""
    counts = {"inserted": 0, "updated": 0, "unchanged": 0}
    for row in rows:
        result = upsert(
            conn,
            row["email"],
            publication,
            source,
            name=row.get("name"),
            plan=row.get("plan"),
            quality_stars=row.get("quality_stars"),
            created_at=row.get("created_at"),
        )
        counts[result] += 1
    conn.commit()
    return counts


def dedupe_summary(conn):
    """Per-publication counts, deduped total across all publications, and pairwise overlaps."""
    pubs = [r[0] for r in conn.execute("SELECT DISTINCT publication FROM subscribers ORDER BY 1")]
    by_pub = {
        p: set(
            r[0]
            for r in conn.execute("SELECT email FROM subscribers WHERE publication = ?", (p,))
        )
        for p in pubs
    }
    total_unique = len(set.union(*by_pub.values())) if by_pub else 0
    total_with_dupes = sum(len(s) for s in by_pub.values())
    overlaps = {
        (a, b): len(by_pub[a] & by_pub[b]) for a, b in combinations(pubs, 2)
    }
    all_overlap = len(set.intersection(*by_pub.values())) if len(by_pub) > 1 else None
    return {
        "per_publication": {p: len(s) for p, s in by_pub.items()},
        "total_with_duplicates": total_with_dupes,
        "total_unique": total_unique,
        "pairwise_overlap": overlaps,
        "all_publications_overlap": all_overlap,
    }


def print_dedupe_summary(conn):
    s = dedupe_summary(conn)
    print("Per-publication subscriber counts:")
    for pub, count in s["per_publication"].items():
        print(f"  {pub}: {count}")
    print(f"\nSum with duplicates: {s['total_with_duplicates']}")
    print(f"Unique total: {s['total_unique']}")
    print("\nPairwise overlap:")
    for (a, b), n in s["pairwise_overlap"].items():
        print(f"  {a} & {b}: {n}")
    if s["all_publications_overlap"] is not None:
        print(f"\nIn all publications: {s['all_publications_overlap']}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) == 2 and sys.argv[1] == "--summary":
        print_dedupe_summary(get_conn())
    elif len(sys.argv) == 2:
        conn = get_conn()
        publication, counts = import_csv(conn, sys.argv[1])
        total = conn.execute(
            "SELECT COUNT(*) FROM subscribers WHERE publication = ?", (publication,)
        ).fetchone()[0]
        print(f"[{publication}] {counts} — total in db for this publication: {total}")
    else:
        print("Usage:")
        print("  python subscribers.py <path-to-email_list-csv>   (publication inferred from filename)")
        print("  python subscribers.py --summary                  (deduped counts + overlaps)")
        sys.exit(1)
