"""Short-lived, persistent cache for validated Gemini JSON responses."""

import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import time


logger = logging.getLogger("formfriend.gemini.cache")
DEFAULT_TTL_SECONDS = 3600
DEFAULT_PATH = Path(__file__).resolve().parents[1] / ".cache" / "gemini-responses.sqlite3"


def response_key(payload: object) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _ttl_seconds() -> int:
    try:
        return max(0, int(os.getenv("GEMINI_CACHE_TTL_SECONDS", str(DEFAULT_TTL_SECONDS))))
    except ValueError:
        return DEFAULT_TTL_SECONDS


def _path() -> Path:
    configured = os.getenv("GEMINI_CACHE_PATH")
    return Path(configured).expanduser() if configured else DEFAULT_PATH


def _connect() -> sqlite3.Connection:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS responses ("
        "cache_key TEXT PRIMARY KEY, response_json TEXT NOT NULL, created_at REAL NOT NULL)"
    )
    return connection


def get_response(cache_key: str) -> str | None:
    ttl = _ttl_seconds()
    if ttl == 0:
        return None
    try:
        with _connect() as connection:
            cutoff = time.time() - ttl
            connection.execute("DELETE FROM responses WHERE created_at < ?", (cutoff,))
            row = connection.execute(
                "SELECT response_json FROM responses WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
        return row[0] if row else None
    except (OSError, sqlite3.Error):
        logger.warning("Gemini cache read failed", exc_info=True)
        return None


def put_response(cache_key: str, response_json: str) -> None:
    if _ttl_seconds() == 0:
        return
    try:
        with _connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO responses(cache_key, response_json, created_at) "
                "VALUES (?, ?, ?)",
                (cache_key, response_json, time.time()),
            )
    except (OSError, sqlite3.Error):
        logger.warning("Gemini cache write failed", exc_info=True)


def delete_response(cache_key: str) -> None:
    if _ttl_seconds() == 0:
        return
    try:
        with _connect() as connection:
            connection.execute("DELETE FROM responses WHERE cache_key = ?", (cache_key,))
    except (OSError, sqlite3.Error):
        logger.warning("Gemini cache delete failed", exc_info=True)
