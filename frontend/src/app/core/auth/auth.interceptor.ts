import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, throwError } from 'rxjs';

import { API_URL } from '../api';
import { AuthStore } from './auth-store';

/** Adds "Authorization: Bearer <token>" to every API call except the login itself. */
export const authInterceptor: HttpInterceptorFn = (request, next) => {
  const token = inject(AuthStore).token();
  const api = inject(API_URL);
  if (!token || !request.url.startsWith(api) || isLogin(request.url, api)) {
    return next(request);
  }
  return next(request.clone({ setHeaders: { Authorization: `Bearer ${token}` } }));
};

/**
 * A 401 from any API call (except a failed login) means the token is missing, wrong or
 * expired: sign out and send the user to the login page.
 */
export const unauthorizedInterceptor: HttpInterceptorFn = (request, next) => {
  const auth = inject(AuthStore);
  const api = inject(API_URL);
  return next(request).pipe(
    catchError((error: unknown) => {
      if (
        error instanceof HttpErrorResponse &&
        error.status === 401 &&
        !isLogin(request.url, api)
      ) {
        auth.logout('expired');
      }
      return throwError(() => error);
    }),
  );
};

function isLogin(url: string, api: string): boolean {
  return url === `${api}/auth/login`;
}
