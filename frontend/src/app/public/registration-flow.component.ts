import { DatePipe } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { GuestsApiService } from '../core/guests-api.service';
import { apiErrorMessage } from '../core/http-error';
import type { AttendanceDeclined, GuestPass, OtpSent, PublicEventInfo } from '../core/models';
import { IST, utcIso } from '../core/time';
import { ButtonComponent } from '../ui/button/button.component';
import { CardComponent } from '../ui/card/card.component';
import { InputComponent } from '../ui/input/input.component';
import { SpinnerComponent } from '../ui/spinner/spinner.component';
import {
  clearInapplicable,
  emailError,
  employeeIdError,
  familyMembersError,
  FOOD_PREFERENCES,
  foodPreferenceError,
  isFormValid,
  kidAgeError,
  kidsError,
  MAX_KID_AGE,
  MIN_KID_AGE,
  MAX_KIDS,
  mobileError,
  partyError,
  personNameError,
  toRegistrationPayload,
  yesNoError,
  type FoodPreference,
  type RegistrationFormValue,
} from './registration-form';

type Step = 'loading' | 'not-open' | 'register' | 'verify' | 'pass' | 'declined' | 'error';

const EMPTY_ANSWERS = {
  attending: null,
  familyAttending: null,
  withAdult: false,
  withKids: false,
  adultName: '',
  kidNames: [],
  kidAges: [],
  foodPreference: null,
} satisfies Partial<RegistrationFormValue>;

/**
 * Public, no-login flow opened from an event's registration link (`/register/:eventPublicId`):
 * view event → employee enters their details, whether they will attend, their accompanying family and food
 * preference → verify email OTP → one QR pass for the whole party, or a recorded decline for an employee who
 * will not attend. Mirrors `backend/app/modules/guests/router.py`.
 */
@Component({
  selector: 'app-registration-flow',
  standalone: true,
  imports: [DatePipe, FormsModule, ButtonComponent, CardComponent, InputComponent, SpinnerComponent],
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
  readonly yesNoError = yesNoError;
  readonly foodPreferences = FOOD_PREFERENCES;
  readonly maxKids = MAX_KIDS;
  readonly minKidAge = MIN_KID_AGE;
  readonly maxKidAge = MAX_KID_AGE;
  readonly kidAgeError = kidAgeError;
  readonly ist = IST;

  readonly step = signal<Step>('loading');
  readonly errorMessage = signal('');
  readonly submitting = signal(false);

  readonly event = signal<PublicEventInfo | null>(null);
  readonly employeeId = signal('');
  readonly employeeName = signal('');
  readonly email = signal('');
  readonly mobile = signal('');
  /** Attendance, family and food answers. Always kept with inapplicable answers cleared (`clearInapplicable`). */
  readonly answers = signal<Pick<RegistrationFormValue, keyof typeof EMPTY_ANSWERS>>(EMPTY_ANSWERS);
  readonly consent = signal(false);
  /** Fields the employee has left, plus every field once they try to submit, to show inline errors. */
  readonly touched = signal<ReadonlySet<string>>(new Set());
  readonly submitAttempted = signal(false);

  readonly maxGuests = computed(() => this.event()?.max_guests_per_registration ?? 0);
  readonly seatsLeft = computed(() => this.event()?.seats_left ?? 0);
  /** The event date for the attendance question, e.g. "Tuesday, 20 October 2026", in Mumbai time. */
  readonly eventStartsAt = computed(() => utcIso(this.event()?.starts_at));
  readonly formValue = computed<RegistrationFormValue>(() => ({
    employeeId: this.employeeId(),
    employeeName: this.employeeName(),
    email: this.email(),
    mobile: this.mobile(),
    ...this.answers(),
    consent: this.consent(),
  }));
  readonly familyMembersError = computed(() => familyMembersError(this.formValue()));
  readonly kidsError = computed(() => kidsError(this.formValue()));
  readonly foodPreferenceError = computed(() => foodPreferenceError(this.formValue()));
  readonly foodPreferenceRequired = computed(() =>
    !!foodPreferenceError({ ...this.formValue(), foodPreference: null }),
  );
  readonly partyError = computed(() => partyError(this.formValue(), this.maxGuests(), this.seatsLeft()));
  readonly formValid = computed(() => isFormValid(this.formValue(), this.maxGuests(), this.seatsLeft()));

  readonly otpSent = signal<OtpSent | null>(null);
  readonly otpCode = signal('');
  readonly resendCooldownUntil = signal<Date | null>(null);

  readonly pass = signal<GuestPass | null>(null);
  readonly declined = signal<AttendanceDeclined | null>(null);

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

  /** Change answers, clearing anything a changed answer makes inapplicable. */
  private updateAnswers(change: Partial<RegistrationFormValue>): void {
    const next = clearInapplicable({ ...this.formValue(), ...change });
    this.answers.set({
      attending: next.attending,
      familyAttending: next.familyAttending,
      withAdult: next.withAdult,
      withKids: next.withKids,
      adultName: next.adultName,
      kidNames: next.kidNames,
      kidAges: next.kidAges,
      foodPreference: next.foodPreference,
    });
  }

  setAttending(attending: boolean): void {
    this.updateAnswers({ attending });
  }

  setFamilyAttending(familyAttending: boolean): void {
    this.updateAnswers({ familyAttending });
  }

  setWithAdult(withAdult: boolean): void {
    this.updateAnswers({ withAdult });
  }

  /** Ticking Kids starts with one name and age row, since at least one kid is required. */
  setWithKids(withKids: boolean): void {
    this.updateAnswers({ withKids, kidNames: withKids ? [''] : [], kidAges: withKids ? [''] : [] });
  }

  setAdultName(adultName: string): void {
    this.updateAnswers({ adultName });
  }

  setFoodPreference(foodPreference: FoodPreference): void {
    this.updateAnswers({ foodPreference });
  }

  setKidName(index: number, name: string): void {
    this.updateAnswers({ kidNames: this.answers().kidNames.map((current, i) => (i === index ? name : current)) });
  }

  setKidAge(index: number, age: string | number | null): void {
    const value = age === null ? '' : String(age);
    this.updateAnswers({ kidAges: this.answers().kidAges.map((current, i) => (i === index ? value : current)) });
  }

  addKid(): void {
    const { kidNames, kidAges } = this.answers();
    if (kidNames.length >= MAX_KIDS) return;
    this.updateAnswers({ kidNames: [...kidNames, ''], kidAges: [...kidAges, ''] });
    // Move focus to the new field so keyboard and screen-reader users land where they will type.
    setTimeout(() => document.getElementById(`kid-name-${kidNames.length}`)?.focus());
  }

  removeKid(index: number): void {
    const kidNames = this.answers().kidNames.filter((_, i) => i !== index);
    const kidAges = this.answers().kidAges.filter((_, i) => i !== index);
    this.updateAnswers({ kidNames, kidAges });
    // Field positions shift, so forget which kid fields were touched rather than blame the wrong one.
    this.touched.update((fields) => new Set([...fields].filter((field) => !field.startsWith('kid'))));
    setTimeout(() => document.getElementById(`kid-name-${Math.min(index, kidNames.length - 1)}`)?.focus());
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
      next: (result) => {
        this.submitting.set(false);
        if (result.attending === false) {
          this.declined.set(result);
          this.step.set('declined');
        } else {
          this.pass.set(result);
          this.step.set('pass');
        }
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

  foodLabel(value: FoodPreference | null): string {
    return this.foodPreferences.find((option) => option.value === value)?.label ?? '';
  }

  printPass(): void {
    window.print();
  }

  canResend(): boolean {
    const until = this.resendCooldownUntil();
    return !until || until.getTime() <= Date.now();
  }
}
