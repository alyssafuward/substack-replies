#!/usr/bin/env python3
"""
Flask app for Substack Replies dashboard.

Usage:
  python app.py
  Then open http://localhost:5000 in your browser.
"""

import sqlite3
import subprocess
import sys
from pathlib import Path
from flask import Flask, Response, request

from dashboard import load_data, load_stats, render_html

app = Flask(__name__)
DB_PATH = Path(__file__).parent / "replies.db"


@app.route("/sync")
def sync():
    count = request.args.get("count", 250, type=int)
    def generate():
        proc = subprocess.Popen(
            [sys.executable, "-u", "scraper.py", "sync", "--count", str(count)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=Path(__file__).parent,
            text=True,
        )
        for line in proc.stdout:
            yield f"data: {line.rstrip()}\n\n"
        proc.wait()
        yield "data: __done__\n\n"
    return Response(generate(), mimetype="text/event-stream",
                    headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})


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
