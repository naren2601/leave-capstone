import { Injectable, computed, inject, signal } from '@angular/core';
import { Observable, firstValueFrom } from 'rxjs';

import { errorMessage } from '../../core/api-errors';
import { AuthStore } from '../../core/auth/auth-store';
import { LeaveRequest } from '../../core/models';
import { LoadStatus } from '../leave/leave-store';
import { ApprovalsApi } from './approvals-api';

/**
 * The manager's queue of pending team requests.
 *
 * Optimistic update: Approve and Reject remove the row at once, before the API answers,
 * so the screen feels instant. If the API says no, the row goes back where it was.
 */
@Injectable()
export class ApprovalsStore {
  private readonly api = inject(ApprovalsApi);
  private readonly auth = inject(AuthStore);

  readonly requests = signal<LeaveRequest[]>([]);
  readonly status = signal<LoadStatus>('idle');
  readonly error = signal<string | null>(null);
  private readonly names = signal<ReadonlyMap<string, string>>(new Map());

  readonly count = computed(() => this.requests().length);

  /** "Asha Rao" for "e1"; the id itself if the name is unknown. */
  nameOf(employeeId: string): string {
    return this.names().get(employeeId) ?? employeeId;
  }

  async load(): Promise<void> {
    this.status.set('loading');
    this.error.set(null);
    try {
      const [team, page] = await Promise.all([
        firstValueFrom(this.api.team()),
        firstValueFrom(this.api.pending()),
      ]);
      this.names.set(new Map(team.map((member) => [member.id, member.name])));
      const me = this.auth.user()?.employeeId;
      // A manager cannot approve their own leave; only the team's requests belong here.
      this.requests.set(page.items.filter((request) => request.employee_id !== me));
      this.status.set('success');
    } catch (error) {
      this.error.set(errorMessage(error));
      this.status.set('error');
    }
  }

  /** Returns null when it worked, or the API's message after putting the row back. */
  approve(request: LeaveRequest): Promise<string | null> {
    return this.decide(request, this.api.approve(request));
  }

  reject(request: LeaveRequest, reason: string): Promise<string | null> {
    return this.decide(request, this.api.reject(request, reason));
  }

  private async decide(
    request: LeaveRequest,
    call: Observable<LeaveRequest>,
  ): Promise<string | null> {
    const index = this.requests().findIndex((r) => r.id === request.id);
    this.requests.update((list) => list.filter((r) => r.id !== request.id)); // gone at once
    try {
      await firstValueFrom(call);
      return null;
    } catch (error) {
      // Roll back: the row returns to the same place in the list.
      this.requests.update((list) => {
        const restored = [...list];
        restored.splice(index < 0 ? restored.length : Math.min(index, restored.length), 0, request);
        return restored;
      });
      return errorMessage(error);
    }
  }
}
