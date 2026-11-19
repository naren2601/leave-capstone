import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';

import { aRequest } from '../../../testing/leave-data';
import { startSignedInAs } from '../../../testing/sign-in';
import { ApplyPage } from './apply-page';

async function setup() {
  sessionStorage.clear();
  startSignedInAs('employee');
  const user = userEvent.setup();
  await render(ApplyPage, {
    providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
  });
  const navigate = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
  const http = TestBed.inject(HttpTestingController);

  async function fill(start: string, end: string, reason = 'Family trip') {
    await user.type(screen.getByLabelText('Start date'), start);
    await user.type(screen.getByLabelText('End date'), end);
    await user.type(screen.getByLabelText('Reason'), reason);
  }
  // findByRole waits until the button says "Submit request" again, not "Sending".
  const submit = async () =>
    user.click(await screen.findByRole('button', { name: 'Submit request' }));
  return { user, http, navigate, fill, submit };
}

describe('ApplyPage', () => {
  it('sends the request with day-first dates and an Idempotency-Key, then goes to My leave', async () => {
    const { http, navigate, fill, submit } = await setup();

    await fill('23/11/2026', '25/11/2026');
    await submit();

    const call = http.expectOne('/api/leave-requests');
    expect(call.request.body).toEqual({
      leave_type: 'ANNUAL',
      start_date: '2026-11-23',
      end_date: '2026-11-25',
      day_part: 'FULL',
      reason: 'Family trip',
    });
    expect(call.request.headers.get('Idempotency-Key')).toMatch(/^[0-9a-f-]{36}$/);
    call.flush(aRequest(), { status: 201, statusText: 'Created' });
    await vi.waitFor(() => expect(navigate).toHaveBeenCalledWith('/leave'));
  });

  it('UI-7: an end date before the start date shows an error and sends nothing', async () => {
    const { http, fill, submit } = await setup();

    await fill('25/11/2026', '23/11/2026');
    await submit();

    expect(await screen.findByText('The end date cannot be before the start date.')).toBeVisible();
    http.expectNone('/api/leave-requests');
  });

  it('submitting an empty form shows what is missing and sends nothing', async () => {
    const { http, submit } = await setup();

    await submit();

    expect(await screen.findByText('Choose a start date.')).toBeVisible();
    expect(screen.getByText('Choose an end date.')).toBeVisible();
    expect(screen.getByText('Give a short reason.')).toBeVisible();
    http.expectNone('/api/leave-requests');
  });

  it("UI-8: an overlap (409) shows the API's message above Submit and keeps the form", async () => {
    const { http, navigate, fill, submit } = await setup();

    await fill('23/11/2026', '25/11/2026');
    await submit();
    http.expectOne('/api/leave-requests').flush(
      {
        error: {
          code: 'OVERLAPPING_LEAVE',
          message: 'these dates overlap request LR-1 (2026-11-24 to 2026-11-24, PENDING)',
          details: [],
        },
      },
      { status: 409, statusText: 'Conflict' },
    );

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('These dates overlap another request');
    expect(alert).toHaveTextContent('These dates overlap request LR-1');
    expect(screen.getByLabelText('Reason')).toHaveValue('Family trip'); // nothing lost
    expect(navigate).not.toHaveBeenCalled();
  });

  it('a retry of the same answers reuses the key; changing the form makes a new one', async () => {
    const { user, http, fill, submit } = await setup();
    await fill('23/11/2026', '25/11/2026');

    await submit();
    const first = http.expectOne('/api/leave-requests');
    first.flush(null, { status: 0, statusText: 'Unknown Error' }); // the network dropped
    await submit();
    const retry = http.expectOne('/api/leave-requests');

    expect(retry.request.headers.get('Idempotency-Key')).toBe(
      first.request.headers.get('Idempotency-Key'),
    );
    retry.flush(null, { status: 0, statusText: 'Unknown Error' });

    await user.type(screen.getByLabelText('Reason'), ' to Mysore');
    await submit();
    expect(http.expectOne('/api/leave-requests').request.headers.get('Idempotency-Key')).not.toBe(
      first.request.headers.get('Idempotency-Key'),
    );
  });
});
