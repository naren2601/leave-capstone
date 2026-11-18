import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';

import { API_URL } from '../api';

export type Role = 'employee' | 'manager';

/** What the app knows about the signed-in person. */
export interface Session {
  token: string;
  employeeId: string; // the token's "sub", such as "e1"
  role: Role;
  email: string; // as typed at login, to show in the toolbar
  expiresAt: number; // milliseconds since 1970, from the token's "exp"
}

interface TokenResponse {
  access_token: string;
  token_type: 'bearer';
  expires_in: number;
}

const STORAGE_KEY = 'leavedesk.session';

/**
 * The signed-in user, as signals.
 *
 * The token lives in sessionStorage: it survives a page reload but is gone when the tab
 * closes. The role inside the token only decides what the UI shows; the API checks the
 * token's signature and the role again on every call.
 */
@Injectable({ providedIn: 'root' })
export class AuthStore {
  private readonly http = inject(HttpClient);
  private readonly router = inject(Router);
  private readonly api = inject(API_URL);

  private readonly session = signal<Session | null>(readStoredSession());

  readonly user = this.session.asReadonly();
  readonly token = computed(() => this.session()?.token ?? null);
  readonly isLoggedIn = computed(() => this.session() !== null);
  readonly isManager = computed(() => this.session()?.role === 'manager');

  /** Signs in. Rejects with the HttpErrorResponse when the API says no. */
  async login(email: string, password: string): Promise<void> {
    const response = await firstValueFrom(
      this.http.post<TokenResponse>(`${this.api}/auth/login`, { email, password }),
    );
    const session = sessionFromToken(response.access_token, email);
    if (session === null) {
      throw new Error('The server sent a token this app cannot read.');
    }
    this.session.set(session);
    store(session);
  }

  /** Forgets the token and goes to the login page. */
  logout(reason?: 'expired'): void {
    this.session.set(null);
    store(null);
    void this.router.navigate(['/login'], reason ? { queryParams: { reason } } : {});
  }

  /** True while there is a session whose token has not expired. */
  hasValidSession(now = Date.now()): boolean {
    const session = this.session();
    if (session !== null && session.expiresAt <= now) {
      this.session.set(null);
      store(null);
      return false;
    }
    return session !== null;
  }
}

/**
 * Reads the claims from the token. This does NOT verify the signature (only the server
 * can, it has the secret); it is just to know who is signed in and until when.
 */
export function sessionFromToken(token: string, email: string): Session | null {
  try {
    const payload = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    const claims = JSON.parse(atob(payload)) as { sub?: unknown; role?: unknown; exp?: unknown };
    if (
      typeof claims.sub !== 'string' ||
      (claims.role !== 'employee' && claims.role !== 'manager') ||
      typeof claims.exp !== 'number'
    ) {
      return null;
    }
    return {
      token,
      employeeId: claims.sub,
      role: claims.role,
      email,
      expiresAt: claims.exp * 1000,
    };
  } catch {
    return null;
  }
}

function readStoredSession(): Session | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    const stored = raw ? (JSON.parse(raw) as Session) : null;
    return stored && stored.expiresAt > Date.now() ? stored : null;
  } catch {
    return null; // storage blocked or the value is damaged: start signed out
  }
}

function store(session: Session | null): void {
  try {
    if (session) {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session));
    } else {
      sessionStorage.removeItem(STORAGE_KEY);
    }
  } catch {
    // Storage blocked (private mode): the session still works until the page reloads.
  }
}
