import { Component, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';

export interface ConfirmData {
  title: string;
  message: string;
  confirmLabel: string;
  /** Ask for a reason (required) before the confirm button works, as for Reject. */
  reasonLabel?: string;
}

/** What the dialog closes with: undefined when the user cancels. */
export interface ConfirmResult {
  reason: string;
}

@Component({
  selector: 'app-confirm-dialog',
  imports: [
    MatButtonModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    ReactiveFormsModule,
  ],
  template: `
    <h2 mat-dialog-title>{{ data.title }}</h2>
    <mat-dialog-content>
      <p>{{ data.message }}</p>
      @if (data.reasonLabel) {
        <mat-form-field appearance="outline" class="reason">
          <mat-label>{{ data.reasonLabel }}</mat-label>
          <textarea
            matInput
            [formControl]="reason"
            rows="3"
            maxlength="500"
            cdkFocusInitial
          ></textarea>
          @if (reason.hasError('required') || reason.hasError('blank')) {
            <mat-error>Write a short reason for the employee.</mat-error>
          }
        </mat-form-field>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button type="button" mat-dialog-close>Cancel</button>
      <button mat-flat-button type="button" [disabled]="status() !== 'VALID'" (click)="confirm()">
        {{ data.confirmLabel }}
      </button>
    </mat-dialog-actions>
  `,
  styles: `
    .reason {
      width: 100%;
    }
  `,
})
export class ConfirmDialog {
  protected readonly data = inject<ConfirmData>(MAT_DIALOG_DATA);
  private readonly ref = inject(MatDialogRef<ConfirmDialog, ConfirmResult>);

  protected readonly reason = new FormControl('', {
    nonNullable: true,
    validators: this.data.reasonLabel
      ? [Validators.required, (c) => (c.value.trim() ? null : { blank: true })]
      : [],
  });

  /**
   * The reason's status as a signal. Without zone.js, Angular redraws when a signal
   * changes; reading reason.invalid directly in the template would not update the button.
   */
  protected readonly status = toSignal(this.reason.statusChanges, {
    initialValue: this.reason.status,
  });

  protected confirm(): void {
    this.ref.close({ reason: this.reason.value.trim() });
  }
}
