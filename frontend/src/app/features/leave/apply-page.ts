import { Component, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatDatepickerModule } from '@angular/material/datepicker';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatRadioModule } from '@angular/material/radio';
import { MatSelectModule } from '@angular/material/select';
import { MatSnackBar } from '@angular/material/snack-bar';
import { Router, RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';

import { apiError } from '../../core/api-errors';
import { provideDayFirstDates } from '../../core/day-first-dates';
import { DayPart, LEAVE_TYPE_NAMES, LeaveType } from '../../core/models';
import { LeaveApi } from './leave-api';
import { datesInOrder, reasonLength, toIsoDate } from './leave-form-rules';

/** A problem only the server could see (overlap, balance, notice), shown above Submit. */
interface ServerProblem {
  title: string;
  message: string;
  details: string[];
}

@Component({
  selector: 'app-apply-page',
  imports: [
    ReactiveFormsModule,
    RouterLink,
    MatButtonModule,
    MatDatepickerModule,
    MatFormFieldModule,
    MatInputModule,
    MatRadioModule,
    MatSelectModule,
  ],
  providers: [provideDayFirstDates()],
  templateUrl: './apply-page.html',
  styleUrl: './apply-page.scss',
})
export class ApplyPage {
  private readonly api = inject(LeaveApi);
  private readonly router = inject(Router);
  private readonly snackBar = inject(MatSnackBar);

  protected readonly leaveTypes = Object.entries(LEAVE_TYPE_NAMES) as [LeaveType, string][];
  protected readonly dayParts: { value: DayPart; label: string }[] = [
    { value: 'FULL', label: 'Full day(s)' },
    { value: 'AM', label: 'Morning only' },
    { value: 'PM', label: 'Afternoon only' },
  ];

  protected readonly form = inject(NonNullableFormBuilder).group(
    {
      leaveType: ['ANNUAL' as LeaveType, Validators.required],
      startDate: [null as Date | null, Validators.required],
      endDate: [null as Date | null, Validators.required],
      dayPart: ['FULL' as DayPart, Validators.required],
      reason: ['', reasonLength],
    },
    { validators: datesInOrder },
  );

  protected readonly sending = signal(false);
  protected readonly problem = signal<ServerProblem | null>(null);

  /**
   * One key per set of answers: a retry of the same answers reuses it (safe), and any
   * change to the form makes a new one (a genuinely new request).
   */
  private idempotencyKey = crypto.randomUUID();

  constructor() {
    this.form.valueChanges.pipe(takeUntilDestroyed()).subscribe(() => {
      this.idempotencyKey = crypto.randomUUID();
      this.problem.set(null);
    });
  }

  protected async submit(): Promise<void> {
    if (this.sending()) {
      return;
    }
    if (this.form.invalid) {
      this.form.markAllAsTouched(); // show every message at once
      return;
    }
    const value = this.form.getRawValue();
    this.sending.set(true);
    this.problem.set(null);
    try {
      await firstValueFrom(
        this.api.apply(
          {
            leave_type: value.leaveType,
            start_date: toIsoDate(value.startDate!),
            end_date: toIsoDate(value.endDate!),
            day_part: value.dayPart,
            reason: value.reason.trim(),
          },
          this.idempotencyKey,
        ),
      );
      this.snackBar.open('Leave requested. Your manager has been told.', 'OK', {
        duration: 5000,
      });
      await this.router.navigateByUrl('/leave');
    } catch (error) {
      this.problem.set(problemFor(error));
    } finally {
      this.sending.set(false);
    }
  }
}

function problemFor(error: unknown): ServerProblem {
  const { code, message, details } = apiError(error);
  const titles: Record<string, string> = {
    OVERLAPPING_LEAVE: 'These dates overlap another request',
    INSUFFICIENT_BALANCE: 'Not enough days left',
    POLICY_VIOLATION: 'This breaks a leave rule',
    VALIDATION_ERROR: 'Please check the form',
  };
  return {
    title: titles[code] ?? 'Could not send the request',
    message: message.charAt(0).toUpperCase() + message.slice(1),
    details: details
      .map((detail) => detail.problem)
      .filter((problem) => problem && problem !== message),
  };
}
