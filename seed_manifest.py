"""Deterministic loader for manifest-based datasets.

Given a folder containing a `manifest.json` and one CSV per declared
table, this module drops only the incoming tables (not the whole schema),
loads the CSVs verbatim, then builds one analytics view per fact table.

For single-fact datasets: one view named `analytics`.
For multi-fact datasets: one view per fact, named `analytics_<fact>`.

Dimension joins are walked transitively — if Fact_Order -> Dim_Store
and Dim_Store -> Dim_Location, the Fact_Order view includes Location
columns via Store.

No LLM involvement anywhere in this path — rows come straight from
the CSVs.
"""
from __future__ import annotations

import io
import json
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg
from psycopg import sql


def _conn_kwargs() -> dict:
    return {
        "host": os.environ.get("PGHOST", "127.0.0.1"),
        "port": int(os.environ.get("PGPORT", "5432")),
        "user": os.environ.get("PGUSER", "demo_studio"),
        "password": os.environ.get("PGPASSWORD", "demo_local_dev"),
        "dbname": os.environ.get("PGDATABASE", "demo_studio"),
    }


_SAFE_IDENT = re.compile(r"[^a-z0-9_]+")


def _ident(raw: str) -> str:
    """Lowercase, snake_case-ify, and strip anything Postgres would reject."""
    s = raw.strip().lower().replace(" ", "_").replace("-", "_")
    s = _SAFE_IDENT.sub("_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    if not s:
        raise ValueError(f"Identifier reduces to empty string: {raw!r}")
    if s[0].isdigit():
        s = f"t_{s}"
    return s


def _pg_type(series: pd.Series) -> str:
    """Pick a Postgres column type from a pandas dtype / content sniff."""
    dtype = series.dtype
    if pd.api.types.is_integer_dtype(dtype):
        return "BIGINT"
    if pd.api.types.is_float_dtype(dtype):
        return "DOUBLE PRECISION"
    if pd.api.types.is_bool_dtype(dtype):
        return "BOOLEAN"
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "TIMESTAMP"
    if dtype == object:
        sample = series.dropna().astype(str).head(50)
        if len(sample) > 0:
            try:
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    parsed = pd.to_datetime(sample, errors="raise")
                if (parsed.dt.time == pd.Timestamp("00:00:00").time()).all():
                    return "DATE"
                return "TIMESTAMP"
            except (ValueError, TypeError):
                pass
    return "TEXT"


def _read_csv(folder: Path, table_name: str) -> pd.DataFrame:
    """Load the CSV for one table. Tries exact name, then case-insensitive."""
    target = folder / f"{table_name}.csv"
    if target.exists():
        return pd.read_csv(target)
    for p in folder.iterdir():
        if p.is_file() and p.suffix.lower() == ".csv" and p.stem.lower() == table_name.lower():
            return pd.read_csv(p)
    raise FileNotFoundError(
        f"Manifest declares table {table_name!r} but no matching "
        f"{table_name}.csv found in {folder}."
    )


def _drop_tables_and_views(
    cur: psycopg.Cursor,
    schema: str,
    table_idents: list[str],
    view_names: list[str],
) -> None:
    """Drop only the specific views and tables we're about to recreate."""
    for v in view_names:
        cur.execute(sql.SQL("DROP VIEW IF EXISTS {}.{} CASCADE").format(
            sql.Identifier(schema), sql.Identifier(v)
        ))
    for t in table_idents:
        cur.execute(sql.SQL("DROP TABLE IF EXISTS {}.{} CASCADE").format(
            sql.Identifier(schema), sql.Identifier(t)
        ))


def _create_and_copy(
    con: psycopg.Connection,
    schema: str,
    table_ident: str,
    df: pd.DataFrame,
) -> None:
    """Create a table from the dataframe's shape and COPY rows into it."""
    col_defs = []
    for col in df.columns:
        col_ident = _ident(str(col))
        col_type = _pg_type(df[col])
        col_defs.append(sql.SQL("{} {}").format(
            sql.Identifier(col_ident),
            sql.SQL(col_type),
        ))
    con.execute(sql.SQL("CREATE TABLE {}.{} ({})").format(
        sql.Identifier(schema),
        sql.Identifier(table_ident),
        sql.SQL(", ").join(col_defs),
    ))

    renamed = df.rename(columns={c: _ident(str(c)) for c in df.columns})
    buf = io.StringIO()
    renamed.to_csv(buf, index=False, header=False, na_rep="\\N")
    buf.seek(0)

    copy_stmt = sql.SQL("COPY {}.{} FROM STDIN WITH (FORMAT csv, NULL '\\N')").format(
        sql.Identifier(schema),
        sql.Identifier(table_ident),
    )
    with con.cursor() as cur, cur.copy(copy_stmt) as copy:
        copy.write(buf.getvalue())


# ── Join graph & transitive walk ────────────────────────────────────


def _build_join_graph(
    manifest: dict,
    table_idents: dict[str, str],
) -> dict[str, list[dict]]:
    """Build an adjacency list: fromTable -> [{toTable, fromField, toField}].

    Keys and field names are already lowercased idents.
    """
    graph: dict[str, list[dict]] = defaultdict(list)
    for jp in manifest.get("joinPaths", []):
        from_t = jp["fromTable"]
        to_t = jp["toTable"]
        if from_t not in table_idents or to_t not in table_idents:
            continue
        graph[from_t].append({
            "from_table": from_t,
            "to_table": to_t,
            "from_field": _ident(jp["fromField"]),
            "to_field": _ident(jp["toField"]),
        })
    return graph


def _walk_from_fact(
    fact_name: str,
    join_graph: dict[str, list[dict]],
) -> list[dict]:
    """BFS from a fact table through all reachable joins (transitive).

    Returns a flat list of join edges in traversal order. Each edge
    carries `from_table`, `to_table`, `from_field`, `to_field`, and
    `parent` (the table we're joining FROM in the final SQL — which may
    differ from `from_table` when we're walking dim->dim edges).
    """
    result: list[dict] = []
    visited: set[str] = {fact_name}
    queue: list[str] = [fact_name]

    while queue:
        current = queue.pop(0)
        for edge in join_graph.get(current, []):
            to_t = edge["to_table"]
            if to_t in visited:
                continue
            visited.add(to_t)
            result.append({**edge, "parent": current})
            queue.append(to_t)

    return result


# ── View builder ────────────────────────────────────────────────────


def _build_fact_view(
    con: psycopg.Connection,
    schema: str,
    view_name: str,
    fact_name: str,
    fact_ident: str,
    join_edges: list[dict],
    table_idents: dict[str, str],
    table_columns: dict[str, list[str]],
) -> None:
    """Build one analytics view for a single fact table."""
    fact_cols = table_columns[fact_ident]

    select_parts: list[sql.Composable] = []
    for c in fact_cols:
        select_parts.append(sql.SQL("f.{}").format(sql.Identifier(c)))

    # Assign a unique alias per joined table.
    alias_map: dict[str, str] = {fact_name: "f"}
    alias_counter = 0
    join_clauses: list[sql.Composable] = []
    used_col_names: set[str] = set(fact_cols)

    for edge in join_edges:
        to_table = edge["to_table"]
        parent = edge["parent"]
        to_ident = table_idents[to_table]

        alias_counter += 1
        alias = f"d{alias_counter}"
        alias_map[to_table] = alias

        parent_alias = alias_map.get(parent, "f")

        join_clauses.append(sql.SQL(
            "LEFT JOIN {schema}.{tbl} {alias} ON {alias}.{to_fld} = {parent}.{from_fld}"
        ).format(
            schema=sql.Identifier(schema),
            tbl=sql.Identifier(to_ident),
            alias=sql.Identifier(alias),
            to_fld=sql.Identifier(edge["to_field"]),
            parent=sql.Identifier(parent_alias),
            from_fld=sql.Identifier(edge["from_field"]),
        ))

        dim_cols = table_columns[to_ident]
        for c in dim_cols:
            if c == edge["to_field"]:
                continue
            out_name = c if c not in used_col_names else f"{to_ident}_{c}"
            used_col_names.add(out_name)
            select_parts.append(sql.SQL("{}.{} AS {}").format(
                sql.Identifier(alias),
                sql.Identifier(c),
                sql.Identifier(out_name),
            ))

    view_sql = sql.SQL(
        "CREATE VIEW {schema}.{view} AS SELECT {cols} FROM {schema}.{fact} f {joins}"
    ).format(
        schema=sql.Identifier(schema),
        view=sql.Identifier(view_name),
        cols=sql.SQL(", ").join(select_parts),
        fact=sql.Identifier(fact_ident),
        joins=sql.SQL(" ").join(join_clauses) if join_clauses else sql.SQL(""),
    )
    con.execute(view_sql)


# ── Public entry point ──────────────────────────────────────────────


def load_manifest(folder: str | os.PathLike[str]) -> dict[str, Any]:
    """Load a manifest dataset into the demo schema.

    Drops only the tables/views being loaded (preserves unrelated tables).
    Builds one analytics view per fact table. Returns a summary dict.
    """
    folder_path = Path(folder).expanduser().resolve()
    if not folder_path.is_dir():
        raise FileNotFoundError(f"Not a directory: {folder_path}")
    manifest_path = folder_path / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"No manifest.json in {folder_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema = os.environ.get("PGSCHEMA", "demo")

    # Identify facts and build identifiers.
    tables_meta = manifest["tables"]
    fact_tables = [t for t in tables_meta if t.get("tableRole") == "fact"]
    if not fact_tables:
        raise ValueError("Manifest has no table with tableRole='fact'.")

    table_idents: dict[str, str] = {}
    for t in tables_meta:
        table_idents[t["tableName"]] = _ident(t["tableName"])

    # Preload all CSVs before touching the database.
    frames: dict[str, pd.DataFrame] = {}
    for t in tables_meta:
        name = t["tableName"]
        frames[name] = _read_csv(folder_path, name)

    # Determine view names.
    if len(fact_tables) == 1:
        view_names = {"analytics": fact_tables[0]["tableName"]}
    else:
        view_names = {}
        for ft in fact_tables:
            view_names[f"analytics_{table_idents[ft['tableName']]}"] = ft["tableName"]

    with psycopg.connect(**_conn_kwargs()) as con:
        con.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
            sql.Identifier(schema)
        ))

        with con.cursor() as cur:
            _drop_tables_and_views(
                cur, schema,
                list(table_idents.values()),
                list(view_names.keys()),
            )

        table_columns: dict[str, list[str]] = {}
        row_counts: dict[str, int] = {}
        for name, df in frames.items():
            ident = table_idents[name]
            _create_and_copy(con, schema, ident, df)
            table_columns[ident] = [_ident(str(c)) for c in df.columns]
            row_counts[ident] = len(df)

        # Build the join graph and create one view per fact.
        join_graph = _build_join_graph(manifest, table_idents)
        created_views: list[str] = []

        for view_name, fact_name in view_names.items():
            fact_ident = table_idents[fact_name]
            edges = _walk_from_fact(fact_name, join_graph)
            _build_fact_view(
                con, schema, view_name, fact_name, fact_ident,
                edges, table_idents, table_columns,
            )
            created_views.append(f"{schema}.{view_name}")

        con.commit()

    return {
        "dataset": manifest.get("datasetName", folder_path.name),
        "folder": str(folder_path),
        "tables": row_counts,
        "views": created_views,
    }
