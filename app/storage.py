from __future__ import annotations

import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "rss.db"


def get_conn(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS feeds (
          source_name TEXT PRIMARY KEY,
          notes TEXT,
          feed_updated TEXT,
          count INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS items (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source_name TEXT NOT NULL,
          title TEXT NOT NULL,
          link TEXT NOT NULL,
          published TEXT,
          published_ts TEXT,
          summary TEXT,
          UNIQUE(source_name, link, title)
        );
        """
    )
    conn.commit()


def save_snapshot(conn: sqlite3.Connection, generated: str, feeds: list[dict]) -> None:
    init_db(conn)
    with conn:
        conn.execute("DELETE FROM items")
        conn.execute("DELETE FROM feeds")
        for feed in feeds:
            conn.execute(
                "INSERT INTO feeds(source_name, notes, feed_updated, count) VALUES(?,?,?,?)",
                (feed["source_name"], feed.get("notes", ""), feed.get("feed_updated", ""), feed.get("count", 0)),
            )
            for item in feed.get("entries", []):
                conn.execute(
                    """
                    INSERT OR REPLACE INTO items(source_name, title, link, published, published_ts, summary)
                    VALUES(?,?,?,?,?,?)
                    """,
                    (
                        feed["source_name"],
                        item.get("title", ""),
                        item.get("link", ""),
                        item.get("published", ""),
                        item.get("published_ts", ""),
                        item.get("summary", ""),
                    ),
                )
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('generated',?)", (generated,))


def load_payload(conn: sqlite3.Connection) -> dict:
    init_db(conn)
    row = conn.execute("SELECT value FROM meta WHERE key='generated'").fetchone()
    generated = row[0] if row else None

    feeds_rows = conn.execute("SELECT source_name, notes, feed_updated, count FROM feeds ORDER BY source_name").fetchall()
    items_rows = conn.execute(
        "SELECT source_name, title, link, published, published_ts, summary FROM items ORDER BY published_ts DESC, id DESC"
    ).fetchall()

    items_by_feed: dict[str, list[dict]] = {}
    for r in items_rows:
        item = dict(r)
        items_by_feed.setdefault(item["source_name"], []).append(item)

    feeds = []
    for fr in feeds_rows:
        f = dict(fr)
        f["entries"] = items_by_feed.get(f["source_name"], [])
        feeds.append(f)

    return {"generated": generated, "feeds": feeds, "items": [dict(r) for r in items_rows]}
