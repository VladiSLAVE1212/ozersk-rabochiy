"""SQLite helpers. Single-file DB for maximum simplicity."""
from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.environ.get("OZERSK_DB", "ozersk.db")).resolve()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    display_name  TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    is_admin      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS categories (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    slug  TEXT UNIQUE NOT NULL,
    name  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS posts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    slug         TEXT UNIQUE NOT NULL,
    title        TEXT NOT NULL,
    summary      TEXT NOT NULL DEFAULT '',
    body         TEXT NOT NULL,
    cover_url    TEXT NOT NULL DEFAULT '',
    category_id  INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    author_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    published    INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_posts_category ON posts(category_id);

CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5(
    title, summary, body, content='posts', content_rowid='id', tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS posts_ai AFTER INSERT ON posts BEGIN
    INSERT INTO posts_fts(rowid, title, summary, body)
    VALUES (new.id, new.title, new.summary, new.body);
END;

CREATE TRIGGER IF NOT EXISTS posts_ad AFTER DELETE ON posts BEGIN
    INSERT INTO posts_fts(posts_fts, rowid, title, summary, body)
    VALUES('delete', old.id, old.title, old.summary, old.body);
END;

CREATE TRIGGER IF NOT EXISTS posts_au AFTER UPDATE ON posts BEGIN
    INSERT INTO posts_fts(posts_fts, rowid, title, summary, body)
    VALUES('delete', old.id, old.title, old.summary, old.body);
    INSERT INTO posts_fts(rowid, title, summary, body)
    VALUES (new.id, new.title, new.summary, new.body);
END;
"""

DEFAULT_CATEGORIES = [
    ("politika", "Политика"),
    ("ekonomika", "Экономика"),
    ("kultura", "Культура"),
    ("zhkkh", "ЖКХ"),
    ("sport", "Спорт"),
    ("proishestviya", "Происшествия"),
    ("nauka", "Наука и Техника"),
    ("za-rubezhom", "За рубежом"),
]


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        for slug, name in DEFAULT_CATEGORIES:
            conn.execute(
                "INSERT OR IGNORE INTO categories (slug, name) VALUES (?, ?)",
                (slug, name),
            )
