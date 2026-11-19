import { Component, computed, input } from '@angular/core';

import { LeaveStatus } from '../core/models';

const LABELS: Record<LeaveStatus, string> = {
  PENDING: 'Pending',
  APPROVED: 'Approved',
  REJECTED: 'Rejected',
  CANCELLED: 'Cancelled',
};

/** A coloured label for a request's status. The word is always shown, never colour alone. */
@Component({
  selector: 'app-status-chip',
  template: `<span class="chip" [class]="'chip ' + status().toLowerCase()">{{ label() }}</span>`,
  styles: `
    .chip {
      display: inline-block;
      padding: 2px 10px;
      border-radius: 12px;
      font: var(--mat-sys-label-medium);
      white-space: nowrap;
    }
    .pending {
      background: var(--mat-sys-secondary-container);
      color: var(--mat-sys-on-secondary-container);
    }
    .approved {
      background: #c8e6c9;
      color: #1b5e20;
    }
    .rejected {
      background: var(--mat-sys-error-container);
      color: var(--mat-sys-on-error-container);
    }
    .cancelled {
      background: var(--mat-sys-surface-container-high);
      color: var(--mat-sys-on-surface-variant);
    }
  `,
})
export class StatusChip {
  readonly status = input.required<LeaveStatus>();
  protected readonly label = computed(() => LABELS[this.status()]);
}
