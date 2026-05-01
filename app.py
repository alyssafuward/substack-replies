#!/usr/bin/env python3
"""
Flask app for Substack Replies dashboard.

Usage:
  python app.py
  Then open http://localhost:5000 in your browser.
"""

import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import threading
from pathlib import Path
from flask import Flask, Response, request, redirect, jsonify

from dashboard import load_data, load_stats, load_post_comments_data, load_responded_data, load_archived_data, render_html
from scraper import init_db, load_next_post, refresh_post_comments
from insights import load_all as load_insights, render_insights_html, search_commenter

app = Flask(__name__)
DB_PATH = Path(__file__).parent / "replies.db"

_sync_proc = None
_sync_lock = threading.Lock()
_sync_log_path = None  # temp file subprocess writes to


def _try_start_sync(cmd):
    """Start a subprocess writing to a temp file. Returns (started, error_str).
    If a sync is already running, returns (False, None) so caller can tail the existing log.
    """
    global _sync_proc, _sync_log_path
    with _sync_lock:
        if _sync_proc is not None and _sync_proc.poll() is None:
            return False, None  # already running — caller should tail existing log
        fd, _sync_log_path = tempfile.mkstemp(suffix=".log", prefix="substack_sync_")
        log_file = os.fdopen(fd, "w")
        _sync_proc = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=Path(__file__).parent,
            text=True,
        )
        log_file.close()  # parent closes its handle; subprocess keeps its own fd
        return True, None


def _finish_sync():
    global _sync_proc
    with _sync_lock:
        _sync_proc = None


def _tail_log(log_path):
    """SSE generator: tail a log file until the subprocess exits, then emit __done__."""
    position = 0
    while True:
        # Read any new output
        try:
            with open(log_path, "r") as f:
                f.seek(position)
                chunk = f.read()
                position = f.tell()
        except Exception:
            break

        if chunk:
            for line in chunk.splitlines():
                if line.strip():
                    yield f"data: {line}\n\n"

        # Check if process has exited
        with _sync_lock:
            proc = _sync_proc

        if proc is not None and proc.poll() is not None:
            # Drain any remaining output
            try:
                with open(log_path, "r") as f:
                    f.seek(position)
                    for line in f:
                        if line.strip():
                            yield f"data: {line.rstrip()}\n\n"
            except Exception:
                pass
            _finish_sync()
            yield "data: __done__\n\n"
            return
        elif proc is None:
            # Already cleaned up by another thread
            yield "data: __done__\n\n"
            return

        # No new content yet — keepalive and wait
        if not chunk:
            yield ": keepalive\n\n"
            time.sleep(0.5)


def _stream(cmd):
    """SSE generator: start subprocess (or attach to running one) and tail its log."""
    started, err = _try_start_sync(cmd)
    if err:
        yield f"data: ERROR: {err}\n\n"
        yield "data: __error__\n\n"
        return

    with _sync_lock:
        log_path = _sync_log_path

    if not log_path:
        yield "data: ERROR: Could not find sync log.\n\n"
        yield "data: __error__\n\n"
        return

    # Whether we started a new sync or attached to an existing one, tail the log
    yield from _tail_log(log_path)


_SSE_HEADERS = {"X-Accel-Buffering": "no", "Cache-Control": "no-cache"}


@app.route("/sync/status")
def sync_status():
    with _sync_lock:
        running = _sync_proc is not None and _sync_proc.poll() is None
    return jsonify({"running": running})


@app.route("/sync")
def sync():
    count = request.args.get("count", 250, type=int)
    cmd = [sys.executable, "-u", "scraper.py", "sync", "--count", str(count)]
    return Response(_stream(cmd), mimetype="text/event-stream", headers=_SSE_HEADERS)


@app.route("/posts/load")
def load_posts():
    pub = request.args.get("pub", "")
    count = request.args.get("count", 25, type=int)
    cmd = [sys.executable, "-u", "scraper.py", "load-posts", "--pub", pub, "--count", str(count)]
    return Response(_stream(cmd), mimetype="text/event-stream", headers=_SSE_HEADERS)


@app.route("/posts/sync")
def sync_posts():
    pub = request.args.get("pub", "")
    cmd = [sys.executable, "-u", "scraper.py", "sync-posts", "--pub", pub]
    return Response(_stream(cmd), mimetype="text/event-stream", headers=_SSE_HEADERS)


@app.route("/sync/stop", methods=["POST"])
def sync_stop():
    global _sync_proc
    with _sync_lock:
        if _sync_proc and _sync_proc.poll() is None:
            _sync_proc.terminate()
        _sync_proc = None
    return ("", 204)


@app.route("/archive", methods=["POST"])
def archive():
    comment_id = request.json.get("comment_id")
    if not comment_id:
        return jsonify({"error": "missing comment_id"}), 400
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        conn.execute(
            "UPDATE activity_items SET is_archived = 1 WHERE comment_id = ?",
            (comment_id,)
        )
    return jsonify({"ok": True})


@app.route("/unarchive", methods=["POST"])
def unarchive():
    comment_id = request.json.get("comment_id")
    if not comment_id:
        return jsonify({"error": "missing comment_id"}), 400
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        conn.execute(
            "UPDATE activity_items SET is_archived = 0 WHERE comment_id = ?",
            (comment_id,)
        )
    return jsonify({"ok": True})


@app.route("/how-it-works")
def how_it_works():
    p = Path(__file__).parent / "docs" / "index.html"
    return Response(p.read_text(), mimetype="text/html")


@app.route("/insights")
def insights():
    if not DB_PATH.exists():
        from flask import redirect
        return redirect("/")
    query = request.args.get("q", "").strip()
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        data = load_insights(conn)
        search_results = search_commenter(conn, query) if query else None
    html = render_insights_html(data, query=query or None, search_results=search_results)
    return Response(html, mimetype="text/html")


@app.route("/")
def index():
    if not DB_PATH.exists():
        return Response(render_empty(), mimetype="text/html")

    from config import OWN_PUBS
    all_pubs = list(OWN_PUBS.keys())
    active_tab = request.args.get("tab", "replies")
    liked_ack = request.args.get("liked_ack", "1") != "0"

    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        items = load_data(conn)
        stats = load_stats(conn)
        all_posts_data = {pub: load_post_comments_data(conn, pub) for pub in all_pubs}
        responded_items = load_responded_data(conn)
        archived_items = load_archived_data(conn)

    html = render_html(items, stats, all_posts_data=all_posts_data,
                       active_tab=active_tab, all_pubs=all_pubs,
                       responded_items=responded_items,
                       archived_items=archived_items,
                       liked_acknowledged=liked_ack)
    return Response(html, mimetype="text/html")


def render_empty():
    return """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Substack Replies</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=DM+Serif+Display&display=swap" rel="stylesheet">
<style>
  body { font-family: 'DM Sans', -apple-system, BlinkMacSystemFont, sans-serif;
         background: #F2F8FD; color: #1A1A1A; padding: 24px; }
  .header { max-width: 720px; margin: 0 auto 20px; }
  h1 { font-family: 'DM Serif Display', Georgia, serif; font-size: 1.8rem; font-weight: 400; margin-bottom: 4px; }
  .subtitle { color: #666; font-size: 0.9rem; margin-bottom: 16px; }
  .sync-row { display: flex; align-items: center; gap: 10px; margin-top: 14px; }
  .sync-btn { background: #1F6FA8; color: white; border: none; border-radius: 6px;
               padding: 6px 16px; font-size: 0.85rem; font-weight: 600; cursor: pointer;
               font-family: 'DM Sans', sans-serif; }
  .sync-btn:disabled { background: #ccc; cursor: default; }
  .sync-status { font-size: 0.82rem; color: #888; }
  .sync-log { margin-top: 10px; padding: 10px; background: #1A1A1A; color: #ccc;
               font-size: 0.75rem; border-radius: 6px; max-height: 300px; overflow-y: auto;
               white-space: pre-wrap; max-width: 720px; }
  select { border: 1px solid #D8ECF8; border-radius: 6px; font-family: 'DM Sans', sans-serif; }
</style></head>
<body>
  <div class="header">
    <h1>Substack Replies</h1>
    <div class="subtitle">No data yet — run a sync to get started.</div>
    <div class="sync-row">
      <label style="font-size:0.82rem; color:#666;">New replies to sync:</label>
      <select id="sync-count" style="font-size:0.82rem; padding:4px 6px;">
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
  <script>
    (function() {
      const saved = localStorage.getItem('lastSyncLog');
      if (saved) {
        const wrap = document.getElementById('last-sync-log-wrap');
        const pre = document.getElementById('last-sync-log');
        pre.textContent = saved;
        wrap.style.display = '';
      }
    })();
    function toggleLastLog(btn) {
      const pre = document.getElementById('last-sync-log');
      const open = pre.style.display === 'block';
      pre.style.display = open ? 'none' : 'block';
      btn.textContent = open ? '▶ Last sync log' : '▼ Last sync log';
    }
    let _es = null;
    function startSync() {
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
      _es.onmessage = function(e) {
        if (e.data === '__done__') {
          _es.close(); _es = null;
          localStorage.setItem('lastSyncLog', log.textContent);
          status.textContent = 'Done — reloading…';
          setTimeout(() => window.location.reload(), 1500);
          return;
        }
        log.textContent += e.data + '\\n';
        log.scrollTop = log.scrollHeight;
        status.textContent = e.data;
      };
      _es.onerror = function() {
        _es.close(); _es = null;
        fetch('/sync/status').then(r => r.json()).then(data => {
          if (data.running) {
            btn.style.display = 'none'; stopBtn.style.display = '';
            status.textContent = 'Connection lost — sync still running. Reconnecting…';
            setTimeout(function reconnect() {
              _es = new EventSource('/sync?count=0');
              _es.onmessage = function(e) {
                if (e.data === '__done__') {
                  _es.close(); _es = null;
                  localStorage.setItem('lastSyncLog', log.textContent);
                  status.textContent = 'Done — reloading…';
                  setTimeout(() => window.location.reload(), 1500);
                  return;
                }
                if (!e.data.startsWith('(')) { log.textContent += e.data + '\\n'; log.scrollTop = log.scrollHeight; }
                status.textContent = e.data;
              };
              _es.onerror = function() {
                _es.close(); _es = null;
                status.textContent = 'Connection lost — sync still running in background. Will reload when done.';
                var poll = setInterval(() => {
                  fetch('/sync/status').then(r => r.json()).then(d => {
                    if (!d.running) { clearInterval(poll); status.textContent = 'Done — reloading…'; setTimeout(() => window.location.reload(), 1500); }
                  });
                }, 5000);
              };
            }, 2000);
          } else {
            btn.style.display = ''; stopBtn.style.display = 'none';
            status.textContent = 'Sync completed. Reloading…';
            setTimeout(() => window.location.reload(), 1500);
          }
        }).catch(() => {
          btn.style.display = ''; stopBtn.style.display = 'none';
          status.textContent = 'Connection lost — reload to check status.';
        });
      };
    }
    function stopSync() {
      if (_es) { _es.close(); _es = null; }
      fetch('/sync/stop', {method: 'POST'});
      document.getElementById('sync-btn').style.display = '';
      document.getElementById('stop-btn').style.display = 'none';
      document.getElementById('sync-status').textContent = 'Stopped.';
    }
  </script>
</body></html>"""


if __name__ == "__main__":
    print("Starting Substack Replies...")
    print("Open http://localhost:5001 in your browser")
    app.run(debug=True, port=5001)
