# Spec: Demo Studio — Public Release Audit

## Objective

Clean up Demo Studio for public release: remove cruft from rapid iteration, fix error-path bugs, and apply consistent design principles to the existing UI. The result should be a professional-grade single-page app that looks intentional — not an internal prototype.

**Target users:** Salesforce SEs demonstrating Tableau + AI-generated data pipelines to prospects. They load a dataset, chat with an LLM to reshape it, and Tableau refreshes live.

**Success criteria:**
- Zero JS console errors on index.html, embed.html, extension.html, and history.html
- No dead code, unused imports, or stale naming in any Python or JS file
- Every interactive element has a visible hover and focus state
- Button visual weight matches action importance (primary > secondary > utility)
- Status is always communicated with text labels, never color alone
- The embed page works standalone with no errors and shows enough context for the user to know what they're acting on
- The dataset load/reset flow is obvious on first use (destructive action is clearly marked, current state is always visible)

---

## Pass 1: Code & Logic Cleanup

### 1.1 Dead code and unused imports

| File | Issue | Fix |
|------|-------|-----|
| `seed.py:5` | `from typing import Iterable` — unused | Remove |
| `snapshots_store.py:5` | `from typing import Iterable` — unused | Remove |
| `app.py:15` | `import shutil` — used (line 902) | Keep |
| `app.py:16` | `import zipfile` — used (line 911) | Keep |
| `history.js` | Duplicates `escapeHtml` and `fmtTime` from `app.js` | Acceptable — separate entry point, no shared module system |

### 1.2 Stale references

| File | Issue | Fix |
|------|-------|-----|
| `index.html:17` | `<code id="conn-view-inline">demo.analytics</code>` hardcodes "analytics" — should show actual view | Change to placeholder `…` and let JS populate it via the existing `setText("#conn-view-inline", viewName)` call (already done at app.js:101). The HTML default just needs to be neutral. |
| `planner.py:3` | Default model is Sonnet — correct, but user should be able to choose between Opus 4.6 and Sonnet 4.6 | Add a model selector to the main page UI. Planner already reads `ANTHROPIC_MODEL` env var; wire a dropdown that passes the chosen model to `/api/chat` and `/api/apply`. |

### 1.3 Overly complex logic

| File | Area | Assessment |
|------|------|------------|
| `app.js` | Straightforward imperative DOM code. No unnecessary abstractions. | Clean — no changes needed |
| `seed.py` | Linear data generation with clear structure | Clean |
| `seed_superstore.py` | XLS → Postgres with column rename map | Clean |
| `seed_manifest.py` | Join graph BFS is appropriate for the problem | Clean |
| `app.py:111-157` | `_distill_pitfalls_background` — imports `logging` inside the function body, nested try/finally | Minor: move `import logging` to top of file (it's already imported at line 118 via `logging.getLogger`) — actually `logging` is not imported at module level. Add it to the top-level imports. |

### 1.4 Error-path bugs

| File:Line | Bug | Fix |
|-----------|-----|-----|
| `app.js:11` | `api()` sets `Content-Type: application/json` on GET requests (harmless but incorrect — some proxies reject body-less requests with this header) | Only set Content-Type when `opts.body` is present |
| `app.js:134` | `$("#send").addEventListener(...)` runs unconditionally — would throw if `#send` is absent | Not a bug: both index.html and embed.html have `#send`. But add a guard for robustness since app.js is shared. |
| `embed.html:12` | `tableau.extensions.initializeAsync().catch(() => {})` swallows all init errors silently | Log to console: `.catch((e) => console.warn("Tableau init:", e))` |
| `app.py:280-281` | `@app.on_event("startup")` is deprecated in modern FastAPI (still works but emits a deprecation warning) | Replace with `@app.router.on_event("startup")` or use the `lifespan` pattern. For minimal change, keep `on_event` — it works in FastAPI 0.115. |
| `EventBus.publish_sync` (app.py:247-254) | If the event loop is closed (during shutdown), `call_soon_threadsafe` raises `RuntimeError` | Wrap in try/except RuntimeError: pass |
| `snapshots_store.py:195-199` | `CREATE OR REPLACE VIEW ... AS {body}` injects raw SQL from the stored view_definition — this is intentional (restoring a prior state) but worth a comment | Add a brief comment noting this is trusted internal data |

### 1.5 UX friction

| Issue | Location | Fix |
|-------|----------|-----|
| Embed page shows no context about active dataset/view | `embed.html` | Add a small status line below the textarea showing the active view name (fetch from `/api/status` on load). A single `<span>` is enough. |
| "Load / Reset" button intent is ambiguous — does it load the selected dataset or reset the current one? | `index.html:48` | Rename to "Load" — the `confirm()` dialog already warns about wiping. The destructive nature is communicated by the `danger` class + confirmation. |
| After a failed apply, there's no guidance on what to do next | `app.js:188-192` | Status message already shows the error. Sufficient. |
| The `conn-view-inline` in the instructional paragraph shows stale "demo.analytics" until JS loads | `index.html:17` | Change default text to `…` (ellipsis) |

### 1.6 Embed page standalone correctness

The embed page (`/embed`) shares `app.js` with the main page. Potential issues:

| Check | Result |
|-------|--------|
| Missing DOM elements that app.js expects | Safe — all event listeners are guarded with `if ($(...))` or the element exists in embed.html |
| `refreshAll()` calls `loadPitfalls()` and `refreshDatasets()` | Safe — both null-check their DOM elements and return early |
| `applyMaxMode(true)` is triggered by `#chat` hash | Works correctly — embed.html sets hash before app.js loads |
| `showPlan` / `hidePlan` | Both reference elements that exist in embed.html |

**One issue:** `refreshAll()` calls `refresh()` which calls `setText("#conn-host", ...)` etc. for elements that don't exist on the embed page. `setText` uses `$(sel)` which returns null, and then `el.textContent = value` would throw.

Wait — checking `setText`:
```js
const setText = (sel, value) => { const el = $(sel); if (el) el.textContent = value; };
```
It null-guards. **Safe.**

**Verdict:** Embed page is already robust. Only improvement needed is adding active-view context.

---

## Pass 2: Design Quality Audit

### 2.1 Visual hierarchy

| Issue | Severity | Fix |
|-------|----------|-----|
| All cards have identical visual weight — Connection, Chat, History, and Pitfalls all look the same | Medium | Give the Chat card a slightly elevated appearance: add `box-shadow: 0 2px 8px rgba(0,0,0,0.3)` to `#chat-card`. This makes the primary interaction surface stand out. |
| Pitfalls card (admin maintenance) has equal prominence to Chat (primary action) | Low | Move Pitfalls into a `<details>` wrapper or give it a more subdued border color. Recommend: wrap its content in a collapsible `<details>` within the existing card. |
| Header is minimal (just title + subtitle) — no visual anchor | Low | Acceptable for a tool UI. No change needed. |

### 2.2 Spacing consistency

| Issue | Fix |
|-------|-----|
| `.muted` has `margin: 0 0 12px` globally — applies unwanted bottom margin to inline `.muted` spans (e.g., `#conn-view-rows`, `#pitfalls-raw-count`) | Scope the margin: `.muted` gets `margin: 0`, and add `.muted` as a block-level paragraph style only when it's a `<p class="muted">`. Use `p.muted { margin: 0 0 12px; }` |
| `.card h2` has `margin: 0 0 4px` but `.card-head` already handles spacing via flexbox | Harmless — the 4px bottom margin on h2 provides fallback spacing when there's no card-head wrapper |
| Gap between cards is 16px (grid gap) — tight for a tool with dense content | Acceptable. No change. |

### 2.3 Missing hover/focus states

| Element | Current state | Fix |
|---------|--------------|-----|
| `button` (default) | Hover: border becomes accent | Add: `background: var(--accent-dim)` on hover for more visible feedback |
| `button.primary` | No distinct hover | Add: `filter: brightness(1.2)` or lighten background on hover |
| `button.primary:disabled` | `opacity: 0.5` | Fine |
| `textarea` | No focus ring | Add: `textarea:focus { border-color: var(--accent); outline: none; }` |
| `select` (dataset-select) | No focus ring | Add: `select:focus { border-color: var(--accent); outline: none; }` |
| `button:focus-visible` | No style | Add: `button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }` |
| `details summary` | `cursor: pointer` only | Add: `details summary:hover { color: var(--text); }` |

### 2.4 Button weight and clarity

| Button | Current styling | Assessment |
|--------|----------------|------------|
| "Plan change" (`#send.primary`) | Accent-dim bg + accent border | Correct — primary action |
| "Apply" (`#apply-top.primary`) | Same as above | Correct — primary action in its context |
| "Discard" (`#discard-top`) | Default button style | Correct — secondary/dismissive |
| "Load / Reset" (`.danger`) | Danger text + danger border, no fill | Appropriate — destructive secondary |
| "Rollback last change" | Default button style | Should arguably be `.danger` since it's destructive — but it has a confirm dialog, so default is acceptable |
| "Refresh" | Default button | Correct — utility action |
| "copy" (`.mini`) | Tiny utility button | Correct |
| "Save curated" (`.primary`) | Primary styling | Correct — it's the primary action in the Pitfalls section |
| "Clear raw log" (`.mini.danger`) | Mini + danger | Correct |

**No changes needed** — button weight is already well-considered.

### 2.5 Status communication

| Element | Color-only? | Fix needed? |
|---------|-------------|-------------|
| Status messages (`.status.ok`, `.status.err`) | No — always has text | Good |
| Extension badge (`#state`) | Has text label ("connected"/"disconnected") | Good |
| History items | Time + language + summary in text | Good |
| Toggle states | Visual track position + label color change | Good — position change is primary indicator |
| `.tag` (language pills) | Text content present | Good |

**No violations found.** Status is always communicated with text.

### 2.6 Embed page as standalone experience

| Aspect | Assessment | Fix |
|--------|------------|-----|
| Visual completeness | Clean — just the chat card filling the viewport | Good |
| Context | No indication of what dataset/view is active | Add a subtle status line: view name + row count |
| Branding | Title says "Demo Studio" — sufficient identity | Good |
| Controls | Autorun toggle, Show code toggle, Plan/Apply/Discard | Complete set for the interaction |
| Missing: no Refresh or Rollback in embed | Intentional — those are admin actions for the main UI | Good |

### 2.7 Additional CSS issues

| Issue | Fix |
|-------|-----|
| `#history li` grid has fixed `120px` first column for timestamp — on narrow viewports this wastes space | Add a responsive breakpoint or use `auto` min. Low priority — main page is expected to be used on desktop. |
| `.dataset-switch` class is used in HTML but has no CSS definition | Add minimal styling: `margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--border);` |
| The `.manifest-load` CSS class exists but isn't used in any HTML | Remove it from styles.css |

---

## Commands

```
Dev server:     uvicorn app:app --reload --port 8000
Seed database:  python seed.py
Seed Superstore: python seed_superstore.py
```

## Project Structure

```
app.py                 → FastAPI backend (routes, EventBus, apply/rollback logic)
planner.py             → LLM gateway client + response parser
seed.py                → Salesforce dataset generator
seed_superstore.py     → Superstore XLS loader
seed_manifest.py       → Manifest-based dataset loader (CSV + join graph)
snapshots_store.py     → Postgres snapshot/rollback store
static/
  app.js               → Main UI logic (shared by index.html and embed.html)
  extension.js         → Live Refresh extension logic
  history.js           → History-only page logic
  styles.css           → All CSS (no build step)
  index.html           → Main page
  embed.html           → Chat embed (Tableau dashboard extension)
  extension.html       → Live Refresh extension page
  history.html         → History-only embed
  live-chat.trex       → Tableau extension manifest (chat)
  live-refresh.trex    → Tableau extension manifest (auto-refresh)
  tableau.extensions.1.latest.min.js → Tableau Extensions API (vendored)
prompts/
  pitfalls.md          → Curated model guidance
  pitfalls_raw.jsonl   → Raw failure log
  pitfalls_distill_prompt.md → Distillation system prompt
  pitfalls_rag_prompt.md     → RAG build system prompt
  pitfalls_rag.json          → RAG store
datasets/              → User-uploaded manifest datasets
```

## Code Style

Vanilla JS, no framework, no build step. Python uses type hints and psycopg3.

```javascript
// JS: Guard DOM access, use $ helper, early return on missing elements
const el = $("#some-element");
if (!el) return;
el.textContent = value;
```

```python
# Python: psycopg.sql for identifiers, type hints, docstrings on public functions
def _helper(cur: psycopg.Cursor, schema: str) -> list[str]:
    cur.execute(
        sql.SQL("SELECT ... FROM {}.{}").format(
            sql.Identifier(schema), sql.Identifier(table)
        )
    )
    return [r[0] for r in cur.fetchall()]
```

## Testing Strategy

No automated test suite exists and adding one is out of scope for this audit. Verification is manual:

- Load each HTML page, check browser console for errors
- Test the chat → plan → apply → rollback flow
- Test dataset switching (Salesforce, Superstore, manifest upload)
- Open embed.html in isolation and verify no console errors
- Verify the Live Refresh extension initializes without errors

## Boundaries

**Always:**
- Preserve all existing API contracts (request/response shapes)
- Keep the Tableau Extensions API integration working
- Maintain app.js as a single file
- Test embed.html standalone after any change to app.js or styles.css

**Ask first:**
- Renaming CSS classes (could break extension.html/history.html selectors)
- Changing the model ID list (adding/removing models from the selector)

**Never:**
- Add new npm/pip dependencies
- Add a build step (bundler, preprocessor, etc.)
- Introduce a theme system, design tokens file, or CSS custom properties layer beyond what exists
- Change database schema or API response contracts
- Modify the vendored `tableau.extensions.1.latest.min.js`

---

## Task Breakdown

### Phase A: Code cleanup (low risk, high confidence)

- [ ] **A1: Remove unused imports**
  - `seed.py`: remove `from typing import Iterable`
  - `snapshots_store.py`: remove `Iterable` from typing import
  - `app.py`: add `import logging` at module level, remove the in-function import
  - Verify: `python -c "import app; import seed; import snapshots_store"`

- [ ] **A2: Fix hardcoded "demo.analytics" in index.html**
  - Change `<code id="conn-view-inline">demo.analytics</code>` to `<code id="conn-view-inline">…</code>`
  - Verify: page loads, JS populates the correct view name

- [ ] **A3: Fix `api()` Content-Type on GET requests**
  - Only set `Content-Type: application/json` when `opts.body` is present
  - Verify: network tab shows no Content-Type on GET calls

- [ ] **A4: Guard EventBus against closed loop**
  - Wrap `call_soon_threadsafe` in try/except RuntimeError
  - Verify: app shuts down cleanly without traceback

- [ ] **A5: Fix silent Tableau init error in embed.html**
  - Change `.catch(() => {})` to `.catch((e) => console.warn("Tableau ext init:", e))`
  - Verify: if opened outside Tableau, console shows warning instead of silence

- [ ] **A6: Rename "Load / Reset" button to "Load"**
  - Verify: button text is shorter, confirm dialog still fires

- [ ] **A7: Remove dead `.manifest-load` CSS**
  - Verify: no visual regression

- [ ] **A8: Remove Pitfalls card from index.html**
  - Delete the entire `#pitfalls-card` section from index.html
  - Remove pitfalls-related CSS (if any is card-specific)
  - Keep all backend pitfalls endpoints and background distillation logic intact
  - Remove `loadPitfalls()` from `refreshAll()` in app.js; remove the pitfalls UI event listeners
  - Verify: page loads, no console errors, pitfalls endpoints still respond

- [ ] **A9: Make XLS_PATH configurable in seed_superstore.py**
  - Check `os.environ.get("SUPERSTORE_XLS_PATH")` first, fall back to the current hardcoded path
  - If neither exists when `seed_superstore()` is called, raise a clear `FileNotFoundError` with guidance
  - Verify: works when file exists at default path; errors clearly when it doesn't

### Phase B: Design polish (CSS + HTML, no logic changes)

- [ ] **B1: Fix `.muted` margin scoping**
  - Change `.muted { margin: 0 0 12px; }` to `.muted { color: var(--muted); font-size: 13px; }` (no margin)
  - Add `p.muted, .chat-intro { margin: 0 0 12px; }` for block-level usage
  - Verify: inline `.muted` spans no longer have unwanted bottom margin; paragraph intros still have spacing

- [ ] **B2: Add hover/focus states**
  - `button:hover` → add subtle background shift
  - `button.primary:hover` → brighten
  - `textarea:focus`, `select:focus` → accent border
  - `button:focus-visible` → outline ring
  - `details summary:hover` → color shift
  - Verify: tab through all interactive elements, check visual feedback

- [ ] **B3: Elevate chat card**
  - Add `box-shadow` to `#chat-card` to visually lift it above other cards
  - Verify: chat card reads as the primary interaction surface

- [ ] **B4: Add `.dataset-switch` styling**
  - Add top border and margin to separate it from the connection details
  - Verify: dataset switch area has clear visual separation

- [ ] **B5: Add active-view context to embed page**
  - Add a small `<span id="embed-context" class="muted"></span>` after the textarea
  - In app.js, populate it from `/api/status` (view name + row count) if the element exists
  - Verify: embed page shows "demo.salesforce (2,000 rows)" or similar

### Phase C: Model selector feature

- [ ] **C1: Add model selector to main page**
  - Add a `<select id="model-select">` next to the Autorun toggle in the chat card header with two options: Sonnet 4.6 (default) and Opus 4.6
  - Store selection in localStorage
  - Pass model ID in the `/api/chat` request body
  - Verify: dropdown persists across reloads, selected model is sent to backend

- [ ] **C2: Wire model through backend**
  - Add optional `model` field to `ChatRequest` schema
  - If provided, pass it to `planner.plan()` which overrides `self.model` for that call
  - Verify: switching models in the UI produces plans from the selected model

### Phase D: Verification

- [ ] **D1: Manual smoke test all four HTML pages**
  - index.html: full flow (plan, apply, rollback, dataset switch, model selector)
  - embed.html: standalone, plan + apply
  - extension.html: loads without error (outside Tableau shows graceful message)
  - history.html: shows history list, auto-refreshes

---

## Resolved Decisions

1. **Model selection** — Sonnet 4.6 is the default. Add a UI dropdown on the main page letting the user choose between Opus 4.6 and Sonnet 4.6. The selected model is passed per-request to the planner.
2. **Pitfalls card** — Remove from the user-facing UI entirely. This is internal model-improvement machinery, not user-relevant. The backend endpoints and background distillation remain; just don't expose the card in index.html.
3. **XLS_PATH in seed_superstore.py** — The Superstore dataset ships in the Tableau Repository of any Tableau Desktop install. Keep the path as a constant but fall back to an env var `SUPERSTORE_XLS_PATH` if set. If neither exists, the `/api/reseed?dataset=superstore` endpoint returns a clear error. No over-engineering — an agent setting this up will find the file or skip Superstore.
