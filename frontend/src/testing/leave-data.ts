import { Balance, LeaveRequest, Page } from '../app/core/models';

export function aRequest(overrides: Partial<LeaveRequest> = {}): LeaveRequest {
  return {
    id: 'r1',
    employee_id: 'e1',
    leave_type: 'ANNUAL',
    start_date: '2026-11-23',
    end_date: '2026-11-25',
    day_part: 'FULL',
    reason: 'Family trip',
    status: 'PENDING',
    days: 3,
    decision_note: null,
    version: 1,
    ...overrides,
  };
}

export function aPage(items: LeaveRequest[], total = items.length): Page<LeaveRequest> {
  return { items, total, limit: 10, offset: 0, next_cursor: null };
}

export const BALANCES: Balance[] = [
  { leave_type: 'ANNUAL', entitled: 18, used: 2, pending: 3, available: 13 },
  { leave_type: 'SICK', entitled: 12, used: 0, pending: 0, available: 12 },
  { leave_type: 'CASUAL', entitled: 6, used: 0.5, pending: 0, available: 5.5 },
];
