import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { environment } from '../../environments/environment';
import type { AttendanceDeclined, GuestPass, OtpSent, PublicEventInfo, RegistrationCreate } from './models';

/** `backend/app/modules/guests/router.py`, mounted under `/public`. No auth: employees register from the event's public link. */
@Injectable({ providedIn: 'root' })
export class GuestsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/public`;

  /** `eventPublicId` is the event's UUID from its registration link, never the internal numeric id. */
  getEvent(eventPublicId: string) {
    return this.http.get<PublicEventInfo>(`${this.base}/events/${encodeURIComponent(eventPublicId)}`);
  }

  register(eventPublicId: string, payload: RegistrationCreate) {
    return this.http.post<OtpSent>(`${this.base}/events/${encodeURIComponent(eventPublicId)}/registrations`, payload);
  }

  resendOtp(registrationId: string) {
    return this.http.post<OtpSent>(`${this.base}/registrations/${registrationId}/otp`, {});
  }

  verifyOtp(registrationId: string, code: string) {
    return this.http.post<GuestPass | AttendanceDeclined>(`${this.base}/registrations/${registrationId}/verify`, { code });
  }
}
