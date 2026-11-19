import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { render, screen } from '@testing-library/angular';

import { FakeEventSource, provideFakeEventSource } from '../testing/fake-event-source';
import { fakeToken } from '../testing/tokens';
import { App } from './app';
import { AuthStore } from './core/auth/auth-store';

async function renderSignedInAs(role: 'employee' | 'manager' | null) {
  sessionStorage.clear();
  const view = await render(App, {
    providers: [
      provideRouter([]),
      provideHttpClient(),
      provideHttpClientTesting(),
      provideFakeEventSource(),
    ],
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

  it('signing in opens the live notification line; logging out closes it', async () => {
    await renderSignedInAs('employee');
    await vi.waitFor(() => expect(FakeEventSource.latest).not.toBeNull());
    const line = FakeEventSource.latest!;
    vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true); // no real pages here

    TestBed.inject(AuthStore).logout();

    await vi.waitFor(() => expect(line.closed).toBe(true));
  });
});
