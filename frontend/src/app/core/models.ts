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

// ---- Events (backend/app/modules/events) ----------------------------------

export interface EventRead {
  id: number;
  title: string;
  description: string | null;
  location: string;
  starts_at: string;
  ends_at: string | null;
  capacity: number;
  created_at: string;
  updated_at: string;
  created_by: number | null;
  updated_by: number | null;
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
}

export type EventUpdate = Partial<EventCreate>;

// ---- Public guest registration (backend/app/modules/guests) ---------------

export interface PublicEventRead {
  id: number;
  title: string;
  description: string | null;
  location: string;
  starts_at: string;
  ends_at: string | null;
}

export interface PublicEventInfo extends PublicEventRead {
  registration_open: boolean;
  seats_left: number;
}

export interface RegistrationCreate {
  guest_name: string;
  mobile: string;
  consent: true;
}

export interface OtpSent {
  registration_id: string;
  mobile: string;
  otp_expires_at: string;
  resend_available_at: string;
}

export interface OtpVerify {
  code: string;
}

export interface GuestPass {
  registration_id: string;
  status: string;
  guest_name: string;
  event: PublicEventRead;
  qr_token: string;
  qr_svg: string;
  issued_at: string;
}

// ---- Gate scanning (backend/app/modules/gate) ------------------------------

export type ScanResult = 'ADMITTED' | 'ALREADY_CHECKED_IN' | 'WRONG_EVENT' | 'INVALID' | 'GATE_CLOSED';

export interface ScannedGuest {
  name: string;
  mobile: string;
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

export interface ApiError {
  error: {
    code: string;
    message: string;
    request_id?: string;
  };
}
