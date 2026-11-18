import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';

import { fakeToken } from '../testing/tokens';
import { App } from './app';
import { AuthStore } from './core/auth/auth-store';

async function renderSignedInAs(role: 'employee' | 'manager' | null) {
  sessionStorage.clear();
  const view = await render(App, {
    providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
  });
  if (role) {
    const done = TestBed.inject(AuthStore).login(`${role}@leavedesk.dev`, 'demo1234');
    TestBed.inject(HttpTestingController)
      .expectOne('/api/auth/login')
      .flush({ access_token: fakeToken(role) });
    await done;
    view.detectChanges();
  }
}

describe('App toolbar', () => {
  it('shows only the app name when signed out', async () => {
    await renderSignedInAs(null);

    expect(screen.getByRole('banner')).toHaveTextContent('LeaveDesk');
    expect(screen.queryByRole('button', { name: 'Log out' })).toBeNull();
  });

  it('shows My leave, the email and Log out to an employee, but not Approvals', async () => {
    await renderSignedInAs('employee');

    expect(screen.getByRole('link', { name: 'My leave' })).toBeVisible();
    expect(screen.queryByRole('link', { name: 'Approvals' })).toBeNull();
    expect(screen.getByText('employee@leavedesk.dev')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Log out' })).toBeVisible();
  });

  it('shows Approvals to a manager', async () => {
    await renderSignedInAs('manager');

    expect(screen.getByRole('link', { name: 'Approvals' })).toBeVisible();
  });
});
