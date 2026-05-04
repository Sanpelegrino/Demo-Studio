---
name: pitfalls
description: Read the raw failed-apply log at prompts/pitfalls_raw.jsonl, categorize, dedupe, and distill the errors into concrete "don't do X, do Y" guidance. Merge with whatever is already in prompts/pitfalls.md, then save the merged result back to pitfalls.md. Finally clear the raw log via DELETE /api/pitfalls/raw so the next cycle starts fresh. Use this when the user types /pitfalls or asks to "clean up pitfalls" / "distill errors" / "update the prompt with new pitfalls".
---

# pitfalls

Turn the raw failure log for Demo Studio into
clean, categorized pitfalls that get appended to Claude's system prompt.

## What this skill does

1. Reads the raw log: `prompts/pitfalls_raw.jsonl` (relative to the
   workspace root — usually `prompts/pitfalls_raw.jsonl`
   or discoverable via `GET /api/pitfalls`).
2. Reads the current curated file: `prompts/pitfalls.md`.
3. Categorizes failures (SQL syntax, view maintenance, schema DDL,
   bulk data, Python exec, safety, etc.).
4. Deduplicates: identical or near-identical failures collapse into
   one rule.
5. Rewrites each cluster as one prescriptive rule in "**Don't** X.
   **Do** Y." style — short, concrete, actionable.
6. Merges with existing curated rules, removing any that now
   contradict or are superseded.
7. Writes the merged content back to `prompts/pitfalls.md` via
   `PUT /api/pitfalls` (or by directly editing the file).
8. Clears the raw log via `DELETE /api/pitfalls/raw`.

## Required inputs

- The URL of the running app (default `http://localhost:3777`).
- Write access to `prompts/pitfalls.md` OR ability to call the API.

## Steps

### 1. Fetch the current state

Try the API first (it works whether or not you're running locally):

```bash
curl -s http://localhost:3777/api/pitfalls
curl -s http://localhost:3777/api/pitfalls/raw -o pitfalls_raw.jsonl
```

If the API is unreachable, read the files directly:
- `prompts/pitfalls.md`
- `prompts/pitfalls_raw.jsonl`

If the raw log is empty, stop and tell the user there's nothing to distill.

### 2. Parse and cluster

Each raw entry looks like:

```json
{
  "summary": "user's intent, e.g. 'Add churn_risk column'",
  "language": "sql" | "python",
  "code": "the code the model wrote",
  "error_type": "Postgres exception class, e.g. UndefinedTable",
  "error_message": "the full error text",
  "ts": 1714561234.56
}
```

Group by root cause, not error type. Two `UndefinedTable` errors that
stem from different mistakes should be separate clusters; two
`GroupingError`s with the same pattern should merge.

### 3. Write each cluster as a rule

Format each rule like:

```markdown
- **Don't** mix `MAX(...)` with bare non-grouped columns in the same
  SELECT. **Do** compute the aggregate in a subquery or CTE first, then
  join it back.
```

Keep rules under ~2 lines each. Skip generic hedges ("be careful with
SQL"). Every rule must name a specific mistake the model actually made.

### 4. Categorize

Group rules under headings. Use these when they apply, and add new
ones as needed:

```markdown
## View maintenance
## Schema DDL
## SQL correctness
## Bulk data operations
## Python execution environment
## Id generation / uniqueness
## Transactions and commits
```

### 5. Merge with the existing curated file

- Keep any existing rules that still apply.
- If a new distilled rule supersedes an old one (same category,
  clearer phrasing), replace the old one.
- Never duplicate rules across categories.
- Preserve the top-level header and comment block in `pitfalls.md`.

### 6. Save and clear

Write the merged content back:

```bash
curl -X PUT http://localhost:3777/api/pitfalls \
  -H "Content-Type: application/json" \
  -d "$(jq -n --arg c "$NEW_CONTENT" '{curated: $c}')"
```

Or edit `prompts/pitfalls.md` directly with Write.

Then clear the raw log:

```bash
curl -X DELETE http://localhost:3777/api/pitfalls/raw
```

### 7. Report back

Tell the user:
- How many raw failures you processed.
- How many final categorized rules resulted.
- Which categories were affected.
- Whether the raw log was cleared.

## Style

- Keep the curated file short. If the file grows past ~50 rules,
  aggressively merge and cut. The goal is guidance, not a changelog.
- Don't include timestamps, error codes, stack traces, or the raw
  model-generated code in the curated file — those live in the raw log
  for reference.
- Write rules in the imperative, addressed to the model: "Don't DROP
  tables that have incoming FK references without CASCADE" — not
  "The user wants you to...".
