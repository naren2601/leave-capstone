import { HttpErrorResponse } from '@angular/common/http';
import { Component, inject, input, signal } from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { Router } from '@angular/router';

import { AuthStore } from '../../core/auth/auth-store';

@Component({
  selector: 'app-login-page',
  imports: [
    ReactiveFormsModule,
    MatButtonModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatProgressSpinnerModule,
  ],
  templateUrl: './login-page.html',
  styleUrl: './login-page.scss',
})
export class LoginPage {
  private readonly auth = inject(AuthStore);
  private readonly router = inject(Router);

  /** From the URL: ?returnUrl=/approvals and ?reason=expired (route input binding). */
  readonly returnUrl = input<string>();
  readonly reason = input<string>();

  protected readonly form = inject(NonNullableFormBuilder).group({
    email: ['', [Validators.required, Validators.email]],
    password: ['', Validators.required],
  });
  protected readonly sending = signal(false);
  protected readonly error = signal<string | null>(null);

  protected async submit(): Promise<void> {
    if (this.form.invalid || this.sending()) {
      return;
    }
    this.sending.set(true);
    this.error.set(null);
    const { email, password } = this.form.getRawValue();
    try {
      await this.auth.login(email.trim(), password);
      await this.router.navigateByUrl(safeReturnUrl(this.returnUrl()));
    } catch (error) {
      this.error.set(messageFor(error));
      this.form.controls.password.reset();
    } finally {
      this.sending.set(false);
    }
  }
}

function messageFor(error: unknown): string {
  if (error instanceof HttpErrorResponse && error.status === 401) {
    // Same words for a wrong email, a wrong password and a locked account.
    return 'Email or password is wrong.';
  }
  if (error instanceof HttpErrorResponse && error.status === 0) {
    return 'Cannot reach the server. Check your connection and try again.';
  }
  return 'Something went wrong. Please try again.';
}

/** Only go back to pages of this app, never to another site. */
function safeReturnUrl(url: string | undefined): string {
  return url && url.startsWith('/') && !url.startsWith('//') ? url : '/leave';
}
