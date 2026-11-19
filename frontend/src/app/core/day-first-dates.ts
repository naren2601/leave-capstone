import { Injectable, Provider } from '@angular/core';
import {
  DateAdapter,
  MAT_DATE_LOCALE,
  NativeDateAdapter,
  provideNativeDateAdapter,
} from '@angular/material/core';

/**
 * Dates typed and shown day first: 23/11/2026 means 23 November 2026.
 *
 * Angular Material's built-in adapter parses with the browser's Date.parse, which reads
 * "05/11/2026" the American way, as 11 May. This adapter reads DD/MM/YYYY (also with
 * - or .), and refuses dates that do not exist, such as 31/02/2026.
 */
@Injectable()
export class DayFirstDateAdapter extends NativeDateAdapter {
  override parse(value: unknown, parseFormat?: unknown): Date | null {
    if (typeof value !== 'string') {
      return super.parse(value, parseFormat);
    }
    const text = value.trim();
    if (text === '') {
      return null;
    }
    const match = /^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$/.exec(text);
    if (!match) {
      return this.invalid();
    }
    const [day, month, year] = [Number(match[1]), Number(match[2]), Number(match[3])];
    const date = new Date(year, month - 1, day);
    const real =
      date.getFullYear() === year && date.getMonth() === month - 1 && date.getDate() === day;
    return real ? date : this.invalid();
  }
}

/** Use in a component's providers next to the date pickers. */
export function provideDayFirstDates(): Provider[] {
  return [
    provideNativeDateAdapter(), // the standard display formats (MAT_DATE_FORMATS)
    { provide: MAT_DATE_LOCALE, useValue: 'en-GB' }, // shows 23/11/2026
    { provide: DateAdapter, useClass: DayFirstDateAdapter }, // reads 23/11/2026
  ];
}
