import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { environment } from '../../environments/environment';
import type { CurrentUser, OfficerOtpSent, StaffSession } from './models';

/**
 * Talks to the staff auth endpoints in `backend/app/modules/auth/router.py` (`POST /auth/...`).
 * The access token is kept in memory only, per the spec, so a page reload signs the user out.
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

  /** Officer login step 1: email an OTP to a pre-registered address. */
  requestOfficerOtp(email: string) {
    return this.http.post<OfficerOtpSent>(`${this.base}/auth/officer/otp`, { email });
  }

  /** Officer login step 2: verify the OTP and get a shift-bound session. */
  verifyOfficerOtp(email: string, code: string) {
    return this.http.post<StaffSession>(`${this.base}/auth/officer/verify`, {
      email,
      code,
    });
  }

  applySession(res: Pick<StaffSession, 'access_token' | 'user'>): void {
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
