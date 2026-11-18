import { Component, inject } from '@angular/core';

import { AuthStore } from '../../core/auth/auth-store';

/** Placeholder until step 4 builds the balance cards and the requests table. */
@Component({
  selector: 'app-my-leave-page',
  template: `
    <h1>My leave</h1>
    <p>Signed in as {{ auth.user()?.email }} ({{ auth.user()?.role }}).</p>
    <p>Your balances and requests come in the next step.</p>
  `,
})
export class MyLeavePage {
  protected readonly auth = inject(AuthStore);
}
