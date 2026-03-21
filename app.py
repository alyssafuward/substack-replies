#!/usr/bin/env python3
"""
Flask app for Substack Replies dashboard.

Usage:
  python app.py
  Then open http://localhost:5001 in your browser.
"""

import sqlite3
import subprocess
from pathlib import Path
from flask import Flask, Response

from dashboard import load_data, load_stats, render_html

app = Flask(__name__)
DB_PATH = Path(__file__).parent / "replies.db"
BASE_DIR = Path(__file__).parent

# Injected into the dashboard HTML after the .stats row in the header
SYNC_UI = """
<style>
  .sync-row {
    display: flex; align-items: center; gap: 12px;
    max-width: 720px; margin: 0 auto 16px; padding-top: 12px;
    border-top: 1px solid #eee;
  }
  .sync-btn {
    background: #ff3300; color: white; border: none;
    border-radius: 6px; padding: 6px 16px; font-size: 0.85rem;
    font-weight: 600; cursor: pointer; white-space: nowrap;
    flex-shrink: 0;
  }
  .sync-btn:disabled { background: #ddd; cursor: default; color: #999; }
  .sync-btn:hover:not(:disabled) { background: #cc2900; }
  .sync-phase {
    font-size: 0.82rem; color: #888; flex: 1; min-width: 0;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .sync-timer { font-size: 0.82rem; color: #bbb; flex-shrink: 0; }
  .sync-log-toggle {
    background: none; border: none; cursor: pointer;
    font-size: 0.75rem; color: #bbb; padding: 0; flex-shrink: 0;
    text-decoration: underline; text-underline-offset: 2px;
  }
  .sync-log-toggle:hover { color: #888; }
  .sync-log {
    display: none; margin: 0 auto 16px; max-width: 720px;
    background: #f7f7f7; border-radius: 6px; border: 1px solid #e5e5e5;
    font-family: monospace; font-size: 0.75rem; color: #555;
    max-height: 180px; overflow-y: auto; padding: 10px 14px;
  }
  .sync-log-line { margin: 1px 0; white-space: pre-wrap; }
</style>

<div class="sync-row">
  <button class="sync-btn" id="sync-btn" onclick="startSync()">↻ Sync</button>
  <span class="sync-phase" id="sync-phase">Last sync: {last_sync}</span>
  <span class="sync-timer" id="sync-timer"></span>
  <button class="sync-log-toggle" id="sync-log-toggle" style="display:none" onclick="toggleSyncLog()">Show log</button>
</div>
<div class="sync-log" id="sync-log"></div>

<script>
var _syncTimer = null;
var _syncStart = null;

function startSync() {
  const btn = document.getElementById('sync-btn');
  const phase = document.getElementById('sync-phase');
  const timer = document.getElementById('sync-timer');
  const log = document.getElementById('sync-log');
  const logToggle = document.getElementById('sync-log-toggle');

  btn.disabled = true;
  btn.textContent = 'Syncing…';
  phase.textContent = 'Starting…';
  timer.textContent = '0s';
  log.innerHTML = '';
  logToggle.style.display = 'inline';
  logToggle.textContent = 'Show log';
  log.style.display = 'none';

  _syncStart = Date.now();
  _syncTimer = setInterval(() => {
    timer.textContent = Math.floor((Date.now() - _syncStart) / 1000) + 's';
  }, 1000);

  const es = new EventSource('/sync');
  es.onmessage = function(e) {
    const text = e.data;

    if (text === '__DONE__') {
      es.close();
      clearInterval(_syncTimer);
      const elapsed = Math.floor((Date.now() - _syncStart) / 1000);
      phase.textContent = 'Sync complete (' + elapsed + 's) — reloading…';
      timer.textContent = '';
      setTimeout(() => location.reload(), 1200);
      return;
    }
    if (text === '__RATE_LIMITED__') {
      es.close();
      clearInterval(_syncTimer);
      btn.disabled = false;
      btn.textContent = '↻ Sync';
      phase.textContent = 'Too many requests to Substack — wait a few minutes and try again.';
      timer.textContent = '';
      return;
    }
    if (text === '__ERROR__') {
      es.close();
      clearInterval(_syncTimer);
      btn.disabled = false;
      btn.textContent = '↻ Sync';
      phase.textContent = 'Sync failed — check log';
      timer.textContent = '';
      return;
    }

    // Parse phase from log line
    if (text.includes('[activity]')) {
      const m = text.match(/page (\\d+)/);
      if (m) phase.textContent = 'Activity feed — page ' + m[1] + '…';
    } else if (text.includes('unanswered activity')) {
      const m = text.match(/(\\d+) unanswered/);
      if (m) phase.textContent = 'Activity feed — ' + m[1] + ' unanswered found…';
    } else if (text.includes('Reached target')) {
      phase.textContent = 'Activity feed done — scanning your posts…';
    } else if (text.match(/\\[\\d+\\/\\d+\\] fetching/)) {
      const m = text.match(/\\[(\\d+)\\/(\\d+)\\]/);
      const title = text.split('fetching:')[1] || '';
      if (m) phase.textContent = 'Posts ' + m[1] + '/' + m[2] + ': ' + title.trim().slice(0, 50);
    } else if (text.includes('Sync complete')) {
      phase.textContent = 'Finishing up…';
    }

    // Always append to log
    const line = document.createElement('div');
    line.className = 'sync-log-line';
    line.textContent = text;
    log.appendChild(line);
    if (log.style.display === 'block') log.scrollTop = log.scrollHeight;
  };

  es.onerror = function() {
    es.close();
    clearInterval(_syncTimer);
    btn.disabled = false;
    btn.textContent = '↻ Sync';
    phase.textContent = 'Connection error';
    timer.textContent = '';
  };
}

function toggleSyncLog() {
  const log = document.getElementById('sync-log');
  const btn = document.getElementById('sync-log-toggle');
  const open = log.style.display === 'block';
  log.style.display = open ? 'none' : 'block';
  btn.textContent = open ? 'Show log' : 'Hide log';
  if (!open) log.scrollTop = log.scrollHeight;
}
</script>
"""


@app.route("/sync")
def sync():
    def generate():
        import os
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        proc = subprocess.Popen(
            ["python", "-u", "scraper.py", "sync"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(BASE_DIR),
            env=env,
        )
        rate_limited = False
        for line in proc.stdout:
            text = line.rstrip()
            if text == "RATE_LIMITED":
                rate_limited = True
                yield f"data: Too many requests to Substack — wait a few minutes and try again.\n\n"
            else:
                yield f"data: {text}\n\n"
        proc.wait()
        if rate_limited:
            yield "data: __RATE_LIMITED__\n\n"
        elif proc.returncode == 0:
            yield "data: __DONE__\n\n"
        else:
            yield "data: __ERROR__\n\n"

    return Response(generate(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


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
    sync_ui = SYNC_UI.replace("{last_sync}", stats["last_sync"])
    # Inject sync UI before the intro section (after the header)
    html = html.replace('<div class="intro">', sync_ui + '\n  <div class="intro">', 1)
    return Response(html, mimetype="text/html")


if __name__ == "__main__":
    print("Starting Substack Replies...")
    print("Open http://localhost:5001 in your browser")
    app.run(debug=False, port=5001, threaded=True)
