import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, computed, inject, OnInit } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTableModule } from '@angular/material/table';
import { firstValueFrom } from 'rxjs';

import { LEAVE_TYPE_NAMES, LeaveRequest, LeaveType } from '../../core/models';
import { ConfirmData, ConfirmDialog, ConfirmResult } from '../../shared/confirm-dialog';
import { LoadState } from '../../shared/load-state';
import { ApprovalsStore } from './approvals-store';

/** Managers only (managerGuard) and lazy-loaded: employees never download this code. */
@Component({
  selector: 'app-approvals-page',
  imports: [DatePipe, DecimalPipe, MatButtonModule, MatTableModule, LoadState],
  providers: [ApprovalsStore],
  templateUrl: './approvals-page.html',
  styleUrl: './approvals-page.scss',
})
export class ApprovalsPage implements OnInit {
  protected readonly store = inject(ApprovalsStore);
  private readonly dialog = inject(MatDialog);
  private readonly snackBar = inject(MatSnackBar);

  protected readonly columns = ['employee', 'type', 'dates', 'days', 'reason', 'actions'];

  protected readonly state = computed(() => {
    const status = this.store.status();
    if (status === 'error') return 'error';
    if (status === 'loading' || status === 'idle') return 'loading';
    return this.store.count() === 0 ? 'empty' : 'ready';
  });

  ngOnInit(): void {
    void this.store.load();
  }

  protected typeName(type: LeaveType): string {
    return LEAVE_TYPE_NAMES[type];
  }

  protected describe(request: LeaveRequest): string {
    const days = request.days === 1 ? '1 day' : `${request.days} days`;
    return `${this.store.nameOf(request.employee_id)}: ${this.typeName(request.leave_type)} leave, ${days}, from ${request.start_date}.`;
  }

  protected async approve(request: LeaveRequest): Promise<void> {
    const ok = await this.ask({
      title: 'Approve this leave?',
      message: this.describe(request),
      confirmLabel: 'Approve',
    });
    if (ok) {
      this.report(await this.store.approve(request), 'Approved. The employee has been told.');
    }
  }

  protected async reject(request: LeaveRequest): Promise<void> {
    const ok = await this.ask({
      title: 'Reject this leave?',
      message: this.describe(request),
      confirmLabel: 'Reject',
      reasonLabel: 'Reason for the employee',
    });
    if (ok) {
      this.report(
        await this.store.reject(request, ok.reason),
        'Rejected. The employee has been told.',
      );
    }
  }

  private ask(data: ConfirmData): Promise<ConfirmResult | undefined> {
    const ref = this.dialog.open<ConfirmDialog, ConfirmData, ConfirmResult>(ConfirmDialog, {
      data,
      width: '440px',
      maxWidth: '95vw',
    });
    return firstValueFrom(ref.afterClosed());
  }

  private report(problem: string | null, success: string): void {
    this.snackBar.open(problem ? `Not saved: ${problem}` : success, 'OK', { duration: 6000 });
  }
}
