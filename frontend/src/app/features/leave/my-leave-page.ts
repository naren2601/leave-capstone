import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, computed, effect, inject, OnInit, untracked } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatCardModule } from '@angular/material/card';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTableModule } from '@angular/material/table';
import { RouterLink } from '@angular/router';

import { LEAVE_TYPE_NAMES, LeaveRequest, LeaveStatus, LeaveType } from '../../core/models';
import { LoadState } from '../../shared/load-state';
import { NotificationsStore } from '../notifications/notifications-store';
import { StatusChip } from '../../shared/status-chip';
import { LeaveStore } from './leave-store';

@Component({
  selector: 'app-my-leave-page',
  imports: [
    DatePipe,
    DecimalPipe,
    MatButtonModule,
    MatButtonToggleModule,
    MatCardModule,
    MatPaginatorModule,
    MatTableModule,
    RouterLink,
    LoadState,
    StatusChip,
  ],
  providers: [LeaveStore],
  templateUrl: './my-leave-page.html',
  styleUrl: './my-leave-page.scss',
})
export class MyLeavePage implements OnInit {
  protected readonly store = inject(LeaveStore);
  private readonly snackBar = inject(MatSnackBar);

  protected readonly typeNames = LEAVE_TYPE_NAMES;
  protected readonly columns = ['type', 'dates', 'days', 'status', 'reason', 'actions'];
  protected readonly filters: { value: LeaveStatus | null; label: string }[] = [
    { value: null, label: 'All' },
    { value: 'PENDING', label: 'Pending' },
    { value: 'APPROVED', label: 'Approved' },
    { value: 'REJECTED', label: 'Rejected' },
    { value: 'CANCELLED', label: 'Cancelled' },
  ];

  /** Which of the three list states to show, or 'ready' to show the table. */
  protected readonly listState = computed(() => {
    const status = this.store.listStatus();
    if (status === 'error') return 'error';
    if (status === 'loading' && this.store.requests().length === 0) return 'loading';
    if (status === 'success' && this.store.requests().length === 0) return 'empty';
    return 'ready';
  });

  protected readonly emptyText = computed(() =>
    this.store.statusFilter()
      ? 'No requests with this status.'
      : 'You have not asked for any leave yet.',
  );

  /** Table rows arrive untyped from mat-table, so look names up through a typed method. */
  protected typeName(type: LeaveType): string {
    return LEAVE_TYPE_NAMES[type];
  }

  constructor() {
    // When a notification arrives (say "approved"), reload the balances and the list, so
    // the page matches the message without the user pressing reload.
    const notifications = inject(NotificationsStore);
    let seen = notifications.lastReceived(); // ignore one that arrived before this page
    effect(() => {
      const latest = notifications.lastReceived();
      if (latest && latest !== seen) {
        seen = latest;
        untracked(() => this.store.load());
      }
    });
  }

  ngOnInit(): void {
    this.store.load();
  }

  protected onPage(event: PageEvent): void {
    this.store.setPage(event.pageIndex);
  }

  protected async cancel(request: LeaveRequest): Promise<void> {
    const problem = await this.store.cancel(request);
    this.snackBar.open(problem ?? 'Request cancelled. The days are available again.', 'OK', {
      duration: 5000,
    });
  }
}
