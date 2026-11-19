import { expect, test } from '@playwright/test';

import { ASHA, bell, logIn, PASSWORD, RAVI, scrollsSideways, tabTo } from './helpers';

// UI-16: a 375 px wide phone screen.
test.use({ viewport: { width: 375, height: 740 } });

test('UI-16: no screen scrolls sideways at 375 px', async ({ page }) => {
  await page.goto('/login');
  expect(await scrollsSideways(page), 'Login').toBe(false);

  await logIn(page, RAVI.email); // a manager sees every screen
  await expect(page.getByRole('heading', { name: 'My requests' })).toBeVisible();
  expect(await scrollsSideways(page), 'My leave').toBe(false);

  await bell(page).click();
  await expect(page.getByRole('menu')).toBeVisible();
  expect(await scrollsSideways(page), 'Notification panel').toBe(false);
  await page.keyboard.press('Escape');

  await page.goto('/leave/apply');
  await expect(page.getByLabel('Reason')).toBeVisible();
  expect(await scrollsSideways(page), 'Apply').toBe(false);

  await page.goto('/approvals');
  await expect(page.getByRole('heading', { name: 'Approvals' })).toBeVisible();
  expect(await scrollsSideways(page), 'Approvals').toBe(false);
});

test('UI-16: a keyboard alone can sign in, use the bell and reach every Apply field', async ({
  page,
}) => {
  // Sign in with Tab, typing and Enter only.
  await page.goto('/login');
  await tabTo(page, page.getByLabel('Email'));
  await page.keyboard.type(ASHA.email);
  await tabTo(page, page.getByLabel('Password'));
  await page.keyboard.type(PASSWORD);
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/\/leave$/);

  // The bell: Enter opens the panel, Escape closes it and gives focus back.
  await tabTo(page, bell(page));
  await page.keyboard.press('Enter');
  await expect(page.getByRole('menu')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('menu')).toHaveCount(0);
  await expect(bell(page)).toBeFocused();

  // Apply: every control can be reached with Tab.
  await tabTo(page, page.getByRole('link', { name: 'Apply for leave' }));
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/\/leave\/apply$/);
  for (const field of [
    page.getByLabel('Leave type'),
    page.getByLabel('Start date'),
    page.getByLabel('End date'),
    page.getByRole('radio', { name: /^Full day/ }),
    page.getByLabel('Reason'),
    page.getByRole('button', { name: 'Submit request' }),
  ]) {
    await tabTo(page, field);
  }
});
