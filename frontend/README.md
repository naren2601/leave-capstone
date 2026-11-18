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

## Structure

```text
src/app/
  core/        app-wide pieces: API address, auth, interceptors, guards
  shared/      reusable UI: status chip, confirm dialog, loading/empty/error view
  features/    one folder per screen area: login, leave, approvals, notifications
```
