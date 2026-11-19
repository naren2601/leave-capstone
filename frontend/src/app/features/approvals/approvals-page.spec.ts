import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';

import { aPage, aRequest } from '../../../testing/leave-data';
import { startSignedInAs } from '../../../testing/sign-in';
import { ApprovalsPage } from './approvals-page';

async function setup(requests = [aRequest({ id: 'a', employee_id: 'e1', reason: 'Family trip' })]) {
  sessionStorage.clear();
  startSignedInAs('manager');
  const user = userEvent.setup();
  await render(ApprovalsPage, {
    providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
  });
  const http = TestBed.inject(HttpTestingController);
  http.expectOne('/api/team').flush([{ id: 'e1', name: 'Asha Rao', manager_id: 'm1' }]);
  http.expectOne((r) => r.url === '/api/leave-requests').flush(aPage(requests));
  return { user, http };
}

describe('ApprovalsPage', () => {
  it("shows each waiting request with the employee's name", async () => {
    await setup();

    expect(await screen.findByText('Asha Rao')).toBeVisible();
    expect(screen.getByText('1 request is waiting for you.')).toBeVisible();
  });

  it('says so when nothing is waiting', async () => {
    await setup([]);

    expect(await screen.findByText(/Nothing is waiting for you/)).toBeVisible();
  });

  it('Approve asks first, then the row disappears', async () => {
    const { user, http } = await setup();

    await user.click(await screen.findByRole('button', { name: /approve asha rao/i }));
    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveTextContent('Asha Rao: Annual leave, 3 days, from 2026-11-23.');
    await user.click(within(dialog).getByRole('button', { name: 'Approve' }));

    // Gone before the API has answered (the call below is still waiting).
    await vi.waitFor(() => expect(screen.queryByText('Asha Rao')).toBeNull());
    http.expectOne('/api/leave-requests/a/approve').flush(aRequest({ status: 'APPROVED' }));
    expect(await screen.findByText(/Nothing is waiting for you/)).toBeVisible();
  });

  it('Reject opens the dialog with a reason field', async () => {
    // The reason rules themselves are tested in confirm-dialog.spec.ts.
    const { user } = await setup();

    await user.click(await screen.findByRole('button', { name: /reject asha rao/i }));
    const dialog = await screen.findByRole('dialog');

    expect(within(dialog).getByLabelText('Reason for the employee')).toBeVisible();
    expect(within(dialog).getByRole('button', { name: 'Reject' })).toBeDisabled();
  });

  it('cancelling the dialog changes nothing', async () => {
    const { user, http } = await setup();

    await user.click(await screen.findByRole('button', { name: /approve asha rao/i }));
    await user.click(
      within(await screen.findByRole('dialog')).getByRole('button', { name: 'Cancel' }),
    );

    expect(screen.getByText('Asha Rao')).toBeVisible();
    http.expectNone('/api/leave-requests/a/approve');
  });
});
