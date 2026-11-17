# LeaveDesk

A leave-management system. Employees apply for leave, managers approve or reject it,
and everyone involved is notified.

| Day | What it adds | Spec |
|---|---|---|
| 1 | Domain core in plain Python | [SPEC.md](SPEC.md) |
| 2 | REST API with FastAPI, JWT login, live notifications, Docker | [API_SPEC.md](API_SPEC.md) |
| 3 | PostgreSQL with SQLAlchemy 2 and Alembic | [SCHEMA.md](SCHEMA.md) |

## Requirements

- Python 3.12 or newer
- Git
- Docker Desktop (only for `docker compose up`)

## Setup

All commands run from the `backend` folder.

### Windows (PowerShell)

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
copy .env.example .env
```

If activation is blocked with a "scripts are disabled" error, run this first, then activate again:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

If `pip` is blocked by Windows security, always use `python -m pip` instead of `pip`.

### macOS or Linux

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
cp .env.example .env
```

Then open `.env` and replace every `replace-...` value. Generate a JWT secret with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

`.env` holds secrets, so it is in `.gitignore` and must never be committed.
`requirements.txt` has only what the app needs to run; `requirements-dev.txt` adds pytest,
httpx and Ruff.

## Run the API

```bash
uvicorn leavedesk.api.main:create_app --factory --reload
```

Open <http://localhost:8000/docs> for Swagger. Log in with `POST /auth/login`, copy the
`access_token`, click **Authorize** and paste it.

Demo users (password is `LEAVEDESK_SEED_PASSWORD` from your `.env`):

| Email | Role | Manager |
|---|---|---|
| `ravi@leavedesk.dev` | Manager | — |
| `meena@leavedesk.dev` | Manager | — |
| `asha@leavedesk.dev` | Employee | Ravi |
| `kiran@leavedesk.dev` | Employee | Ravi |
| `sam@leavedesk.dev` | Employee | Meena |

Data is kept in memory, so it resets every time the API restarts. Day 3 moves it to PostgreSQL.

### Watch live notifications

In one terminal, log in as Ravi and open the stream:

```bash
curl -N "http://localhost:8000/notifications/stream?access_token=<ravi's token>"
```

Then submit leave as Asha from Swagger. The notification appears in the stream straight away.

## Run with Docker

```bash
docker compose up --build
```

This starts the API on <http://localhost:8000/docs> and a PostgreSQL database
(not used until Day 3). Stop it with `Ctrl+C`, then `docker compose down`.

## Database (Day 3)

Without `LEAVEDESK_DATABASE_URL` the API keeps everything in memory, as on Day 2. Set it
and the API stores everything in PostgreSQL: one transaction per API request, so each
request saves all its changes together or none of them.

Start PostgreSQL with Docker, create the tables, then run the API:

```bash
docker compose up -d db
alembic upgrade head
uvicorn leavedesk.api.main:create_app --factory --reload
```

In `dev`, the API creates the demo company, people and balances on first start. You can
also seed by hand with `python -m leavedesk.db.seed`.

`alembic` and the API read `LEAVEDESK_DATABASE_URL`. Put it in `.env`, or set it for the
current PowerShell terminal with:

```powershell
$env:LEAVEDESK_DATABASE_URL = "postgresql+psycopg://leavedesk:<password>@localhost:5432/leavedesk"
```

Set `LEAVEDESK_DATABASE_ECHO=true` to print every SQL statement, which makes N+1 queries
easy to spot.

Useful commands:

```bash
alembic current             # which migration the database is on
alembic downgrade -1        # undo the latest migration
alembic upgrade head --sql  # print the SQL without running it
```

### Database tests

Tests in `tests/db/` run against a real PostgreSQL, and every API test in `tests/api/`
runs twice: once in memory (`[memory]`) and once on PostgreSQL (`[postgres]`). Each run
creates its own temporary database, applies every migration, and drops it afterwards.
Set `LEAVEDESK_TEST_DATABASE_URL` to enable them; without it they are skipped.

```powershell
$env:LEAVEDESK_TEST_DATABASE_URL = "postgresql+psycopg://leavedesk:<password>@localhost:5432/postgres"
python -m pytest tests/db
```

### Windows security ("An Application Control policy has blocked this file")

Some Windows laptops block compiled files that come inside Python packages. If you see
that error, two packages need a workaround. Run these from `backend` with the venv active:

```powershell
# SQLAlchemy: reinstall without its compiled speed-ups (plain Python, same behaviour)
$env:DISABLE_SQLALCHEMY_CEXT = "1"
python -m pip install --force-reinstall --no-deps --no-binary sqlalchemy "SQLAlchemy>=2.0.36,<3"

# psycopg: use pg8000 instead, a driver written entirely in Python
python -m pip install -r requirements-dev.txt
```

Then write `postgresql+pg8000://` instead of `postgresql+psycopg://` at the start of
`LEAVEDESK_DATABASE_URL` and `LEAVEDESK_TEST_DATABASE_URL`. Everything else stays the same,
and the full test suite passes with either driver. Docker always uses psycopg.

## Run the Day 1 demo

```bash
python -m leavedesk.demo            # happy path and the five edge cases
python -m leavedesk.demo --verbose  # also shows the audit log
```

## Tests and code quality

```bash
python -m pytest              # every test, domain and API
ruff check .                  # lint
ruff format --check .         # formatting
```

## Project structure

```
backend/
├── leavedesk/
│   ├── demo.py                 Day 1 end-to-end demo
│   ├── domain/                 Day 1 domain core
│   │   ├── models.py           Employee, Manager, LeaveRequest (Pydantic)
│   │   ├── exceptions.py       Custom exceptions
│   │   ├── dates.py            Working days and overlap detection
│   │   ├── policies.py         LeaveBalance and the leave policies
│   │   ├── repository.py       Storage interface and in-memory version
│   │   ├── service.py          LeaveService: apply, approve, reject, cancel
│   │   ├── instrumentation.py  @audit decorator and timed() context manager
│   │   └── notifications.py    Notifier, email and in-app notifiers
│   ├── db/                     Day 3 PostgreSQL storage
│   │   ├── models.py           SQLAlchemy models: every table, constraint and index
│   │   ├── repository.py       LeaveRepository on PostgreSQL, with the ledger
│   │   ├── errors.py           Database errors turned into LeaveDesk errors
│   │   ├── notifications.py    Inbox, outbox worker and LISTEN listener
│   │   ├── seed.py             Demo company, people and balances
│   │   └── ids.py              UUIDv7 ids
│   └── api/                    Day 2 REST API
│       ├── main.py             App factory: create_app()
│       ├── settings.py         Settings from environment variables
│       ├── auth.py             Argon2id passwords, JWT, route protection
│       ├── errors.py           One JSON shape for every error
│       ├── middleware.py       Request id and access log
│       ├── stream.py           Live notifications (SSE)
│       ├── state.py            Shared objects and demo users
│       ├── schemas.py          Request and response bodies
│       └── routes/             auth, leave and notification endpoints
├── migrations/                 Alembic migrations (schema changes only go here)
├── alembic.ini
├── tests/                      Domain tests, API tests in tests/api/, database tests in tests/db/
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── pyproject.toml              Pytest and Ruff settings
├── requirements.txt
└── requirements-dev.txt
```

## Git workflow

1. Create a feature branch, for example `git switch -c feature/my-change`.
2. Commit your work and push the branch: `git push -u origin feature/my-change`.
3. Open a pull request into `main` on GitHub.
4. A teammate reviews and merges it. Never push straight to `main`.
