import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';

import { aNotification, provideFakeEventSource } from '../../../testing/fake-event-source';
import { aPage, aRequest, BALANCES } from '../../../testing/leave-data';
import { startSignedInAs } from '../../../testing/sign-in';
import { NotificationsStore } from '../notifications/notifications-store';
import { MyLeavePage } from './my-leave-page';

async function setup() {
  sessionStorage.clear();
  startSignedInAs('employee');
  const view = await render(MyLeavePage, {
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      provideRouter([]),
      provideFakeEventSource(),
    ],
  });
  const http = TestBed.inject(HttpTestingController);
  const answerBalances = () => http.expectOne('/api/employees/e1/balance').flush(BALANCES);
  const list = () => http.expectOne((r) => r.url === '/api/leave-requests');
  return { view, http, answerBalances, list, user: userEvent.setup() };
}

describe('MyLeavePage', () => {
  it('UI-14: shows a loading message while the requests load', async () => {
    await setup();

    expect(screen.getByRole('status')).toHaveTextContent('Loading your requests');
  });

  it('UI-5: shows a card per leave type and the total days available', async () => {
    const { answerBalances, list } = await setup();
    answerBalances();
    list().flush(aPage([]));

    expect(await screen.findByText(/30\.5 in total/)).toBeVisible();
    expect(screen.getByText('Annual')).toBeVisible();
    expect(screen.getByText('5.5')).toBeVisible(); // casual days left
  });

  it('UI-14: says so when there are no requests yet', async () => {
    const { answerBalances, list } = await setup();
    answerBalances();
    list().flush(aPage([]));

    expect(await screen.findByText('You have not asked for any leave yet.')).toBeVisible();
  });

  it('UI-14: shows the error with Retry, and Retry loads again', async () => {
    const { answerBalances, list, user } = await setup();
    answerBalances();
    list().flush(null, { status: 0, statusText: 'Unknown Error' });

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Cannot reach the server');

    await user.click(within(alert).getByRole('button', { name: 'Retry' }));
    list().flush(aPage([aRequest()]));
    expect(await screen.findByText('Family trip')).toBeVisible();
  });

  it('lists requests, with Cancel only on pending ones', async () => {
    const { answerBalances, list } = await setup();
    answerBalances();
    list().flush(
      aPage([
        aRequest({ id: 'r1', status: 'PENDING', reason: 'Family trip' }),
        aRequest({ id: 'r2', status: 'APPROVED', reason: 'Wedding', start_date: '2026-10-05' }),
      ]),
    );

    const rows = await screen.findAllByRole('row');
    expect(rows).toHaveLength(3); // header + 2
    expect(within(rows[1]).getByText('Pending')).toBeVisible();
    expect(within(rows[1]).getByRole('button', { name: /cancel/i })).toBeVisible();
    expect(within(rows[2]).queryByRole('button', { name: /cancel/i })).toBeNull();
  });

  it('UI-6: choosing a status filter asks the API for that status', async () => {
    const { answerBalances, list, user } = await setup();
    answerBalances();
    list().flush(aPage([aRequest()]));

    await user.click(await screen.findByRole('radio', { name: 'Approved' }));

    expect(list().request.params.get('status')).toBe('APPROVED');
  });

  it('cancelling a request shows it as cancelled', async () => {
    const { answerBalances, list, http, user } = await setup();
    answerBalances();
    list().flush(aPage([aRequest()]));

    await user.click(await screen.findByRole('button', { name: /cancel annual leave/i }));
    http.expectOne('/api/leave-requests/r1').flush(aRequest({ status: 'CANCELLED' }));
    await vi.waitFor(() => answerBalances()); // the days are reloaded right after

    const row = (await screen.findAllByRole('row'))[1];
    expect(await within(row).findByText('Cancelled')).toBeVisible();
    expect(screen.queryByRole('button', { name: /cancel annual leave/i })).toBeNull();
  });

  it('reloads balances and requests when a notification arrives (say "approved")', async () => {
    const { answerBalances, list, view } = await setup();
    answerBalances();
    list().flush(aPage([aRequest({ status: 'PENDING' })]));
    expect(await screen.findByText('Pending')).toBeVisible();

    // What NotificationsStore does when the server pushes one.
    TestBed.inject(NotificationsStore)['receive'](aNotification({ id: 'n9' }));
    view.detectChanges();

    await vi.waitFor(() => answerBalances());
    list().flush(aPage([aRequest({ status: 'APPROVED' })]));
    view.detectChanges();
    await vi.waitFor(() => {
      const row = screen.getAllByRole('row')[1];
      expect(within(row).getByText('Approved')).toBeVisible();
    });
  });
});
