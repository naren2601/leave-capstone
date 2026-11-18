import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';

import { fakeToken } from '../../../testing/tokens';
import { AuthStore } from './auth-store';
import { authGuard, guestGuard, managerGuard } from './guards';

@Component({ template: 'page' })
class Page {}

describe('route guards', () => {
  beforeEach(() => {
    sessionStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([
          { path: 'login', component: Page, canActivate: [guestGuard] },
          {
            path: '',
            canActivate: [authGuard],
            children: [
              { path: 'leave', component: Page },
              { path: 'approvals', component: Page, canActivate: [managerGuard] },
            ],
          },
        ]),
      ],
    });
  });

  async function signInAs(role: 'employee' | 'manager') {
    const auth = TestBed.inject(AuthStore);
    const done = auth.login('someone@leavedesk.dev', 'demo1234');
    TestBed.inject(HttpTestingController)
      .expectOne('/api/auth/login')
      .flush({ access_token: fakeToken(role) });
    await done;
  }

  async function visit(url: string): Promise<string> {
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl(url);
    return TestBed.inject(Router).url;
  }

  it('signed-out users go to login, remembering where they wanted to go', async () => {
    expect(await visit('/approvals')).toBe('/login?returnUrl=%2Fapprovals');
  });

  it('UI-9: an employee who opens /approvals is sent to My leave', async () => {
    await signInAs('employee');

    expect(await visit('/approvals')).toBe('/leave');
  });

  it('a manager can open /approvals', async () => {
    await signInAs('manager');

    expect(await visit('/approvals')).toBe('/approvals');
  });

  it('a signed-in user who opens /login goes to My leave', async () => {
    await signInAs('employee');

    expect(await visit('/login')).toBe('/leave');
  });
});
