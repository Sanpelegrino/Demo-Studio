"""Demo Studio: FastAPI app for Postgres-backed synthetic data.

Tables live in the `demo` schema. Tableau connects via the native
PostgreSQL connector. The LLM is free to ALTER/DROP/CREATE anything in
that schema — snapshots in the `snapshots` schema back it up.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import threading
import time
import zipfile
from pathlib import Path
from typing import Literal

import pandas as pd
import polars as pl
import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from planner import PITFALLS_RAG_PATH, Plan, Planner, lookup_pitfalls_rag
from seed import seed as seed_workspace
from seed_manifest import load_manifest
from seed_superstore import seed_superstore
from snapshots_store import SnapshotStore


BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
DATASETS_DIR = BASE_DIR / "datasets"
PROMPTS_DIR = BASE_DIR / "prompts"
PITFALLS_PATH = PROMPTS_DIR / "pitfalls.md"
PITFALLS_RAW_PATH = PROMPTS_DIR / "pitfalls_raw.jsonl"
DATASETS_DIR.mkdir(exist_ok=True)
PROMPTS_DIR.mkdir(exist_ok=True)

load_dotenv(BASE_DIR / ".env")

LIVE_SCHEMA = os.environ.get("PGSCHEMA", "demo")

# Active dataset state — tracks which dataset/view the LLM should maintain.
_active_dataset: str = "salesforce"
_active_view: str = "salesforce"


def _conn_kwargs() -> dict:
    return {
        "host": os.environ.get("PGHOST", "127.0.0.1"),
        "port": int(os.environ.get("PGPORT", "5432")),
        "user": os.environ.get("PGUSER", "demo_studio"),
        "password": os.environ.get("PGPASSWORD", "demo_local_dev"),
        "dbname": os.environ.get("PGDATABASE", "demo_studio"),
    }


def connect() -> psycopg.Connection:
    return psycopg.connect(**_conn_kwargs())


def _nuke_schema() -> None:
    """Drop ALL views and tables in the live schema. Guaranteed clean slate."""
    with connect() as con, con.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.views "
            "WHERE table_schema = %s", (LIVE_SCHEMA,)
        )
        for (name,) in cur.fetchall():
            cur.execute(
                psycopg.sql.SQL("DROP VIEW IF EXISTS {}.{} CASCADE").format(
                    psycopg.sql.Identifier(LIVE_SCHEMA),
                    psycopg.sql.Identifier(name),
                )
            )
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = %s AND table_type = 'BASE TABLE'",
            (LIVE_SCHEMA,)
        )
        for (name,) in cur.fetchall():
            cur.execute(
                psycopg.sql.SQL("DROP TABLE IF EXISTS {}.{} CASCADE").format(
                    psycopg.sql.Identifier(LIVE_SCHEMA),
                    psycopg.sql.Identifier(name),
                )
            )
        con.commit()


_apply_lock = threading.Lock()
_pitfalls_lock = threading.Lock()

PITFALLS_DISTILL_THRESHOLD = 5
PITFALLS_MAX_LINES = 120
_distill_in_progress = threading.Event()


def _raw_pitfall_count() -> int:
    if not PITFALLS_RAW_PATH.exists():
        return 0
    with PITFALLS_RAW_PATH.open("r", encoding="utf-8") as f:
        return sum(1 for _ in f)


def _distill_pitfalls_background() -> None:
    """Run pitfalls distillation in a background thread."""
    if _distill_in_progress.is_set():
        return
    _distill_in_progress.set()
    try:
        log = logging.getLogger(__name__)
        log.info("Auto-distilling pitfalls (%d raw entries)…", _raw_pitfall_count())
        updated = planner.distill_pitfalls()
        if updated is None:
            return

        lines = updated.strip().splitlines()
        if len(lines) > PITFALLS_MAX_LINES:
            log.warning(
                "Distilled pitfalls (%d lines) exceeds cap (%d). "
                "Truncating to keep prompt size manageable.",
                len(lines), PITFALLS_MAX_LINES,
            )
            updated = "\n".join(lines[:PITFALLS_MAX_LINES]) + "\n"

        PITFALLS_PATH.write_text(updated, encoding="utf-8")

        log.info("Building pitfalls RAG store…")
        try:
            rag_entries = planner.build_pitfalls_rag()
            PITFALLS_RAG_PATH.write_text(
                json.dumps(rag_entries, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            log.info("Pitfalls RAG store updated (%d entries).", len(rag_entries))
        except Exception:
            import traceback
            log.error("RAG build failed (pitfalls.md was still updated):\n%s",
                      traceback.format_exc())

        if PITFALLS_RAW_PATH.exists():
            PITFALLS_RAW_PATH.unlink()
        log.info("Pitfalls distilled and raw log cleared.")
    except Exception:
        import traceback
        logging.getLogger(__name__).error(
            "Pitfalls distillation failed:\n%s", traceback.format_exc()
        )
    finally:
        _distill_in_progress.clear()


def _log_pitfall(entry: dict) -> None:
    """Append a failed-apply record to the raw pitfalls log (JSONL)."""
    entry["ts"] = time.time()
    line = json.dumps(entry, ensure_ascii=False)
    with _pitfalls_lock:
        with PITFALLS_RAW_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    if _raw_pitfall_count() >= PITFALLS_DISTILL_THRESHOLD:
        threading.Thread(
            target=_distill_pitfalls_background, daemon=True
        ).start()


def _detect_active_dataset() -> tuple[str, str]:
    """Detect active dataset from existing views in the schema."""
    with connect() as con, con.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.views "
            "WHERE table_schema = %s ORDER BY table_name",
            (LIVE_SCHEMA,),
        )
        views = [r[0] for r in cur.fetchall()]
    if "superstore" in views:
        return "superstore", "superstore"
    if "salesforce" in views:
        return "salesforce", "salesforce"
    # Manifest datasets use analytics or analytics_<name>
    for v in views:
        if v.startswith("analytics"):
            return "manifest", v
    return "salesforce", "salesforce"


def _ensure_seeded() -> None:
    global _active_dataset, _active_view
    with connect() as con, con.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = %s AND table_type = 'BASE TABLE' LIMIT 1",
            (LIVE_SCHEMA,),
        )
        if cur.fetchone() is None:
            print("Seeding initial Salesforce-style dataset…")
            _nuke_schema()
            a, o = seed_workspace()
            _active_dataset = "salesforce"
            _active_view = "salesforce"
            print(f"  {a} accounts, {o} opportunities")
        else:
            _active_dataset, _active_view = _detect_active_dataset()
            print(f"Detected active dataset: {_active_dataset} (view: {_active_view})")


_ensure_seeded()
snapshots = SnapshotStore(_conn_kwargs(), LIVE_SCHEMA)
planner = Planner()


class EventBus:
    """Tiny in-process pub/sub: SSE clients subscribe, handlers publish.

    Each subscriber gets its own asyncio.Queue. Publishers call
    `publish_sync` from threadpool endpoints; it walks the subscriber
    list under a lock and posts the payload to every queue. The SSE
    stream endpoint pulls from the queue and formats as text/event-stream.
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: list[asyncio.Queue] = []
        self._lock = threading.Lock()

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=64)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def publish_sync(self, event: str, data: dict) -> None:
        if self._loop is None:
            return
        payload = {"event": event, "data": data, "ts": time.time()}
        with self._lock:
            subs = list(self._subscribers)
        for q in subs:
            try:
                self._loop.call_soon_threadsafe(self._safe_put, q, payload)
            except RuntimeError:
                pass

    @staticmethod
    def _safe_put(q: asyncio.Queue, payload: dict) -> None:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            # Drop the oldest item, push the new one — we'd rather lose
            # a stale event than block mutations.
            try:
                q.get_nowait()
            except Exception:
                pass
            try:
                q.put_nowait(payload)
            except Exception:
                pass


events = EventBus()


app = FastAPI(title="Demo Studio")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.on_event("startup")
async def _bind_loop():
    events.bind_loop(asyncio.get_running_loop())


@app.get("/api/events")
async def sse_events(request: Request):
    """Server-Sent Events stream.

    Clients (the dashboard extension, optionally the main UI) subscribe
    here and receive events whenever the workspace changes. Payload:

        event: workspace_changed
        data:  {"kind": "apply"|"rollback"|"reseed", "summary": "..."}
    """
    queue = events.subscribe()

    async def gen():
        try:
            # Greet so the client knows the stream is live.
            yield "event: ready\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # Keep-alive comment — browsers close idle EventSource
                    # connections after ~30s otherwise.
                    yield ": keepalive\n\n"
                    continue
                line = (
                    f"event: {payload['event']}\n"
                    f"data: {json.dumps(payload['data'])}\n\n"
                )
                yield line
        finally:
            events.unsubscribe(queue)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )




def _list_tables(cur: psycopg.Cursor) -> list[str]:
    cur.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = %s AND table_type = 'BASE TABLE' "
        "ORDER BY table_name",
        (LIVE_SCHEMA,),
    )
    return [r[0] for r in cur.fetchall()]


def _list_views(cur: psycopg.Cursor) -> list[tuple[str, str]]:
    cur.execute(
        "SELECT table_name, view_definition FROM information_schema.views "
        "WHERE table_schema = %s ORDER BY table_name",
        (LIVE_SCHEMA,),
    )
    return [(r[0], r[1]) for r in cur.fetchall()]


def _columns(cur: psycopg.Cursor, name: str) -> list[tuple[str, str, str]]:
    cur.execute(
        "SELECT column_name, data_type, is_nullable "
        "FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s "
        "ORDER BY ordinal_position",
        (LIVE_SCHEMA, name),
    )
    return cur.fetchall()


def _schema_text(cur: psycopg.Cursor) -> str:
    tables = _list_tables(cur)
    views = _list_views(cur)
    if not tables and not views:
        return "(empty)"
    lines = []
    for t in tables:
        cur.execute(f'SELECT COUNT(*) FROM "{LIVE_SCHEMA}"."{t}"')
        count = cur.fetchone()[0]
        lines.append(f"TABLE {LIVE_SCHEMA}.{t}  ({count:,} rows)")
        for name, dtype, nullable in _columns(cur, t):
            null = "" if nullable == "YES" else "  NOT NULL"
            lines.append(f"  {name}  {dtype}{null}")
        lines.append("")
    for vname, vdef in views:
        lines.append(f"VIEW {LIVE_SCHEMA}.{vname}")
        for name, dtype, _ in _columns(cur, vname):
            lines.append(f"  {name}  {dtype}")
        lines.append("  -- definition:")
        for line in (vdef or "").strip().splitlines():
            lines.append(f"  {line}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _sample_rows_text(cur: psycopg.Cursor, n: int = 5) -> str:
    tables = _list_tables(cur)
    if not tables:
        return ""
    blocks = []
    for t in tables:
        cur.execute(f'SELECT * FROM "{LIVE_SCHEMA}"."{t}" LIMIT {n}')
        cols = [d.name for d in cur.description]
        rows = cur.fetchall()
        df = pd.DataFrame(rows, columns=cols)
        blocks.append(f"-- {LIVE_SCHEMA}.{t} (first {n} rows)\n{df.to_string(index=False)}")
    return "\n\n".join(blocks)


def _total_rows(cur: psycopg.Cursor) -> int:
    total = 0
    for t in _list_tables(cur):
        cur.execute(f'SELECT COUNT(*) FROM "{LIVE_SCHEMA}"."{t}"')
        total += cur.fetchone()[0]
    return total


class ChatRequest(BaseModel):
    message: str
    model: str | None = None


class ApplyRequest(BaseModel):
    language: Literal["sql", "python"]
    code: str
    summary: str
    original_message: str | None = None


class ChatResponse(BaseModel):
    summary: str
    language: str
    code: str
    notes: str


class ApplyAttempt(BaseModel):
    language: str
    summary: str
    code: str
    error: str


class ApplyResponse(BaseModel):
    ok: bool
    error: str | None = None
    row_count: int
    schema: str
    attempts: list[ApplyAttempt] = []
    final_language: str | None = None
    final_code: str | None = None
    final_summary: str | None = None


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/history")
def history_page():
    return FileResponse(STATIC_DIR / "history.html")


@app.get("/embed")
def chat_embed():
    return FileResponse(STATIC_DIR / "embed.html")


@app.get("/extension/manifest")
def extension_manifest():
    """The Live Refresh extension — subscribes to /api/events and refreshes
    the dashboard's data sources whenever the workspace changes."""
    return FileResponse(
        STATIC_DIR / "live-refresh.trex",
        media_type="application/xml",
        filename="live-refresh.trex",
    )


@app.get("/extension/chat")
def extension_chat_manifest():
    """The Live Chat extension — hosts the /embed chat UI inside a
    dashboard extension zone so analysts can reshape the data without
    leaving Tableau."""
    return FileResponse(
        STATIC_DIR / "live-chat.trex",
        media_type="application/xml",
        filename="live-chat.trex",
    )


@app.get("/api/pitfalls")
def get_pitfalls():
    """Return current pitfalls.md contents and raw-log stats."""
    curated = ""
    if PITFALLS_PATH.exists():
        curated = PITFALLS_PATH.read_text(encoding="utf-8")
    raw_count = 0
    if PITFALLS_RAW_PATH.exists():
        with PITFALLS_RAW_PATH.open("r", encoding="utf-8") as f:
            raw_count = sum(1 for _ in f)
    return {
        "curated": curated,
        "curated_path": str(PITFALLS_PATH.resolve()),
        "raw_count": raw_count,
        "raw_path": str(PITFALLS_RAW_PATH.resolve()) if PITFALLS_RAW_PATH.exists() else None,
    }


class PitfallsUpdate(BaseModel):
    curated: str


@app.put("/api/pitfalls")
def put_pitfalls(update: PitfallsUpdate):
    """Overwrite pitfalls.md with new curated content (e.g. after LLM cleanup)."""
    PITFALLS_PATH.write_text(update.curated, encoding="utf-8")
    return {"ok": True, "bytes": len(update.curated)}


@app.get("/api/pitfalls/raw")
def download_pitfalls_raw():
    """Download the raw JSONL failure log."""
    if not PITFALLS_RAW_PATH.exists():
        raise HTTPException(404, "No failures logged yet.")
    return FileResponse(
        PITFALLS_RAW_PATH,
        media_type="application/x-ndjson",
        filename="pitfalls_raw.jsonl",
    )


@app.delete("/api/pitfalls/raw")
def clear_pitfalls_raw():
    """Clear the raw log (e.g., after distilling it into curated guidance)."""
    if PITFALLS_RAW_PATH.exists():
        PITFALLS_RAW_PATH.unlink()
    return {"ok": True}


@app.post("/api/pitfalls/distill")
def distill_pitfalls_endpoint():
    """Manually trigger pitfalls distillation (merges raw log into curated)."""
    raw_count = _raw_pitfall_count()
    if raw_count == 0:
        return {"ok": True, "message": "No raw errors to distill.", "updated": False}
    try:
        updated = planner.distill_pitfalls()
    except Exception as e:
        raise HTTPException(500, f"Distillation failed: {e}")
    if updated is None:
        return {"ok": True, "message": "Nothing to distill.", "updated": False}

    lines = updated.strip().splitlines()
    if len(lines) > PITFALLS_MAX_LINES:
        updated = "\n".join(lines[:PITFALLS_MAX_LINES]) + "\n"

    PITFALLS_PATH.write_text(updated, encoding="utf-8")

    rag_count = 0
    try:
        rag_entries = planner.build_pitfalls_rag()
        PITFALLS_RAG_PATH.write_text(
            json.dumps(rag_entries, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        rag_count = len(rag_entries)
    except Exception:
        pass

    if PITFALLS_RAW_PATH.exists():
        PITFALLS_RAW_PATH.unlink()
    return {"ok": True, "updated": True, "raw_processed": raw_count, "rag_entries": rag_count}


@app.get("/api/status")
def status():
    with connect() as con, con.cursor() as cur:
        views = [v for v, _ in _list_views(cur)]
        tableau_view = _active_view if _active_view in views else (views[0] if views else None)
        tableau_view_cols = []
        tableau_view_rows = 0
        if tableau_view:
            tableau_view_cols = [c for c, _, _ in _columns(cur, tableau_view)]
            try:
                cur.execute(f'SELECT COUNT(*) FROM "{LIVE_SCHEMA}"."{tableau_view}"')
                tableau_view_rows = cur.fetchone()[0]
            except Exception:
                pass
        return {
            "connection": {
                "host": _conn_kwargs()["host"],
                "port": _conn_kwargs()["port"],
                "database": _conn_kwargs()["dbname"],
                "user": _conn_kwargs()["user"],
                "password": _conn_kwargs()["password"],
                "schema": LIVE_SCHEMA,
                "view": tableau_view,
            },
            "active_dataset": _active_dataset,
            "tables": _list_tables(cur),
            "views": views,
            "tableau_view_columns": tableau_view_cols,
            "tableau_view_row_count": tableau_view_rows,
            "row_count": _total_rows(cur),
            "schema": _schema_text(cur),
            "sample": _sample_rows_text(cur),
            "history": snapshots.list(),
        }


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    with connect() as con, con.cursor() as cur:
        schema = _schema_text(cur)
        sample = _sample_rows_text(cur)
    history = snapshots.list()
    try:
        plan: Plan = planner.plan(
            req.message, schema, sample, history,
            active_view=_active_view,
            active_dataset=_active_dataset,
            model=req.model,
        )
    except Exception as e:
        raise HTTPException(500, f"Planner failed: {e}")
    if plan.language not in ("sql", "python"):
        raise HTTPException(500, f"Planner returned invalid language: {plan.language!r}")
    if not plan.code:
        raise HTTPException(500, "Planner returned empty code")
    return ChatResponse(
        summary=plan.summary,
        language=plan.language,
        code=plan.code,
        notes=plan.notes,
    )


MAX_APPLY_ATTEMPTS = 3


def _execute_plan(language: str, code: str) -> None:
    """Run one plan inside a transaction. Commits on success, rolls back and
    re-raises on failure."""
    con = connect()
    try:
        con.autocommit = False
        with con.cursor() as cur:
            cur.execute(f'SET search_path TO "{LIVE_SCHEMA}", public')
            if language == "sql":
                cur.execute(code)
            else:
                exec_globals = {
                    "con": con,
                    "cur": cur,
                    "pd": pd,
                    "pl": pl,
                    "schema": LIVE_SCHEMA,
                }
                exec(compile(code, "<plan>", "exec"), exec_globals)
        con.commit()
    except Exception:
        try:
            con.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            con.close()
        except Exception:
            pass


@app.post("/api/apply", response_model=ApplyResponse)
def apply(req: ApplyRequest):
    with _apply_lock:
        attempts: list[ApplyAttempt] = []
        current_language = req.language
        current_code = req.code
        current_summary = req.summary

        for attempt_idx in range(MAX_APPLY_ATTEMPTS):
            snapshots.take(
                summary=current_summary,
                language=current_language,
                code=current_code,
            )
            try:
                _execute_plan(current_language, current_code)
            except Exception as e:
                err_str = f"{type(e).__name__}: {e}"
                snapshots.rollback_last(discard=True)
                _log_pitfall({
                    "summary": current_summary,
                    "language": current_language,
                    "code": current_code,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                })
                attempts.append(ApplyAttempt(
                    language=current_language,
                    summary=current_summary,
                    code=current_code,
                    error=err_str,
                ))

                remaining = MAX_APPLY_ATTEMPTS - (attempt_idx + 1)
                can_retry = remaining > 0 and bool(req.original_message)
                if not can_retry:
                    return ApplyResponse(
                        ok=False,
                        error=err_str,
                        row_count=0,
                        schema="",
                        attempts=attempts,
                    )

                # Ask planner for a corrected plan using all prior attempts.
                try:
                    with connect() as con, con.cursor() as cur:
                        schema_text = _schema_text(cur)
                        sample = _sample_rows_text(cur)
                    history = snapshots.list()
                    previous = [
                        {"language": a.language, "code": a.code, "error": a.error}
                        for a in attempts
                    ]
                    rag_context = lookup_pitfalls_rag(
                        type(e).__name__, str(e)
                    )
                    retry_message = req.original_message
                    if rag_context:
                        retry_message += "\n" + rag_context
                    new_plan = planner.plan(
                        retry_message,
                        schema_text,
                        sample,
                        history,
                        previous_attempts=previous,
                        active_view=_active_view,
                        active_dataset=_active_dataset,
                    )
                except Exception as planner_err:
                    return ApplyResponse(
                        ok=False,
                        error=f"Retry planner failed: {planner_err}",
                        row_count=0,
                        schema="",
                        attempts=attempts,
                    )

                current_language = new_plan.language
                current_code = new_plan.code
                current_summary = new_plan.summary
                continue

            # Success.
            with connect() as con, con.cursor() as cur:
                row_count = _total_rows(cur)
                schema_text = _schema_text(cur)
            events.publish_sync("workspace_changed", {
                "kind": "apply",
                "summary": current_summary,
                "language": current_language,
            })
            return ApplyResponse(
                ok=True,
                row_count=row_count,
                schema=schema_text,
                attempts=attempts,
                final_language=current_language,
                final_code=current_code,
                final_summary=current_summary,
            )

        # Exhausted retries without success — shouldn't reach here because
        # the failure branch returns, but keep a safety net.
        return ApplyResponse(
            ok=False,
            error="Exceeded retry limit.",
            row_count=0,
            schema="",
            attempts=attempts,
        )


@app.post("/api/rollback")
def rollback():
    with _apply_lock:
        snap = snapshots.rollback_last()
        if snap is None:
            raise HTTPException(400, "No snapshots to roll back to.")
        with connect() as con, con.cursor() as cur:
            result = {
                "rolled_back_to": snap.id,
                "summary": snap.summary,
                "row_count": _total_rows(cur),
                "schema": _schema_text(cur),
            }
        events.publish_sync("workspace_changed", {
            "kind": "rollback",
            "summary": snap.summary,
        })
        return result


@app.post("/api/reseed")
def reseed(dataset: str = "salesforce"):
    global _active_dataset, _active_view
    dataset = (dataset or "salesforce").lower()
    if dataset not in ("salesforce", "superstore"):
        raise HTTPException(400, f"Unknown dataset: {dataset!r}")
    with _apply_lock:
        _nuke_schema()
        if dataset == "superstore":
            o, r, p = seed_superstore()
            summary = f"Reseeded Superstore ({o} orders, {r} returns, {p} people)"
            counts = {"orders": o, "returns": r, "people": p}
            _active_dataset = "superstore"
            _active_view = "superstore"
        else:
            a, o = seed_workspace()
            summary = f"Reseeded Salesforce ({a} accounts, {o} opportunities)"
            counts = {"accounts": a, "opportunities": o}
            _active_dataset = "salesforce"
            _active_view = "salesforce"
        snapshots.clear()
        with connect() as con, con.cursor() as cur:
            result = {
                "ok": True,
                "dataset": dataset,
                "active_view": _active_view,
                **counts,
                "row_count": _total_rows(cur),
                "schema": _schema_text(cur),
            }
        events.publish_sync("workspace_changed", {
            "kind": "reseed",
            "summary": summary,
        })
        return result


class ManifestLoadRequest(BaseModel):
    folder: str


@app.post("/api/load-manifest")
def load_manifest_endpoint(req: ManifestLoadRequest):
    global _active_dataset, _active_view
    with _apply_lock:
        _nuke_schema()
        try:
            info = load_manifest(req.folder)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))
        except Exception as e:
            raise HTTPException(500, f"{type(e).__name__}: {e}")
        # Track the first view created by the manifest.
        created_views = info.get("views", [])
        if created_views:
            # Views are stored as "schema.name" — extract just the name.
            _active_view = created_views[0].split(".")[-1]
        else:
            _active_view = "analytics"
        _active_dataset = info.get("dataset", "manifest")
        snapshots.clear()
        with connect() as con, con.cursor() as cur:
            result = {
                "ok": True,
                **info,
                "active_view": _active_view,
                "row_count": _total_rows(cur),
                "schema": _schema_text(cur),
            }
        total_rows = sum(info["tables"].values())
        view_count = len(created_views)
        summary = (
            f"Loaded manifest '{info['dataset']}' "
            f"({len(info['tables'])} tables, {view_count} view{'s' if view_count != 1 else ''}, "
            f"{total_rows:,} rows)"
        )
        events.publish_sync("workspace_changed", {
            "kind": "load_manifest",
            "summary": summary,
        })
        return result


@app.get("/api/datasets")
def list_datasets():
    """List subfolders of datasets/ that contain a manifest.json."""
    results = []
    if DATASETS_DIR.is_dir():
        for p in sorted(DATASETS_DIR.iterdir()):
            if p.is_dir() and (p / "manifest.json").exists():
                results.append({"name": p.name, "folder": str(p.resolve())})
    return {"datasets": results}


@app.post("/api/datasets/upload")
async def upload_dataset(file: UploadFile = File(...)):
    """Accept a .zip, extract into datasets/<stem>/, return the folder path."""
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(400, "Upload must be a .zip file.")
    stem = Path(file.filename).stem
    dest = DATASETS_DIR / stem
    # If already exists, remove so we get a clean replacement.
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    # Write the zip to a temp path then extract.
    tmp_zip = DATASETS_DIR / f"_upload_{stem}.zip"
    try:
        contents = await file.read()
        tmp_zip.write_bytes(contents)
        with zipfile.ZipFile(tmp_zip, "r") as zf:
            zf.extractall(dest)
        # Some zips nest everything inside a single root folder.
        # If dest contains exactly one subfolder and no manifest.json
        # at the top level, pull the subfolder contents up.
        children = list(dest.iterdir())
        if (
            len(children) == 1
            and children[0].is_dir()
            and not (dest / "manifest.json").exists()
        ):
            nested = children[0]
            for item in nested.iterdir():
                item.rename(dest / item.name)
            nested.rmdir()
    finally:
        if tmp_zip.exists():
            tmp_zip.unlink()

    if not (dest / "manifest.json").exists():
        shutil.rmtree(dest)
        raise HTTPException(400, "Zip does not contain a manifest.json.")

    return {"ok": True, "name": stem, "folder": str(dest.resolve())}
