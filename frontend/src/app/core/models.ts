/** Shapes the API sends back (see API_SPEC.md, section 4). */

export type LeaveType = 'ANNUAL' | 'SICK' | 'CASUAL';
export type DayPart = 'FULL' | 'AM' | 'PM';
export type LeaveStatus = 'PENDING' | 'APPROVED' | 'REJECTED' | 'CANCELLED';

export interface LeaveRequest {
  id: string;
  employee_id: string;
  leave_type: LeaveType;
  start_date: string; // ISO date, such as "2026-11-23"
  end_date: string;
  day_part: DayPart;
  reason: string;
  status: LeaveStatus;
  days: number;
  decision_note: string | null;
  version: number; // sent back as If-Match when changing the request
}

export interface Balance {
  leave_type: LeaveType;
  entitled: number;
  used: number;
  pending: number;
  available: number;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
  next_cursor: string | null;
}

export const LEAVE_TYPE_NAMES: Record<LeaveType, string> = {
  ANNUAL: 'Annual',
  SICK: 'Sick',
  CASUAL: 'Casual',
};
