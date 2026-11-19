import { Component, effect, inject, untracked } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatToolbarModule } from '@angular/material/toolbar';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { AuthStore } from './core/auth/auth-store';
import { NotificationBell } from './features/notifications/notification-bell';
import { NotificationsStore } from './features/notifications/notifications-store';

@Component({
  selector: 'app-root',
  imports: [
    RouterOutlet,
    RouterLink,
    RouterLinkActive,
    MatToolbarModule,
    MatButtonModule,
    NotificationBell,
  ],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App {
  protected readonly auth = inject(AuthStore);
  private readonly notifications = inject(NotificationsStore);

  constructor() {
    // effect() runs now and again whenever a signal it reads changes: signing in
    // connects the live notification line, signing out closes it.
    effect(() => {
      const signedIn = this.auth.isLoggedIn(); // the only signal this effect follows
      untracked(() => (signedIn ? this.notifications.connect() : this.notifications.disconnect()));
    });
  }
}
