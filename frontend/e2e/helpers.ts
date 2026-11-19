import { expect, type APIRequestContext, type Locator, type Page } from '@playwright/test';

/** The seeded demo users (backend/leavedesk/api/state.py). */
export const ASHA = { id: 'e1', email: 'asha@leavedesk.dev', name: 'Asha Rao' };
export const RAVI = { id: 'm1', email: 'ravi@leavedesk.dev', name: 'Ravi Kumar' };
export const PASSWORD = process.env['E2E_PASSWORD'] ?? 'demo1234';

/** Sign in through the Login screen, the way a person does, and wait for My leave. */
export async function logIn(page: Page, email: string): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/leave$/);
}

/** The notification bell in the toolbar. Its label is "Notifications, 2 unread". */
export function bell(page: Page): Locator {
  return page.getByRole('button', { name: /^Notifications, / });
}

/** The unread count from the bell's label ("none unread" is 0). */
export async function unreadCount(page: Page): Promise<number> {
  const label = (await bell(page).getAttribute('aria-label')) ?? '';
  const match = /(\d+) unread/.exec(label);
  return match ? Number(match[1]) : 0;
}

/** The big "days left" number on one balance card, for example Annual. */
export function daysLeft(page: Page, typeName: string): Locator {
  return page.locator('mat-card', { hasText: typeName }).locator('.available');
}

/** Press Tab until `target` has focus. Fails if Tab never reaches it (UI-16). */
export async function tabTo(page: Page, target: Locator, maxPresses = 30): Promise<void> {
  for (let i = 0; i < maxPresses; i++) {
    if (await target.evaluate((el) => el === document.activeElement)) {
      return;
    }
    await page.keyboard.press('Tab');
  }
  await expect(target, `Tab never reached it after ${maxPresses} presses`).toBeFocused();
}

/** True when the page itself scrolls sideways (only inner boxes such as tables may). */
export function scrollsSideways(page: Page): Promise<boolean> {
  return page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
}

export interface FreeDay {
  iso: string; // 2026-12-07, as the API speaks
  typed: string; // 07/12/2026, as a person types it in the date field
}

/**
 * The tests use the same database as the demo, so each run needs dates that Asha has not
 * used yet. Ask the API which working days are taken and pick the first free one that
 * respects annual leave's three days' notice, this year (the year her balance is for).
 */
export async function freeWorkingDayForAsha(api: APIRequestContext): Promise<FreeDay> {
  const login = await api.post('/api/auth/login', {
    data: { email: ASHA.email, password: PASSWORD },
  });
  expect(login.ok(), 'Asha could not sign in through the API').toBeTruthy();
  const headers = { Authorization: `Bearer ${(await login.json()).access_token}` };

  const balances: { leave_type: string; available: number }[] = await (
    await api.get(`/api/employees/${ASHA.id}/balance`, { headers })
  ).json();
  const annual = balances.find((b) => b.leave_type === 'ANNUAL');
  if (!annual || annual.available < 1) {
    throw new Error(noRoomLeft('Asha has no annual leave left'));
  }

  const taken = new Set<string>();
  let cursor: string | null = null;
  do {
    const page: { items: unknown[]; next_cursor: string | null } = await (
      await api.get('/api/leave-requests', {
        headers,
        params: { employee_id: ASHA.id, limit: 100, ...(cursor ? { cursor } : {}) },
      })
    ).json();
    for (const r of page.items as { start_date: string; end_date: string; status: string }[]) {
      if (r.status === 'PENDING' || r.status === 'APPROVED') {
        for (let d = parse(r.start_date); d <= parse(r.end_date); d.setDate(d.getDate() + 1)) {
          taken.add(iso(d));
        }
      }
    }
    cursor = page.next_cursor;
  } while (cursor);

  const day = new Date();
  day.setHours(0, 0, 0, 0);
  day.setDate(day.getDate() + 4); // annual leave needs 3 days' notice; one spare for time zones
  const year = new Date().getFullYear();
  for (; day.getFullYear() === year; day.setDate(day.getDate() + 1)) {
    const weekend = day.getDay() === 0 || day.getDay() === 6;
    if (!weekend && !taken.has(iso(day))) {
      return { iso: iso(day), typed: iso(day).split('-').reverse().join('/') };
    }
  }
  throw new Error(noRoomLeft(`Asha has no free working day left in ${year}`));
}

function noRoomLeft(why: string): string {
  return (
    `${why}, so the test cannot apply for leave. Start again from fresh demo data: ` +
    'docker compose down -v, then docker compose up -d, alembic upgrade head and ' +
    'python -m leavedesk.db.seed (see README.md).'
  );
}

function parse(isoDate: string): Date {
  const [y, m, d] = isoDate.split('-').map(Number);
  return new Date(y, m - 1, d);
}

function iso(day: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`;
}
