import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { AuthService } from '../core/auth.service';
import { apiErrorMessage } from '../core/http-error';
import { emailError } from '../public/registration-form';
import { ButtonComponent } from '../ui/button/button.component';
import { CardComponent } from '../ui/card/card.component';

/** Matches the backend's limit on password length. */
const PASSWORD_MAX_LENGTH = 128;

/**
 * Maps officer sign-in errors to guidance. The backend deliberately answers 401 for a wrong password, an unknown
 * address and a locked account alike, so the page never reveals which one it was.
 */
export function officerLoginErrorMessage(err: unknown): string {
  if (err instanceof HttpErrorResponse) {
    if (err.status === 401) {
      return 'Incorrect email or password. After several wrong tries the account is locked for a while; ask an administrator if you are stuck.';
    }
    if (err.status === 422) return 'Enter a valid email address and your password.';
    if (err.status === 0) return 'Could not reach the server. Check the connection and try again.';
  }
  return apiErrorMessage(err, 'Could not sign in. Please try again.');
}

/**
 * Security officer sign in: email and password of a pre-registered account, no self sign-up.
 * Calls `POST /auth/officer/login` and goes to the assigned-event list.
 * The password lives only in this component's memory: never in the URL, storage or logs, and is cleared after each try.
 */
@Component({
  selector: 'app-officer-login',
  standalone: true,
  imports: [FormsModule, ButtonComponent, CardComponent],
  templateUrl: './officer-login.component.html',
})
export class OfficerLoginComponent {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  readonly email = signal('');
  readonly password = signal('');
  readonly submitting = signal(false);
  readonly errorMessage = signal('');
  readonly passwordMaxLength = PASSWORD_MAX_LENGTH;

  readonly canSubmit = computed(() => !emailError(this.email()) && this.password().length > 0);

  constructor() {
    const user = this.auth.currentUser();
    if (user && this.auth.isAuthenticated() && (user.role === 'security_officer' || user.role === 'admin')) {
      this.router.navigateByUrl('/gate/events', { replaceUrl: true });
    }
  }

  signIn(): void {
    if (this.submitting()) return;
    if (emailError(this.email())) {
      this.errorMessage.set('Enter a valid email address.');
      return;
    }
    if (!this.password()) {
      this.errorMessage.set('Enter your password.');
      return;
    }
    this.submitting.set(true);
    this.errorMessage.set('');
    this.auth.officerLogin(this.email().trim(), this.password()).subscribe({
      next: (session) => {
        this.submitting.set(false);
        this.password.set('');
        this.auth.applySession(session);
        this.router.navigateByUrl('/gate/events', { replaceUrl: true });
      },
      error: (err) => {
        this.submitting.set(false);
        this.password.set('');
        this.errorMessage.set(officerLoginErrorMessage(err));
      },
    });
  }
}
