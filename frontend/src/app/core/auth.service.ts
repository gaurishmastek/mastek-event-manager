import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { environment } from '../../environments/environment';
import type { CurrentUser } from './models';

/**
 * Talks to the staff auth endpoints planned in `docs/event-management.md` (`POST /auth/...`).
 * That module is not on `main` yet (see the "Add secure login and roles" thread), so every
 * call here 401s until it lands. The access token is kept in memory only, per the spec
 * (refresh token lives in an HttpOnly cookie the backend sets).
 */
@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly base = environment.apiBaseUrl;

  private readonly accessToken = signal<string | null>(null);
  private readonly user = signal<CurrentUser | null>(null);

  readonly currentUser = this.user.asReadonly();
  readonly isAuthenticated = computed(() => this.accessToken() !== null);

  getAccessToken(): string | null {
    return this.accessToken();
  }

  /** Step 1 of admin login: email + password. Returns a 2FA challenge id. */
  loginWithPassword(email: string, password: string) {
    return this.http.post<{ challenge_id: string }>(`${this.base}/auth/login`, { email, password });
  }

  /** Step 2 of admin login: the OTP/TOTP second factor. */
  verifyLoginSecondFactor(challengeId: string, code: string) {
    return this.http.post<{ access_token: string; user: CurrentUser }>(`${this.base}/auth/login/verify`, {
      challenge_id: challengeId,
      code,
    });
  }

  /** Officer login step 1: send an OTP to a pre-registered mobile. */
  requestOfficerOtp(mobile: string) {
    return this.http.post<{ resend_available_at: string }>(`${this.base}/auth/officer/otp`, { mobile });
  }

  /** Officer login step 2: verify the OTP and get a shift-bound session. */
  verifyOfficerOtp(mobile: string, code: string) {
    return this.http.post<{ access_token: string; user: CurrentUser }>(`${this.base}/auth/officer/verify`, {
      mobile,
      code,
    });
  }

  applySession(res: { access_token: string; user: CurrentUser }): void {
    this.accessToken.set(res.access_token);
    this.user.set(res.user);
  }

  logout() {
    return this.http.post(`${this.base}/auth/logout`, {}).subscribe({
      complete: () => this.clearSession(),
      error: () => this.clearSession(),
    });
  }

  clearSession(): void {
    this.accessToken.set(null);
    this.user.set(null);
  }
}
