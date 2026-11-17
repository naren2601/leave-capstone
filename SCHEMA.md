# LeaveDesk: Database Schema (Capstone 3)

Day 3 moves LeaveDesk from memory into PostgreSQL 16 using SQLAlchemy 2 (psycopg 3) and
Alembic. The database itself enforces the rules: constraints block bad data, an EXCLUDE
constraint blocks overlapping leave, and a CHECK on the balance row blocks overspending,
even when two managers approve at the same moment.

The Day 2 API keeps working unchanged: it talks to `LeaveRepository`, and a new
`PostgresLeaveRepository` implements that interface.

## 1. Tables

Every business table has `tenant_id`, so one database can serve several companies.

| Table | Purpose | Primary key |
|---|---|---|
| `tenants` | One row per company | `id bigint identity` |
| `departments` | Teams within a tenant | `id bigint identity` |
| `employees` | People, their manager and department | `id bigint identity`, plus `code` (the API id, such as `e1`) |
| `users` | Login details for an employee | `employee_id` (one login per employee) |
| `leave_types` | Annual, Sick, Casual, with their rules | `id bigint identity` |
| `leave_requests` | Each request and its status | `id uuid` (UUIDv7) |
| `leave_balances` | Current entitled, used and pending days per employee, type and year | (`employee_id`, `leave_type_id`, `year`) |
| `leave_ledger` | Append-only record of every balance movement | `id bigint identity` |
| `notifications` | In-app notifications | `id uuid` (UUIDv7) |
| `notification_outbox` | Deliveries waiting to be sent (email) | `id bigint identity` |
| `audit_log` | Append-only record of who did what | `id bigint identity` |
| `idempotency_keys` | First result of each `POST /leave-requests` retry key | (`tenant_id`, `employee_id`, `key`) |

### Columns

```text
tenants            id, name UNIQUE, created_at

departments        id, tenant_id → tenants, name
                   UNIQUE (tenant_id, name)

employees          id, tenant_id → tenants, code, name, email, is_manager,
                   department_id → departments NULL, manager_id → employees NULL,
                   created_at, updated_at
                   UNIQUE (tenant_id, code)
                   UNIQUE (tenant_id, lower(email))            -- email unique per tenant
                   CHECK  (manager_id <> id)
                   FK     (tenant_id, manager_id) → employees (tenant_id, id)  -- same tenant only

users              employee_id → employees PK, tenant_id, password_hash,
                   failed_login_count, locked_until timestamptz NULL, last_login_at
                   CHECK (password_hash LIKE '$argon2id$%')     -- never a plain password

leave_types        id, tenant_id, code, name, days_per_year numeric(5,1),
                   min_start_offset_days, max_days_per_request numeric(5,1) NULL
                   UNIQUE (tenant_id, code)
                   -- min_start_offset_days: earliest start in days from today.
                   --   Annual 3 (three days' notice), Sick -7 (backdate a week), Casual 0.

leave_requests     id uuid, tenant_id, employee_id → employees, leave_type_id → leave_types,
                   start_date date, end_date date, day_part, reason, status,
                   days numeric(5,1), decision_note NULL, decided_by → employees NULL,
                   period tsrange GENERATED ALWAYS AS (...) STORED,
                   version integer, created_at, updated_at
                   CHECK (end_date >= start_date)
                   CHECK (day_part = 'FULL' OR start_date = end_date)
                   CHECK (status IN ('PENDING','APPROVED','REJECTED','CANCELLED'))
                   CHECK (day_part IN ('FULL','AM','PM'))
                   CHECK (days > 0)
                   CHECK (char_length(btrim(reason)) BETWEEN 5 AND 500)
                   EXCLUDE (see section 3)

leave_balances     tenant_id, employee_id, leave_type_id, year,
                   entitled, used, pending numeric(5,1), version integer
                   CHECK (used >= 0 AND pending >= 0)
                   CHECK (used + pending <= entitled)           -- no overspending, ever

leave_ledger       id, tenant_id, employee_id, leave_type_id, year,
                   leave_request_id → leave_requests NULL,
                   movement ('ENTITLEMENT','RESERVE','RELEASE','CONSUME','RESTORE'),
                   entitled_delta, pending_delta, used_delta numeric(5,1),
                   created_at, created_by → employees NULL

notifications      id uuid, tenant_id, recipient_id → employees, event, payload jsonb,
                   read_at timestamptz NULL, created_at

notification_outbox id, tenant_id, notification_id → notifications, channel ('email'),
                   status ('PENDING','SENT','FAILED'), attempts, claimed_at, sent_at,
                   last_error, created_at

audit_log          id, tenant_id, actor_id → employees NULL, action, entity, entity_id,
                   request_id, details jsonb, created_at

idempotency_keys   tenant_id, employee_id, key, leave_request_id → leave_requests, created_at
```

Every foreign key has its own index. PostgreSQL does not create one automatically, and
without it, deleting or updating a parent row scans the whole child table.

## 2. Design decisions

### Keys: identity for internal tables, UUIDv7 for requests and notifications

- **`bigint GENERATED ALWAYS AS IDENTITY`** for small, internal tables (tenants,
  departments, employees, leave types, ledger, audit, outbox). They are compact (8 bytes),
  fast to join, and never shown in URLs, except employees, which have a separate `code`.
- **UUIDv7** for `leave_requests` and `notifications`. Their ids appear in URLs, so they must
  not be guessable: a sequential id like `/leave-requests/41` invites trying `/42`.
  UUIDv7 starts with a timestamp, so new rows land at the end of the index like an identity
  column, unlike random UUIDv4, which scatters inserts across the whole B-tree and causes
  page splits. PostgreSQL 16 has no built-in `uuidv7()`, so the app generates them.
- **`employees.code`** (`e1`, `m1`) is the business key used by the API, like an HR employee
  number. It is unique per tenant. Joins use the internal `id`.

### Leave type: a lookup table. Status and day part: CHECK constraints

- **Leave type is a lookup table** because each type carries data: days per year, how far
  ahead or back a request may start, and the per-request maximum. A tenant can add or change a type with
  an `INSERT` or `UPDATE`, without a migration.
- **Status and day part are `CHECK` constraints** on `text`. The values are fixed by the code's
  state machine, so a new value always needs a code change anyway. CHECK is easier to change
  than an `ENUM` (an `ENUM` value cannot be removed or renamed easily, and adding one cannot
  run in the same transaction that uses it), and a lookup table would add a join for no
  benefit.

### `numeric(5,1)` for days

Days can be halves (0.5). `float` stores 0.1 inexactly, so sums drift (`0.1 + 0.2` is not
`0.3`). `numeric` is exact. `(5,1)` allows up to 9999.9 days with one decimal place, which
covers any balance and rejects values like 0.25 that the business does not allow.

### `timestamptz` for audit columns

`timestamptz` stores an exact moment (in UTC) and converts on display. A plain `timestamp`
stores a wall-clock time with no zone, so "10:00" from Kolkata and "10:00" from London look
the same. Audit columns must record the real moment, so they are all `timestamptz`.
Leave dates (`start_date`, `end_date`) stay `date`, because leave is a whole calendar day.

### Ledger and balances

- **`leave_ledger` is the source of truth.** Every change appends a row, and rows are never
  updated or deleted. A trigger rejects `UPDATE` and `DELETE`, and the app role has no
  `UPDATE` or `DELETE` permission on it.
- **`leave_balances` is a running total** of the ledger, kept in the same transaction. It
  exists so there is one row to lock (`SELECT ... FOR UPDATE`) and one row the
  `CHECK (used + pending <= entitled)` can protect. A test checks that every balance equals
  the sum of its ledger movements.

| Action | Ledger movement | pending | used |
|---|---|---|---|
| New year's entitlement | `ENTITLEMENT` | 0 | 0 (entitled +18) |
| Apply | `RESERVE` | +days | 0 |
| Approve | `CONSUME` | −days | +days |
| Reject, or cancel pending | `RELEASE` | −days | 0 |
| Cancel approved | `RESTORE` | 0 | −days |

## 3. No overlapping leave: the EXCLUDE constraint

The brief suggests `daterange ... WITH &&`. A plain date range would block an AM and a PM
half-day on the same date, which the Day 1 spec allows (AC-3.3). So each request gets a
generated `period` column with **half-day precision**:

| `day_part` | `period` |
|---|---|
| `FULL` | `[start_date 00:00, end_date + 1 day 00:00)` |
| `AM` | `[date 00:00, date 12:00)` |
| `PM` | `[date 12:00, date + 1 day 00:00)` |

```sql
CREATE EXTENSION IF NOT EXISTS btree_gist;

ALTER TABLE leave_requests ADD CONSTRAINT no_overlapping_leave
  EXCLUDE USING gist (tenant_id WITH =, employee_id WITH =, period WITH &&)
  WHERE (status IN ('PENDING', 'APPROVED'));
```

If the end date is before the start date, `period` is `NULL`, so the clear
`CHECK (end_date >= start_date)` reports the problem instead of a confusing range error.
All of this was tested on PostgreSQL 16: AM and PM on the same date are allowed, and
overlapping full days, a second AM, and a full day over a half day are all rejected.

`btree_gist` lets plain columns (`tenant_id`, `employee_id`) use `=` inside a GiST index.
Rejected and cancelled requests are outside the `WHERE`, so their dates can be reused.
Even if two requests arrive at the same moment, the database lets only one in.

## 4. Safe approvals

Approve runs as one transaction:

1. `SELECT ... FROM leave_requests WHERE id = :id FOR UPDATE`, which locks the request.
2. Check its `version` matches the one the client read; if not, return **409**
   (optimistic locking with SQLAlchemy's `version_id_col`).
3. `SELECT ... FROM leave_balances ... FOR UPDATE`, which locks the balance row.
4. Update the balance, append a `CONSUME` ledger row, set the request to `APPROVED`.
5. Insert the notifications and their outbox rows.
6. `COMMIT`. If anything fails, everything rolls back, including the notifications.

A second manager approving at the same moment waits at step 1, then sees `APPROVED` and
gets 409. A pytest test fires two approvals in parallel and checks only one deducts days.

`POST /leave-requests` accepts an `Idempotency-Key` header. The key is saved in the same
transaction as the request, so a retry returns the first result instead of a duplicate.

## 5. Notifications: outbox and LISTEN/NOTIFY

- In the same transaction as each submit, approve, reject or cancel, the app inserts the
  `notifications` rows and one `notification_outbox` row per email.
- A trigger on `notifications` calls `pg_notify('leavedesk_notifications', ...)`. PostgreSQL
  delivers it **only after the transaction commits**, so a rolled-back change never notifies.
- The SSE stream runs `LISTEN leavedesk_notifications` and pushes new rows to the browser,
  replacing in-memory pushing.
- An outbox worker claims rows with `SELECT ... FOR UPDATE SKIP LOCKED`, sends the email,
  and marks them `SENT`. `SKIP LOCKED` means two workers never take the same row.
- A partial index on unread rows keeps the bell count fast:
  `CREATE INDEX ON notifications (recipient_id, created_at DESC) WHERE read_at IS NULL;`

## 6. Indexes for the three main queries

Details and before/after `EXPLAIN (ANALYZE, BUFFERS)` plans go in `PERF.md`.

| Query | Index | Why this shape |
|---|---|---|
| Manager's pending queue | Partial: `leave_requests (tenant_id, employee_id, start_date) WHERE status = 'PENDING'` | Only pending rows are indexed, so it stays small as history grows |
| Employee's history | Composite: `leave_requests (tenant_id, employee_id, start_date DESC, id DESC)` | Equality columns first, then the sort columns, so rows come back already sorted and keyset pagination can seek straight to the next page |
| Employee name search | GIN `pg_trgm`: `employees USING gin (name gin_trgm_ops)` | A normal B-tree cannot help `LIKE '%sha%'`; trigrams can |

Lists switch from `OFFSET` to **keyset pagination** (`WHERE (start_date, id) < (:last_date, :last_id)`),
which reads only the rows on the page instead of skipping over every earlier row.

## 7. Security

- **Two database roles.** `leavedesk_migrator` owns the tables and runs Alembic.
  `leavedesk_app` can only read and write rows: no `CREATE`, `ALTER` or `DROP`, and no
  `UPDATE` or `DELETE` on `leave_ledger` and `audit_log`.
- **Timeouts on the app role:** `statement_timeout = '5s'`, `lock_timeout = '2s'`,
  `idle_in_transaction_session_timeout = '30s'`.
- **Login lockout:** 5 wrong passwords lock the account for 15 minutes. The error message stays
  the same, so it does not reveal whether the account exists or is locked.
- **Parameterized queries only.** The ORM binds every value; raw SQL goes through `text()`
  with bound parameters.
- **No secrets in the repo.** Database passwords come from `.env`.
- **Stretch: row-level security** on `tenant_id`, using `current_setting('app.tenant_id')`.

**Built in step 5:** the roles are created by `backend/docker/initdb/01-roles.sh` when the
database volume is first created; `leavedesk/db/roles.py` re-applies the app role's grants
after every `alembic upgrade`. The timeouts are set on the role and on every connection
(`leavedesk/db/engine.py`); a timeout becomes HTTP 503 `TRY_AGAIN`. Tests prove the app role
cannot `DROP`, `ALTER`, `CREATE`, `TRUNCATE` or change the ledger, and that the whole API works
with only its privileges. Row-level security was not done.

## 8. Build plan

| # | Task | Part |
|---|---|---|
| 1 | SQLAlchemy models and the first Alembic revision (tables, constraints, EXCLUDE, triggers) | A |
| 2 | `PostgresLeaveRepository` and one session per request; Day 2 tests running on PostgreSQL | A |
| 3 | Ledger-based balances, row locks, version column, idempotency key | C |
| 4 | Notifications, outbox, worker, LISTEN/NOTIFY for SSE | C2 |
| 5 | Login lockout, app role, timeouts | D |
| 6 | Seed 100,000 requests, indexes, keyset pagination, `PERF.md` | B |
| 7 | Overlap, concurrency and outbox-rollback tests | Done-when |
