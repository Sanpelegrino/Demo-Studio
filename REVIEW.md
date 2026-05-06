# Pre-Release Review: Demo Studio

**Date:** 2026-05-06  
**Reviewer:** Automated audit (Claude)  
**Branch:** master  
**Verdict:** SHIP — all critical issues resolved

---

## Summary

Demo Studio is ready for release. This review covered all production source files across five axes: correctness, readability, architecture, security, and performance. Two code fixes were applied (unused imports, path traversal guard). All working documents, test scaffolding, and development artifacts have been removed.

---

## Files Audited

### Python (8 files)
| File | Lines | Status |
|------|-------|--------|
| `app.py` | ~1400 | Clean — 4 prints converted to logging, path traversal fixed |
| `planner.py` | ~460 | Clean |
| `seed.py` | ~270 | Clean |
| `seed_superstore.py` | ~210 | Clean |
| `seed_manifest.py` | ~320 | Clean |
| `snapshots_store.py` | ~200 | Clean — unused `import os` removed |
| `manifest_builder.py` | ~240 | Clean — unused `field` import removed |
| `upload.py` | ~180 | Clean |

### JavaScript/HTML/CSS (8 files)
| File | Status |
|------|--------|
| `static/app.js` | Clean — no dead code, no console.log, all DOM refs guarded |
| `static/extension.js` | Clean |
| `static/history.js` | Clean |
| `static/index.html` | Clean |
| `static/embed.html` | Clean |
| `static/extension.html` | Clean |
| `static/history.html` | Clean |
| `static/styles.css` | Clean — no dead selectors |

### Documentation (4 files)
| File | Status |
|------|--------|
| `README.md` | Accurate |
| `docs/SETUP_GUIDE.md` | Accurate — all env vars documented |
| `docs/USER_GUIDE.md` | Updated — removed stale pitfalls panel reference |
| `.env.example` | Placeholder values only |

### Prompts (4 files)
| File | Status |
|------|--------|
| `prompts/pitfalls.md` | Curated guidance, ships with app |
| `prompts/pitfalls_raw.jsonl` | Cleared for release (runtime artifact) |
| `prompts/pitfalls_distill_prompt.md` | System prompt for auto-distillation |
| `prompts/pitfalls_rag_prompt.md` | System prompt for RAG builder |

---

## Issues Found and Fixed

### Critical
| Issue | File | Fix Applied |
|-------|------|-------------|
| Path traversal in `/api/load-manifest` — accepted arbitrary filesystem paths | `app.py:1022` | Added `is_relative_to(DATASETS_DIR.resolve())` check |

### Important
| Issue | File | Fix Applied |
|-------|------|-------------|
| Unused `import os` | `snapshots_store.py:12` | Removed |
| Unused `field` import | `manifest_builder.py:10` | Removed |
| 4x `print()` during startup instead of logging | `app.py:206,219,224,228` | Converted to `logging.info()` |
| Stale "Pitfalls panel" reference in User Guide | `docs/USER_GUIDE.md:66` | Rewritten |
| Raw error log contained 3 stale entries | `prompts/pitfalls_raw.jsonl` | Cleared |
| `.gitignore` missing `.pytest_cache/` | `.gitignore` | Added |

### Suggestions (not fixed — acceptable for release)
| Issue | File | Assessment |
|-------|------|------------|
| `print()` in `__main__` blocks of seed/upload scripts | `seed.py`, `upload.py` | Legitimate CLI output |
| `from typing import List, Optional` (could use builtins) | `snapshots_store.py`, `planner.py` | Style preference, not a bug |
| Inline `import json` inside method | `snapshots_store.py:115` | Works fine, low-frequency path |

---

## Security Assessment

| Category | Status |
|----------|--------|
| Hardcoded secrets in source | None — `.env` is gitignored |
| SQL injection | Low risk — `psycopg.sql` used for identifiers; f-string SQL uses env vars and `information_schema` values only |
| Path traversal | Fixed — all upload/load endpoints validate paths against `DATASETS_DIR` |
| XSS | Mitigated — `escapeHtml()` used for user content in innerHTML; non-user fields (language, timestamps) are server-controlled |
| Arbitrary code execution (`exec()`) | By design — core feature for SE demo tool, local-only |
| Authentication | None — intentional for local dev tool |
| CORS | Not configured — FastAPI default (same-origin) is appropriate |
| DB password in `/api/status` | Intentional — SEs need connection details for Tableau setup |

**Accepted risks (documented, not fixed):**
- `exec()` runs LLM-generated code unsandboxed — acceptable for a local SE tool where the user controls the LLM prompts
- No authentication — acceptable for localhost binding
- Database password visible via API — necessary for the Tableau connection workflow

---

## Architecture Assessment

| Aspect | Status |
|--------|--------|
| Module boundaries | Clean — `planner.py`, `snapshots_store.py`, `seed_*.py`, `manifest_builder.py` are self-contained |
| Dependency direction | Correct — `app.py` orchestrates; leaf modules have no app dependencies |
| State management | Global `_active_dataset`/`_active_view` with `_apply_lock` — appropriate for single-server tool |
| Error handling | Structured — `HTTPException` at API layer, typed exceptions in helpers |
| Event system | `EventBus` with SSE — clean pub/sub for Tableau extension updates |

---

## Performance Assessment

| Aspect | Status |
|--------|--------|
| Database queries | Bounded — all queries hit specific schemas, no full-table scans without filters |
| File uploads | Size-limited (`MAX_UPLOAD_SIZE` 500MB, `MAX_EXTRACT_SIZE` 2GB) |
| SSE connections | Non-blocking asyncio queue per client |
| LLM calls | Sequential with retry (max 3) — appropriate for single-user tool |
| Startup | Synchronous seed check — acceptable (runs once) |

---

## Files Removed

| File/Directory | Reason |
|----------------|--------|
| `SPEC-upload.md` | Completed feature spec |
| `tasks/plan.md` | Completed implementation plan |
| `tasks/todo.md` | Completed task tracker |
| `tasks/` | Empty directory |
| `tests/` | Development test scaffolding (untracked) |

---

## Release Checklist

- [x] All Python files parse without syntax errors
- [x] All JS files pass `node --check`
- [x] No unused imports
- [x] No debug print statements (logging used instead)
- [x] No TODO/FIXME/HACK comments
- [x] No hardcoded secrets in tracked files
- [x] `.gitignore` covers all generated artifacts
- [x] Documentation is accurate
- [x] Path traversal vulnerability fixed
- [x] Working documents removed
- [x] Raw error log cleared
- [x] All 16 production files audited

---

## Verdict

**SHIP.** The codebase is clean, secure for its intended use case (local SE demo tool), well-documented, and free of dead code or development artifacts.
