import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { GuestsApiService } from '../core/guests-api.service';
import { apiErrorMessage } from '../core/http-error';
import type { GuestPass, OtpSent, PublicEventInfo } from '../core/models';
import { ButtonComponent } from '../ui/button/button.component';
import { CardComponent } from '../ui/card/card.component';
import { InputComponent } from '../ui/input/input.component';
import { SpinnerComponent } from '../ui/spinner/spinner.component';

type Step = 'loading' | 'not-open' | 'register' | 'verify' | 'pass' | 'error';

/**
 * Public, no-login guest flow: view event → register (name, mobile, consent) → verify OTP
 * → QR pass. Mirrors `backend/app/modules/guests/router.py`.
 */
@Component({
  selector: 'app-registration-flow',
  standalone: true,
  imports: [FormsModule, ButtonComponent, CardComponent, InputComponent, SpinnerComponent],
  templateUrl: './registration-flow.component.html',
})
export class RegistrationFlowComponent {
  private readonly route = inject(ActivatedRoute);
  private readonly guests = inject(GuestsApiService);

  private readonly eventId = Number(this.route.snapshot.paramMap.get('eventId'));

  readonly step = signal<Step>('loading');
  readonly errorMessage = signal('');
  readonly submitting = signal(false);

  readonly event = signal<PublicEventInfo | null>(null);
  readonly guestName = signal('');
  readonly mobile = signal('');
  readonly consent = signal(false);

  readonly otpSent = signal<OtpSent | null>(null);
  readonly otpCode = signal('');
  readonly resendCooldownUntil = signal<Date | null>(null);

  readonly pass = signal<GuestPass | null>(null);

  constructor() {
    this.loadEvent();
  }

  private loadEvent(): void {
    this.guests.getEvent(this.eventId).subscribe({
      next: (event) => {
        this.event.set(event);
        this.step.set(event.registration_open ? 'register' : 'not-open');
      },
      error: (err) => {
        this.errorMessage.set(apiErrorMessage(err, 'This event could not be found.'));
        this.step.set('error');
      },
    });
  }

  submitRegistration(): void {
    if (!this.consent() || !this.guestName().trim() || !this.mobile().trim()) {
      return;
    }
    this.submitting.set(true);
    this.errorMessage.set('');
    this.guests
      .register(this.eventId, {
        guest_name: this.guestName().trim(),
        mobile: this.mobile().trim(),
        consent: true,
      })
      .subscribe({
        next: (sent) => {
          this.submitting.set(false);
          this.otpSent.set(sent);
          this.resendCooldownUntil.set(new Date(sent.resend_available_at));
          this.step.set('verify');
        },
        error: (err) => {
          this.submitting.set(false);
          this.errorMessage.set(apiErrorMessage(err, 'Could not start registration. Please try again.'));
        },
      });
  }

  resendOtp(): void {
    const sent = this.otpSent();
    if (!sent) return;
    this.submitting.set(true);
    this.errorMessage.set('');
    this.guests.resendOtp(sent.registration_id).subscribe({
      next: (resent) => {
        this.submitting.set(false);
        this.otpSent.set(resent);
        this.resendCooldownUntil.set(new Date(resent.resend_available_at));
      },
      error: (err) => {
        this.submitting.set(false);
        this.errorMessage.set(apiErrorMessage(err, 'Could not resend the code.'));
      },
    });
  }

  submitOtp(): void {
    const sent = this.otpSent();
    if (!sent || this.otpCode().trim().length !== 6) return;
    this.submitting.set(true);
    this.errorMessage.set('');
    this.guests.verifyOtp(sent.registration_id, this.otpCode().trim()).subscribe({
      next: (pass) => {
        this.submitting.set(false);
        this.pass.set(pass);
        this.step.set('pass');
      },
      error: (err) => {
        this.submitting.set(false);
        this.errorMessage.set(apiErrorMessage(err, 'That code did not match. Please try again.'));
      },
    });
  }

  canResend(): boolean {
    const until = this.resendCooldownUntil();
    return !until || until.getTime() <= Date.now();
  }
}
