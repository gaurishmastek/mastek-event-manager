import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { environment } from '../../environments/environment';
import type { DecisionRequest, EntryPage, ScanRequest, ScanResponse } from './models';

/** `backend/app/modules/gate/router.py` — security officers (assigned event) and admins. */
@Injectable({ providedIn: 'root' })
export class GateApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/gate`;

  /** Looks a pass up. Nobody is admitted until the officer approves with `decide`. */
  scan(eventId: number, payload: ScanRequest) {
    return this.http.post<ScanResponse>(`${this.base}/events/${eventId}/scan`, payload);
  }

  /** The officer's approve or reject for a scanned pass. */
  decide(eventId: number, payload: DecisionRequest) {
    return this.http.post<ScanResponse>(`${this.base}/events/${eventId}/decision`, payload);
  }

  entries(eventId: number, limit = 20, offset = 0) {
    const params = new HttpParams().set('limit', limit).set('offset', offset);
    return this.http.get<EntryPage>(`${this.base}/events/${eventId}/entries`, { params });
  }
}
