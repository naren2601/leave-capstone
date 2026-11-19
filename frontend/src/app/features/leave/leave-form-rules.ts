import { AbstractControl, ValidationErrors, ValidatorFn } from '@angular/forms';

/**
 * Checks the browser can do before sending. The API checks everything again; these
 * only save the user a round trip and point at the exact field.
 */

/** Reason: 5 to 500 characters once spaces at the ends are removed (same rule as the API). */
export const reasonLength: ValidatorFn = (control) => {
  const length = String(control.value ?? '').trim().length;
  if (length === 0) return { required: true };
  if (length < 5) return { tooShort: { min: 5, actual: length } };
  if (length > 500) return { tooLong: { max: 500, actual: length } };
  return null;
};

/**
 * Form-level rules that involve two fields at once. The error is also put on the end
 * date field, so the message appears right under it.
 */
export const datesInOrder: ValidatorFn = (form: AbstractControl): ValidationErrors | null => {
  const start = form.get('startDate')?.value as Date | null;
  const end = form.get('endDate')?.value as Date | null;
  const dayPart = form.get('dayPart')?.value as string;
  const endControl = form.get('endDate');

  let problem: ValidationErrors | null = null;
  if (start && end && toIsoDate(end) < toIsoDate(start)) {
    problem = { endBeforeStart: true };
  } else if (start && end && dayPart !== 'FULL' && toIsoDate(end) !== toIsoDate(start)) {
    problem = { halfDayNotOneDay: true };
  }

  // Keep the end date field's own errors (like "required") and add or remove ours.
  if (endControl) {
    const { endBeforeStart, halfDayNotOneDay, ...others } = endControl.errors ?? {};
    void endBeforeStart;
    void halfDayNotOneDay;
    const merged = { ...others, ...(problem ?? {}) };
    endControl.setErrors(Object.keys(merged).length ? merged : null, { emitEvent: false });
  }
  return problem;
};

/**
 * A calendar date as "YYYY-MM-DD" in the user's own time zone.
 *
 * Not date.toISOString(): that converts to UTC first, so in India (UTC+5:30) midnight
 * on 23 November becomes "2026-11-22T18:30Z" and the request would be for the wrong day.
 */
export function toIsoDate(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${date.getFullYear()}-${month}-${day}`;
}
