import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { AuthStore } from './auth-store';

/** Signed-in users only. Others go to the login page, which brings them back afterwards. */
export const authGuard: CanActivateFn = (_route, state) => {
  const auth = inject(AuthStore);
  if (auth.hasValidSession()) {
    return true;
  }
  return inject(Router).createUrlTree(['/login'], { queryParams: { returnUrl: state.url } });
};

/** Managers only. An employee who types the address is sent to My leave. */
export const managerGuard: CanActivateFn = () =>
  inject(AuthStore).isManager() || inject(Router).createUrlTree(['/leave']);

/** The login page is for signed-out users; signed-in users go to My leave. */
export const guestGuard: CanActivateFn = () =>
  !inject(AuthStore).hasValidSession() || inject(Router).createUrlTree(['/leave']);
