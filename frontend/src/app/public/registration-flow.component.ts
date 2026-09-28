import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { GuestsApiService } from '../core/guests-api.service';
import { apiErrorMessage } from '../core/http-error';
import type { GuestPass, OtpSent, PublicEventInfo } from '../core/models';
import { ButtonComponent } from '../ui/button/button.component';
import { CardComponent } from '../ui/card/card.component';
import { InputComponent } from '../ui/input/input.component';
import { SpinnerComponent } from '../ui/spinner/spinner.component';
import {
  emailError,
  employeeIdError,
  guestCountError,
  isFormValid,
  mobileError,
  personNameError,
  resizeGuestNames,
  toRegistrationPayload,
  type RegistrationFormValue,
} from './registration-form';

type Step = 'loading' | 'not-open' | 'register' | 'verify' | 'pass' | 'error';

/**
 * Public, no-login flow opened from an event's registration link (`/register/:eventPublicId`):
 * view event → employee enters their details and accompanying guests → verify email OTP → one QR
 * pass for the whole party. Mirrors `backend/app/modules/guests/router.py`.
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

  private readonly eventPublicId = this.route.snapshot.paramMap.get('eventPublicId') ?? '';

  readonly employeeIdError = employeeIdError;
  readonly personNameError = personNameError;
  readonly emailError = emailError;
  readonly mobileError = mobileError;

  readonly step = signal<Step>('loading');
  readonly errorMessage = signal('');
  readonly submitting = signal(false);

  readonly event = signal<PublicEventInfo | null>(null);
  readonly employeeId = signal('');
  readonly employeeName = signal('');
  readonly email = signal('');
  readonly mobile = signal('');
  readonly guestCount = signal<number | null>(0);
  /** One entry per guest; kept in step with `guestCount`, preserving names at indexes that remain. */
  readonly guestNames = signal<string[]>([]);
  readonly consent = signal(false);
  /** Fields the employee has left, plus every field once they try to submit, to show inline errors. */
  readonly touched = signal<ReadonlySet<string>>(new Set());
  readonly submitAttempted = signal(false);

  readonly maxGuests = computed(() => this.event()?.max_guests_per_registration ?? 0);
  readonly seatsLeft = computed(() => this.event()?.seats_left ?? 0);
  readonly guestCountError = computed(() => guestCountError(this.guestCount(), this.maxGuests(), this.seatsLeft()));
  readonly formValue = computed<RegistrationFormValue>(() => ({
    employeeId: this.employeeId(),
    employeeName: this.employeeName(),
    email: this.email(),
    mobile: this.mobile(),
    guestCount: this.guestCount(),
    guestNames: this.guestNames(),
    consent: this.consent(),
  }));
  readonly formValid = computed(() => isFormValid(this.formValue(), this.maxGuests(), this.seatsLeft()));

  readonly otpSent = signal<OtpSent | null>(null);
  readonly otpCode = signal('');
  readonly resendCooldownUntil = signal<Date | null>(null);

  readonly pass = signal<GuestPass | null>(null);

  constructor() {
    this.loadEvent();
  }

  private loadEvent(): void {
    this.guests.getEvent(this.eventPublicId).subscribe({
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

  setGuestCount(value: number | string | null): void {
    const count = value === null || value === '' ? null : Number(value);
    this.guestCount.set(count);
    if (count !== null && Number.isInteger(count) && count >= 0 && count <= this.maxGuests()) {
      this.guestNames.set(resizeGuestNames(this.guestNames(), count));
    }
  }

  setGuestName(index: number, name: string): void {
    this.guestNames.update((names) => names.map((current, i) => (i === index ? name : current)));
  }

  markTouched(field: string): void {
    this.touched.update((fields) => new Set(fields).add(field));
  }

  /** Whether to show a field's inline error yet. */
  show(field: string): boolean {
    return this.submitAttempted() || this.touched().has(field);
  }

  submitRegistration(): void {
    this.submitAttempted.set(true);
    if (!this.formValid() || this.submitting()) {
      return;
    }
    this.submitting.set(true);
    this.errorMessage.set('');
    this.guests
      .register(this.eventPublicId, toRegistrationPayload(this.formValue()))
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

  /** File name for the downloaded pass, e.g. `diwali-night-pass.svg`. */
  passFileName(): string {
    const slug = (this.pass()?.event.title ?? 'event')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-|-$/g, '');
    return `${slug || 'event'}-pass.svg`;
  }

  printPass(): void {
    window.print();
  }

  canResend(): boolean {
    const until = this.resendCooldownUntil();
    return !until || until.getTime() <= Date.now();
  }
}
