import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { AuthService } from '../core/auth.service';
import { apiErrorMessage } from '../core/http-error';
import { ButtonComponent } from '../ui/button/button.component';
import { CardComponent } from '../ui/card/card.component';
import { InputComponent } from '../ui/input/input.component';

type Step = 'email' | 'otp';

/**
 * Security officer login: OTP emailed to a pre-registered address, no self sign-up.
 * Calls `POST /auth/officer/otp` and `POST /auth/officer/verify`.
 */
@Component({
  selector: 'app-officer-login',
  standalone: true,
  imports: [FormsModule, ButtonComponent, CardComponent, InputComponent],
  templateUrl: './officer-login.component.html',
})
export class OfficerLoginComponent {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  readonly step = signal<Step>('email');
  readonly email = signal('');
  readonly code = signal('');
  readonly submitting = signal(false);
  readonly errorMessage = signal('');
  readonly eventId = signal('');

  requestOtp(): void {
    if (!this.email().trim().includes('@')) return;
    this.submitting.set(true);
    this.errorMessage.set('');
    this.auth.requestOfficerOtp(this.email().trim()).subscribe({
      next: () => {
        this.submitting.set(false);
        this.step.set('otp');
      },
      error: (err) => {
        this.submitting.set(false);
        this.errorMessage.set(apiErrorMessage(err, 'Could not send the code.'));
      },
    });
  }

  verifyOtp(): void {
    if (this.code().trim().length === 0) return;
    this.submitting.set(true);
    this.errorMessage.set('');
    this.auth.verifyOfficerOtp(this.email().trim(), this.code().trim()).subscribe({
      next: (res) => {
        this.submitting.set(false);
        this.auth.applySession(res);
        const eventId = this.eventId().trim();
        this.router.navigateByUrl(eventId ? `/gate/scan/${eventId}` : '/gate/login');
      },
      error: (err) => {
        this.submitting.set(false);
        this.errorMessage.set(apiErrorMessage(err, 'That code did not match. Please try again.'));
      },
    });
  }
}
