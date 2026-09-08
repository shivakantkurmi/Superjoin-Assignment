from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any


class DatabaseConfigurationError(RuntimeError):
    """Raised when Supabase database configuration is missing."""


class SupabaseRepository:
    """Thin PostgreSQL adapter; business logic stays outside the persistence layer."""

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or os.getenv("SUPABASE_DB_URL")
        self._connection = None

    def connect(self) -> Any:
        if not self.database_url:
            raise DatabaseConfigurationError("SUPABASE_DB_URL is not configured")
        if self._connection is None:
            try:
                import psycopg
            except ImportError as exc:  # pragma: no cover - setup failure path
                raise DatabaseConfigurationError("psycopg is not installed") from exc
            self._connection = psycopg.connect(self.database_url)
        return self._connection

    def insert(self, table: str, values: Mapping[str, Any]) -> None:
        """Insert one row using parameterized SQL; table names are allow-listed."""
        allowed_tables = {
            "documents", "pages", "chunks", "facts", "evidence", "relationships",
            "processing_runs", "processing_errors",
        }
        if table not in allowed_tables:
            raise ValueError(f"Unsupported table: {table}")
        columns = list(values)
        placeholders = ", ".join([f"%s"] * len(columns))
        query = f"insert into {table} ({', '.join(columns)}) values ({placeholders})"
        with self.connect().cursor() as cursor:
            cursor.execute(query, [values[column] for column in columns])
        self.connect().commit()