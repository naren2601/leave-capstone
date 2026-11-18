import { InjectionToken } from '@angular/core';

/**
 * Where the LeaveDesk API lives, as seen from the browser.
 *
 * Always "/api": in development `ng serve` forwards /api to http://127.0.0.1:8000
 * (proxy.conf.json), and in Docker the web server does the same. The browser only ever
 * talks to one address, so there are no CORS problems.
 */
export const API_URL = new InjectionToken<string>('API_URL', { factory: () => '/api' });
