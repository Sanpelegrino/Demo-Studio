# Demo Studio — Public Release Audit: Task List

## Phase 1: Backend Cleanup
- [x] Task 1: Remove unused imports + fix module-level logging (`seed.py`, `snapshots_store.py`, `app.py`)
- [x] Task 2: Guard EventBus against closed event loop (`app.py`)
- [x] Task 3: Make XLS_PATH configurable in seed_superstore.py (`seed_superstore.py`)

## Phase 2: Frontend Cleanup
- [x] Task 4: Fix api() Content-Type on GET requests (`app.js`)
- [x] Task 5: Fix hardcoded text + rename Load button (`index.html`)
- [x] Task 6: Fix embed.html Tableau init error swallowing (`embed.html`)
- [x] Task 7: Remove Pitfalls card from UI (`index.html`, `app.js`, `styles.css`)
- [x] Task 8: Remove dead .manifest-load CSS (`styles.css`)

## Checkpoint: Phases 1+2
- [x] Python imports clean
- [x] Server starts and /api/status responds
- [x] index.html + embed.html: zero console errors
- [x] No Pitfalls card visible; backend endpoints intact
- [x] "Load" button with confirm dialog

## Phase 3: Design Polish
- [x] Task 9: Fix .muted margin scoping (`styles.css`)
- [x] Task 10: Add hover/focus states (`styles.css`)
- [x] Task 11: Elevate chat card + style .dataset-switch (`styles.css`)
- [x] Task 12: Add active-view context to embed page (`embed.html`, `app.js`)

## Checkpoint: Phase 3
- [x] All interactive elements have hover/focus feedback
- [x] Chat card visually elevated
- [x] Embed page shows active view context
- [x] Zero console errors on all pages

## Phase 4: Model Selector Feature
- [x] Task 13: Add model field to backend (`app.py`, `planner.py`)
- [x] Task 14: Add model selector dropdown to frontend (`index.html`, `embed.html`, `app.js`, `styles.css`)

## Checkpoint: Phase 4
- [x] Model dropdown visible and functional
- [x] Selection persists, sent to backend
- [x] Default (Sonnet) works when no selection made

## Phase 5: Final Verification
- [ ] Task 15: Smoke test all four HTML pages (no code changes)
