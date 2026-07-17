from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any

from platformdirs import user_data_path


class SessionNotFoundError(KeyError):
    pass


class SessionStore:
    def __init__(self, database_path: Path | None = None) -> None:
        self.database_path = database_path or (
            user_data_path("brooks-model-mcp", "Brooks-Sem", ensure_exists=True)
            / "sessions.db"
        )
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10.0)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    messages_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def create(self, provider: str, model: str, messages: list[dict[str, Any]]) -> str:
        session_id = str(uuid.uuid4())
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO sessions(session_id, provider, model, messages_json) VALUES(?,?,?,?)",
                (session_id, provider, model, json.dumps(messages, ensure_ascii=False)),
            )
        return session_id

    def load(self, session_id: str, provider: str) -> tuple[str, list[dict[str, Any]]]:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT model, messages_json FROM sessions WHERE session_id=? AND provider=?",
                (session_id, provider),
            ).fetchone()
        if row is None:
            raise SessionNotFoundError(session_id)
        return str(row[0]), list(json.loads(row[1]))

    def save(
        self,
        session_id: str,
        provider: str,
        model: str,
        messages: list[dict[str, Any]],
    ) -> None:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE sessions
                SET model=?, messages_json=?, updated_at=CURRENT_TIMESTAMP
                WHERE session_id=? AND provider=?
                """,
                (model, json.dumps(messages, ensure_ascii=False), session_id, provider),
            )
            if cursor.rowcount != 1:
                raise SessionNotFoundError(session_id)

    def delete(self, session_id: str, provider: str) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM sessions WHERE session_id=? AND provider=?",
                (session_id, provider),
            )
            return cursor.rowcount == 1
