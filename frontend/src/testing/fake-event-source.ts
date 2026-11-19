import { AppNotification } from '../app/core/models';
import { EVENT_SOURCE } from '../app/features/notifications/notification-stream';

/** Stands in for the browser's EventSource, so a test can push notifications itself. */
export class FakeEventSource {
  static latest: FakeEventSource | null = null;

  readyState = 1; // OPEN
  onerror: (() => void) | null = null;
  private readonly listeners: ((event: { data: string }) => void)[] = [];

  constructor(readonly url: string) {
    FakeEventSource.latest = this;
  }

  addEventListener(type: string, listener: (event: { data: string }) => void): void {
    if (type === 'notification') this.listeners.push(listener);
  }

  /** What the server would push: "event: notification" with this JSON. */
  push(notification: AppNotification): void {
    this.listeners.forEach((listener) => listener({ data: JSON.stringify(notification) }));
  }

  close(): void {
    this.readyState = 2; // CLOSED
  }

  get closed(): boolean {
    return this.readyState === 2;
  }
}

export function provideFakeEventSource() {
  FakeEventSource.latest = null;
  return { provide: EVENT_SOURCE, useValue: (url: string) => new FakeEventSource(url) };
}

export function aNotification(overrides: Partial<AppNotification> = {}): AppNotification {
  return {
    id: 'n1',
    recipient: 'e1',
    event: 'APPROVED',
    message: 'Ravi Kumar approved your leave.',
    read: false,
    created_at: '2026-11-19T10:00:00+05:30',
    ...overrides,
  };
}
