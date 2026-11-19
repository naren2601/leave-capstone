import { TestBed } from '@angular/core/testing';
import { FormControl, FormGroup } from '@angular/forms';
import { DateAdapter } from '@angular/material/core';

import { provideDayFirstDates } from '../../core/day-first-dates';
import { datesInOrder, reasonLength, toIsoDate } from './leave-form-rules';

function form(start: Date | null, end: Date | null, dayPart = 'FULL') {
  return new FormGroup(
    {
      startDate: new FormControl(start),
      endDate: new FormControl(end),
      dayPart: new FormControl(dayPart),
    },
    { validators: datesInOrder },
  );
}

describe('leave form rules', () => {
  it('turns a date into YYYY-MM-DD in local time, never shifted to UTC', () => {
    expect(toIsoDate(new Date(2026, 10, 23))).toBe('2026-11-23');
    expect(toIsoDate(new Date(2026, 0, 5, 0, 30))).toBe('2026-01-05'); // just after midnight
  });

  it('UI-7: an end date before the start date is an error on the end date', () => {
    const f = form(new Date(2026, 10, 25), new Date(2026, 10, 23));

    expect(f.hasError('endBeforeStart')).toBe(true);
    expect(f.controls.endDate.hasError('endBeforeStart')).toBe(true);

    f.controls.endDate.setValue(new Date(2026, 10, 26));
    expect(f.valid).toBe(true);
  });

  it('a half day must be one date', () => {
    const f = form(new Date(2026, 10, 23), new Date(2026, 10, 24), 'AM');

    expect(f.controls.endDate.hasError('halfDayNotOneDay')).toBe(true);

    f.controls.dayPart.setValue('FULL');
    expect(f.valid).toBe(true);
  });

  it('the reason needs 5 to 500 characters, not counting spaces at the ends', () => {
    expect(reasonLength(new FormControl('   '))).toEqual({ required: true });
    expect(reasonLength(new FormControl('  trip  '))).toHaveProperty('tooShort');
    expect(reasonLength(new FormControl('Family trip'))).toBeNull();
    expect(reasonLength(new FormControl('x'.repeat(501)))).toHaveProperty('tooLong');
  });
});

describe('DayFirstDateAdapter', () => {
  let adapter: DateAdapter<Date>;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideDayFirstDates()] });
    adapter = TestBed.inject(DateAdapter);
  });

  it('shows dates day first', () => {
    expect(
      adapter.format(new Date(2026, 10, 5), { year: 'numeric', month: 'numeric', day: 'numeric' }),
    ).toBe('05/11/2026');
  });

  it('reads dates day first', () => {
    expect(toIsoDate(adapter.parse('05/11/2026', null)!)).toBe('2026-11-05'); // 5 Nov, not 11 May
    expect(toIsoDate(adapter.parse('23-11-2026', null)!)).toBe('2026-11-23');
  });

  it('refuses dates that do not exist or are not dates', () => {
    expect(adapter.isValid(adapter.parse('31/02/2026', null)!)).toBe(false);
    expect(adapter.isValid(adapter.parse('next monday', null)!)).toBe(false);
    expect(adapter.parse('', null)).toBeNull();
  });
});
