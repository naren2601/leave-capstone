# LeaveDesk Web App: UI Specification (Capstone 4)

Day 4 puts an Angular front end on the Day 3 API (`API_SPEC.md`). The browser never decides
anything on its own: every rule (balances, overlaps, who may approve) is still checked by the
API, and the UI shows the API's answer.

**Stack:** Angular (standalone components, Signals), Angular Material and CDK, Reactive
Forms, HttpClient with interceptors, RxJS for the live stream, Vitest with Angular Testing
Library, Playwright, ESLint and Prettier.

## 1. Users and screens

| Screen | URL | Who | Purpose |
|---|---|---|---|
| Login | `/login` | Anyone | Sign in with email and password |
| My leave | `/leave` | Everyone signed in | Balance cards and my requests (filter, pages, cancel) |
| Apply | `/leave/apply` | Everyone signed in | Request leave |
| Approvals | `/approvals` | Managers only (lazy-loaded) | Approve or reject the team's pending requests |
| Toolbar | every page after login | Everyone signed in | App name, notification bell, user name, Log out |

After login, everyone lands on **My leave**. Managers also see an **Approvals** link.
An unknown URL goes to My leave (or Login when signed out).

## 2. Screens in detail

### Login
- Email and password fields, both required; the email must look like an email.
- The **Sign in** button is disabled while the form is invalid or a sign-in is running.
- Wrong email or password, or a locked account: one message, "Email or password is wrong",
  the same for every case (the API does not reveal which).
- On success the token is stored, the user goes to My leave (or back to the page they wanted).

### My leave
- **Balance cards**, one per leave type: available days in large text, then entitled, used
  and pending. The total available days across types is a `computed()` signal.
- **Requests table** (Material table): type, dates, days, status (as a coloured chip), reason,
  and a **Cancel** button on `PENDING` rows only.
- **Status filter** (All, Pending, Approved, Rejected, Cancelled) and **paginator** (10 per
  page). Changing the filter goes back to page 1.
- After Cancel succeeds, the row shows `CANCELLED` and the balance cards reload.

### Apply for leave
- Fields: leave type (select), start date, end date (date pickers), day part (Full, Morning,
  Afternoon), reason.
- Checks in the browser, before sending:
  - all fields required; reason 5 to 500 characters;
  - end date not before start date (form-level validator, error shown under the end date);
  - a half day (Morning or Afternoon) must be a single day.
- Rules only the server knows (notice period, balance, overlap) are shown **inline above the
  Submit button**, using the API's message:
  - **409 `OVERLAPPING_LEAVE`**: "These dates overlap another request" plus the API's details;
  - **422 `INSUFFICIENT_BALANCE`** and **`POLICY_VIOLATION`**: the API's message.
- Each submit sends an `Idempotency-Key`, so a double click cannot create two requests.
- On success: a snackbar "Leave requested", then back to My leave.

### Approvals (managers)
- A table of the team's `PENDING` requests: employee, type, dates, days, reason, with
  **Approve** and **Reject** buttons.
- Both open a **confirm dialog**. Reject requires a reason (not just spaces).
- **Optimistic update:** the row disappears at once. If the API fails, the row comes back in
  its place and a snackbar shows the error (for example 409 "already decided").
- Approve and Reject send `If-Match` with the request's version, so a stale screen gets a
  clear 409 instead of overwriting someone else's decision.
- The route is lazy-loaded and protected by a role guard; an employee who types
  `/approvals` is sent to My leave.

### Notification bell (toolbar)
- A bell icon with a badge showing the **unread count**, a `computed()` signal over the
  notifications store. No badge when the count is 0.
- After login the store loads `/notifications` and opens the live stream
  `/notifications/stream?access_token=...`; it closes the stream on logout.
- A new notification shows a snackbar with its message, and the badge goes up.
- Clicking the bell opens a panel: the newest notifications, unread ones in bold. Opening the
  panel marks them read (`POST /notifications/read-all`), and the badge clears.
- Panel states: loading spinner, "No notifications", and an error message with **Retry**.
- Keyboard: the bell is a real button (Tab, Enter, Escape closes the panel). Its label reads
  "Notifications, 3 unread", and changes are announced to screen readers (`aria-live`).

## 3. Shared behaviour

- **Token:** stored in `sessionStorage` (cleared when the tab closes). An interceptor adds
  `Authorization: Bearer <token>` to every API call except login.
- **401 anywhere** (expired or missing token): clear the token, go to Login, show "Please
  sign in again".
- **Every list has three states:** loading (spinner), empty (a friendly sentence), and error
  (message plus **Retry**). Buttons that send are disabled while sending.
- **Errors** use the API's error shape (`error.code`, `error.message`, `error.details`).
- **Layout:** works at **375 px** phone width (cards stack, tables scroll sideways inside
  their box) and on desktop. Every form control has a visible label and can be reached with
  the keyboard; focus is visible.

## 4. State (signal stores)

| Store | Holds | Exposes |
|---|---|---|
| `AuthStore` | token, user id, role, name | `isLoggedIn`, `isManager` (computed), `login()`, `logout()` |
| `LeaveStore` | my requests page, filter, page index, balances, status (`idle`, `loading`, `success`, `error`) | `load()`, `cancel()`, `apply()`, `totalAvailable` (computed) |
| `ApprovalsStore` | pending team requests, status | `load()`, `approve()`, `reject()` with optimistic update and rollback |
| `NotificationsStore` | notifications, stream status | `unreadCount` (computed), `connect()`, `disconnect()`, `markAllRead()` |

Server state (what the API returned) lives in the stores; UI-only state (is a dialog open,
form values) stays in the component.

## 5. Folder structure

```text
frontend/src/app/
  core/        auth (store, guard, role guard), interceptors, API error helpers, config
  shared/      status chip, confirm dialog, loading/empty/error view
  features/
    login/
    leave/         my-leave page, apply page, leave store, leave API service
    approvals/     approvals page, approvals store (lazy-loaded)
    notifications/ bell, panel, notifications store, SSE stream service
```

## 6. Acceptance criteria

| ID | Given / When | Then | Test |
|---|---|---|---|
| UI-1 | Valid email and password, Sign in | Lands on My leave; the token is sent on the next API call | Vitest (auth store, interceptor), E2E |
| UI-2 | Wrong password | "Email or password is wrong"; stays on Login | Vitest (login form) |
| UI-3 | Login form empty or bad email | Sign in disabled; field errors shown | Vitest (login form) |
| UI-4 | Any API call returns 401 | Token cleared; redirected to Login | Vitest (interceptor) |
| UI-5 | My leave opens | Balance cards and requests shown; total available is the sum | Vitest (leave store) |
| UI-6 | Filter by Pending | Only pending rows; paginator back to page 1 | Vitest (leave store) |
| UI-7 | Apply with end date before start date | Error under end date; nothing sent | Vitest (apply form) |
| UI-8 | Apply for dates that overlap | The API's 409 message shown inline; form kept | Vitest (apply form, HTTP mocked) |
| UI-9 | Employee opens `/approvals` | Sent to My leave | Vitest (role guard) |
| UI-10 | Manager approves | Row disappears at once; stays gone on success | Vitest (approvals store) |
| UI-11 | Approve fails (409) | Row comes back; snackbar with the error | Vitest (approvals store) |
| UI-12 | A new notification arrives on the stream | Snackbar shown; unread count goes up | Vitest (notifications store) |
| UI-13 | Open the bell panel | Notifications listed; all marked read; badge clears | Vitest (notifications store) |
| UI-14 | Lists while loading, when empty, after an error | Spinner; empty sentence; message with Retry | Vitest |
| UI-15 | Full flow | Employee logs in and applies; manager approves; employee sees the notification; available balance drops | **Playwright E2E** |
| UI-16 | Phone width 375 px | No sideways page scroll; every control reachable by keyboard | Playwright (viewport) |

## 7. Build plan

| # | Task | Covers |
|---|---|---|
| 1 | This spec | — |
| 2 | Angular app in `frontend/`: Material, routing, dev proxy to the API, ESLint and Prettier | — |
| 3 | Core: auth store, interceptors, guards, login page | UI-1 to UI-4 |
| 4 | My leave: leave store, balance cards, table, filter, paginator, cancel | UI-5, UI-6, UI-14 |
| 5 | Apply form with validators and inline server errors | UI-7, UI-8 |
| 6 | Approvals: lazy route, role guard, confirm dialog, optimistic update | UI-9 to UI-11 |
| 7 | Notifications: store, SSE stream, bell, panel, snackbar | UI-12, UI-13 |
| 8 | Tests: Vitest (at least 6) and the Playwright flow | UI-15, UI-16 |
| 9 | Docker: web service in `docker-compose.yml`; Playwright passes against `docker compose up` | Done-when |

**Done when:** the Playwright test passes against `docker compose up` running the API, the
database and the Angular app.

**Stretch (not planned):** PWA manifest, service worker and Web Push; NgRx SignalStore.
