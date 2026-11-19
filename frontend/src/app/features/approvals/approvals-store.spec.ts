import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { aPage, aRequest } from '../../../testing/leave-data';
import { startSignedInAs } from '../../../testing/sign-in';
import { ApprovalsStore } from './approvals-store';

const TEAM = [
  { id: 'e1', name: 'Asha Rao', manager_id: 'm1' },
  { id: 'e2', name: 'Kiran Das', manager_id: 'm1' },
];

describe('ApprovalsStore', () => {
  let store: ApprovalsStore;
  let http: HttpTestingController;

  beforeEach(async () => {
    sessionStorage.clear();
    startSignedInAs('manager'); // Ravi, m1
    TestBed.configureTestingModule({
      providers: [
        ApprovalsStore,
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    });
    store = TestBed.inject(ApprovalsStore);
    http = TestBed.inject(HttpTestingController);

    const loaded = store.load();
    http.expectOne('/api/team').flush(TEAM);
    http
      .expectOne((r) => r.url === '/api/leave-requests')
      .flush(
        aPage([
          aRequest({ id: 'a', employee_id: 'e1' }),
          aRequest({ id: 'own', employee_id: 'm1' }), // Ravi's own request
          aRequest({ id: 'b', employee_id: 'e2', version: 3 }),
          aRequest({ id: 'c', employee_id: 'e1' }),
        ]),
      );
    await loaded;
  });

  const ids = () => store.requests().map((r) => r.id);

  it("loads the team's pending requests, not the manager's own, with names", () => {
    expect(ids()).toEqual(['a', 'b', 'c']);
    expect(store.nameOf('e2')).toBe('Kiran Das');
    expect(store.nameOf('x9')).toBe('x9'); // unknown: show the id
  });

  it('UI-10: approving removes the row at once, before the API answers', async () => {
    const done = store.approve(store.requests()[1]);

    expect(ids()).toEqual(['a', 'c']); // already gone
    const call = http.expectOne('/api/leave-requests/b/approve');
    expect(call.request.headers.get('If-Match')).toBe('"3"');
    call.flush(aRequest({ id: 'b', status: 'APPROVED' }));

    expect(await done).toBeNull();
    expect(ids()).toEqual(['a', 'c']); // and stays gone
  });

  it('UI-11: if the API refuses (409), the row comes back in the same place', async () => {
    const done = store.approve(store.requests()[1]);
    expect(ids()).toEqual(['a', 'c']);

    http
      .expectOne('/api/leave-requests/b/approve')
      .flush(
        { error: { code: 'INVALID_TRANSITION', message: 'cannot approve a REJECTED request' } },
        { status: 409, statusText: 'Conflict' },
      );

    expect(await done).toBe('Cannot approve a REJECTED request');
    expect(ids()).toEqual(['a', 'b', 'c']);
  });

  it('rejecting sends the reason, with the same optimistic removal', async () => {
    const done = store.reject(store.requests()[0], 'Team is short that week');

    expect(ids()).toEqual(['b', 'c']);
    const call = http.expectOne('/api/leave-requests/a/reject');
    expect(call.request.body).toEqual({ reason: 'Team is short that week' });
    call.flush(aRequest({ id: 'a', status: 'REJECTED' }));
    expect(await done).toBeNull();
  });
});
