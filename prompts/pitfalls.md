# Pitfalls — things the model has gotten wrong before

Curated list of mistakes Claude has made on this workspace. Keep each
item short and prescriptive: what to avoid, and what to do instead.
When it grows messy, hand the raw failure log to an LLM and have it
re-distill this file.

## SQL correctness

- **Don't** reference unqualified columns (`account_id`, `created_date`) in a SELECT/UPDATE that joins or touches multiple tables with the same name. **Do** always prefix with the table or alias (`o.account_id`, `a.created_date`).
- **Don't** concatenate integers and text with `+` (`COUNT(*) + rn::text`, `(SELECT COUNT(*) + 1)::text + row_number()`). **Do** use `||` for string concatenation, and cast the numeric side to text first (`(COUNT(*) + rn)::text`).
- **Don't** subtract a bare integer from a date (`CURRENT_DATE - (row_num * 5)`). **Do** multiply by an interval: `CURRENT_DATE - (row_num * 5) * INTERVAL '1 day'`, or cast the integer: `CURRENT_DATE - (row_num * 5)::integer` only where the operand type is explicitly `integer`.
- **Don't** call `ROUND(double precision, integer)` — Postgres only defines the 2-arg form for `numeric`. **Do** cast the first arg: `ROUND(x::numeric, 2)`.
- **Don't** write `CASE WHEN 0, 1 THEN ...` — `CASE` branches take a single expression. **Do** use `WHEN x IN (0, 1) THEN ...` or split into separate `WHEN` clauses.
- **Don't** put a window function (`ROW_NUMBER() OVER ...`) inside a `WHERE` clause. **Do** compute it in a subquery or CTE and filter on the aliased result in the outer query.
- **Don't** leave non-aggregated columns out of `GROUP BY` when any aggregate is used. **Do** list every non-aggregated select expression in `GROUP BY`, or wrap the aggregate in a CTE and join it back.
- **Don't** reference an outer table's column (`opportunity_id`) from inside a nested aggregate subquery where it isn't in scope. **Do** move the aggregate to a CTE computed over the outer table, or use a correlated subquery with explicit aliases.
- **Don't** reference a column from a CTE (`eo.target_orders`, `c.country_region`) that isn't in that CTE's SELECT list, or whose alias differs from what the outer query uses. **Do** make every column the outer query references — including filter-only columns — appear in the CTE's SELECT under the exact name used downstream.
- **Don't** use `(unnest(array_of_composite_values)).*` to expand anonymous records built from `VALUES`/`ARRAY[(...)]` — Postgres raises `record type has not been registered`. **Do** use parallel `unnest(arr1, arr2, ...)` into named columns, declare a composite type with `CREATE TYPE`, or use `jsonb_to_record` / `jsonb_array_elements` with typed aliases.

## Schema DDL

- **Don't** add a `FOREIGN KEY` pointing at a column that isn't covered by a `PRIMARY KEY` or `UNIQUE` constraint. **Do** verify the referenced column is unique first, or add a unique index before creating the FK.

## ID generation / uniqueness

- **Don't** assume `opportunity_id` (or any text ID) follows a single numeric-after-prefix pattern like `006xxxxxxx`. Rows inserted later may use different prefixes (`RUS0001`, `_SEA005`, `_CN_L001`) that break `SUBSTRING(id FROM N)::integer` or `id::integer`. **Do** generate new IDs from `MAX(SUBSTRING(id FROM '[0-9]+$')::bigint)` after filtering to the prefix family you care about, or from a dedicated sequence — never cast the whole ID to integer.
- **Don't** construct FK-linked IDs by independently concatenating prefixes and padded numbers across two INSERTs — `'001' || LPAD(1000001,7)` and `'0011' || LPAD(1000001,6)` look similar but produce different strings and will blow up the FK. **Do** build each ID exactly once (shared CTE, helper function, or capture via `INSERT ... RETURNING`) and reference that value from both the parent and child insert.

## Python execution environment

- **Don't** multiply `decimal.Decimal` by a Python `float` — it raises `TypeError`. **Do** convert explicitly: `Decimal(str(f)) * d`, or coerce both sides to `float` when precision isn't needed.
- **Don't** build very large synthetic datasets entirely in Python memory (lists of millions of rows before insert). **Do** generate in SQL with `generate_series`/CTEs, or stream in batches and `COPY`/`executemany` incrementally.
- **Don't** write Python block code (imports, loops, list comprehensions) directly in a SQL file or query string — it will parse as SQL and fail with "syntax error at or near 'import'" or similar. **Do** place Python logic in a separate execution block (magic command, script file, or explicit language tag) so it runs in the Python interpreter, not the SQL engine.
- **Don't** sample or slice Python lists that may be shorter than expected (e.g., `return_accounts[i]` when the list has fewer than `i` elements). **Do** validate list length first, use `random.choice()` on the full list, or fetch enough rows upfront to guarantee coverage.

<!-- Add new items above. Example format:
- **Don't** do X because Y. **Do** Z instead.
-->