"""SQLite storage layer for the Repo Analysis Tool."""
from __future__ import annotations

import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = REPO_ROOT / "data" / "rat.sqlite3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS repositories (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    source_type   TEXT    NOT NULL CHECK (source_type IN ('zip', 'clone')),
    source        TEXT    NOT NULL,
    path          TEXT    NOT NULL,
    ref           TEXT    NOT NULL DEFAULT 'HEAD',
    status        TEXT    NOT NULL DEFAULT 'pending',
    progress      INTEGER NOT NULL DEFAULT 0,
    commit_total  INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS authors (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id      INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    name         TEXT    NOT NULL,
    email        TEXT    NOT NULL,
    canonical_id INTEGER REFERENCES authors(id),
    UNIQUE (repo_id, name, email)
);

CREATE TABLE IF NOT EXISTS commits (
    repo_id        INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    hash           TEXT    NOT NULL,
    author_id      INTEGER NOT NULL REFERENCES authors(id),
    committer_date INTEGER NOT NULL,
    parent_hash    TEXT,
    subject        TEXT    NOT NULL DEFAULT '',
    PRIMARY KEY (repo_id, hash)
);
CREATE INDEX IF NOT EXISTS idx_commits_date ON commits(repo_id, committer_date);

CREATE TABLE IF NOT EXISTS changes (
    repo_id     INTEGER NOT NULL,
    commit_hash TEXT    NOT NULL,
    path        TEXT    NOT NULL,
    is_dir      INTEGER NOT NULL,
    added       INTEGER NOT NULL,
    removed     INTEGER NOT NULL,
    PRIMARY KEY (repo_id, commit_hash, path, is_dir)
);
CREATE INDEX IF NOT EXISTS idx_changes_object ON changes(repo_id, path, is_dir, commit_hash);
"""


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn
