import { expect, test } from '@playwright/test';

import { ASHA, bell, daysLeft, freeWorkingDayForAsha, logIn, RAVI, unreadCount } from './helpers';

/**
 * UI-15, the whole story in two browsers at once: Asha applies, Ravi approves, and Asha's
 * screen updates by itself (live notification, unread count, status and balance).
 */
test('UI-15: Asha applies, Ravi approves, Asha is told and her balance drops', async ({
  browser,
  request,
}) => {
  const day = await freeWorkingDayForAsha(request);
  const reason = `E2E check ${Date.now()}`; // unique, so we can find this run's row

  // Two separate browser contexts = two people on two computers (separate sessions).
  const asha = await (await browser.newContext()).newPage();
  const ravi = await (await browser.newContext()).newPage();

  // 1. Asha signs in and notes where she starts.
  await logIn(asha, ASHA.email);
  await expect(daysLeft(asha, 'Annual')).toBeVisible();
  const annualBefore = parseFloat((await daysLeft(asha, 'Annual').innerText()).trim());
  const unreadBefore = await unreadCount(asha);

  // 2. She applies for one day of annual leave.
  await asha.getByRole('link', { name: 'Apply for leave' }).click();
  await asha.getByLabel('Start date').fill(day.typed);
  await asha.getByLabel('End date').fill(day.typed);
  await asha.getByLabel('Reason').fill(reason);
  await asha.getByRole('button', { name: 'Submit request' }).click();

  await expect(asha).toHaveURL(/\/leave$/);
  await asha.getByRole('radio', { name: 'Pending' }).click();
  await expect(asha.getByRole('row', { name: reason })).toContainText('Pending');

  // 3. Ravi, her manager, approves it from the Approvals screen.
  await logIn(ravi, RAVI.email);
  await ravi.getByRole('link', { name: 'Approvals' }).click();
  const approve = ravi.getByRole('button', { name: `Approve ${ASHA.name}, ${day.iso}` });
  await approve.click();
  const dialog = ravi.getByRole('dialog');
  await expect(dialog).toContainText('Approve this leave?');
  await dialog.getByRole('button', { name: 'Approve' }).click();
  await expect(approve).toHaveCount(0); // the row leaves Ravi's list
  await expect(ravi.getByText('Approved. The employee has been told.')).toBeVisible();

  // 4. Asha's open page changes by itself (no reload): the live stream told it.
  // (The snack bar, not the copy read out to screen readers; a new one replaces the last.)
  const approvedNote = `(ANNUAL, ${day.iso} to ${day.iso}) was approved.`;
  await expect(asha.locator('mat-snack-bar-container', { hasText: approvedNote })).toBeVisible();
  // +2: "was submitted" when she applied and "was approved" now.
  await expect(bell(asha)).toHaveAttribute(
    'aria-label',
    `Notifications, ${unreadBefore + 2} unread`,
  );
  await expect(asha.getByRole('row', { name: reason })).toHaveCount(0); // no longer pending
  await asha.getByRole('radio', { name: 'Approved' }).click();
  await expect(asha.getByRole('row', { name: reason })).toContainText('Approved');
  await expect(daysLeft(asha, 'Annual')).toHaveText(
    new RegExp(`^\\s*${annualBefore - 1}\\s*days left`),
  );

  // 5. Opening the bell lists the news and marks everything read.
  await bell(asha).click();
  await expect(asha.getByRole('menu')).toContainText(approvedNote);
  await asha.keyboard.press('Escape');
  await expect(bell(asha)).toHaveAttribute('aria-label', 'Notifications, none unread');
});
