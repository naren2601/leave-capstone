import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';

import { fakeToken } from '../../../testing/tokens';
import { AuthStore, sessionFromToken } from './auth-store';

describe('AuthStore', () => {
  let store: AuthStore;
  let http: HttpTestingController;

  beforeEach(() => {
    sessionStorage.clear();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    store = TestBed.inject(AuthStore);
    http = TestBed.inject(HttpTestingController);
  });

  async function login(role: 'employee' | 'manager') {
    const done = store.login('ravi@leavedesk.dev', 'demo1234');
    const request = http.expectOne('/api/auth/login');
    expect(request.request.body).toEqual({ email: 'ravi@leavedesk.dev', password: 'demo1234' });
    request.flush({ access_token: fakeToken(role), token_type: 'bearer', expires_in: 1800 });
    await done;
  }

  it('signs in, reads who it is from the token and keeps it for this tab', async () => {
    await login('manager');

    expect(store.isLoggedIn()).toBe(true);
    expect(store.isManager()).toBe(true);
    expect(store.user()?.employeeId).toBe('m1');
    expect(sessionStorage.getItem('leavedesk.session')).toContain('m1');
  });

  it('an employee is not a manager', async () => {
    await login('employee');

    expect(store.isManager()).toBe(false);
  });

  it('logging out forgets the token and goes to the login page', async () => {
    await login('employee');
    const navigate = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);

    store.logout('expired');

    expect(store.isLoggedIn()).toBe(false);
    expect(sessionStorage.getItem('leavedesk.session')).toBeNull();
    expect(navigate).toHaveBeenCalledWith(['/login'], { queryParams: { reason: 'expired' } });
  });

  it('an expired session does not count as signed in', async () => {
    await login('employee');

    expect(store.hasValidSession(Date.now() + 31 * 60 * 1000)).toBe(false);
    expect(store.isLoggedIn()).toBe(false);
  });

  it('rejects tokens it cannot read', () => {
    expect(sessionFromToken('not-a-token', 'a@b.c')).toBeNull();
    expect(sessionFromToken(fakeToken('employee').replace(/\..*\./, '.e30.'), 'a@b.c')).toBeNull();
  });
});
