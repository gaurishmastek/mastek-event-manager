import { HttpErrorResponse } from '@angular/common/http';
import { Component, NgZone, OnDestroy, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { AuthService } from '../core/auth.service';
import { apiErrorMessage } from '../core/http-error';
import { utcIso } from '../core/time';
import { emailError } from '../public/registration-form';
import { ButtonComponent } from '../ui/button/button.component';
import { CardComponent } from '../ui/card/card.component';

type Step = 'email' | 'otp';

const CODE_PATTERN = /^\d{6}$/;

/** The same words whatever the address, so the page never reveals whether an officer account exists. */
export const CODE_SENT_MESSAGE =
  'If this email belongs to an active security officer, a 6-digit code is on its way. It expires in a few minutes.';

/** Maps officer OTP errors to guidance. The backend deliberately uses one 400 for wrong, expired and used-up codes. */
export function officerOtpErrorMessage(err: unknown, stage: 'send' | 'verify'): string {
  if (err instanceof HttpErrorResponse) {
    if (stage === 'verify' && err.status === 400) {
      return 'That code is incorrect, has expired, or has been tried too many times. Check the latest email, or send a new code.';
    }
    if (err.status === 429) {
      const seconds = Number(err.headers?.get('Retry-After'));
      const wait = Number.isFinite(seconds) && seconds > 0 ? ` Try again in ${formatWait(seconds)}.` : ' Please wait and try again.';
      return `Too many code requests.${wait}`;
    }
    if (err.status === 503) {
      return 'Codes cannot be sent right now. Please try again shortly or contact an administrator.';
    }
    if (err.status === 422) {
      return stage === 'send' ? 'Enter a valid email address.' : 'Enter the 6-digit code from the email.';
    }
  }
  return apiErrorMessage(err, stage === 'send' ? 'Could not send the code.' : 'Could not verify the code.');
}

function formatWait(seconds: number): string {
  if (seconds < 60) return `${Math.ceil(seconds)} seconds`;
  const minutes = Math.ceil(seconds / 60);
  return `${minutes} minute${minutes === 1 ? '' : 's'}`;
}

/**
 * Security officer sign in: a code emailed to a pre-registered address, no password and no self sign-up.
 * Calls `POST /auth/officer/otp` then `POST /auth/officer/verify`, and goes to the assigned-event list.
 * The code lives only in this component's memory: never in the URL, storage or logs.
 */
@Component({
  selector: 'app-officer-login',
  standalone: true,
  imports: [FormsModule, ButtonComponent, CardComponent],
  templateUrl: './officer-login.component.html',
})
export class OfficerLoginComponent implements OnDestroy {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  readonly step = signal<Step>('email');
  readonly email = signal('');
  readonly code = signal('');
  readonly submitting = signal(false);
  readonly resending = signal(false);
  readonly errorMessage = signal('');
  readonly infoMessage = signal('');
  readonly resendAvailableAt = signal<number | null>(null);
  readonly now = signal(Date.now());
  readonly codeSentMessage = CODE_SENT_MESSAGE;

  readonly emailInvalid = computed(() => !!emailError(this.email()));
  readonly codeValid = computed(() => CODE_PATTERN.test(this.code()));
  readonly resendSecondsLeft = computed(() => {
    const at = this.resendAvailableAt();
    return at === null ? 0 : Math.max(0, Math.ceil((at - this.now()) / 1000));
  });

  private readonly zone = inject(NgZone);
  private ticker: ReturnType<typeof setInterval> | null = null;

  constructor() {
    const user = this.auth.currentUser();
    if (user && this.auth.isAuthenticated() && (user.role === 'security_officer' || user.role === 'admin')) {
      this.router.navigateByUrl('/gate/events', { replaceUrl: true });
    }
  }

  ngOnDestroy(): void {
    this.stopTicker();
  }

  requestOtp(): void {
    if (this.submitting() || this.emailInvalid()) {
      if (this.emailInvalid()) this.errorMessage.set('Enter a valid email address.');
      return;
    }
    this.submitting.set(true);
    this.errorMessage.set('');
    this.infoMessage.set('');
    this.auth.requestOfficerOtp(this.email().trim()).subscribe({
      next: (sent) => {
        this.submitting.set(false);
        this.setCooldown(sent.resend_available_at);
        this.code.set('');
        this.infoMessage.set(CODE_SENT_MESSAGE);
        this.step.set('otp');
      },
      error: (err) => {
        this.submitting.set(false);
        this.errorMessage.set(officerOtpErrorMessage(err, 'send'));
      },
    });
  }

  resendOtp(): void {
    if (this.resending() || this.resendSecondsLeft() > 0) return;
    this.resending.set(true);
    this.errorMessage.set('');
    this.infoMessage.set('');
    this.auth.requestOfficerOtp(this.email().trim()).subscribe({
      next: (sent) => {
        this.resending.set(false);
        this.setCooldown(sent.resend_available_at);
        this.code.set('');
        this.infoMessage.set(`${CODE_SENT_MESSAGE} Earlier codes no longer work.`);
      },
      error: (err) => {
        this.resending.set(false);
        this.errorMessage.set(officerOtpErrorMessage(err, 'send'));
      },
    });
  }

  onCodeInput(value: string): void {
    this.code.set((value ?? '').replace(/\D/g, '').slice(0, 6));
  }

  verifyOtp(): void {
    if (this.submitting()) return;
    if (!this.codeValid()) {
      this.errorMessage.set('Enter the 6-digit code from the email.');
      return;
    }
    this.submitting.set(true);
    this.errorMessage.set('');
    this.auth.verifyOfficerOtp(this.email().trim(), this.code()).subscribe({
      next: (session) => {
        this.submitting.set(false);
        this.code.set('');
        this.auth.applySession(session);
        this.router.navigateByUrl('/gate/events', { replaceUrl: true });
      },
      error: (err) => {
        this.submitting.set(false);
        this.code.set('');
        this.errorMessage.set(officerOtpErrorMessage(err, 'verify'));
      },
    });
  }

  changeEmail(): void {
    this.step.set('email');
    this.code.set('');
    this.errorMessage.set('');
    this.infoMessage.set('');
  }

  private setCooldown(resendAvailableAt: string): void {
    const at = Date.parse(utcIso(resendAvailableAt) ?? '');
    this.now.set(Date.now());
    this.resendAvailableAt.set(Number.isNaN(at) ? Date.now() + 60_000 : at);
    this.stopTicker();
    // Outside the zone so the countdown does not keep the app "busy"; signals still refresh the view.
    this.zone.runOutsideAngular(() => {
      this.ticker = setInterval(() => {
        this.now.set(Date.now());
        if (this.resendSecondsLeft() === 0) this.stopTicker();
      }, 1000);
    });
  }

  private stopTicker(): void {
    if (this.ticker !== null) clearInterval(this.ticker);
    this.ticker = null;
  }
}
