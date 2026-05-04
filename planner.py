"""Ask Claude (via the Salesforce Bedrock gateway) for a mutation plan.

The model returns a small metadata header (language, summary, notes)
followed by a fenced code block. We parse those two pieces separately
so long SQL/Python blocks can't break our JSON escaping.

A pitfalls file (`prompts/pitfalls.md`) is appended to the system
prompt on every call. It's read fresh each time so you can edit it
without restarting the server.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List

import httpx


PITFALLS_PATH = Path(__file__).parent / "prompts" / "pitfalls.md"


SYSTEM_PROMPT = """You are the data mutation engine for a synthetic Salesforce-style
analytics workspace running on PostgreSQL. Your work directly shapes
what the user sees in their Tableau dashboard, so treat every request
as a chance to deliver a thorough, realistic, production-quality
result — interpret requests generously, think through second-order
effects on the view and related tables, and don't stop at the bare
minimum that technically satisfies the ask.

The user is building a Tableau dashboard. Tableau connects to a single
view — `demo.analytics` — NOT the underlying tables. You may freely
reshape the tables beneath, but you MUST keep the view in sync so the
dashboard stays useful.

The `demo` schema currently holds tables like `demo.accounts` and
`demo.opportunities`, plus the view `demo.analytics`. You'll see the
exact current schema (including the view definition) in every request.

RESPONSE FORMAT (strict):
Return exactly these four blocks, in this order, and nothing else:

LANGUAGE: sql
SUMMARY: <one sentence describing what the code does>
NOTES: <optional caveats; write NONE if no notes>
CODE:
```
<your SQL or Python here>
```

- The first line must be `LANGUAGE: sql` or `LANGUAGE: python`.
- SUMMARY and NOTES must each be a single line.
- The CODE block must be fenced with three backticks on their own lines.
- Do not add prose before LANGUAGE or after the closing ``` fence.

Rules for the code:

VIEW CONTRACT (critical):
- Tableau reads from `demo.analytics`. After any DDL that affects a
  column the view references, you MUST redefine the view so it still
  compiles and reflects the change the user asked for.
- ALWAYS use this pattern to rebuild the view — never use
  `CREATE OR REPLACE VIEW`:

      DROP VIEW IF EXISTS demo.analytics CASCADE;
      CREATE VIEW demo.analytics AS
      SELECT ... FROM demo.opportunities o JOIN demo.accounts a ...;

  Reason: `CREATE OR REPLACE VIEW` in Postgres only allows appending
  new columns at the end; inserting a column in the middle or changing
  the column order makes Postgres think you're renaming existing
  columns and it errors out. DROP + CREATE sidesteps that entirely.
- When the user's request implies new fields they want to see in
  Tableau (e.g., "add a churn_risk column"), add the column to the
  appropriate base table AND expose it in the view. You can place the
  new column anywhere in the SELECT list — group it logically with
  related columns.
- When the user asks to hide/remove a field from Tableau, it's usually
  enough to remove it from the view's SELECT list — you don't have to
  drop the underlying column unless asked.
- Never drop `demo.analytics` without recreating it in the same script.

DATA / SCHEMA FREEDOM:
- The user wants freedom to ADD, DROP, and RENAME columns and tables.
  Use ALTER TABLE / DROP TABLE / CREATE TABLE / TRUNCATE / UPDATE /
  INSERT / DELETE freely. Do not refuse reasonable requests.
- Match the scale of existing data: when asked to add records for a
  new slice (country, region, product line, etc.), generate a volume
  comparable to similar existing slices — not a token handful.
- Populate the full row, not just the requested field. When inserting
  new records, fill every column with realistic values consistent with
  the rest of the dataset — correct data types, plausible ranges,
  sensible defaults, matching referential keys — so the new rows are
  indistinguishable from existing ones in Tableau. Don't leave
  unrelated columns NULL or at trivial defaults just because the user
  only mentioned one field.
- `search_path` is set to `demo, public`, so unqualified names resolve
  to `demo` — but prefer fully-qualified `demo.table_name` for clarity.

SQL:
- Multiple statements separated by `;` are fine. The whole script runs
  in one transaction; any error rolls back everything.
- Do NOT use SQL to synthesize new rows. Generating realistic records
  in pure SQL (with `generate_series`, nested `CASE`, `random()`,
  `ROW_NUMBER()` tricks, or string-concatenated IDs) is brittle,
  produces unrealistic uniform data, and is the single biggest source
  of failures on this workspace. Use Python instead — see below.

PYTHON:
- You get:
    `con`     : psycopg3 Connection (open transaction)
    `cur`     : psycopg3 Cursor on `con`
    `pd`      : pandas
    `pl`      : polars
    `schema`  : the live schema name (usually "demo")
  You also get the standard library: `random`, `datetime`, `math`, etc.
- Read with `pd.read_sql('SELECT ... FROM demo.accounts', con)` or
  `cur.execute(...)`. Write with `cur.execute` / `cur.executemany` /
  psycopg's `copy` API.
- Do NOT call `con.commit()` or `con.rollback()` — the harness handles
  transaction boundaries.
- If your Python changes table schemas, you still must rebuild
  `demo.analytics` at the end.

CHOOSING:
- Use Python by default whenever the task generates new rows,
  synthesizes data, or derives per-row values from random/statistical
  logic. Loop in Python, build tuples, and insert with
  `cur.executemany` — this is vastly more reliable than SQL row
  generation and produces more realistic variation.
- Use SQL only for: bulk filters/updates over existing rows, DDL
  (ALTER/CREATE/DROP), and view maintenance.
- When in doubt — especially if the script is reaching for
  `generate_series`, nested `CASE` expressions, or `random()` to
  build row content — switch to Python.

SAFETY:
- Only touch the `demo` and `public` schemas. Never read from the
  filesystem. Never call external network APIs."""


def _load_pitfalls() -> str:
    """Read the curated pitfalls file. Return empty string if missing."""
    try:
        text = PITFALLS_PATH.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""
    # Strip the HTML comment block if it's still the template.
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL).strip()
    return text


@dataclass
class Plan:
    summary: str
    language: str
    code: str
    notes: str


class Planner:
    """Calls the Salesforce Bedrock gateway using the Anthropic-on-Bedrock payload."""

    def __init__(self, model: str | None = None):
        self.base_url = os.environ["ANTHROPIC_BEDROCK_BASE_URL"].rstrip("/")
        self.token = os.environ["ANTHROPIC_AUTH_TOKEN"]
        self.model = model or os.environ.get(
            "ANTHROPIC_MODEL", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
        )
        ca_bundle = os.environ.get("NODE_EXTRA_CA_CERTS")
        self.verify = ca_bundle if ca_bundle and os.path.exists(ca_bundle) else True
        self.client = httpx.Client(timeout=180.0, verify=self.verify)

    def plan(
        self,
        user_message: str,
        schema: str,
        sample_rows: str,
        history: List[dict],
        previous_attempts: List[dict] | None = None,
    ) -> Plan:
        history_text = "\n".join(
            f"- ({h['language']}) {h['summary']}" for h in history[-10:]
        ) or "(none yet)"

        user_content = f"""Current schema:
{schema}

Sample rows:
{sample_rows}

Recent changes applied to this workspace:
{history_text}

User request:
{user_message}
"""

        if previous_attempts:
            attempt_blocks = []
            for i, a in enumerate(previous_attempts, 1):
                attempt_blocks.append(
                    f"--- Attempt {i} ({a.get('language', '?')}) ---\n"
                    f"{a.get('code', '')}\n"
                    f"--- Error ---\n"
                    f"{a.get('error', '')}"
                )
            user_content += (
                "\nPREVIOUS ATTEMPTS FAILED — the scripts below were tried for "
                "this same request and each rolled back with the error shown. "
                "Diagnose the failure, fix the root cause, and produce a "
                "corrected script. Do not repeat the same mistake.\n\n"
                + "\n\n".join(attempt_blocks)
                + "\n"
            )

        system_prompt = SYSTEM_PROMPT
        pitfalls = _load_pitfalls()
        if pitfalls:
            system_prompt += (
                "\n\nPITFALLS (mistakes previously made on this workspace — "
                "read carefully and avoid):\n" + pitfalls
            )

        url = f"{self.base_url}/model/{self.model}/invoke"
        payload = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 8192,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_content}],
        }
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        resp = self.client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(f"Gateway {resp.status_code}: {resp.text[:500]}")
        body = resp.json()
        content = body.get("content", [])
        raw = "".join(b.get("text", "") for b in content if b.get("type") == "text")
        if not raw:
            raise RuntimeError(f"Empty response from gateway: {body}")

        stop_reason = body.get("stop_reason")
        if stop_reason == "max_tokens":
            # Output was cut off. Surface a clearer error than a parse failure.
            raise RuntimeError(
                "Model response was truncated by max_tokens — the requested "
                "change generates more code than fits in one turn. Try asking "
                "for a smaller batch, or have the model use Python with a "
                "programmatic loop instead of embedding all rows in SQL."
            )

        return _parse_plan(raw)


def _parse_plan(text: str) -> Plan:
    text = text.strip()

    def field(name: str) -> str:
        m = re.search(rf"^{name}:\s*(.+?)\s*$", text, flags=re.MULTILINE | re.IGNORECASE)
        return m.group(1).strip() if m else ""

    language = field("LANGUAGE").lower()
    summary = field("SUMMARY")
    notes = field("NOTES")
    if notes.upper() == "NONE":
        notes = ""

    # Grab the first fenced block after the CODE: marker. Accept ```sql,
    # ```python, or an unlabelled ```.
    code = ""
    code_match = re.search(
        r"CODE:\s*```(?:sql|python|postgres|postgresql)?\s*\n(.*?)\n```",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if code_match:
        code = code_match.group(1).strip()
    else:
        # Fall back to any fenced block anywhere in the response.
        fallback = re.search(r"```(?:sql|python|postgres|postgresql)?\s*\n(.*?)\n```", text, flags=re.DOTALL)
        if fallback:
            code = fallback.group(1).strip()

    if language not in ("sql", "python"):
        raise ValueError(
            f"Could not parse LANGUAGE from model response. Got: {language!r}\n\n"
            f"First 400 chars of response:\n{text[:400]}"
        )
    if not code:
        raise ValueError(
            "Could not find a ```code``` block in model response.\n\n"
            f"First 600 chars:\n{text[:600]}"
        )

    return Plan(summary=summary, language=language, code=code, notes=notes)
