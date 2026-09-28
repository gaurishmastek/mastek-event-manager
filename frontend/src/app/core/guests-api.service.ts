import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { environment } from '../../environments/environment';
import type { GuestPass, OtpSent, PublicEventInfo, RegistrationCreate } from './models';

/** `backend/app/modules/guests/router.py`, mounted under `/public`. No auth — anonymous guests. */
@Injectable({ providedIn: 'root' })
export class GuestsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/public`;

  getEvent(eventId: number) {
    return this.http.get<PublicEventInfo>(`${this.base}/events/${eventId}`);
  }

  register(eventId: number, payload: RegistrationCreate) {
    return this.http.post<OtpSent>(`${this.base}/events/${eventId}/registrations`, payload);
  }

  resendOtp(registrationId: string) {
    return this.http.post<OtpSent>(`${this.base}/registrations/${registrationId}/otp`, {});
  }

  verifyOtp(registrationId: string, code: string) {
    return this.http.post<GuestPass>(`${this.base}/registrations/${registrationId}/verify`, { code });
  }
}
