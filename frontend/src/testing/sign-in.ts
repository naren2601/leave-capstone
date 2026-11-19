import { HttpTestingController } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { AuthStore } from '../app/core/auth/auth-store';
import { fakeToken } from './tokens';

/** Signs the test user in through the real AuthStore, answering the login call. */
export async function signInAs(role: 'employee' | 'manager'): Promise<void> {
  const done = TestBed.inject(AuthStore).login(`${role}@leavedesk.dev`, 'demo1234');
  TestBed.inject(HttpTestingController)
    .expectOne('/api/auth/login')
    .flush({ access_token: fakeToken(role) });
  await done;
}

/**
 * Puts a signed-in session in sessionStorage BEFORE the app starts, exactly as a page
 * reload would find it. Use this when the test renders a component afterwards.
 */
export function startSignedInAs(role: 'employee' | 'manager'): void {
  const sub = role === 'manager' ? 'm1' : 'e1';
  sessionStorage.setItem(
    'leavedesk.session',
    JSON.stringify({
      token: fakeToken(role),
      employeeId: sub,
      role,
      email: `${role}@leavedesk.dev`,
      expiresAt: Date.now() + 30 * 60 * 1000,
    }),
  );
}
