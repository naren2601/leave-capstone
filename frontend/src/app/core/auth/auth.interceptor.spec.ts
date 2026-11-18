import {
  HttpClient,
  HttpErrorResponse,
  provideHttpClient,
  withInterceptors,
} from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';

import { fakeToken } from '../../../testing/tokens';
import { authInterceptor, unauthorizedInterceptor } from './auth.interceptor';
import { AuthStore } from './auth-store';

describe('auth interceptors', () => {
  let client: HttpClient;
  let http: HttpTestingController;
  let auth: AuthStore;

  beforeEach(async () => {
    sessionStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([authInterceptor, unauthorizedInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    });
    client = TestBed.inject(HttpClient);
    http = TestBed.inject(HttpTestingController);
    auth = TestBed.inject(AuthStore);
    const signedIn = auth.login('asha@leavedesk.dev', 'demo1234');
    http.expectOne('/api/auth/login').flush({ access_token: fakeToken('employee') });
    await signedIn;
  });

  it('UI-1: sends the token with every API call', () => {
    client.get('/api/leave-requests').subscribe();

    const header = http.expectOne('/api/leave-requests').request.headers.get('Authorization');
    expect(header).toBe(`Bearer ${auth.token()}`);
  });

  it('never sends the token to other websites', () => {
    client.get('https://example.com/data').subscribe();

    expect(http.expectOne('https://example.com/data').request.headers.has('Authorization')).toBe(
      false,
    );
  });

  it('UI-4: a 401 signs the user out and goes to the login page', async () => {
    const navigate = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    const call = firstValueFrom(client.get('/api/leave-requests'));

    http
      .expectOne('/api/leave-requests')
      .flush({ error: { code: 'UNAUTHORIZED' } }, { status: 401, statusText: 'Unauthorized' });

    await expect(call).rejects.toBeInstanceOf(HttpErrorResponse);
    expect(auth.isLoggedIn()).toBe(false);
    expect(navigate).toHaveBeenCalledWith(['/login'], { queryParams: { reason: 'expired' } });
  });

  it('other errors leave the user signed in', async () => {
    const call = firstValueFrom(client.get('/api/leave-requests'));

    http.expectOne('/api/leave-requests').flush(null, { status: 403, statusText: 'Forbidden' });

    await expect(call).rejects.toBeInstanceOf(HttpErrorResponse);
    expect(auth.isLoggedIn()).toBe(true);
  });
});
