import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { MatSnackBar } from '@angular/material/snack-bar';
import { Subscription, firstValueFrom } from 'rxjs';

import { API_URL } from '../../core/api';
import { errorMessage } from '../../core/api-errors';
import { AuthStore } from '../../core/auth/auth-store';
import { AppNotification, Page } from '../../core/models';
import { LoadStatus } from '../leave/leave-store';
import { NotificationStream } from './notification-stream';

/**
 * The signed-in user's notifications. One for the whole app (providedIn: 'root'), because
 * the bell is in the toolbar on every page.
 */
@Injectable({ providedIn: 'root' })
export class NotificationsStore {
  private readonly http = inject(HttpClient);
  private readonly api = inject(API_URL);
  private readonly auth = inject(AuthStore);
  private readonly stream = inject(NotificationStream);
  private readonly snackBar = inject(MatSnackBar);

  readonly notifications = signal<AppNotification[]>([]);
  readonly status = signal<LoadStatus>('idle');
  readonly error = signal<string | null>(null);
  /** The newest message, for screen readers (an aria-live region reads it out). */
  readonly announcement = signal('');
  /** The last notification pushed live. Pages watch it to reload their data. */
  readonly lastReceived = signal<AppNotification | null>(null);

  /** The badge number (UI-12, UI-13). */
  readonly unreadCount = computed(() => this.notifications().filter((n) => !n.read).length);

  private live: Subscription | null = null;

  /** After sign-in: load what is already there, then listen for new ones. */
  connect(): void {
    const token = this.auth.token();
    if (!token || this.live) {
      return; // signed out, or already listening
    }
    void this.load();
    this.live = this.stream.connect(token).subscribe({
      next: (notification) => this.receive(notification),
      error: () => (this.live = null), // the line closed; the next sign-in reconnects
    });
  }

  /** On sign-out: stop listening and forget everything. */
  disconnect(): void {
    this.live?.unsubscribe(); // closes the EventSource
    this.live = null;
    this.notifications.set([]);
    this.status.set('idle');
  }

  async load(): Promise<void> {
    this.status.set('loading');
    this.error.set(null);
    try {
      const params = new HttpParams().set('limit', 20);
      const page = await firstValueFrom(
        this.http.get<Page<AppNotification>>(`${this.api}/notifications`, { params }),
      );
      this.notifications.set(page.items);
      this.status.set('success');
    } catch (error) {
      this.error.set(errorMessage(error));
      this.status.set('error');
    }
  }

  /** Marks all read on screen at once, then tells the API. Reloads if the API fails. */
  async markAllRead(): Promise<void> {
    if (this.unreadCount() === 0) {
      return;
    }
    this.notifications.update((list) => list.map((n) => ({ ...n, read: true })));
    try {
      await firstValueFrom(this.http.post(`${this.api}/notifications/read-all`, null));
    } catch {
      void this.load(); // show what the server really has
    }
  }

  /** A new notification arrived on the live line (UI-12). */
  private receive(notification: AppNotification): void {
    if (this.notifications().some((n) => n.id === notification.id)) {
      return; // already have it (it can also come with load())
    }
    this.notifications.update((list) => [notification, ...list]);
    this.announcement.set(notification.message);
    this.lastReceived.set(notification);
    this.snackBar.open(notification.message, 'OK', { duration: 6000 });
  }
}
