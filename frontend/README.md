# LeaveDesk web app (Day 4)

Angular front end for the LeaveDesk API. The screens and acceptance criteria are in
[`../UI_SPEC.md`](../UI_SPEC.md).

## Run it

You need Node.js 22.22+ or 24.15+, and the API running on port 8000
(see `../backend/README.md`).

```powershell
cd frontend
npm install          # once, and after package.json changes
npm start            # http://localhost:4200
```

`npm start` forwards every `/api/...` call to the API at `http://127.0.0.1:8000`
(`proxy.conf.json`), so the browser talks to one address and needs no CORS setup.

## Check it

| Command | What it does |
|---|---|
| `npm test` | Unit tests with Vitest and Angular Testing Library |
| `npm run lint` | ESLint, including accessibility rules for templates |
| `npm run format:check` | Prettier (`npm run format` fixes the files) |
| `npm run build` | Production build into `dist/` |
| `npm run e2e` | End-to-end tests with Playwright, in a real browser against the real API |

## End-to-end tests (Playwright)

The tests in `e2e/` drive a real Chromium browser through the app, which talks to the real
API and database:

- `leave-flow.spec.ts` (UI-15): Asha applies, Ravi approves in a second browser, and
  Asha's open page shows the notification, the new status and the lower balance by itself.
- `phone-and-keyboard.spec.ts` (UI-16): no screen scrolls sideways at 375 px, and the
  keyboard alone can sign in, use the bell and reach every field on Apply.

```powershell
npx playwright install chromium   # once: downloads the browser Playwright uses
# start the database and API first (..\start-dev.ps1 starts everything)
npm run e2e                       # starts `npm start` itself if it is not running
npm run e2e:report                # the HTML report of the last run
```

To test another address, such as the Docker web service, set `E2E_BASE_URL` first:
`$env:E2E_BASE_URL = "http://localhost:8080"; npm run e2e`.

The tests use the demo users, so each run applies for one more day of Asha's annual
leave, on the first free working day at least four days ahead. When she runs out, start
again from fresh demo data (see the main README).

## Structure

```text
src/app/
  core/        app-wide pieces: API address, auth, interceptors, guards
  shared/      reusable UI: status chip, confirm dialog, loading/empty/error view
  features/    one folder per screen area: login, leave, approvals, notifications
```
