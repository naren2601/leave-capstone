import { httpResource } from '@angular/common/http';
import { Component, computed, inject } from '@angular/core';
import { MatCardModule } from '@angular/material/card';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';

import { API_URL } from '../../core/api';

/**
 * Step 2 check: can the browser reach the API? Replaced by the login page in step 3.
 *
 * httpResource() turns a GET request into signals: value(), isLoading() and error().
 */
@Component({
  selector: 'app-status-page',
  imports: [MatCardModule, MatProgressSpinnerModule],
  template: `
    <mat-card appearance="outlined">
      <mat-card-header>
        <mat-card-title>LeaveDesk web app</mat-card-title>
        <mat-card-subtitle>Day 4 is under construction</mat-card-subtitle>
      </mat-card-header>
      <mat-card-content>
        <p aria-live="polite">
          @if (health.isLoading()) {
            <mat-spinner diameter="20" aria-label="Checking the API" />
          } @else {
            API status: <strong>{{ status() }}</strong>
          }
        </p>
      </mat-card-content>
    </mat-card>
  `,
})
export class StatusPage {
  private readonly api = inject(API_URL);
  protected readonly health = httpResource<{ status: string }>(() => `${this.api}/health`);
  protected readonly status = computed(() =>
    this.health.error()
      ? 'not reachable'
      : this.health.value()?.status === 'ok'
        ? 'connected'
        : '…',
  );
}
