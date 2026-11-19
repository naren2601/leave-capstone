import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { API_URL } from '../../core/api';
import { LeaveRequest, Page } from '../../core/models';

export interface TeamMember {
  id: string;
  name: string;
  manager_id: string | null;
}

/** The manager's endpoints. Every change sends If-Match with the version the screen showed. */
@Injectable({ providedIn: 'root' })
export class ApprovalsApi {
  private readonly http = inject(HttpClient);
  private readonly api = inject(API_URL);

  team(): Observable<TeamMember[]> {
    return this.http.get<TeamMember[]>(`${this.api}/team`);
  }

  /** Pending requests the manager can see (their own and their reports'), soonest first. */
  pending(): Observable<Page<LeaveRequest>> {
    const params = new HttpParams()
      .set('status', 'PENDING')
      .set('sort', 'start_date')
      .set('limit', 100);
    return this.http.get<Page<LeaveRequest>>(`${this.api}/leave-requests`, { params });
  }

  approve(request: LeaveRequest): Observable<LeaveRequest> {
    return this.http.post<LeaveRequest>(
      `${this.api}/leave-requests/${encodeURIComponent(request.id)}/approve`,
      null,
      { headers: { 'If-Match': `"${request.version}"` } },
    );
  }

  reject(request: LeaveRequest, reason: string): Observable<LeaveRequest> {
    return this.http.post<LeaveRequest>(
      `${this.api}/leave-requests/${encodeURIComponent(request.id)}/reject`,
      { reason },
      { headers: { 'If-Match': `"${request.version}"` } },
    );
  }
}
