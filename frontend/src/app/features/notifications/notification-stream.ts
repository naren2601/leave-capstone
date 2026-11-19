import { Injectable, InjectionToken, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { API_URL } from '../../core/api';
import { AppNotification } from '../../core/models';

/** Makes the EventSource. A token, so tests can hand in a fake one. */
export const EVENT_SOURCE = new InjectionToken<(url: string) => EventSource>('EVENT_SOURCE', {
  factory: () => (url: string) => new EventSource(url),
});

/**
 * The live line from the API: Server-Sent Events (SSE).
 *
 * The browser opens GET /notifications/stream once and keeps it open; the server pushes
 * an "event: notification" for each new one. EventSource also reconnects by itself if
 * the line drops.
 *
 * EventSource cannot send an Authorization header, so the token goes in the URL. The
 * API accepts ?access_token= on this one route only.
 */
@Injectable({ providedIn: 'root' })
export class NotificationStream {
  private readonly api = inject(API_URL);
  private readonly createEventSource = inject(EVENT_SOURCE);

  /** Each pushed notification. Unsubscribing closes the line. */
  connect(token: string): Observable<AppNotification> {
    return new Observable<AppNotification>((subscriber) => {
      const url = `${this.api}/notifications/stream?access_token=${encodeURIComponent(token)}`;
      const source = this.createEventSource(url);

      source.addEventListener('notification', (event) => {
        try {
          subscriber.next(JSON.parse((event as MessageEvent<string>).data) as AppNotification);
        } catch {
          // A damaged message: skip it, keep listening.
        }
      });
      source.onerror = () => {
        // CONNECTING: EventSource is retrying by itself. CLOSED: it gave up (for example
        // the token expired), so tell the subscriber.
        if (source.readyState === EventSource.CLOSED) {
          subscriber.error(new Error('The live notification line closed.'));
        }
      };

      return () => source.close(); // runs on unsubscribe
    });
  }
}
