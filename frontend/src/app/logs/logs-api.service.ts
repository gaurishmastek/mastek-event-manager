import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, InjectionToken, NgZone, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { Facets, Histogram, LIST_FILTERS, LiveEvent, LogEntry, LogFilters, LogPage, LogsStatus } from './logs.models';

/** Base URL of the logs API. Override it in your app's providers if the API lives elsewhere. */
export const LOGS_API_BASE = new InjectionToken<string>('LOGS_API_BASE', {
  providedIn: 'root',
  factory: () => '/api/logs',
});

/**
 * Extra query parameters sent with every logs API call, including the Live stream
 * and downloads (which cannot carry custom headers). Use it to pass an auth token:
 *   { provide: LOGS_EXTRA_PARAMS, useFactory: () => { const auth = inject(AuthService); return () => ({ token: auth.getToken() ?? '' }); } }
 */
export const LOGS_EXTRA_PARAMS = new InjectionToken<() => Record<string, string>>('LOGS_EXTRA_PARAMS', {
  providedIn: 'root',
  factory: () => () => ({}),
});

@Injectable({ providedIn: 'root' })
export class LogsApiService {
  private http = inject(HttpClient);
  private zone = inject(NgZone);
  private base = inject(LOGS_API_BASE);
  private extraParams = inject(LOGS_EXTRA_PARAMS);

  list(filters: LogFilters, cursor?: string | null, limit = 50): Observable<LogPage> {
    let params = this.params(filters).set('limit', limit);
    if (cursor) params = params.set('cursor', cursor);
    return this.http.get<LogPage>(this.base, { params });
  }

  facets(filters: LogFilters): Observable<Facets> {
    return this.http.get<Facets>(`${this.base}/facets`, { params: this.params(filters) });
  }

  histogram(filters: LogFilters, buckets = 60): Observable<Histogram> {
    return this.http.get<Histogram>(`${this.base}/histogram`, {
      params: this.params(filters).set('buckets', buckets),
    });
  }

  status(): Observable<LogsStatus> {
    return this.http.get<LogsStatus>(`${this.base}/status`, { params: this.withExtras(new HttpParams()) });
  }

  /** Demo only: ask the backend to insert fake logs (needs LOGS_ENABLE_DEMO_DATA=true). */
  seedDemo(count: number, hours: number): Observable<{ inserted: number }> {
    const params = this.withExtras(new HttpParams().set('count', count).set('hours', hours));
    return this.http.post<{ inserted: number }>(`${this.base}/demo/seed`, null, { params });
  }

  get(id: string): Observable<LogEntry> {
    return this.http.get<LogEntry>(`${this.base}/${encodeURIComponent(id)}`, { params: this.withExtras(new HttpParams()) });
  }

  exportUrl(filters: LogFilters, format: 'json' | 'csv'): string {
    return `${this.base}/export?${this.params(filters).set('format', format).toString()}`;
  }

  /** New entries as they arrive (Server-Sent Events). Unsubscribe to stop. */
  stream(filters: LogFilters): Observable<LiveEvent> {
    return new Observable<LiveEvent>((subscriber) => {
      if (typeof EventSource === 'undefined') {
        subscriber.next({ type: 'failure', detail: 'This browser does not support live streaming.' });
        subscriber.complete();
        return;
      }
      const emit = (event: LiveEvent) => this.zone.run(() => subscriber.next(event));
      const source = new EventSource(`${this.base}/stream?${this.params(filters).toString()}`);
      source.onopen = () => emit({ type: 'open' });
      // EventSource reconnects by itself and resumes from the last event id.
      source.onerror = () => emit({ type: 'reconnecting' });
      source.addEventListener('ready', () => emit({ type: 'open' }));
      source.addEventListener('log', (event) =>
        emit({ type: 'log', entry: JSON.parse((event as MessageEvent).data) as LogEntry }),
      );
      source.addEventListener('failure', (event) => {
        let detail = 'The live stream failed.';
        try {
          detail = JSON.parse((event as MessageEvent).data).detail ?? detail;
        } catch {}
        emit({ type: 'failure', detail });
      });
      return () => source.close();
    });
  }

  params(filters: LogFilters): HttpParams {
    let params = new HttpParams().set('range', filters.range);
    if (filters.q.trim()) params = params.set('q', filters.q.trim());
    if (filters.path.trim()) params = params.set('path', filters.path.trim());
    for (const name of LIST_FILTERS) {
      for (const value of filters[name]) params = params.append(name, value);
    }
    return this.withExtras(params);
  }

  private withExtras(params: HttpParams): HttpParams {
    for (const [key, value] of Object.entries(this.extraParams())) {
      if (value) params = params.set(key, value);
    }
    return params;
  }
}
