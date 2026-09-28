import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { environment } from '../../environments/environment';
import type { EventCreate, EventPage, EventRead, EventUpdate, RegistrationAdminPage, RegistrationStatus } from './models';

function toParams(params: Record<string, string | number | boolean | undefined | null>): HttpParams {
  let httpParams = new HttpParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') {
      httpParams = httpParams.set(key, String(value));
    }
  }
  return httpParams;
}

/** `backend/app/modules/events/router.py` — admin-only writes, admin/officer reads. */
@Injectable({ providedIn: 'root' })
export class EventsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/events`;

  list(params: { search?: string; upcoming?: boolean; limit?: number; offset?: number } = {}) {
    return this.http.get<EventPage>(this.base, { params: toParams(params) });
  }

  /** Admin only (`backend/app/modules/guests/admin_router.py`). Contacts come back masked. */
  registrations(
    eventId: number,
    params: { search?: string; status?: RegistrationStatus | ''; limit?: number; offset?: number } = {},
  ) {
    return this.http.get<RegistrationAdminPage>(`${this.base}/${eventId}/registrations`, { params: toParams(params) });
  }

  get(id: number) {
    return this.http.get<EventRead>(`${this.base}/${id}`);
  }

  create(payload: EventCreate) {
    return this.http.post<EventRead>(this.base, payload);
  }

  update(id: number, payload: EventUpdate) {
    return this.http.patch<EventRead>(`${this.base}/${id}`, payload);
  }

  delete(id: number) {
    return this.http.delete<void>(`${this.base}/${id}`);
  }
}
