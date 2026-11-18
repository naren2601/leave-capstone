import { Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { errorMessage } from '../../core/api-errors';
import { AuthStore } from '../../core/auth/auth-store';
import { Balance, LeaveRequest, LeaveStatus } from '../../core/models';
import { LeaveApi } from './leave-api';

export type LoadStatus = 'idle' | 'loading' | 'success' | 'error';

/**
 * Everything the My leave page shows, as signals. The page only reads these and
 * calls the methods; it never talks to the API itself.
 *
 * Provided by the page (not the whole app), so it starts fresh on every visit.
 */
@Injectable()
export class LeaveStore {
  private readonly api = inject(LeaveApi);
  private readonly auth = inject(AuthStore);

  readonly pageSize = 10;

  // The list
  readonly requests = signal<LeaveRequest[]>([]);
  readonly total = signal(0);
  readonly statusFilter = signal<LeaveStatus | null>(null);
  readonly pageIndex = signal(0);
  readonly listStatus = signal<LoadStatus>('idle');
  readonly listError = signal<string | null>(null);

  // The balance cards
  readonly balances = signal<Balance[]>([]);
  readonly balanceStatus = signal<LoadStatus>('idle');

  /** Ids of requests being cancelled right now, to disable their buttons. */
  readonly cancelling = signal<ReadonlySet<string>>(new Set());

  /** Total days left across all leave types (UI-5). */
  readonly totalAvailable = computed(() =>
    this.balances().reduce((sum, balance) => sum + balance.available, 0),
  );

  load(): void {
    void this.loadBalances();
    void this.loadRequests();
  }

  /** A new filter always starts again at page 1 (UI-6). */
  setStatusFilter(status: LeaveStatus | null): void {
    this.statusFilter.set(status);
    this.pageIndex.set(0);
    void this.loadRequests();
  }

  setPage(pageIndex: number): void {
    this.pageIndex.set(pageIndex);
    void this.loadRequests();
  }

  /** Cancels a pending request. Returns an error message, or null when it worked. */
  async cancel(request: LeaveRequest): Promise<string | null> {
    this.cancelling.update((ids) => new Set(ids).add(request.id));
    try {
      const updated = await firstValueFrom(this.api.cancel(request));
      this.requests.update((list) => list.map((r) => (r.id === updated.id ? updated : r)));
      void this.loadBalances(); // the days come back
      return null;
    } catch (error) {
      void this.loadRequests(); // show what the server has now
      return errorMessage(error);
    } finally {
      this.cancelling.update((ids) => {
        const rest = new Set(ids);
        rest.delete(request.id);
        return rest;
      });
    }
  }

  async loadRequests(): Promise<void> {
    const employeeId = this.auth.user()?.employeeId;
    if (!employeeId) {
      return;
    }
    this.listStatus.set('loading');
    this.listError.set(null);
    try {
      const page = await firstValueFrom(
        this.api.myRequests({
          employeeId,
          status: this.statusFilter(),
          limit: this.pageSize,
          offset: this.pageIndex() * this.pageSize,
        }),
      );
      this.requests.set(page.items);
      this.total.set(page.total);
      this.listStatus.set('success');
    } catch (error) {
      this.listError.set(errorMessage(error));
      this.listStatus.set('error');
    }
  }

  async loadBalances(): Promise<void> {
    const employeeId = this.auth.user()?.employeeId;
    if (!employeeId) {
      return;
    }
    this.balanceStatus.set('loading');
    try {
      this.balances.set(await firstValueFrom(this.api.balances(employeeId)));
      this.balanceStatus.set('success');
    } catch {
      this.balanceStatus.set('error');
    }
  }
}
