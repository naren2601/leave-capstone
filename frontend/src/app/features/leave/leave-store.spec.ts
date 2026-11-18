import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { aPage, aRequest, BALANCES } from '../../../testing/leave-data';
import { signInAs } from '../../../testing/sign-in';
import { LeaveStore } from './leave-store';

describe('LeaveStore', () => {
  let store: LeaveStore;
  let http: HttpTestingController;

  beforeEach(async () => {
    sessionStorage.clear();
    TestBed.configureTestingModule({
      providers: [LeaveStore, provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    http = TestBed.inject(HttpTestingController);
    await signInAs('employee');
    store = TestBed.inject(LeaveStore);
  });

  const listCall = () => http.expectOne((r) => r.url === '/api/leave-requests');

  it('UI-5: loads my balances and requests; total available is the sum of all types', async () => {
    store.load();
    http.expectOne('/api/employees/e1/balance').flush(BALANCES);
    listCall().flush(aPage([aRequest()]));
    await vi.waitFor(() => expect(store.listStatus()).toBe('success'));

    expect(store.totalAvailable()).toBe(13 + 12 + 5.5);
    expect(store.requests()).toHaveLength(1);
  });

  it('asks only for my own requests, newest first, 10 per page', async () => {
    void store.loadRequests();

    const params = listCall().request.params;
    expect(params.get('employee_id')).toBe('e1');
    expect(params.get('sort')).toBe('-start_date');
    expect(params.get('limit')).toBe('10');
  });

  it('UI-6: a new status filter is sent to the API and goes back to page 1', async () => {
    store.setPage(2);
    expect(listCall().request.params.get('offset')).toBe('20');

    store.setStatusFilter('PENDING');

    const params = listCall().request.params;
    expect(params.get('status')).toBe('PENDING');
    expect(params.get('offset')).toBe('0');
    expect(store.pageIndex()).toBe(0);
  });

  it('cancelling sends the version, updates the row and reloads the balances', async () => {
    store.requests.set([aRequest({ version: 4 })]);

    const done = store.cancel(store.requests()[0]);
    const call = http.expectOne('/api/leave-requests/r1');
    expect(call.request.method).toBe('DELETE');
    expect(call.request.headers.get('If-Match')).toBe('"4"');
    expect(store.cancelling().has('r1')).toBe(true);
    call.flush(aRequest({ status: 'CANCELLED', version: 5 }));

    expect(await done).toBeNull();
    expect(store.requests()[0].status).toBe('CANCELLED');
    expect(store.cancelling().has('r1')).toBe(false);
    http.expectOne('/api/employees/e1/balance');
  });

  it("a failed cancel returns the API's message and reloads the list", async () => {
    store.requests.set([aRequest()]);

    const done = store.cancel(store.requests()[0]);
    http
      .expectOne('/api/leave-requests/r1')
      .flush(
        { error: { code: 'VERSION_CONFLICT', message: 'the request was changed by someone else' } },
        { status: 409, statusText: 'Conflict' },
      );

    expect(await done).toBe('The request was changed by someone else');
    listCall();
  });

  it('a failed list load is an error state with a message', async () => {
    void store.loadRequests();
    listCall().flush(null, { status: 0, statusText: 'Unknown Error' });

    await vi.waitFor(() => expect(store.listStatus()).toBe('error'));
    expect(store.listError()).toBe('Cannot reach the server. Try again.');
  });
});
