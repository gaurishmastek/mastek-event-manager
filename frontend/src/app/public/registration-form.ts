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

export type FoodPreference = 'VEG' | 'JAIN' | 'FAST_FOOD';

export const FOOD_PREFERENCES: readonly { value: FoodPreference; label: string }[] = [
  { value: 'VEG', label: 'Veg' },
  { value: 'JAIN', label: 'Jain' },
  { value: 'FAST_FOOD', label: 'Fast Food' },
];

/** Kids' ages are whole years in this range. Mirrors `MIN_KID_AGE`/`MAX_KID_AGE` in `backend/app/modules/guests/models.py`. */
export const MIN_KID_AGE = 0;
export const MAX_KID_AGE = 17;

/** An attending employee may bring one adult family member and up to this many kids. */
export const MAX_KIDS = 3;

/**
 * Whether an employee attending alone must still choose a food preference. Attendees who bring family always must.
 * Mirrors `FOOD_PREFERENCE_REQUIRED_WHEN_ALONE` in `backend/app/modules/guests/schemas.py`.
 */
export const FOOD_PREFERENCE_REQUIRED_WHEN_ALONE = true;

export interface RegistrationFormValue {
  employeeId: string;
  employeeName: string;
  email: string;
  mobile: string;
  /** "Will you be attending the event?" — null until answered. */
  attending: boolean | null;
  /** "Will you be accompanied by your family members?" — null until answered. */
  familyAttending: boolean | null;
  withAdult: boolean;
  withKids: boolean;
  adultName: string;
  kidNames: string[];
  /** Each kid's age as typed, at the same index as their name. */
  kidAges: string[];
  foodPreference: FoodPreference | null;
  consent: boolean;
}

/**
 * The form with every answer that no longer applies cleared: not attending clears the family and food answers,
 * attending alone clears the family members, and unticking Adult or Kids clears those names. Hidden fields
 * therefore never keep stale values or block submission.
 */
export function clearInapplicable(form: RegistrationFormValue): RegistrationFormValue {
  if (form.attending !== true) {
    return {
      ...form,
      familyAttending: null,
      withAdult: false,
      withKids: false,
      adultName: '',
      kidNames: [],
      kidAges: [],
      foodPreference: null,
    };
  }
  if (form.familyAttending !== true) {
    return { ...form, withAdult: false, withKids: false, adultName: '', kidNames: [], kidAges: [] };
  }
  const kidNames = form.withKids ? form.kidNames.slice(0, MAX_KIDS) : [];
  return {
    ...form,
    adultName: form.withAdult ? form.adultName : '',
    kidNames,
    // One age per kid name, always at the same index.
    kidAges: kidNames.map((_, index) => form.kidAges[index] ?? ''),
  };
}

/** Accompanying family members named on the form (adult first), who take seats alongside the employee. */
export function accompanyingCount(form: RegistrationFormValue): number {
  const applicable = clearInapplicable(form);
  if (applicable.familyAttending !== true) return 0;
  return (applicable.withAdult ? 1 : 0) + (applicable.withKids ? applicable.kidNames.length : 0);
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
  // if (!mobile) return 'Enter your mobile number.';
  if (mobile) {
    if (!INDIAN_MOBILE.test(mobile)) return 'Enter a valid Indian mobile number, e.g. 98765 43210.';
  }
  return null;
}

export function yesNoError(value: boolean | null): string | null {
  return value === null ? 'Please choose Yes or No.' : null;
}

/** Family members chosen but not who: at least one of Adult and Kids must be ticked. */
export function familyMembersError(form: RegistrationFormValue): string | null {
  if (form.attending !== true || form.familyAttending !== true) return null;
  return form.withAdult || form.withKids ? null : 'Select Adult, Kids or both.';
}

/** A kid's age as typed: a whole number of years from 0 to 17. */
export function kidAgeError(value: string): string | null {
  const age = value.trim();
  if (!age) return 'Enter an age.';
  if (!/^\d{1,2}$/.test(age) || Number(age) < MIN_KID_AGE || Number(age) > MAX_KID_AGE) {
    return `Enter an age from ${MIN_KID_AGE} to ${MAX_KID_AGE}.`;
  }
  return null;
}

export function kidsError(form: RegistrationFormValue): string | null {
  if (form.attending !== true || form.familyAttending !== true || !form.withKids) return null;
  if (form.kidNames.length === 0) return "Add at least one kid's name.";
  if (form.kidNames.length > MAX_KIDS) return `You can bring at most ${MAX_KIDS} kids.`;
  return null;
}

export function foodPreferenceError(form: RegistrationFormValue): string | null {
  if (form.attending !== true || form.foodPreference !== null) return null;
  const required = form.familyAttending === true || FOOD_PREFERENCE_REQUIRED_WHEN_ALONE;
  return required ? 'Please choose a food preference.' : null;
}

/** `maxGuests` is the event's limit; `seatsLeft` counts people, so the employee needs one of them. */
export function guestCountError(count: number | null, maxGuests: number, seatsLeft: number): string | null {
  if (count === null || !Number.isInteger(count)) return 'Enter the number of guests as a whole number.';
  if (count < 0) return 'The number of guests cannot be negative.';
  if (count > maxGuests) return `You can bring at most ${maxGuests} guest${maxGuests === 1 ? '' : 's'} to this event.`;
  if (1 + count > seatsLeft) {
    return seatsLeft <= 0
      ? 'This event is full.'
      : `Only ${seatsLeft} seat${seatsLeft === 1 ? '' : 's'} left, including you.`;
  }
  return null;
}

/** Seats and the event's guest limit only matter for employees who will attend. */
export function partyError(form: RegistrationFormValue, maxGuests: number, seatsLeft: number): string | null {
  if (form.attending !== true) return null;
  return guestCountError(accompanyingCount(form), maxGuests, seatsLeft);
}

export function isFormValid(form: RegistrationFormValue, maxGuests: number, seatsLeft: number): boolean {
  const applicable = clearInapplicable(form);
  const common =
    applicable.consent &&
    !employeeIdError(applicable.employeeId) &&
    !personNameError(applicable.employeeName) &&
    !emailError(applicable.email) &&
    !mobileError(applicable.mobile) &&
    !yesNoError(applicable.attending);
  if (!common) return false;
  if (applicable.attending === false) return true;
  return (
    !yesNoError(applicable.familyAttending) &&
    !familyMembersError(applicable) &&
    !(applicable.withAdult && personNameError(applicable.adultName)) &&
    !kidsError(applicable) &&
    applicable.kidNames.every((name) => !personNameError(name)) &&
    applicable.kidAges.every((age) => !kidAgeError(age)) &&
    !foodPreferenceError(applicable) &&
    !partyError(applicable, maxGuests, seatsLeft)
  );
}

/** The request body: trimmed, with only the answers that apply (see `clearInapplicable`). */
export function toRegistrationPayload(form: RegistrationFormValue): RegistrationCreate {
  const applicable = clearInapplicable(form);
  const base = {
    employee_id: applicable.employeeId.trim(),
    employee_name: applicable.employeeName.trim(),
    email: applicable.email.trim(),
    mobile: applicable.mobile.trim(),
    consent: true as const,
  };
  if (applicable.attending !== true) {
    return { ...base, attending: false };
  }
  const payload: RegistrationCreate = {
    ...base,
    attending: true,
    family_attending: applicable.familyAttending === true,
    food_preference: applicable.foodPreference,
  };
  if (applicable.familyAttending === true) {
    payload.accompanying_adult = applicable.withAdult;
    payload.adult_name = applicable.withAdult ? applicable.adultName.trim() : null;
    payload.accompanying_kids = applicable.withKids;
    payload.kid_names = applicable.kidNames.map((name) => name.trim());
    payload.kid_ages = applicable.kidAges.map((age) => Number(age.trim()));
  }
  return payload;
}
