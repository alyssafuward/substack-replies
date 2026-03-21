#!/usr/bin/env python3
"""
Flask app for Substack Replies dashboard.

Usage:
  python app.py
  Then open http://localhost:5000 in your browser.
"""

import sqlite3
from pathlib import Path
from flask import Flask, Response

from dashboard import load_data, load_stats, render_html

app = Flask(__name__)
DB_PATH = Path(__file__).parent / "replies.db"


@app.route("/")
def index():
    if not DB_PATH.exists():
        return Response(
            "No data found. Run: python scraper.py sync",
            mimetype="text/plain",
            status=503,
        )
    with sqlite3.connect(DB_PATH) as conn:
        items = load_data(conn)
        stats = load_stats(conn)
    html = render_html(items, stats)
    return Response(html, mimetype="text/html")


if __name__ == "__main__":
    print("Starting Substack Replies...")
    print("Open http://localhost:5001 in your browser")
    app.run(debug=False, port=5001)
