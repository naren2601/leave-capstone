import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';

import { App } from './app';
import { routes } from './app.routes';

describe('App shell', () => {
  it('shows the LeaveDesk toolbar and says when the API is connected', async () => {
    await render(App, {
      providers: [provideRouter(routes), provideHttpClient(), provideHttpClientTesting()],
      initialRoute: '/',
    });

    expect(screen.getByRole('banner')).toHaveTextContent('LeaveDesk');
    const http = TestBed.inject(HttpTestingController);
    (await vi.waitFor(() => http.expectOne('/api/health'))).flush({ status: 'ok' });
    expect(await screen.findByText('connected')).toBeVisible();
  });

  it('says when the API cannot be reached', async () => {
    await render(App, {
      providers: [provideRouter(routes), provideHttpClient(), provideHttpClientTesting()],
      initialRoute: '/',
    });

    const http = TestBed.inject(HttpTestingController);
    (await vi.waitFor(() => http.expectOne('/api/health'))).flush('down', {
      status: 503,
      statusText: 'Service Unavailable',
    });
    expect(await screen.findByText('not reachable')).toBeVisible();
  });
});
