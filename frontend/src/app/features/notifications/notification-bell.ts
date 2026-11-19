import { DatePipe } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { MatBadgeModule } from '@angular/material/badge';
import { MatButtonModule } from '@angular/material/button';
import { MatMenuModule } from '@angular/material/menu';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';

import { NotificationsStore } from './notifications-store';

/**
 * The toolbar bell: a badge with the unread count, and a panel listing notifications.
 * Opening the panel marks everything read (UI-13); the ones that were unread stay bold
 * while the panel is open, so the user can still see which are new.
 */
@Component({
  selector: 'app-notification-bell',
  imports: [DatePipe, MatBadgeModule, MatButtonModule, MatMenuModule, MatProgressSpinnerModule],
  templateUrl: './notification-bell.html',
  styleUrl: './notification-bell.scss',
})
export class NotificationBell {
  protected readonly store = inject(NotificationsStore);

  /** Ids that were unread when the panel opened. */
  protected readonly newIds = signal<ReadonlySet<string>>(new Set());

  protected readonly label = computed(() => {
    const count = this.store.unreadCount();
    return count === 0 ? 'Notifications, none unread' : `Notifications, ${count} unread`;
  });

  protected onOpened(): void {
    this.newIds.set(
      new Set(
        this.store
          .notifications()
          .filter((n) => !n.read)
          .map((n) => n.id),
      ),
    );
    void this.store.markAllRead();
  }
}
