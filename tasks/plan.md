# Implementation Plan: Demo Studio Public Release Audit

## Overview

Clean Demo Studio for public release by removing dead code, fixing error-path bugs, applying consistent design polish, and adding a model selector feature. The app is a single-page FastAPI tool used by Salesforce SEs to reshape Tableau datasets via AI chat. Work is organized so each task delivers a verifiable, independently testable change.

## Architecture Decisions

- **No new dependencies.** All changes use existing stack (vanilla JS, CSS custom properties, FastAPI, psycopg3).
- **No build step.** CSS and JS are authored directly and served from `/static`.
- **app.js remains a single file** shared by index.html and embed.html. All DOM access is guarded.
- **Backend pitfalls endpoints stay intact.** Only the Pitfalls UI card is removed from index.html.
- **Model selector is per-request.** The planner already supports model override; we add a frontend dropdown + request field.

## Dependency Graph

```
seed.py / seed_superstore.py / snapshots_store.py (standalone, no upstream deps)
    │
app.py (depends on planner, seeds, snapshots_store)
    │
    ├── planner.py (model, prompt, parsing)
    │       │
    │       └── ChatRequest model ← needs `model` field for Phase C
    │
    └── static/
            ├── styles.css (design tokens, all selectors)
            ├── app.js (DOM logic, api() helper, event binding)
            ├── index.html (main page structure)
            └── embed.html (chat-only embed)
```

Key dependency: Phase C (model selector) requires both a backend schema change (ChatRequest + planner.plan signature) AND a frontend dropdown. Phase B (design) is purely CSS/HTML. Phase A (cleanup) touches both backend and frontend but each task is independent.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Removing Pitfalls card breaks app.js logic elsewhere | Medium | loadPitfalls() already null-guards its DOM elements; removal just means those guards return early. Verify no console errors. |
| api() Content-Type change breaks POST requests | Medium | Only skip the header when `opts.body` is absent; POSTs always pass a body. |
| Model selector localStorage conflicts across sessions | Low | Use a namespaced key (`demo-studio.model`). |
| embed.html regression from app.js changes | Medium | Every app.js change is verified on both pages. |

## Open Questions

None — spec decisions are resolved. Proceeding with implementation plan.

---

## Phase 1: Backend Cleanup (low risk, foundational)

### Task 1: Remove unused imports + fix module-level logging

**Description:** Remove `from typing import Iterable` in seed.py and snapshots_store.py. Add `import logging` to app.py module-level imports and remove the in-function `import logging` in `_distill_pitfalls_background`.

**Acceptance criteria:**
- [ ] `seed.py` has no `Iterable` import
- [ ] `snapshots_store.py` has no `Iterable` import  
- [ ] `app.py` has `import logging` at the top and no `import logging` inside `_distill_pitfalls_background`
- [ ] `python -c "import app; import seed; import snapshots_store"` succeeds with no errors

**Verification:**
- [ ] Run: `python -c "import app; import seed; import snapshots_store"` (no ImportError or SyntaxError)

**Dependencies:** None

**Files touched:** `seed.py`, `snapshots_store.py`, `app.py`

**Estimated scope:** XS (3 files, 1-line changes each)

---

### Task 2: Guard EventBus against closed event loop

**Description:** Wrap `call_soon_threadsafe` in `EventBus.publish_sync` with try/except RuntimeError so shutdown doesn't produce tracebacks.

**Acceptance criteria:**
- [ ] `publish_sync` catches `RuntimeError` on `call_soon_threadsafe` and silently passes
- [ ] No behavior change during normal operation

**Verification:**
- [ ] `python -c "import app"` still works
- [ ] Server starts and `/api/status` responds

**Dependencies:** None

**Files touched:** `app.py`

**Estimated scope:** XS (1 file, 3-line change)

---

### Task 3: Make XLS_PATH configurable in seed_superstore.py

**Description:** Check `os.environ.get("SUPERSTORE_XLS_PATH")` first, fall back to the current hardcoded path. If neither file exists at call time, raise a clear `FileNotFoundError`.

**Acceptance criteria:**
- [ ] `SUPERSTORE_XLS_PATH` env var is checked first
- [ ] Falls back to existing hardcoded path
- [ ] `FileNotFoundError` with descriptive message when file is missing
- [ ] Works normally when file exists at default path

**Verification:**
- [ ] `python -c "from seed_superstore import XLS_PATH; print(XLS_PATH)"` shows the path
- [ ] With `SUPERSTORE_XLS_PATH` unset and file missing: calling `seed_superstore()` raises a clear error

**Dependencies:** None

**Files touched:** `seed_superstore.py`

**Estimated scope:** XS (1 file, ~5 lines)

---

## Phase 2: Frontend Cleanup (independent of Phase 1)

### Task 4: Fix api() Content-Type on GET requests

**Description:** Only set `Content-Type: application/json` header when `opts.body` is present. GET requests should not send this header.

**Acceptance criteria:**
- [ ] `api()` without a body sends no Content-Type header
- [ ] `api()` with a body still sends `Content-Type: application/json`
- [ ] All existing POST calls continue working (they all pass `body`)

**Verification:**
- [ ] Load index.html, open Network tab — GET `/api/status` has no Content-Type request header
- [ ] Plan + Apply flow still works (POST calls send Content-Type)

**Dependencies:** None

**Files touched:** `static/app.js`

**Estimated scope:** XS (1 file, 3-line change)

---

### Task 5: Fix hardcoded text + button label in index.html

**Description:** Change `<code id="conn-view-inline">demo.analytics</code>` to `…` (JS already populates it). Rename "Load / Reset" button to "Load".

**Acceptance criteria:**
- [ ] `conn-view-inline` default text is `…` (not "demo.analytics")
- [ ] Button text reads "Load" (not "Load / Reset")
- [ ] JS still populates the correct view name on load
- [ ] Confirm dialog still fires on click

**Verification:**
- [ ] View page source: no "demo.analytics" hardcoded
- [ ] Load page: view name appears correctly after JS runs
- [ ] Click Load button: confirm dialog appears

**Dependencies:** None

**Files touched:** `static/index.html`

**Estimated scope:** XS (1 file, 2-line change)

---

### Task 6: Fix embed.html Tableau init error swallowing

**Description:** Change `.catch(() => {})` to `.catch((e) => console.warn("Tableau ext init:", e))` so initialization errors are visible in the console.

**Acceptance criteria:**
- [ ] Tableau init errors are logged to console as warnings
- [ ] No behavior change when Tableau extensions are available
- [ ] Opening embed.html outside Tableau shows a console warning (not silence)

**Verification:**
- [ ] Open `/embed` in browser (outside Tableau): console shows "Tableau ext init:" warning
- [ ] No uncaught exceptions

**Dependencies:** None

**Files touched:** `static/embed.html`

**Estimated scope:** XS (1 file, 1-line change)

---

### Task 7: Remove Pitfalls card from index.html + app.js cleanup

**Description:** Delete the `#pitfalls-card` section from index.html. Remove `loadPitfalls()` from `refreshAll()` in app.js. Remove the pitfalls UI event listeners (`#pitfalls-save`, `#pitfalls-download`, `#pitfalls-clear`) and the `loadPitfalls` function from app.js. Remove `#pitfalls-card` and `#pitfalls-text` CSS rules from styles.css. Keep all backend pitfalls endpoints intact.

**Acceptance criteria:**
- [ ] No `#pitfalls-card` in index.html
- [ ] No `loadPitfalls` function in app.js
- [ ] No pitfalls event listeners in app.js
- [ ] `refreshAll()` calls only `refresh()` and `refreshDatasets()`
- [ ] No `#pitfalls-card` or `#pitfalls-text` CSS in styles.css
- [ ] Backend endpoints (`/api/pitfalls`, etc.) still respond normally
- [ ] Zero console errors on index.html and embed.html

**Verification:**
- [ ] Load index.html: no Pitfalls section visible, no console errors
- [ ] Load embed.html: no console errors
- [ ] `curl http://localhost:3777/api/pitfalls` returns valid JSON

**Dependencies:** None

**Files touched:** `static/index.html`, `static/app.js`, `static/styles.css`

**Estimated scope:** S (3 files, removing ~50 lines total)

---

### Task 8: Remove dead `.manifest-load` CSS

**Description:** Delete the `.manifest-load` rule block from styles.css (not used in any HTML).

**Acceptance criteria:**
- [ ] No `.manifest-load` selector in styles.css
- [ ] No visual regression (class isn't used)

**Verification:**
- [ ] Grep codebase for "manifest-load": only appears in git history, not in current files

**Dependencies:** None (but order after Task 7 to avoid merge conflict in styles.css)

**Files touched:** `static/styles.css`

**Estimated scope:** XS (1 file, ~4 lines removed)

---

## Checkpoint: After Phase 1+2 (Tasks 1-8)

- [ ] `python -c "import app; import seed; import snapshots_store"` passes
- [ ] Server starts: `uvicorn app:app --port 8000`
- [ ] `/api/status` returns valid JSON
- [ ] index.html loads with zero console errors
- [ ] embed.html loads with zero console errors
- [ ] No Pitfalls card visible on main page
- [ ] Backend pitfalls endpoints still work
- [ ] "Load" button (not "Load / Reset") with confirm dialog

---

## Phase 3: Design Polish (CSS + minor HTML)

### Task 9: Fix `.muted` margin scoping

**Description:** Remove the `margin: 0 0 12px` from `.muted` (it's a generic utility class used on inline spans too). Add `p.muted, .chat-intro { margin: 0 0 12px; }` for block-level usage only.

**Acceptance criteria:**
- [ ] `.muted` rule has no margin property
- [ ] `p.muted` and `.chat-intro` have `margin: 0 0 12px`
- [ ] Inline `.muted` spans (e.g., `#conn-view-rows`, `#pitfalls-raw-count`) have no unwanted bottom margin
- [ ] Block `.muted` paragraphs still have correct spacing

**Verification:**
- [ ] Inspect `#conn-view-rows` in devtools: no bottom margin
- [ ] Chat intro text still has bottom spacing

**Dependencies:** Task 7 (pitfalls card removed, so fewer .muted elements to worry about)

**Files touched:** `static/styles.css`

**Estimated scope:** XS (1 file, 2-line change)

---

### Task 10: Add hover/focus states to interactive elements

**Description:** Add visible hover and focus-visible states to: buttons (default + primary), textarea, select, and details summary.

**Acceptance criteria:**
- [ ] `button:hover` has a visible background change (not just border)
- [ ] `button.primary:hover` brightens
- [ ] `textarea:focus` shows accent border color
- [ ] `select:focus` shows accent border color
- [ ] `button:focus-visible` has an outline ring
- [ ] `details summary:hover` has a color shift

**Verification:**
- [ ] Tab through all interactive elements on index.html: each has visible focus indicator
- [ ] Hover each button type: visible feedback
- [ ] Click into textarea: accent border appears

**Dependencies:** None

**Files touched:** `static/styles.css`

**Estimated scope:** S (1 file, ~15 lines added)

---

### Task 11: Elevate chat card + style `.dataset-switch`

**Description:** Add a subtle box-shadow to `#chat-card` so it stands out as the primary interaction surface. Add styling to `.dataset-switch` (top border, padding, margin) to visually separate it from connection details.

**Acceptance criteria:**
- [ ] `#chat-card` has a box-shadow making it visually elevated above other cards
- [ ] `.dataset-switch` has a top border and vertical spacing separating it from the KV grid above

**Verification:**
- [ ] Visual inspection: chat card stands out as primary surface
- [ ] Dataset switch area has clear separation from connection details

**Dependencies:** None

**Files touched:** `static/styles.css`

**Estimated scope:** XS (1 file, ~6 lines)

---

### Task 12: Add active-view context to embed page

**Description:** Add a `<span id="embed-context" class="muted"></span>` to embed.html below the status line. In app.js, after `refresh()` completes, populate this element with the view name and row count if the element exists.

**Acceptance criteria:**
- [ ] embed.html has an `#embed-context` element
- [ ] After page load, it shows something like "demo.salesforce (2,000 rows)"
- [ ] On index.html (where the element doesn't exist): no error
- [ ] Styling matches existing `.muted` text

**Verification:**
- [ ] Open `/embed`: context line shows view name and row count
- [ ] Open `/`: no console errors (element doesn't exist, guard handles it)

**Dependencies:** Task 4 (api() fix should be in place first)

**Files touched:** `static/embed.html`, `static/app.js`

**Estimated scope:** S (2 files, ~5 lines each)

---

## Checkpoint: After Phase 3 (Tasks 9-12)

- [ ] Zero console errors on index.html and embed.html
- [ ] All interactive elements have visible hover and focus states
- [ ] Chat card visually elevated
- [ ] Dataset switch area has clear separation
- [ ] Embed page shows active view context
- [ ] Tab navigation works smoothly across all controls

---

## Phase 4: Model Selector Feature

### Task 13: Add model field to backend (ChatRequest + planner)

**Description:** Add an optional `model` field to `ChatRequest`. If provided, pass it to `planner.plan()` which uses it to override `self.model` for that single call (not mutating the instance). Update the `/api/chat` endpoint to pass `req.model` through.

**Acceptance criteria:**
- [ ] `ChatRequest` has `model: str | None = None`
- [ ] `planner.plan()` accepts an optional `model` parameter
- [ ] When `model` is provided, that model ID is used for the API call
- [ ] When `model` is None, the default (`self.model`) is used
- [ ] Existing callers (retry in `/api/apply`) continue working unchanged

**Verification:**
- [ ] `python -c "import app"` succeeds
- [ ] POST `/api/chat` with `{"message": "test", "model": "some-id"}` uses the specified model
- [ ] POST `/api/chat` with `{"message": "test"}` uses the default model

**Dependencies:** Tasks 1-2 (backend cleanup should be done first)

**Files touched:** `app.py`, `planner.py`

**Estimated scope:** S (2 files, ~10 lines each)

---

### Task 14: Add model selector dropdown to frontend

**Description:** Add a `<select id="model-select">` in the chat card header (next to Autorun toggle) with options for Sonnet 4.6 and Opus 4.6. Persist selection in localStorage. Include the selected model in the `/api/chat` POST body.

**Acceptance criteria:**
- [ ] Dropdown visible in chat card header with two model options
- [ ] Selection persists across page reloads (localStorage key: `demo-studio.model`)
- [ ] Selected model ID is included in the `/api/chat` request body as `model`
- [ ] Default is Sonnet 4.6
- [ ] Dropdown is styled consistently with existing controls (matches select element styles)

**Verification:**
- [ ] Load index.html: dropdown visible with two options
- [ ] Select Opus, reload: Opus still selected
- [ ] Open Network tab, send a chat: request body includes `"model": "<selected-id>"`
- [ ] embed.html also shows the dropdown (shared app.js)

**Dependencies:** Task 13 (backend must accept the model field)

**Files touched:** `static/index.html`, `static/embed.html`, `static/app.js`, `static/styles.css`

**Estimated scope:** M (4 files, ~20 lines total)

---

## Checkpoint: After Phase 4 (Tasks 13-14)

- [ ] Model dropdown visible on both index.html and embed.html
- [ ] Model selection persists across reloads
- [ ] Selected model is sent to backend and used by the planner
- [ ] Default model (Sonnet) works when no selection is made
- [ ] All four HTML pages load with zero console errors

---

## Phase 5: Final Verification

### Task 15: Smoke test all pages

**Description:** Manual end-to-end verification of all four HTML entry points. This task is verification-only, no code changes.

**Acceptance criteria:**
- [ ] index.html: full flow (plan, apply, rollback, dataset switch, model selector) — zero console errors
- [ ] embed.html: standalone (plan + apply, view context shown, show-code toggle) — zero console errors
- [ ] extension.html: loads without error, shows graceful state outside Tableau
- [ ] history.html: shows history list, auto-refreshes

**Verification:**
- [ ] Open each page with DevTools console open
- [ ] Execute the chat → plan → apply → rollback flow on index.html
- [ ] Switch datasets (Salesforce → Superstore → back)
- [ ] Toggle model selector and verify it takes effect
- [ ] Open embed.html in isolation, verify context line and chat flow

**Dependencies:** All prior tasks

**Files touched:** None (verification only)

**Estimated scope:** N/A (manual testing)

---

## Summary

| Phase | Tasks | Scope | Risk |
|-------|-------|-------|------|
| 1: Backend cleanup | 1-3 | 4 files | Low |
| 2: Frontend cleanup | 4-8 | 5 files | Low |
| 3: Design polish | 9-12 | 3 files | Low |
| 4: Model selector | 13-14 | 5 files | Medium |
| 5: Verification | 15 | 0 files | None |

Total: 15 tasks, 4 checkpoints, estimated ~45 minutes of agent execution time.
