import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';

import { ConfirmData, ConfirmDialog } from './confirm-dialog';

async function setup(data: Partial<ConfirmData> = {}) {
  const close = vi.fn();
  const user = userEvent.setup();
  await render(ConfirmDialog, {
    providers: [
      {
        provide: MAT_DIALOG_DATA,
        useValue: {
          title: 'Reject?',
          message: 'Asha Rao: 3 days',
          confirmLabel: 'Reject',
          ...data,
        },
      },
      { provide: MatDialogRef, useValue: { close } },
    ],
  });
  return { user, close };
}

describe('ConfirmDialog', () => {
  it('a reason is required, and spaces alone do not count', async () => {
    const { user, close } = await setup({ reasonLabel: 'Reason for the employee' });
    const confirm = screen.getByRole('button', { name: 'Reject' });
    expect(confirm).toBeDisabled();

    await user.type(screen.getByLabelText('Reason for the employee'), '   ');
    expect(confirm).toBeDisabled();

    await user.type(screen.getByLabelText('Reason for the employee'), 'Team is short');
    await vi.waitFor(() => expect(confirm).toBeEnabled());
    await user.click(confirm);

    expect(close).toHaveBeenCalledWith({ reason: 'Team is short' });
  });

  it('without a reason field, confirm works straight away', async () => {
    const { user, close } = await setup({ confirmLabel: 'Approve' });

    await user.click(screen.getByRole('button', { name: 'Approve' }));

    expect(close).toHaveBeenCalledWith({ reason: '' });
    expect(screen.getByText('Asha Rao: 3 days')).toBeVisible();
  });
});
