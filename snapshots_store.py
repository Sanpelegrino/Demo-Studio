"""Postgres-based snapshots: clone tables into a parallel `snapshots` schema.

Each snapshot copies every table in the live schema into
`snapshots.<snapshot_id>__<table_name>`. Rollback drops the live tables
and rebuilds them from the snapshot.

History metadata (id, summary, timestamp, language, code) is kept in
`snapshots.__history`.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import List, Optional

import psycopg
from psycopg import sql


SNAPSHOT_SCHEMA = "snapshots"
HISTORY_TABLE = "__history"


@dataclass
class Snapshot:
    id: str
    created_at: float
    summary: str
    language: str
    code: str


class SnapshotStore:
    def __init__(self, conn_kwargs: dict, live_schema: str):
        self.conn_kwargs = conn_kwargs
        self.live_schema = live_schema
        self._init_schema()

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(**self.conn_kwargs)

    def _init_schema(self) -> None:
        with self._connect() as con, con.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(SNAPSHOT_SCHEMA)))
            cur.execute(sql.SQL("""
                CREATE TABLE IF NOT EXISTS {schema}.{table} (
                    id          TEXT PRIMARY KEY,
                    created_at  DOUBLE PRECISION NOT NULL,
                    summary     TEXT,
                    language    TEXT,
                    code        TEXT,
                    tables      TEXT[],
                    views       JSONB
                )
            """).format(
                schema=sql.Identifier(SNAPSHOT_SCHEMA),
                table=sql.Identifier(HISTORY_TABLE),
            ))
            # Add views column to older history tables if missing.
            cur.execute(sql.SQL("""
                ALTER TABLE {schema}.{table} ADD COLUMN IF NOT EXISTS views JSONB
            """).format(
                schema=sql.Identifier(SNAPSHOT_SCHEMA),
                table=sql.Identifier(HISTORY_TABLE),
            ))
            con.commit()

    def _live_tables(self, cur: psycopg.Cursor) -> List[str]:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = %s AND table_type = 'BASE TABLE' "
            "ORDER BY table_name",
            (self.live_schema,),
        )
        return [r[0] for r in cur.fetchall()]

    def _live_views(self, cur: psycopg.Cursor) -> dict[str, str]:
        """Return {view_name: view_definition_sql} for all views in the schema."""
        cur.execute(
            "SELECT table_name, view_definition "
            "FROM information_schema.views "
            "WHERE table_schema = %s "
            "ORDER BY table_name",
            (self.live_schema,),
        )
        return {r[0]: r[1] for r in cur.fetchall()}

    def list(self) -> List[dict]:
        with self._connect() as con, con.cursor() as cur:
            cur.execute(sql.SQL("""
                SELECT id, created_at, summary, language, code
                FROM {schema}.{table}
                ORDER BY created_at ASC
            """).format(
                schema=sql.Identifier(SNAPSHOT_SCHEMA),
                table=sql.Identifier(HISTORY_TABLE),
            ))
            return [
                {
                    "id": r[0],
                    "created_at": float(r[1]),
                    "summary": r[2],
                    "language": r[3],
                    "code": r[4],
                }
                for r in cur.fetchall()
            ]

    def take(self, summary: str, language: str, code: str) -> Snapshot:
        import json
        sid = f"snap_{int(time.time() * 1000)}"
        with self._connect() as con, con.cursor() as cur:
            tables = self._live_tables(cur)
            views = self._live_views(cur)
            for t in tables:
                snap_name = f"{sid}__{t}"
                cur.execute(sql.SQL("""
                    CREATE TABLE {snap_schema}.{snap_name} AS
                    TABLE {live_schema}.{table}
                """).format(
                    snap_schema=sql.Identifier(SNAPSHOT_SCHEMA),
                    snap_name=sql.Identifier(snap_name),
                    live_schema=sql.Identifier(self.live_schema),
                    table=sql.Identifier(t),
                ))
            cur.execute(sql.SQL("""
                INSERT INTO {schema}.{table} (id, created_at, summary, language, code, tables, views)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """).format(
                schema=sql.Identifier(SNAPSHOT_SCHEMA),
                table=sql.Identifier(HISTORY_TABLE),
            ), (sid, time.time(), summary, language, code, tables, json.dumps(views)))
            con.commit()
        return Snapshot(sid, time.time(), summary, language, code)

    def clear(self) -> None:
        """Drop every snapshot clone and empty the history table."""
        with self._connect() as con, con.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = %s AND table_name <> %s",
                (SNAPSHOT_SCHEMA, HISTORY_TABLE),
            )
            snap_tables = [r[0] for r in cur.fetchall()]
            for t in snap_tables:
                cur.execute(sql.SQL("DROP TABLE IF EXISTS {}.{} CASCADE").format(
                    sql.Identifier(SNAPSHOT_SCHEMA), sql.Identifier(t),
                ))
            cur.execute(sql.SQL("DELETE FROM {}.{}").format(
                sql.Identifier(SNAPSHOT_SCHEMA), sql.Identifier(HISTORY_TABLE),
            ))
            con.commit()

    def rollback_last(self, *, discard: bool = False) -> Optional[Snapshot]:
        with self._connect() as con, con.cursor() as cur:
            cur.execute(sql.SQL("""
                SELECT id, created_at, summary, language, code, tables, views
                FROM {schema}.{table}
                ORDER BY created_at DESC
                LIMIT 1
            """).format(
                schema=sql.Identifier(SNAPSHOT_SCHEMA),
                table=sql.Identifier(HISTORY_TABLE),
            ))
            row = cur.fetchone()
            if row is None:
                return None
            sid, created_at, summary, language, code, tables, views = row
            views = views or {}
            # Drop current views first (so we can drop tables with CASCADE
            # cleanly), then drop live tables, then rebuild tables, then
            # recreate views.
            for v in self._live_views(cur):
                cur.execute(sql.SQL("DROP VIEW IF EXISTS {}.{} CASCADE").format(
                    sql.Identifier(self.live_schema), sql.Identifier(v),
                ))
            for t in self._live_tables(cur):
                cur.execute(sql.SQL("DROP TABLE IF EXISTS {}.{} CASCADE").format(
                    sql.Identifier(self.live_schema), sql.Identifier(t),
                ))
            for t in tables:
                snap_name = f"{sid}__{t}"
                cur.execute(sql.SQL("""
                    CREATE TABLE {live_schema}.{table} AS
                    TABLE {snap_schema}.{snap_name}
                """).format(
                    live_schema=sql.Identifier(self.live_schema),
                    table=sql.Identifier(t),
                    snap_schema=sql.Identifier(SNAPSHOT_SCHEMA),
                    snap_name=sql.Identifier(snap_name),
                ))
            for view_name, view_def in views.items():
                cur.execute(sql.SQL(
                    "CREATE OR REPLACE VIEW {schema}.{name} AS {body}"
                ).format(
                    schema=sql.Identifier(self.live_schema),
                    name=sql.Identifier(view_name),
                    body=sql.SQL(view_def),
                ))
            if discard:
                for t in tables:
                    snap_name = f"{sid}__{t}"
                    cur.execute(sql.SQL("DROP TABLE IF EXISTS {}.{}").format(
                        sql.Identifier(SNAPSHOT_SCHEMA), sql.Identifier(snap_name),
                    ))
                cur.execute(sql.SQL("""
                    DELETE FROM {schema}.{table} WHERE id = %s
                """).format(
                    schema=sql.Identifier(SNAPSHOT_SCHEMA),
                    table=sql.Identifier(HISTORY_TABLE),
                ), (sid,))
            con.commit()
        return Snapshot(sid, float(created_at), summary, language, code)
