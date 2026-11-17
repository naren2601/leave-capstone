# LeaveDesk performance check (Day 3, step 6)

Measured on 17 Nov 2026 with **100,000 leave requests** and **10,000 employees**
(100 managers with 99 reports each, 10 requests per person, about 10% pending).
PostgreSQL 16, warm cache, the median of repeated runs. Timings move by ±30% between
runs; the **buffer counts** (8 kB pages read) are stable and are the fairer measure.

Reproduce it on a database you can throw away, from `backend/`:

```bash
alembic upgrade head
python -m leavedesk.db.perf seed      # about 6 seconds
python -m leavedesk.db.perf explain   # EXPLAIN (ANALYZE, BUFFERS) of each query below
```

The script explains the queries the API really sends: it builds them with the same
repository code.

## 1. The biggest win: the list endpoint itself

`GET /leave-requests?status=PENDING` for a manager with 99 reports, timed end to end in
Python (queries plus turning rows into objects):

| | Old route (Day 2 logic on PostgreSQL) | New route | |
|---|---|---|---|
| Time | 707 ms | **16.5 ms** | **43× faster** |
| SQL queries, team of 49 | 149 | **5** | Same 5 for a team of 1 |

The old route was written for the in-memory store and moved to the database unchanged:

1. It loaded **all 10,000 employees** to find one manager's 99 reports.
2. It then ran **one query per report** for their requests (the N+1 problem), loaded all
   990 rows, filtered and sorted them in Python, and kept 20.

Now `direct_reports()` asks for just the reports (an index lookup), and `page_requests()`
lets PostgreSQL filter, sort, count and cut the page in one query.
`test_a_bigger_team_does_not_mean_more_queries` fails if this ever goes back to 149.

## 2. Each query, before and after the new indexes

"Before" is the step 5 schema (every foreign key already indexed since step 1).
"After" is migration `0003` plus remembering employee ids within a request.

| # | Query (what the API asks) | Before | After | Pages read |
|---|---|---|---|---|
| 1 | Manager's pending queue, first page | 2.76 ms | **0.40 ms** | 1,347 → **299** |
| 2 | One employee's history, newest first | 0.08 ms | 0.04 ms | 15 → 14 |
| 3a | Team history, page 40, `OFFSET 780` | 3.54 ms | 0.98 ms | 1,344 → 1,287 |
| 3b | Team history, page 40, **keyset cursor** | 2.36 ms | **0.27 ms** | 1,344 → **507** |
| 4 | A manager's direct reports | 0.07 ms | 0.06 ms | 8 → 8 |
| 5 | Name search `?q=meena kh` | 5.86 ms | **0.53 ms** | 156 → 113 |

### What changed, and why

**`ix_leave_requests_pending` (partial index, `WHERE status = 'PENDING'`).** The approval
queue only wants pending rows, about 1 in 10. Before, PostgreSQL read every request of all
99 reports and threw 9 in 10 away (`Rows Removed by Filter: 9`). A partial index only
contains pending rows, so it is small (592 kB against 5.8 MB) and holds exactly the queue.

```text
Before: Index Scan using ix_leave_requests_tenant_id_employee_id   Filter: (status = 'PENDING')
        Rows Removed by Filter: 9   (x 99 reports)            Buffers: shared hit=1347
After:  Index Scan using ix_leave_requests_pending                  Buffers: shared hit=299
```

**`ix_leave_requests_history (tenant_id, employee_id, start_date, id)`.** It replaces the
plain `(tenant_id, employee_id)` index. It still serves the employee foreign key (its first
columns are the same), and its rows are also stored in date order, so one person's history
comes out already sorted, and a cursor can be used as an index condition.

**Keyset pagination (`?cursor=`).** With `OFFSET 780` the database must still find and
sort 801 rows and throw 780 away; page 400 would read even more. A cursor says "after
(2026-04-17, 5bc0...)", which becomes part of the index condition, so rows before it are
never read:

```text
3a OFFSET:  Sort ... rows=801          then skip 780            Buffers: shared hit=1287
3b cursor:  Index Cond: ... AND (ROW(start_date, id) > ROW('2026-04-17', '5bc0...'))
            rows=210                                             Buffers: shared hit=507
```

The cost of an offset grows with the page number; a cursor's stays flat. Offsets still
work for jumping to a page number; apps that scroll should use `next_cursor`.

**Remembering employee ids.** Queries 1 and 3 first had to turn 99 employee codes
("e4100") into internal ids, and PostgreSQL chose to read all 10,000 employees for that
(`Seq Scan on employees ... Rows Removed by Filter: 9901`, about 1.5 ms). The repository
already has those ids from `direct_reports()`, so it now remembers them for the rest of the
request and sends the ids directly.

**`ix_employees_name_trgm` (GIN, `pg_trgm`).** `ILIKE '%meena kh%'` starts with a
wildcard, so a normal B-tree index cannot help, and PostgreSQL read all 10,000 employees.
A trigram index splits names into 3-letter pieces ("mee", "een", ...) and finds the
matches directly: **11× faster**.

```text
Before: Seq Scan on employees  Filter: (name ~~* '%meena kh%')  Rows Removed by Filter: 9901
After:  Bitmap Index Scan on ix_employees_name_trgm  Index Cond: (name ~~* '%meena kh%')
```

## 3. What we did not change, and why

- **No index on `status` alone.** With 4 values, it would match a quarter of the table on
  average. The partial index covers the one status that is rare and queried often.
- **`total` is still a `COUNT(*)`.** It reads at most one team's requests (about 1,000
  rows), well under a millisecond. For a company-wide list it would need rethinking.
- **The indexes cost space and write time.** Together they add about 6.8 MB to an 18 MB
  table. Each insert updates them; leave requests are written rarely and read often, so
  this is a good trade.
- **Built with `CREATE INDEX CONCURRENTLY`** in the migration, which does not block
  writes while it runs, so it is safe on a live database.

## 4. Tests that keep this true

- `tests/db/test_performance.py`: the pending queue uses `ix_leave_requests_pending`,
  history and cursors use `ix_leave_requests_history` with the cursor in the index
  condition, the trigram index can serve name search, and the team list costs the same
  number of queries for 1 or 49 reports.
- `tests/api/test_paging.py`: cursor pages return every request once, in order, in both
  directions, with filters, and match offset pages; bad cursors are 422; name search
  treats `%` and `_` as plain characters.
