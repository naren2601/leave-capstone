import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { API_URL } from '../../core/api';
import { Balance, LeaveRequest, LeaveStatus, Page } from '../../core/models';

/** The leave endpoints of the API. Only talks HTTP; no state, no decisions. */
@Injectable({ providedIn: 'root' })
export class LeaveApi {
  private readonly http = inject(HttpClient);
  private readonly api = inject(API_URL);

  balances(employeeId: string): Observable<Balance[]> {
    return this.http.get<Balance[]>(
      `${this.api}/employees/${encodeURIComponent(employeeId)}/balance`,
    );
  }

  /** One person's requests, newest first. A manager would otherwise also get the team's. */
  myRequests(query: {
    employeeId: string;
    status: LeaveStatus | null;
    limit: number;
    offset: number;
  }): Observable<Page<LeaveRequest>> {
    let params = new HttpParams()
      .set('employee_id', query.employeeId)
      .set('limit', query.limit)
      .set('offset', query.offset)
      .set('sort', '-start_date');
    if (query.status) {
      params = params.set('status', query.status);
    }
    return this.http.get<Page<LeaveRequest>>(`${this.api}/leave-requests`, { params });
  }

  /** If-Match: the API refuses (409) if someone changed the request since we loaded it. */
  cancel(request: LeaveRequest): Observable<LeaveRequest> {
    return this.http.delete<LeaveRequest>(
      `${this.api}/leave-requests/${encodeURIComponent(request.id)}`,
      { headers: { 'If-Match': `"${request.version}"` } },
    );
  }
}
