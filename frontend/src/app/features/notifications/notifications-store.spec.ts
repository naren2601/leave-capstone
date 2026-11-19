import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { MatSnackBar } from '@angular/material/snack-bar';
import { provideRouter } from '@angular/router';

import {
  aNotification,
  FakeEventSource,
  provideFakeEventSource,
} from '../../../testing/fake-event-source';
import { startSignedInAs } from '../../../testing/sign-in';
import { NotificationsStore } from './notifications-store';

describe('NotificationsStore', () => {
  let store: NotificationsStore;
  let http: HttpTestingController;
  let snackBar: ReturnType<typeof vi.spyOn>;

  beforeEach(async () => {
    sessionStorage.clear();
    startSignedInAs('employee');
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        provideFakeEventSource(),
      ],
    });
    store = TestBed.inject(NotificationsStore);
    http = TestBed.inject(HttpTestingController);
    snackBar = vi.spyOn(TestBed.inject(MatSnackBar), 'open');

    store.connect();
    http
      .expectOne((r) => r.url === '/api/notifications')
      .flush({
        items: [aNotification({ id: 'old', read: true, message: 'Leave requested.' })],
        total: 1,
        limit: 20,
        offset: 0,
        next_cursor: null,
      });
    await vi.waitFor(() => expect(store.status()).toBe('success'));
  });

  it('opens the live line with the token in the URL (EventSource cannot send headers)', () => {
    expect(FakeEventSource.latest?.url).toMatch(/^\/api\/notifications\/stream\?access_token=ey/);
    expect(store.unreadCount()).toBe(0);
  });

  it('UI-12: a pushed notification is added on top, counted as unread and shown', () => {
    FakeEventSource.latest!.push(aNotification({ id: 'n1' }));

    expect(store.notifications().map((n) => n.id)).toEqual(['n1', 'old']);
    expect(store.unreadCount()).toBe(1);
    expect(snackBar).toHaveBeenCalledWith('Ravi Kumar approved your leave.', 'OK', {
      duration: 6000,
    });
    expect(store.announcement()).toBe('Ravi Kumar approved your leave.');
  });

  it('the same notification twice is only counted once', () => {
    FakeEventSource.latest!.push(aNotification({ id: 'n1' }));
    FakeEventSource.latest!.push(aNotification({ id: 'n1' }));

    expect(store.unreadCount()).toBe(1);
  });

  it('UI-13: marking all read clears the count at once and tells the API', async () => {
    FakeEventSource.latest!.push(aNotification({ id: 'n1' }));
    FakeEventSource.latest!.push(aNotification({ id: 'n2' }));

    const done = store.markAllRead();
    expect(store.unreadCount()).toBe(0);
    http.expectOne('/api/notifications/read-all').flush({ updated: 2 });
    await done;
    expect(store.unreadCount()).toBe(0);
  });

  it('if marking read fails, it reloads what the server has', async () => {
    FakeEventSource.latest!.push(aNotification({ id: 'n1' }));

    const done = store.markAllRead();
    http.expectOne('/api/notifications/read-all').flush(null, { status: 500, statusText: 'Error' });
    await done;

    http.expectOne((r) => r.url === '/api/notifications');
  });

  it('disconnecting closes the line and forgets the notifications', () => {
    const line = FakeEventSource.latest!;

    store.disconnect();

    expect(line.closed).toBe(true);
    expect(store.notifications()).toEqual([]);
  });
});
