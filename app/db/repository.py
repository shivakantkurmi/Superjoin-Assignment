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
            from psycopg.rows import dict_row
            self._connection = psycopg.connect(self.database_url, row_factory=dict_row)
        return self._connection

    @staticmethod
    def _adapt_value(val: Any) -> Any:
        if isinstance(val, (dict, list)):
            try:
                from psycopg.types.json import Jsonb
                return Jsonb(val)
            except ImportError:
                import json
                return json.dumps(val)
        return val

    def fetch_all(self, table: str) -> list[dict[str, Any]]:
        allowed_tables = {
            "documents", "pages", "chunks", "facts", "evidence", "relationships",
            "processing_runs", "processing_errors",
        }
        if table not in allowed_tables:
            raise ValueError(f"Unsupported table: {table}")
        try:
            with self.connect().cursor() as cursor:
                cursor.execute(f"select * from {table}")
                return list(cursor.fetchall())
        except Exception:
            if self._connection:
                self._connection.rollback()
            raise

    def insert(self, table: str, values: Mapping[str, Any]) -> None:
        """Insert one row using parameterized SQL; table names are allow-listed."""
        self.insert_many(table, [values])

    def insert_many(self, table: str, rows: list[Mapping[str, Any]]) -> None:
        """Insert multiple rows in a single batch using executemany."""
        if not rows:
            return
        allowed_tables = {
            "documents", "pages", "chunks", "facts", "evidence", "relationships",
            "processing_runs", "processing_errors",
        }
        if table not in allowed_tables:
            raise ValueError(f"Unsupported table: {table}")
        columns = list(rows[0])
        placeholders = ", ".join(["%s"] * len(columns))
        query = f"insert into {table} ({', '.join(columns)}) values ({placeholders})"
        try:
            with self.connect().cursor() as cursor:
                params_list = [
                    [self._adapt_value(row.get(col)) for col in columns]
                    for row in rows
                ]
                cursor.executemany(query, params_list)
            self.connect().commit()
        except Exception:
            if self._connection:
                self._connection.rollback()
            raise

    def update(self, table: str, row_id: str, values: Mapping[str, Any]) -> None:
        """Update a single row by id using parameterized SQL; table names are allow-listed."""
        allowed_tables = {
            "documents", "pages", "chunks", "facts", "evidence", "relationships",
            "processing_runs", "processing_errors",
        }
        if table not in allowed_tables:
            raise ValueError(f"Unsupported table: {table}")
        columns = list(values)
        set_clause = ", ".join(f"{col} = %s" for col in columns)
        query = f"update {table} set {set_clause} where id = %s"
        try:
            with self.connect().cursor() as cursor:
                cursor.execute(query, [self._adapt_value(values[col]) for col in columns] + [row_id])
            self.connect().commit()
        except Exception:
            if self._connection:
                self._connection.rollback()
            raise