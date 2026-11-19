import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';

import { aNotification, provideFakeEventSource } from '../../../testing/fake-event-source';
import { NotificationBell } from './notification-bell';
import { NotificationsStore } from './notifications-store';

async function setup() {
  sessionStorage.clear();
  const view = await render(NotificationBell, {
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      provideRouter([]),
      provideFakeEventSource(),
    ],
  });
  const store = TestBed.inject(NotificationsStore);
  store.notifications.set([
    aNotification({ id: 'n2', message: 'Ravi Kumar approved your leave.' }),
    aNotification({ id: 'n1', message: 'Ravi Kumar rejected your leave.' }),
    aNotification({ id: 'n0', message: 'Leave requested.', read: true }),
  ]);
  store.status.set('success');
  view.detectChanges();
  return { user: userEvent.setup(), http: TestBed.inject(HttpTestingController), store };
}

describe('NotificationBell', () => {
  it('UI-12: the bell says how many are unread, for eyes and screen readers', async () => {
    await setup();

    const bell = screen.getByRole('button', { name: 'Notifications, 2 unread' });
    expect(bell).toHaveTextContent('2'); // the badge
  });

  it('UI-13: opening the panel lists them and marks them read', async () => {
    const { user, http } = await setup();

    await user.click(screen.getByRole('button', { name: /notifications/i }));

    expect(await screen.findByText('Ravi Kumar approved your leave.')).toBeVisible();
    expect(screen.getByText('Leave requested.')).toBeVisible();
    http.expectOne('/api/notifications/read-all').flush({ updated: 2 });
    expect(
      await screen.findByRole('button', { name: 'Notifications, none unread' }),
    ).toBeInTheDocument();
  });

  it('an empty list says so', async () => {
    const { user, store } = await setup();
    store.notifications.set([]);

    await user.click(screen.getByRole('button', { name: /notifications/i }));

    expect(await screen.findByText('No notifications')).toBeVisible();
  });
});
