"""SQLite database module for persistence.

Stores submitted requirements and generated test suite runs for auditability
and retrieval by the frontend.
"""
import json
import sqlite3
from pathlib import Path
from typing import Any

from schemas import GenerationResult, Requirement

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "app.db"


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = str(db_path or DEFAULT_DB_PATH)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path | str | None = None) -> None:
    """Initializes SQLite database tables."""
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS requirements (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    rules_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS generation_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    requirement_id TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    schema_valid_on_first_try INTEGER NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (requirement_id) REFERENCES requirements (id)
                )
                """
            )
    finally:
        conn.close()


def save_requirement(requirement: Requirement, db_path: Path | str | None = None) -> None:
    """Inserts or updates a requirement in SQLite."""
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO requirements (id, title, description, actor, priority, rules_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    requirement.id,
                    requirement.title,
                    requirement.description,
                    requirement.actor,
                    requirement.priority.value,
                    json.dumps(requirement.rules),
                ),
            )
    finally:
        conn.close()


def save_generation_run(
    result: GenerationResult,
    db_path: Path | str | None = None,
) -> int:
    """Saves a GenerationResult and returns its generated run ID."""
    conn = get_connection(db_path)
    try:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO generation_runs (requirement_id, model_name, schema_valid_on_first_try, result_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    result.requirement_id,
                    result.model_name,
                    1 if result.schema_valid_on_first_try else 0,
                    result.model_dump_json(),
                ),
            )
            return int(cursor.lastrowid)
    finally:
        conn.close()


def get_generation_history(
    limit: int = 50,
    db_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Retrieves summaries of past generation runs."""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            SELECT g.id, g.requirement_id, g.model_name, g.schema_valid_on_first_try, g.created_at,
                   r.title AS requirement_title, r.actor AS requirement_actor
            FROM generation_runs g
            LEFT JOIN requirements r ON g.requirement_id = r.id
            ORDER BY g.id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()
        return [
            {
                "run_id": row["id"],
                "requirement_id": row["requirement_id"],
                "requirement_title": row["requirement_title"],
                "requirement_actor": row["requirement_actor"],
                "model_name": row["model_name"],
                "schema_valid_on_first_try": bool(row["schema_valid_on_first_try"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]
    finally:
        conn.close()


def get_generation_run(
    run_id: int,
    db_path: Path | str | None = None,
) -> GenerationResult | None:
    """Retrieves the full GenerationResult for a specific run ID."""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            "SELECT result_json FROM generation_runs WHERE id = ?",
            (run_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return GenerationResult.model_validate_json(row["result_json"])
    finally:
        conn.close()

