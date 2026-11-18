import { Component, input, output } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';

/**
 * The three states every list has (UI-14): loading, empty and error with Retry.
 * Shows nothing when there is data; the page shows the data itself.
 */
@Component({
  selector: 'app-load-state',
  imports: [MatButtonModule, MatProgressSpinnerModule],
  template: `
    @switch (state()) {
      @case ('loading') {
        <div class="box" role="status">
          <mat-spinner diameter="32" aria-hidden="true" />
          <span>{{ loadingText() }}</span>
        </div>
      }
      @case ('empty') {
        <p class="box">{{ emptyText() }}</p>
      }
      @case ('error') {
        <div class="box" role="alert">
          <span>{{ errorText() || 'Something went wrong.' }}</span>
          <button mat-stroked-button type="button" (click)="retry.emit()">Retry</button>
        </div>
      }
    }
  `,
  styles: `
    .box {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 12px;
      padding: 32px 16px;
      text-align: center;
      color: var(--mat-sys-on-surface-variant);
    }
  `,
})
export class LoadState {
  readonly state = input.required<'loading' | 'empty' | 'error' | 'ready'>();
  readonly loadingText = input('Loading…');
  readonly emptyText = input('Nothing here yet.');
  readonly errorText = input<string | null>(null);
  readonly retry = output<void>();
}
