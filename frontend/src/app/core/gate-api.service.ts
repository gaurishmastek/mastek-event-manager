import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { environment } from '../../environments/environment';
import type { EntryPage, ScanRequest, ScanResponse } from './models';

/** `backend/app/modules/gate/router.py` — security officers (assigned event) and admins. */
@Injectable({ providedIn: 'root' })
export class GateApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/gate`;

  scan(eventId: number, payload: ScanRequest) {
    return this.http.post<ScanResponse>(`${this.base}/events/${eventId}/scan`, payload);
  }

  entries(eventId: number, limit = 20, offset = 0) {
    const params = new HttpParams().set('limit', limit).set('offset', offset);
    return this.http.get<EntryPage>(`${this.base}/events/${eventId}/entries`, { params });
  }
}
