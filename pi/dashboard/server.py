#!/usr/bin/env python3
# Target path on the Pi: /home/yelopi/dashboard/server.py
#
# Zero-dependency metrics dashboard for the hybrid AI gateway.
# - Pure Python 3 stdlib + sqlite3 (no Flask, no npm, no CDN).
# - Serves a single self-contained HTML page at GET / .
# - Serves a JSON snapshot at GET /api/stats which the page polls every 10 s.
# - Reads /home/yelopi/dashboard/requests.db in URI read-only mode so the
#   router's writes are never blocked by us.
# - HTTP/1.1 keepalive enabled so phone browsers on the LAN can reuse a
#   single TCP connection across the 10 s polling cycle.
#
# Run on port 3000, bind 0.0.0.0 so any device on the LAN can hit it.

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# ---------- Config ---------------------------------------------------------

LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 3000

DB_PATH = os.environ.get("ROUTER_DB_PATH", "/home/yelopi/dashboard/requests.db")

# Tokens "saved" per local request, per the spec.
TOKENS_SAVED_PER_LOCAL = 500

# Browser polling interval. The HTML's JS uses this same value.
REFRESH_SECONDS = 10


# ---------- DB read --------------------------------------------------------

def _db_open_ro() -> sqlite3.Connection | None:
    """Open the DB read-only via URI mode. Returns None if the file does
    not exist yet (router has not logged anything) or if it is briefly
    locked / unreadable. Callers must tolerate None."""
    if not Path(DB_PATH).exists():
        return None
    try:
        uri = f"file:{DB_PATH}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=2.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.OperationalError as e:
        sys.stderr.write(f"[dash] db open failed (will retry next poll): {e}\n")
        return None


def _empty_stats() -> dict:
    return {
        "total":          0,
        "local":          0,
        "cloud":          0,
        "local_pct":      0.0,
        "cloud_pct":      0.0,
        "saved_tokens":   0,
        "avg_local_ms":   0,
        "avg_cloud_ms":   0,
        "recent":         [],
        "db_missing":     True,
        "generated_at":   _now_iso(),
    }


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def gather_stats() -> dict:
    """Pull headline counters + last-50 list. Tolerant of missing DB and
    of transient `database is locked` errors from the router writing."""
    conn = _db_open_ro()
    if conn is None:
        return _empty_stats()

    try:
        try:
            total = conn.execute("SELECT COUNT(*) AS c FROM requests").fetchone()["c"]
        except sqlite3.OperationalError:
            return _empty_stats()

        if total == 0:
            stats = _empty_stats()
            stats["db_missing"] = False
            return stats

        local = conn.execute(
            "SELECT COUNT(*) AS c FROM requests WHERE route = 'local'"
        ).fetchone()["c"]
        cloud = conn.execute(
            "SELECT COUNT(*) AS c FROM requests WHERE route = 'cloud'"
        ).fetchone()["c"]

        avg_local = conn.execute(
            "SELECT COALESCE(AVG(latency_ms), 0) AS a "
            "FROM requests WHERE route = 'local'"
        ).fetchone()["a"]
        avg_cloud = conn.execute(
            "SELECT COALESCE(AVG(latency_ms), 0) AS a "
            "FROM requests WHERE route = 'cloud'"
        ).fetchone()["a"]

        recent_rows = conn.execute(
            "SELECT id, timestamp, route, model, latency_ms, user_message "
            "FROM requests ORDER BY id DESC LIMIT 50"
        ).fetchall()
    finally:
        conn.close()

    recent: list[dict] = []
    for r in recent_rows:
        msg = (r["user_message"] or "")
        recent.append({
            "id":         r["id"],
            "timestamp":  r["timestamp"],
            "route":      r["route"],
            "model":      r["model"],
            "latency_ms": int(r["latency_ms"]),
            "message":    msg[:60],
        })

    return {
        "total":         int(total),
        "local":         int(local),
        "cloud":         int(cloud),
        "local_pct":     round(100.0 * local / total, 1) if total else 0.0,
        "cloud_pct":     round(100.0 * cloud / total, 1) if total else 0.0,
        "saved_tokens":  int(local) * TOKENS_SAVED_PER_LOCAL,
        "avg_local_ms":  int(round(avg_local)),
        "avg_cloud_ms":  int(round(avg_cloud)),
        "recent":        recent,
        "db_missing":    False,
        "generated_at":  _now_iso(),
    }


# ---------- HTML (single self-contained page, no CDN) ---------------------

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Gateway Dashboard</title>
<style>
  *,*::before,*::after { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    font: 14px/1.45 -apple-system, "Segoe UI", Roboto, system-ui, sans-serif;
    background: #0e1116; color: #e6edf3; padding: 20px;
    min-height: 100vh;
  }
  h1 { margin: 0 0 4px; font-size: 22px; letter-spacing: -.01em; }
  .sub { color: #8b949e; margin-bottom: 20px; font-size: 12px; }
  .sub code { background: #161b22; padding: 1px 6px; border-radius: 4px; }
  .grid {
    display: grid; gap: 12px;
    grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
    margin-bottom: 22px;
  }
  .card {
    background: #161b22; border: 1px solid #30363d;
    border-radius: 8px; padding: 14px 16px;
  }
  .card .label {
    color: #8b949e; font-size: 11px; text-transform: uppercase;
    letter-spacing: .08em;
  }
  .card .value { font-size: 26px; font-weight: 600; margin-top: 4px; }
  .card .pct   { color: #8b949e; font-size: 12px; margin-top: 2px; }
  .card.local  { border-left: 4px solid #2ea043; }
  .card.local  .value { color: #56d364; }
  .card.cloud  { border-left: 4px solid #db8f2a; }
  .card.cloud  .value { color: #f0a55b; }
  .card.saved  { border-left: 4px solid #58a6ff; }
  .card.lat    { border-left: 4px solid #8b949e; }

  h2 { font-size: 14px; margin: 0 0 8px; color: #8b949e;
       text-transform: uppercase; letter-spacing: .08em; }

  .table-wrap {
    border: 1px solid #30363d; border-radius: 8px; overflow: hidden;
  }
  table {
    width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums;
  }
  thead th {
    text-align: left; padding: 10px 12px; font-size: 11px;
    text-transform: uppercase; letter-spacing: .06em; color: #8b949e;
    background: #0d1117; border-bottom: 1px solid #30363d;
  }
  tbody td {
    padding: 9px 12px; border-top: 1px solid #21262d;
    vertical-align: top;
  }
  tbody tr.row-local { background: #0f2912; }
  tbody tr.row-cloud { background: #2b1f0a; }
  tbody tr.row-local td.col-route { color: #56d364; font-weight: 600; }
  tbody tr.row-cloud td.col-route { color: #f0a55b; font-weight: 600; }
  td.col-msg {
    color: #c9d1d9; max-width: 360px;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  td.col-lat { text-align: right; color: #8b949e; }
  .empty { padding: 18px; text-align: center; color: #8b949e; }
  .warn {
    background: #2d1f1f; border: 1px solid #6b2c2c; color: #ffa6a6;
    padding: 10px 14px; border-radius: 8px; margin-bottom: 14px; font-size: 13px;
  }
  footer { margin-top: 18px; color: #6e7681; font-size: 11px; }
  .pulse { display: inline-block; width: 6px; height: 6px; border-radius: 50%;
           background: #2ea043; margin-right: 6px; vertical-align: middle; }
  .pulse.stale { background: #db8f2a; }

  @media (max-width: 700px) {
    body { padding: 14px; }
    .card .value { font-size: 22px; }
    table thead th.col-model,
    table tbody td.col-model { display: none; }
    td.col-msg { max-width: 160px; }
  }
</style>
</head>
<body>
  <h1>AI Gateway Dashboard</h1>
  <div class="sub">
    <span class="pulse" id="pulse"></span>
    <span id="status">connecting...</span>
    &middot; auto-refresh every __REFRESH__s
    &middot; reading <code>__DBPATH__</code>
  </div>

  <div id="warn-slot"></div>

  <div class="grid">
    <div class="card">
      <div class="label">Total requests</div>
      <div class="value" id="m-total">0</div>
    </div>
    <div class="card local">
      <div class="label">Local resolved</div>
      <div class="value" id="m-local">0</div>
      <div class="pct"  id="m-local-pct">0.0%</div>
    </div>
    <div class="card cloud">
      <div class="label">Cloud escalated</div>
      <div class="value" id="m-cloud">0</div>
      <div class="pct"  id="m-cloud-pct">0.0%</div>
    </div>
    <div class="card saved">
      <div class="label">Est. tokens saved</div>
      <div class="value" id="m-saved">0</div>
      <div class="pct">500 tokens / local request</div>
    </div>
    <div class="card lat">
      <div class="label">Avg latency &middot; local</div>
      <div class="value" id="m-avg-local">0 ms</div>
    </div>
    <div class="card lat">
      <div class="label">Avg latency &middot; cloud</div>
      <div class="value" id="m-avg-cloud">0 ms</div>
    </div>
  </div>

  <h2>Last 50 requests</h2>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Time (UTC)</th>
          <th>Route</th>
          <th class="col-model">Model</th>
          <th>Message</th>
          <th style="text-align:right">Latency</th>
        </tr>
      </thead>
      <tbody id="tbody">
        <tr><td colspan="5" class="empty">loading...</td></tr>
      </tbody>
    </table>
  </div>

  <footer id="foot">never updated</footer>

<script>
(function () {
  var REFRESH_MS = __REFRESH__ * 1000;
  var $ = function (id) { return document.getElementById(id); };

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function fmt(n) {
    return Number(n || 0).toLocaleString();
  }

  function render(s) {
    $("m-total").textContent      = fmt(s.total);
    $("m-local").textContent      = fmt(s.local);
    $("m-local-pct").textContent  = (s.local_pct || 0).toFixed(1) + "%";
    $("m-cloud").textContent      = fmt(s.cloud);
    $("m-cloud-pct").textContent  = (s.cloud_pct || 0).toFixed(1) + "%";
    $("m-saved").textContent      = fmt(s.saved_tokens);
    $("m-avg-local").textContent  = fmt(s.avg_local_ms) + " ms";
    $("m-avg-cloud").textContent  = fmt(s.avg_cloud_ms) + " ms";

    var warn = "";
    if (s.db_missing) {
      warn = '<div class="warn">requests.db not found at <code>__DBPATH__</code>. ' +
             'Initialise it: <code>sqlite3 __DBPATH__ &lt; /home/yelopi/dashboard/schema.sql</code></div>';
    }
    $("warn-slot").innerHTML = warn;

    var rows = s.recent || [];
    var tbody = $("tbody");
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="empty">No requests yet.</td></tr>';
    } else {
      var html = "";
      for (var i = 0; i < rows.length; i++) {
        var r = rows[i];
        var cls = r.route === "local" ? "row-local" : "row-cloud";
        html += '<tr class="' + cls + '">' +
                  '<td>' + escapeHtml(r.timestamp) + '</td>' +
                  '<td class="col-route">' + escapeHtml(String(r.route).toUpperCase()) + '</td>' +
                  '<td class="col-model">' + escapeHtml(r.model) + '</td>' +
                  '<td class="col-msg" title="' + escapeHtml(r.message) + '">' + escapeHtml(r.message) + '</td>' +
                  '<td class="col-lat">' + fmt(r.latency_ms) + ' ms</td>' +
                '</tr>';
      }
      tbody.innerHTML = html;
    }

    $("status").textContent = "live";
    $("pulse").classList.remove("stale");
    $("foot").textContent = "Updated " + s.generated_at;
  }

  function markStale(msg) {
    $("status").textContent = msg || "stale";
    $("pulse").classList.add("stale");
  }

  function tick() {
    fetch("/api/stats", { cache: "no-store" })
      .then(function (r) {
        if (!r.ok) { throw new Error("HTTP " + r.status); }
        return r.json();
      })
      .then(render)
      .catch(function (e) {
        markStale("offline (" + e.message + ")");
      });
  }

  tick();
  setInterval(tick, REFRESH_MS);
})();
</script>
</body>
</html>
"""


def _render_index() -> bytes:
    page = (
        INDEX_HTML
        .replace("__REFRESH__", str(REFRESH_SECONDS))
        .replace("__DBPATH__",  DB_PATH)
    )
    return page.encode("utf-8")


# Pre-render once at import; the template never changes per request.
_INDEX_BYTES = _render_index()


# ---------- HTTP server ---------------------------------------------------

class DashHandler(BaseHTTPRequestHandler):
    server_version  = "ComputaDash/1.0"
    # HTTP/1.1 enables keepalive; mobile browsers will reuse the TCP socket
    # for the 10 s polling cycle instead of reopening every time.
    protocol_version = "HTTP/1.1"

    def _send_bytes(self, status: int, body: bytes,
                    content_type: str = "text/html; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler API)
        path = self.path.split("?", 1)[0]

        if path in ("/", "/index.html"):
            return self._send_bytes(200, _INDEX_BYTES)

        if path == "/api/stats":
            try:
                stats = gather_stats()
                body  = json.dumps(stats).encode("utf-8")
                return self._send_bytes(200, body, "application/json; charset=utf-8")
            except Exception as e:
                sys.stderr.write(f"[dash] /api/stats failed: {e}\n")
                err = json.dumps({"error": str(e)}).encode("utf-8")
                return self._send_bytes(500, err, "application/json; charset=utf-8")

        if path == "/healthz":
            return self._send_bytes(200, b"ok", "text/plain; charset=utf-8")

        return self._send_bytes(404, b"not found", "text/plain; charset=utf-8")

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("[dash] " + (fmt % args) + "\n")


def main() -> int:
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), DashHandler)
    sys.stderr.write(
        f"[dash] listening on http://{LISTEN_HOST}:{LISTEN_PORT}  db={DB_PATH}\n"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
