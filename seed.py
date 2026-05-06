"""Seed the demo_studio database with a curated Salesforce-style dataset.

Two tables shaped like what you'd find in an analytics datasource:

  demo.accounts       - customer accounts (industry, segment, region, owner...)
  demo.opportunities  - pipeline + closed deals linked to accounts

Idempotent: drops and recreates both tables each time it's called.
"""
from __future__ import annotations

import os
import random
from datetime import date, timedelta

import psycopg
from psycopg import sql


INDUSTRIES = [
    "Technology", "Financial Services", "Healthcare", "Manufacturing",
    "Retail", "Energy", "Media", "Telecommunications",
    "Public Sector", "Education",
]
SEGMENTS = ["Enterprise", "Commercial", "Mid-Market", "SMB"]
REGIONS = ["AMER", "EMEA", "APAC", "LATAM"]
COUNTRIES_BY_REGION = {
    "AMER": ["USA", "Canada", "Mexico"],
    "EMEA": ["UK", "Germany", "France", "Netherlands", "Spain"],
    "APAC": ["Japan", "Australia", "Singapore", "India"],
    "LATAM": ["Brazil", "Argentina", "Chile", "Colombia"],
}
ACCOUNT_TYPES = ["Customer", "Prospect", "Partner"]
OPP_STAGES = [
    ("Prospecting", 0.10),
    ("Qualification", 0.20),
    ("Needs Analysis", 0.35),
    ("Proposal", 0.55),
    ("Negotiation", 0.75),
    ("Closed Won", 1.00),
    ("Closed Lost", 0.00),
]
OPP_TYPES = ["New Business", "Existing Business", "Renewal", "Upsell"]
LEAD_SOURCES = [
    "Inbound", "Outbound", "Partner Referral", "Customer Referral",
    "Event", "Webinar", "Advertisement", "Website",
]
PRODUCTS = [
    "Platform Core", "Data Cloud", "Analytics Plus",
    "Service Pro", "Field Service", "Marketing Suite",
]
OWNERS = [f"user_{i:03d}@company.com" for i in range(1, 41)]


def _conn_kwargs() -> dict:
    return {
        "host": os.environ.get("PGHOST", "127.0.0.1"),
        "port": int(os.environ.get("PGPORT", "5432")),
        "user": os.environ.get("PGUSER", "demo_studio"),
        "password": os.environ.get("PGPASSWORD", "demo_local_dev"),
        "dbname": os.environ.get("PGDATABASE", "demo_studio"),
    }


def seed(account_count: int = 400, opps_per_account_avg: int = 5, seed_value: int = 11) -> tuple[int, int]:
    random.seed(seed_value)
    schema = os.environ.get("PGSCHEMA", "demo")

    # Build accounts
    accounts = []
    for i in range(1, account_count + 1):
        region = random.choice(REGIONS)
        country = random.choice(COUNTRIES_BY_REGION[region])
        industry = random.choice(INDUSTRIES)
        segment = random.choices(
            SEGMENTS, weights=[0.15, 0.25, 0.35, 0.25]
        )[0]
        employees = {
            "Enterprise": random.randint(5000, 250000),
            "Commercial": random.randint(1000, 5000),
            "Mid-Market": random.randint(200, 1000),
            "SMB": random.randint(10, 200),
        }[segment]
        annual_revenue = employees * random.uniform(80_000, 350_000)
        created = date(2019, 1, 1) + timedelta(days=random.randint(0, (date(2024, 12, 31) - date(2019, 1, 1)).days))
        accounts.append({
            "account_id": f"001{i:07d}",
            "account_name": f"{industry.split()[0]}Co {i}",
            "industry": industry,
            "segment": segment,
            "account_type": random.choices(ACCOUNT_TYPES, weights=[0.55, 0.35, 0.10])[0],
            "region": region,
            "country": country,
            "employees": employees,
            "annual_revenue": round(annual_revenue, 2),
            "owner": random.choice(OWNERS),
            "created_date": created,
            "is_active": random.random() > 0.05,
        })

    # Build opportunities
    today = date(2026, 5, 1)
    opportunities = []
    opp_seq = 1
    for acct in accounts:
        n_opps = max(1, int(random.gauss(opps_per_account_avg, 2)))
        for _ in range(n_opps):
            stage, default_prob = random.choice(OPP_STAGES)
            created = acct["created_date"] + timedelta(days=random.randint(30, 1800))
            if created > today:
                created = today - timedelta(days=random.randint(7, 200))
            # sales cycle 14-270 days
            close_offset = random.randint(14, 270)
            close_date = created + timedelta(days=close_offset)
            is_closed = stage.startswith("Closed") or close_date < today
            if is_closed and not stage.startswith("Closed"):
                stage = random.choices(["Closed Won", "Closed Lost"], weights=[0.6, 0.4])[0]
                default_prob = 1.0 if stage == "Closed Won" else 0.0
            is_won = stage == "Closed Won"
            # Amount scales with segment
            base_amount = {
                "Enterprise": random.uniform(80_000, 2_000_000),
                "Commercial": random.uniform(30_000, 500_000),
                "Mid-Market": random.uniform(10_000, 150_000),
                "SMB": random.uniform(2_000, 40_000),
            }[acct["segment"]]
            amount = round(base_amount, 2)
            # ACV = amount / term_years (assume 1–3 yr terms)
            term_years = random.choice([1, 1, 1, 2, 3])
            opportunities.append({
                "opportunity_id": f"006{opp_seq:07d}",
                "account_id": acct["account_id"],
                "opportunity_name": f"{acct['account_name']} - {random.choice(PRODUCTS)}",
                "stage_name": stage,
                "opportunity_type": random.choice(OPP_TYPES),
                "product": random.choice(PRODUCTS),
                "amount": amount,
                "probability": default_prob,
                "expected_revenue": round(amount * default_prob, 2),
                "term_years": term_years,
                "acv": round(amount / term_years, 2),
                "lead_source": random.choice(LEAD_SOURCES),
                "created_date": created,
                "close_date": close_date,
                "is_closed": is_closed,
                "is_won": is_won,
                "owner": acct["owner"] if random.random() > 0.2 else random.choice(OWNERS),
            })
            opp_seq += 1

    with psycopg.connect(**_conn_kwargs()) as con:
        con.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))
        # Tables are created fresh — caller is responsible for wiping schema first.
        con.execute(sql.SQL("DROP TABLE IF EXISTS {}.opportunities CASCADE").format(sql.Identifier(schema)))
        con.execute(sql.SQL("DROP TABLE IF EXISTS {}.accounts CASCADE").format(sql.Identifier(schema)))

        con.execute(sql.SQL("""
            CREATE TABLE {}.accounts (
                account_id      TEXT PRIMARY KEY,
                account_name    TEXT NOT NULL,
                industry        TEXT,
                segment         TEXT,
                account_type    TEXT,
                region          TEXT,
                country         TEXT,
                employees       INTEGER,
                annual_revenue  NUMERIC(18, 2),
                owner           TEXT,
                created_date    DATE,
                is_active       BOOLEAN
            )
        """).format(sql.Identifier(schema)))

        con.execute(sql.SQL("""
            CREATE TABLE {schema}.opportunities (
                opportunity_id    TEXT PRIMARY KEY,
                account_id        TEXT REFERENCES {schema}.accounts(account_id) ON DELETE CASCADE,
                opportunity_name  TEXT,
                stage_name        TEXT,
                opportunity_type  TEXT,
                product           TEXT,
                amount            NUMERIC(18, 2),
                probability       NUMERIC(5, 4),
                expected_revenue  NUMERIC(18, 2),
                term_years        INTEGER,
                acv               NUMERIC(18, 2),
                lead_source       TEXT,
                created_date      DATE,
                close_date        DATE,
                is_closed         BOOLEAN,
                is_won            BOOLEAN,
                owner             TEXT
            )
        """).format(schema=sql.Identifier(schema)))

        with con.cursor() as cur:
            cur.executemany(
                sql.SQL("""
                    INSERT INTO {}.accounts
                    (account_id, account_name, industry, segment, account_type, region, country,
                     employees, annual_revenue, owner, created_date, is_active)
                    VALUES (%(account_id)s, %(account_name)s, %(industry)s, %(segment)s, %(account_type)s,
                            %(region)s, %(country)s, %(employees)s, %(annual_revenue)s, %(owner)s,
                            %(created_date)s, %(is_active)s)
                """).format(sql.Identifier(schema)),
                accounts,
            )
            cur.executemany(
                sql.SQL("""
                    INSERT INTO {}.opportunities
                    (opportunity_id, account_id, opportunity_name, stage_name, opportunity_type, product,
                     amount, probability, expected_revenue, term_years, acv, lead_source,
                     created_date, close_date, is_closed, is_won, owner)
                    VALUES (%(opportunity_id)s, %(account_id)s, %(opportunity_name)s, %(stage_name)s,
                            %(opportunity_type)s, %(product)s, %(amount)s, %(probability)s,
                            %(expected_revenue)s, %(term_years)s, %(acv)s, %(lead_source)s,
                            %(created_date)s, %(close_date)s, %(is_closed)s, %(is_won)s, %(owner)s)
                """).format(sql.Identifier(schema)),
                opportunities,
            )

        con.execute(sql.SQL("""
            CREATE OR REPLACE VIEW {schema}._view_salesforce AS
            SELECT
                o.opportunity_id,
                o.opportunity_name,
                o.stage_name,
                o.opportunity_type,
                o.product,
                o.amount,
                o.probability,
                o.expected_revenue,
                o.term_years,
                o.acv,
                o.lead_source,
                o.created_date       AS opp_created_date,
                o.close_date,
                o.is_closed,
                o.is_won,
                o.owner              AS opp_owner,

                a.account_id,
                a.account_name,
                a.industry,
                a.segment,
                a.account_type,
                a.region,
                a.country,
                a.employees,
                a.annual_revenue,
                a.owner              AS account_owner,
                a.created_date       AS account_created_date,
                a.is_active
            FROM {schema}.opportunities o
            JOIN {schema}.accounts      a ON a.account_id = o.account_id
        """).format(schema=sql.Identifier(schema)))

    return len(accounts), len(opportunities)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    a, o = seed()
    print(f"Seeded {a} accounts and {o} opportunities")
