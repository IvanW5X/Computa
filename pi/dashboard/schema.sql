-- Target path on the Pi: /home/yelopi/dashboard/schema.sql
--
-- Initialise once with:
--   sqlite3 /home/yelopi/dashboard/requests.db < /home/yelopi/dashboard/schema.sql
--
-- WAL mode lets the router keep writing while the dashboard server
-- (read-only) is reading. Without WAL the dashboard would intermittently
-- block the writer on a busy Pi.

PRAGMA journal_mode = WAL;
PRAGMA synchronous  = NORMAL;

CREATE TABLE IF NOT EXISTS requests (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT    NOT NULL,                                   -- ISO-8601 UTC, e.g. 2026-05-03T19:30:14Z
    route         TEXT    NOT NULL CHECK (route IN ('local','cloud')),
    model         TEXT    NOT NULL,                                   -- 'nemotron-mini:4b' or 'nvidia/nemotron-3-super-120b-a12b'
    user_message  TEXT    NOT NULL,                                   -- first 200 chars only
    latency_ms    INTEGER NOT NULL DEFAULT 0
);

-- "Last 50" view scans by id DESC; counters group by route.
CREATE INDEX IF NOT EXISTS idx_requests_id_desc ON requests (id DESC);
CREATE INDEX IF NOT EXISTS idx_requests_route   ON requests (route);
