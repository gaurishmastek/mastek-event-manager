/**
 * Shapes mirror the FastAPI Pydantic schemas in `backend/app/modules/**\/schemas.py`.
 * Keep in sync with the backend when its schemas change.
 */

export type StaffRole = 'admin' | 'security_officer';

export interface CurrentUser {
  id: number;
  role: StaffRole;
  name?: string;
}

// ---- Staff accounts (backend/app/modules/users) ---------------------------

/** `UserRead`: never carries the password hash or the (encrypted) mobile. */
export interface StaffUser {
  id: number;
  email: string;
  full_name: string;
  role: StaffRole;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

/** A security officer account. Officers sign in with an emailed code, so there is no password field. */
export interface SecurityOfficerCreate {
  email: string;
  full_name: string;
  mobile?: string | null;
  role: 'security_officer';
}

export interface OfficerOtpSent {
  resend_available_at: string;
}

export interface StaffSession {
  access_token: string;
  token_type?: string;
  expires_in?: number;
  user: CurrentUser;
}

// ---- Events (backend/app/modules/events) ----------------------------------

export interface EventRead {
  id: number;
  /** Random UUID for the public registration link `/register/{public_id}`. Never use `id` in public links. */
  public_id: string;
  title: string;
  description: string | null;
  location: string;
  starts_at: string;
  ends_at: string | null;
  capacity: number;
  max_guests_per_registration: number;
  created_at: string;
  updated_at: string;
  created_by: number | null;
  updated_by: number | null;
  /** Naive UTC. When the gate starts accepting scans (server setting, before `starts_at`). */
  gate_opens_at: string;
  /** Naive UTC. When the gate stops accepting scans. */
  gate_closes_at: string;
}

export interface EventPage {
  items: EventRead[];
  total: number;
  limit: number;
  offset: number;
}

export interface EventCreate {
  title: string;
  description?: string | null;
  location: string;
  starts_at: string;
  ends_at?: string | null;
  capacity: number;
  max_guests_per_registration: number;
}

export type EventUpdate = Partial<EventCreate>;

// ---- Public guest registration (backend/app/modules/guests) ---------------

export interface PublicEventRead {
  public_id: string;
  title: string;
  description: string | null;
  location: string;
  starts_at: string;
  ends_at: string | null;
  max_guests_per_registration: number;
}

export interface PublicEventInfo extends PublicEventRead {
  registration_open: boolean;
  seats_left: number;
}

export type FoodPreference = 'VEG' | 'JAIN' | 'FAST_FOOD';

/**
 * The public form. Send only the answers that apply: nothing after `attending` when not attending, and no family
 * members when attending alone. The backend rejects inapplicable details rather than ignoring them.
 */
export interface RegistrationCreate {
  employee_id: string;
  employee_name: string;
  email: string;
  /** Indian mobile number; the backend stores it as +91XXXXXXXXXX. OTPs still go by email only. */
  mobile: string;
  attending: boolean;
  family_attending?: boolean;
  accompanying_adult?: boolean;
  /** Required when `accompanying_adult` is true. */
  adult_name?: string | null;
  accompanying_kids?: boolean;
  /** 1 to 3 names (`MAX_KIDS`) when `accompanying_kids` is true. */
  kid_names?: string[];
  /** Each kid's age in whole years (0 to 17), in the same order as `kid_names`. */
  kid_ages?: number[];
  food_preference?: FoodPreference | null;
  consent: true;
}

export interface OtpSent {
  registration_id: string;
  /** Masked address the code was sent to, e.g. as•••@example.com */
  email: string;
  otp_expires_at: string;
  resend_available_at: string;
}

export interface OtpVerify {
  code: string;
}

export interface GuestPass {
  registration_id: string;
  status: string;
  attending: true;
  employee_id: string | null;
  employee_name: string;
  /** Every accompanying guest: the adult first, then the kids. */
  guest_names: string[];
  adult_name: string | null;
  kid_names: string[];
  /** Ages in the same order as `kid_names`; null for kids registered before ages were asked. */
  kid_ages: (number | null)[];
  food_preference: FoodPreference | null;
  /** The employee plus their guests; the one pass admits all of them once. */
  party_size: number;
  event: PublicEventRead;
  qr_token: string;
  qr_svg: string;
  issued_at: string;
}

/** Verification result for an employee who said they will not attend: recorded, with no seat and no pass. */
export interface AttendanceDeclined {
  registration_id: string;
  status: 'DECLINED';
  attending: false;
  employee_id: string | null;
  employee_name: string;
  event: PublicEventRead;
  verified_at: string;
}

// ---- Gate scanning (backend/app/modules/gate) ------------------------------

export type ScanResult = 'admitted' | 'already_checked_in' | 'wrong_event' | 'invalid' | 'gate_closed';

/** The registered party behind a pass. Only returned for admitted or already-used passes. */
export interface ScannedGuest {
  /** The employee's name. */
  name: string;
  /** Masked email (or masked mobile for registrations made before OTPs moved to email). */
  contact: string;
  employee_id: string | null;
  guest_names: string[];
  party_size: number;
  email_masked: string | null;
  mobile_masked: string | null;
}

export interface ScanRequest {
  token: string;
  gate?: string | null;
}

export interface ScanResponse {
  result: ScanResult;
  message: string;
  guest: ScannedGuest | null;
  checked_in_at: string | null;
  gate: string | null;
}

export interface EntryRead {
  guest: ScannedGuest;
  checked_in_at: string;
  gate: string | null;
  officer_id: number;
}

export interface EntryPage {
  items: EntryRead[];
  total: number;
  limit: number;
  offset: number;
}

// ---- Admin registrations list (backend/app/modules/guests/admin_router.py) --

export type RegistrationStatus = 'PENDING_OTP' | 'VERIFIED' | 'CHECKED_IN' | 'DECLINED';

export interface RegistrationAdminRead {
  registration_id: string;
  employee_id: string | null;
  employee_name: string;
  email_masked: string | null;
  mobile_masked: string | null;
  attending: boolean;
  family_attending: boolean | null;
  guest_names: string[];
  adult_name: string | null;
  kid_names: string[];
  /** Ages in the same order as `kid_names`; null for kids registered before ages were asked. */
  kid_ages: (number | null)[];
  food_preference: FoodPreference | null;
  number_of_guests: number;
  party_size: number;
  status: RegistrationStatus;
  verified_at: string | null;
  qr_issued: boolean;
  qr_issued_at: string | null;
  checked_in_at: string | null;
  created_at: string;
}

export interface RegistrationAdminPage {
  items: RegistrationAdminRead[];
  total: number;
  limit: number;
  offset: number;
}

/** Admin correction payload. `email` is omitted to preserve the existing contact address. */
export interface RegistrationAdminUpdate {
  employee_id: string;
  employee_name: string;
  email?: string;
  adult_name: string | null;
  kid_names: string[];
  kid_ages: number[];
}

/** A one-time QR SVG returned only to an admin so it can be downloaded and shared manually. */
export interface AdminQrPass {
  registration_id: string;
  employee_name: string;
  qr_svg: string;
  issued_at: string;
}

export interface ApiError {
  error: {
    code: string;
    message: string;
    request_id?: string;
  };
}
