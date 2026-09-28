/**
 * Validation and shaping for the public employee registration form. Mirrors the backend rules in
 * `backend/app/modules/guests/schemas.py` and `backend/app/core/mobile.py`, which stay authoritative.
 */

import type { RegistrationCreate } from '../core/models';

const EMPLOYEE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
// Control characters other than tab, newline and carriage return, matching the backend.
const CONTROL_CHARS = /[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/;
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const INDIAN_MOBILE = /^(?:\+91|91|0)?[6-9]\d{9}$/;
const MOBILE_SEPARATORS = /[\s\-()]/g;

export interface RegistrationFormValue {
  employeeId: string;
  employeeName: string;
  email: string;
  mobile: string;
  guestCount: number | null;
  guestNames: string[];
  consent: boolean;
}

/**
 * The guest-name list for a new guest count: names at indexes that still exist are kept, new
 * indexes start empty, and names beyond the count are dropped.
 */
export function resizeGuestNames(names: readonly string[], count: number): string[] {
  const size = Number.isInteger(count) && count > 0 ? count : 0;
  return Array.from({ length: size }, (_, index) => names[index] ?? '');
}

export function employeeIdError(value: string): string | null {
  const id = value.trim();
  if (!id) return 'Enter your employee ID.';
  if (id.length > 30) return 'Employee ID must be 30 characters or fewer.';
  if (!EMPLOYEE_ID.test(id)) return 'Use only letters, digits, hyphens, underscores and periods.';
  return null;
}

export function personNameError(value: string, who = 'name'): string | null {
  const name = value.trim();
  if (!name) return `Enter a ${who}.`;
  if (CONTROL_CHARS.test(name) || /[\r\n]/.test(name)) return 'Use a single line of plain text.';
  if (name.length < 2) return 'Must be at least 2 characters.';
  if (name.length > 100) return 'Must be 100 characters or fewer.';
  return null;
}

export function emailError(value: string): string | null {
  const email = value.trim();
  if (!email) return 'Enter your email address.';
  if (email.length > 254 || !EMAIL.test(email)) return 'Enter a valid email address, e.g. you@example.com.';
  return null;
}

export function mobileError(value: string): string | null {
  const mobile = value.replace(MOBILE_SEPARATORS, '');
  if (!mobile) return 'Enter your mobile number.';
  if (!INDIAN_MOBILE.test(mobile)) return 'Enter a valid Indian mobile number, e.g. 98765 43210.';
  return null;
}

/** `maxGuests` is the event's limit; `seatsLeft` counts people, so the employee needs one of them. */
export function guestCountError(count: number | null, maxGuests: number, seatsLeft: number): string | null {
  if (count === null || !Number.isInteger(count)) return 'Enter the number of guests as a whole number.';
  if (count < 0) return 'The number of guests cannot be negative.';
  if (count > maxGuests) return `You can bring at most ${maxGuests} guest${maxGuests === 1 ? '' : 's'}.`;
  if (1 + count > seatsLeft) {
    return seatsLeft <= 0
      ? 'This event is full.'
      : `Only ${seatsLeft} seat${seatsLeft === 1 ? '' : 's'} left, including you.`;
  }
  return null;
}

export function isFormValid(form: RegistrationFormValue, maxGuests: number, seatsLeft: number): boolean {
  return (
    form.consent &&
    !employeeIdError(form.employeeId) &&
    !personNameError(form.employeeName) &&
    !emailError(form.email) &&
    !mobileError(form.mobile) &&
    !guestCountError(form.guestCount, maxGuests, seatsLeft) &&
    resizeGuestNames(form.guestNames, form.guestCount ?? 0).every((name) => !personNameError(name))
  );
}

/** The request body: trimmed, with exactly `guestCount` guest names. */
export function toRegistrationPayload(form: RegistrationFormValue): RegistrationCreate {
  const count = form.guestCount ?? 0;
  return {
    employee_id: form.employeeId.trim(),
    employee_name: form.employeeName.trim(),
    email: form.email.trim(),
    mobile: form.mobile.trim(),
    number_of_guests: count,
    guest_names: resizeGuestNames(form.guestNames, count).map((name) => name.trim()),
    consent: true,
  };
}
