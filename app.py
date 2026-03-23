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
_sync_proc = None


@app.route("/sync")
def sync():
    global _sync_proc
    count = request.args.get("count", 250, type=int)
    def generate():
        global _sync_proc
        _sync_proc = subprocess.Popen(
            [sys.executable, "-u", "scraper.py", "sync", "--count", str(count)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=Path(__file__).parent,
            text=True,
        )
        for line in _sync_proc.stdout:
            yield f"data: {line.rstrip()}\n\n"
        _sync_proc.wait()
        _sync_proc = None
        yield "data: __done__\n\n"
    return Response(generate(), mimetype="text/event-stream",
                    headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})


@app.route("/sync/stop", methods=["POST"])
def sync_stop():
    global _sync_proc
    if _sync_proc and _sync_proc.poll() is None:
        _sync_proc.terminate()
        _sync_proc = None
    return ("", 204)


@app.route("/")
def index():
    if not DB_PATH.exists():
        return Response(render_empty(), mimetype="text/html")
    with sqlite3.connect(DB_PATH) as conn:
        items = load_data(conn)
        stats = load_stats(conn)
    html = render_html(items, stats)
    return Response(html, mimetype="text/html")


def render_empty():
    return """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Substack Replies</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         background: #f5f4f0; color: #1a1a1a; padding: 24px; }
  .header { max-width: 720px; margin: 0 auto 20px; }
  h1 { font-size: 1.6rem; font-weight: 700; margin-bottom: 4px; }
  .subtitle { color: #666; font-size: 0.9rem; margin-bottom: 16px; }
  .sync-row { display: flex; align-items: center; gap: 10px; margin-top: 14px; }
  .sync-btn { background: #ff3300; color: white; border: none; border-radius: 6px;
               padding: 6px 16px; font-size: 0.85rem; font-weight: 600; cursor: pointer; }
  .sync-btn:disabled { background: #ccc; cursor: default; }
  .sync-status { font-size: 0.82rem; color: #888; }
  .sync-log { margin-top: 10px; padding: 10px; background: #1a1a1a; color: #ccc;
               font-size: 0.75rem; border-radius: 6px; max-height: 300px; overflow-y: auto;
               white-space: pre-wrap; max-width: 720px; }
</style></head>
<body>
  <div class="header">
    <h1>Substack Replies</h1>
    <div class="subtitle">No data yet — run a sync to get started.</div>
    <div class="sync-row">
      <label style="font-size:0.82rem; color:#666;">New replies to sync:</label>
      <select id="sync-count" style="font-size:0.82rem; padding:4px 6px; border-radius:4px; border:1px solid #ccc;">
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
        btn.style.display = ''; stopBtn.style.display = 'none';
        status.textContent = 'Error — check terminal';
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
    app.run(debug=False, port=5001)
