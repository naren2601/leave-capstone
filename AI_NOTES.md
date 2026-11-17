# AI usage log

We used an AI coding assistant (Claude) throughout Capstones 1 and 2. This file records
what we asked for, what it produced, and what was found wrong and fixed. Everything it
produced was run and tested before being committed.

## How we used it

| Step | What we asked | What it produced |
|---|---|---|
| Day 1 spec | Write the spec from the capstone brief | `SPEC.md`: entities, 9 functional requirements with Given/When/Then criteria, 5 edge cases, task breakdown |
| Day 1 code | Implement Part B, one item at a time | `leavedesk/domain/`, `demo.py` and unit tests for each module |
| Day 1 Git | Explain branches, PRs and fixing a commit on the wrong branch | Commands we ran ourselves |
| Day 2 spec | Write the API spec for trainer approval | `API_SPEC.md`: endpoints, error contract, 27 acceptance criteria, task plan |
| Day 2 code | Build the approved API | `leavedesk/api/`, API tests, Ruff config, Dockerfile, Compose file |

## Issues found in the AI's output, and fixed

Each of these was in code the AI wrote first. They were caught by reviewing the code,
reading the logs or running the tests, and then fixed.

1. **Privacy: leave reasons were written to the logs (security).** The `@audit` decorator
   logged every argument, so a sick-leave reason such as "fever and rest" appeared in plain
   text in the log. Reasons can be health information. Fixed: `reason`, `note` and
   `password` are now logged as `<redacted>`, with a test to keep it that way.
2. **Audit log lost the duration of failed calls (correctness).** The first `@audit` version
   logged failures before the timer had stopped, so failed calls had no duration, which
   breaks FR-9 (AC-9.1). Fixed by measuring the time directly in both paths.
3. **Failed requests used up request ids (correctness).** Ids were handed out before
   validation, so a failed apply left gaps such as `LR-1`, `LR-3`. Fixed by giving the id
   only after every check passes, with a test.
4. **A request could be saved before a missing manager was noticed (correctness).** The
   manager was looked up only when sending notifications, after saving. Fixed by checking
   the manager exists before anything is saved.
5. **Pydantic's own error escaped instead of our custom exception.** Bad input raised
   `pydantic.ValidationError`, not `InvalidLeaveRequestError`, so the demo would have shown
   the wrong exception. Fixed by converting it in `LeaveService`.
6. **A test claimed more than it checked.** A generated API test was named as if it proved
   notifications are sent after the response, but it only proved they were sent. It was
   replaced with an honest test.
7. **The first migration made `period` NOT NULL (Day 3).** Reversed dates then failed with
   a confusing range error instead of our named `dates_in_order` rule. Fixed: `period` is
   NULL when the dates are reversed, so the named CHECK fires.
8. **Notifications could go out before the commit (Day 3).** FastAPI runs a yield
   dependency's cleanup after background tasks by default, so emails were sent before the
   transaction committed. Fixed with `Depends(..., scope="function")`, with a test that
   fails if the order changes.
9. **A race returned 500 instead of 409 with pg8000 (Day 3).** psycopg reports a broken
   constraint as `IntegrityError`, pg8000 as `ProgrammingError`. Fixed by mapping on the
   SQLSTATE code (`23...`), not the Python class. Tests run on both drivers.
10. **LISTEN silently did nothing with pg8000 (Day 3).** The connection pool's pre-ping had
    already opened a transaction, and `LISTEN` only starts when its transaction commits,
    so SSE streams never heard anything. Fixed by rolling back before switching to
    autocommit. Found by the two-server stream test.

## Security decisions we checked

- Passwords are hashed with Argon2id; the hash, never the password, is stored.
- A wrong email and a wrong password give the same 401 message and take about the same
  time (an unknown email is still checked against a dummy hash).
- JWTs are decoded with the algorithm fixed to HS256, so a token with `alg: none` is
  rejected. There is a test for this.
- The JWT secret and passwords come from `.env`, which is not committed. The app refuses to
  start with a secret shorter than 32 characters.
- 500 errors return a generic message; the details go only to the log. There is a test.
- A client's `X-Request-ID` is reused only if it is short and has safe characters, so it
  cannot inject fake lines into the log.

## Limits we noticed

- The Docker image could not be built in the AI's environment, so `docker compose up` must
  be checked on our own machines.
- Login lockout after 5 failures is not built yet; it is planned for Day 3 (Part D).

## Team review

<!-- Each teammate: add what you checked yourself and anything you changed. -->
