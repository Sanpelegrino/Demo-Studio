"""One-shot loader: Sample - Superstore.xls -> demo.orders / returns / people.

Run once to replace whatever is currently in the `demo` schema with the
Superstore dataset. After this runs, Tableau keeps pointing at the same
`demo.analytics` view and sees Superstore columns instead.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import psycopg
from dotenv import load_dotenv
from psycopg import sql


XLS_PATH = Path(
    r"C:\Users\andrew.hill\Documents\My Tableau Repository"
    r"\Datasources\2026.1\en_US-US\Sample - Superstore.xls"
)


def _conn_kwargs() -> dict:
    return {
        "host": os.environ.get("PGHOST", "127.0.0.1"),
        "port": int(os.environ.get("PGPORT", "5432")),
        "user": os.environ.get("PGUSER", "pulse_app"),
        "password": os.environ.get("PGPASSWORD", "pulse_local_dev"),
        "dbname": os.environ.get("PGDATABASE", "demo_studio"),
    }


COLUMN_RENAMES = {
    "Row ID": "row_id",
    "Order ID": "order_id",
    "Order Date": "order_date",
    "Ship Date": "ship_date",
    "Ship Mode": "ship_mode",
    "Customer ID": "customer_id",
    "Customer Name": "customer_name",
    "Segment": "segment",
    "Country/Region": "country_region",
    "City": "city",
    "State/Province": "state_province",
    "Postal Code": "postal_code",
    "Region": "region",
    "Product ID": "product_id",
    "Category": "category",
    "Sub-Category": "sub_category",
    "Product Name": "product_name",
    "Sales": "sales",
    "Quantity": "quantity",
    "Discount": "discount",
    "Profit": "profit",
    "Returned": "returned",
    "Regional Manager": "regional_manager",
}


def _snake(df: pd.DataFrame) -> pd.DataFrame:
    return df.rename(columns={c: COLUMN_RENAMES.get(c, c.lower().replace(" ", "_")) for c in df.columns})


def seed_superstore() -> tuple[int, int, int]:
    schema = os.environ.get("PGSCHEMA", "demo")

    xls = pd.ExcelFile(XLS_PATH)
    orders = _snake(pd.read_excel(xls, sheet_name="Orders"))
    returns = _snake(pd.read_excel(xls, sheet_name="Returns"))
    people = _snake(pd.read_excel(xls, sheet_name="People"))

    # Normalize: Returned should be boolean
    returns["returned"] = returns["returned"].astype(str).str.strip().str.lower().eq("yes")

    with psycopg.connect(**_conn_kwargs()) as con:
        con.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))
        # Drop existing demo objects so Tableau lands on the Superstore shape.
        con.execute(sql.SQL("DROP VIEW IF EXISTS {}.analytics CASCADE").format(sql.Identifier(schema)))
        for t in ("opportunities", "accounts", "orders", "returns", "people"):
            con.execute(sql.SQL("DROP TABLE IF EXISTS {}.{} CASCADE").format(
                sql.Identifier(schema), sql.Identifier(t)
            ))

        con.execute(sql.SQL("""
            CREATE TABLE {}.orders (
                row_id          INTEGER PRIMARY KEY,
                order_id        TEXT NOT NULL,
                order_date      DATE,
                ship_date       DATE,
                ship_mode       TEXT,
                customer_id     TEXT,
                customer_name   TEXT,
                segment         TEXT,
                country_region  TEXT,
                city            TEXT,
                state_province  TEXT,
                postal_code     TEXT,
                region          TEXT,
                product_id      TEXT,
                category        TEXT,
                sub_category    TEXT,
                product_name    TEXT,
                sales           NUMERIC(18, 4),
                quantity        INTEGER,
                discount        NUMERIC(6, 4),
                profit          NUMERIC(18, 4)
            )
        """).format(sql.Identifier(schema)))

        con.execute(sql.SQL("""
            CREATE TABLE {}.returns (
                order_id  TEXT PRIMARY KEY,
                returned  BOOLEAN
            )
        """).format(sql.Identifier(schema)))

        con.execute(sql.SQL("""
            CREATE TABLE {}.people (
                region            TEXT PRIMARY KEY,
                regional_manager  TEXT
            )
        """).format(sql.Identifier(schema)))

        # Deduplicate returns by order_id (source has a couple dupes in some copies).
        returns = returns.drop_duplicates(subset=["order_id"], keep="first")

        with con.cursor() as cur:
            orders["postal_code"] = orders["postal_code"].astype(str).str.replace(r"\.0$", "", regex=True)
            orders_rows = [tuple(r) for r in orders[[
                "row_id", "order_id", "order_date", "ship_date", "ship_mode",
                "customer_id", "customer_name", "segment", "country_region",
                "city", "state_province", "postal_code", "region",
                "product_id", "category", "sub_category", "product_name",
                "sales", "quantity", "discount", "profit",
            ]].itertuples(index=False, name=None)]
            cur.executemany(
                sql.SQL("""
                    INSERT INTO {}.orders VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                """).format(sql.Identifier(schema)),
                orders_rows,
            )

            returns_rows = [tuple(r) for r in returns[["order_id", "returned"]].itertuples(index=False, name=None)]
            cur.executemany(
                sql.SQL("INSERT INTO {}.returns VALUES (%s, %s)").format(sql.Identifier(schema)),
                returns_rows,
            )

            people_rows = [tuple(r) for r in people[["region", "regional_manager"]].itertuples(index=False, name=None)]
            cur.executemany(
                sql.SQL("INSERT INTO {}.people VALUES (%s, %s)").format(sql.Identifier(schema)),
                people_rows,
            )

        con.execute(sql.SQL("""
            CREATE OR REPLACE VIEW {schema}.analytics AS
            SELECT
                o.row_id,
                o.order_id,
                o.order_date,
                o.ship_date,
                o.ship_mode,
                o.customer_id,
                o.customer_name,
                o.segment,
                o.country_region,
                o.city,
                o.state_province,
                o.postal_code,
                o.region,
                o.product_id,
                o.category,
                o.sub_category,
                o.product_name,
                o.sales,
                o.quantity,
                o.discount,
                o.profit,
                COALESCE(r.returned, FALSE) AS returned,
                p.regional_manager
            FROM {schema}.orders o
            LEFT JOIN {schema}.returns r ON r.order_id = o.order_id
            LEFT JOIN {schema}.people  p ON p.region   = o.region
        """).format(schema=sql.Identifier(schema)))

    return len(orders), len(returns), len(people)


if __name__ == "__main__":
    load_dotenv(Path(__file__).parent / ".env")
    o, r, p = seed_superstore()
    print(f"Seeded Superstore: {o} orders, {r} returns, {p} people")
