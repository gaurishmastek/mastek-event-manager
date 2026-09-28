import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { AuthService } from '../core/auth.service';
import { apiErrorMessage } from '../core/http-error';
import { ButtonComponent } from '../ui/button/button.component';
import { CardComponent } from '../ui/card/card.component';
import { InputComponent } from '../ui/input/input.component';

type Step = 'password' | 'second-factor';

/**
 * Admin login: password, then a second factor (OTP or TOTP per the spec).
 * Calls `POST /auth/login` (password, which emails a 6-digit code to the admin's address) and
 * `POST /auth/login/verify` (the code).
 */
@Component({
  selector: 'app-admin-login',
  standalone: true,
  imports: [FormsModule, RouterLink, ButtonComponent, CardComponent, InputComponent],
  templateUrl: './login.component.html',
})
export class AdminLoginComponent {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  readonly step = signal<Step>('password');
  readonly email = signal('');
  readonly password = signal('');
  readonly code = signal('');
  readonly submitting = signal(false);
  readonly errorMessage = signal('');
  private challengeId = '';

  submitPassword(): void {
    if (!this.email().trim() || !this.password()) return;
    this.submitting.set(true);
    this.errorMessage.set('');
    this.auth.loginWithPassword(this.email().trim(), this.password()).subscribe({
      next: (res) => {
        this.submitting.set(false);
        this.challengeId = res.challenge_id;
        this.step.set('second-factor');
      },
      error: (err) => {
        this.submitting.set(false);
        this.errorMessage.set(apiErrorMessage(err, 'Incorrect email or password.'));
      },
    });
  }

  submitSecondFactor(): void {
    if (this.code().trim().length === 0) return;
    this.submitting.set(true);
    this.errorMessage.set('');
    this.auth.verifyLoginSecondFactor(this.challengeId, this.code().trim()).subscribe({
      next: (res) => {
        this.submitting.set(false);
        this.auth.applySession(res);
        this.router.navigateByUrl('/admin/events');
      },
      error: (err) => {
        this.submitting.set(false);
        this.errorMessage.set(apiErrorMessage(err, 'That code did not match. Please try again.'));
      },
    });
  }
}
