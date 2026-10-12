import { Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Params, Router } from '@angular/router';
import { Subject, Subscription, catchError, forkJoin, of, switchMap, tap, timer } from 'rxjs';

import { FilterSidebarComponent } from './components/filter-sidebar.component';
import { LogDetailComponent } from './components/log-detail.component';
import { LogsTableComponent } from './components/logs-table.component';
import { LogsTimelineComponent } from './components/logs-timeline.component';
import { LogsToolbarComponent } from './components/logs-toolbar.component';
import { LogsApiService } from './logs-api.service';
import {
  DEFAULT_FILTERS,
  Facets,
  Histogram,
  LIST_FILTERS,
  LiveEvent,
  LiveStatus,
  LogEntry,
  LogFilters,
  TIME_RANGES,
  TimeRange,
} from './logs.models';

const LIVE_BUFFER_LIMIT = 1000;
// Demo mode only (backend LOGS_ENABLE_DEMO_DATA=true)
const SAMPLE_BATCH = { count: 300, hours: 24 };
const SAMPLE_TRICKLE_MS = 2500;

@Component({
  selector: 'app-logs-page',
  standalone: true,
  imports: [FilterSidebarComponent, LogsToolbarComponent, LogsTimelineComponent, LogsTableComponent, LogDetailComponent],
  templateUrl: './logs-page.component.html',
  styleUrl: './logs-page.component.css',
})
export class LogsPageComponent implements OnInit {
  private api = inject(LogsApiService);
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private destroyRef = inject(DestroyRef);

  /** Shown in the header; set `data: { title }` on the route to change it. */
  readonly projectName = signal<string>(this.route.snapshot.data['title'] ?? 'fastapi-logs-list');

  readonly filters = signal<LogFilters>({ ...DEFAULT_FILTERS });
  readonly entries = signal<LogEntry[]>([]);
  readonly nextCursor = signal<string | null>(null);
  readonly facets = signal<Facets | null>(null);
  readonly histogram = signal<Histogram | null>(null);
  readonly loading = signal(false);
  readonly loadingMore = signal(false);
  readonly error = signal<string | null>(null);
  readonly live = signal(false);
  readonly liveStatus = signal<LiveStatus>('off');
  readonly liveCount = signal(0);
  readonly liveError = signal<string | null>(null);
  readonly selected = signal<LogEntry | null>(null);
  readonly sidebarOpen = signal(true);
  readonly demoEnabled = signal(false);
  readonly generating = signal(false);
  readonly autoDemo = signal(true);

  readonly activeFilterCount = computed(() => {
    const f = this.filters();
    return LIST_FILTERS.reduce((n, name) => n + f[name].length, 0) + (f.path ? 1 : 0) + (f.q ? 1 : 0);
  });

  private reload$ = new Subject<void>();
  private liveSub?: Subscription;
  private trickleSub?: Subscription;
  private liveStartedAt = 0;

  ngOnInit(): void {
    this.reload$
      .pipe(
        tap(() => {
          this.loading.set(true);
          this.error.set(null);
        }),
        switchMap(() => {
          const f = this.filters();
          return forkJoin({
            page: this.api.list(f),
            facets: this.api.facets(f),
            histogram: this.api.histogram(f),
          }).pipe(
            catchError((err) => {
              this.error.set(this.describe(err));
              return of(null);
            }),
          );
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((result) => {
        this.loading.set(false);
        if (!result) return;
        this.entries.set(result.page.items);
        this.nextCursor.set(result.page.next_cursor);
        this.facets.set(result.facets);
        this.histogram.set(result.histogram);
      });

    this.route.queryParams.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      this.filters.set(this.fromParams(params));
      this.reload$.next();
      if (this.live()) this.startLive();
    });

    this.api.status().subscribe({
      next: (s) => this.demoEnabled.set(!!s.demo_data),
      error: () => this.demoEnabled.set(false),
    });

    this.destroyRef.onDestroy(() => this.stopLive());
  }

  updateFilters(patch: Partial<LogFilters>): void {
    this.setFilters({ ...this.filters(), ...patch });
  }

  resetFilters(): void {
    this.setFilters({ ...DEFAULT_FILTERS, range: this.filters().range });
  }

  refresh(): void {
    this.reload$.next();
  }

  loadMore(): void {
    const cursor = this.nextCursor();
    if (!cursor || this.loadingMore()) return;
    this.loadingMore.set(true);
    this.api.list(this.filters(), cursor).subscribe({
      next: (page) => {
        this.entries.update((rows) => [...rows, ...page.items]);
        this.nextCursor.set(page.next_cursor);
        this.loadingMore.set(false);
      },
      error: (err) => {
        this.error.set(this.describe(err));
        this.loadingMore.set(false);
      },
    });
  }

  toggleLive(): void {
    if (this.live()) {
      this.stopLive();
    } else {
      this.live.set(true);
      this.startLive();
      this.syncTrickle();
    }
  }

  /** Demo only: insert a batch of fake logs, then reload the page data. */
  generateSamples(): void {
    if (this.generating()) return;
    this.generating.set(true);
    this.error.set(null);
    this.api.seedDemo(SAMPLE_BATCH.count, SAMPLE_BATCH.hours).subscribe({
      next: () => {
        this.generating.set(false);
        // Sample rows are spread over the last day, so make sure the window can show them.
        if (this.filters().range === '15m' || this.filters().range === '1h') {
          this.updateFilters({ range: '24h' });
        } else {
          this.refresh();
        }
      },
      error: (err) => {
        this.generating.set(false);
        this.error.set(
          err?.status === 404
            ? 'Demo data is disabled. Set LOGS_ENABLE_DEMO_DATA=true in backend/.env and restart the backend.'
            : this.describe(err),
        );
      },
    });
  }

  setAutoDemo(on: boolean): void {
    this.autoDemo.set(on);
    this.live() ? this.syncTrickle() : null;
  }

  download(format: 'json' | 'csv'): void {
    window.open(this.api.exportUrl(this.filters(), format), '_blank');
  }

  select(entry: LogEntry | null): void {
    this.selected.set(entry);
  }

  private startLive(): void {
    this.liveSub?.unsubscribe();
    this.liveStartedAt = Date.now();
    this.liveCount.set(0);
    this.liveError.set(null);
    this.liveStatus.set('connecting');
    this.liveSub = this.api.stream(this.filters()).subscribe((event) => this.onLive(event));
  }

  private onLive(event: LiveEvent): void {
    switch (event.type) {
      case 'open':
        this.liveStatus.set('live');
        this.liveError.set(null);
        break;
      case 'reconnecting':
        this.liveStatus.set('reconnecting');
        break;
      case 'failure':
        this.liveStatus.set('failed');
        this.liveError.set(event.detail);
        break;
      case 'log': {
        this.liveStatus.set('live');
        // A reconnect can replay the last few seconds, so skip entries we already show.
        if (this.entries().some((e) => e.id === event.entry.id)) return;
        // Demo mode: a sample batch inserted just before pressing Live is backdated; don't replay it as "new".
        if (this.demoEnabled() && Date.parse(event.entry.timestamp) < this.liveStartedAt - 60_000) return;
        this.liveCount.update((n) => n + 1);
        this.entries.update((rows) => [event.entry, ...rows].slice(0, LIVE_BUFFER_LIMIT));
        break;
      }
    }
  }

  /** In demo mode, while Live is on, keep adding a few fake requests so rows keep arriving. */
  private syncTrickle(): void {
    this.trickleSub?.unsubscribe();
    this.trickleSub = undefined;
    if (!this.live() || !this.demoEnabled() || !this.autoDemo()) return;
    this.trickleSub = timer(500, SAMPLE_TRICKLE_MS).subscribe(() => {
      this.api.seedDemo(1 + Math.floor(Math.random() * 3), 0).subscribe({ error: () => this.trickleSub?.unsubscribe() });
    });
  }

  private stopLive(): void {
    this.trickleSub?.unsubscribe();
    this.trickleSub = undefined;
    this.live.set(false);
    this.liveStatus.set('off');
    this.liveSub?.unsubscribe();
    this.liveSub = undefined;
  }

  private setFilters(filters: LogFilters): void {
    // The URL is the source of truth, so filtered views can be bookmarked and shared.
    this.router.navigate([], { relativeTo: this.route, queryParams: this.toParams(filters) });
  }

  private toParams(f: LogFilters): Params {
    const params: Params = {};
    if (f.range !== DEFAULT_FILTERS.range) params['range'] = f.range;
    if (f.q) params['q'] = f.q;
    if (f.path) params['path'] = f.path;
    for (const name of LIST_FILTERS) if (f[name].length) params[name] = f[name];
    return params;
  }

  private fromParams(params: Params): LogFilters {
    const list = (v: unknown): string[] => (v == null ? [] : Array.isArray(v) ? v.map(String) : [String(v)]);
    const range = TIME_RANGES.some((r) => r.value === params['range']) ? (params['range'] as TimeRange) : DEFAULT_FILTERS.range;
    const filters: LogFilters = { ...DEFAULT_FILTERS, range, q: params['q'] ?? '', path: params['path'] ?? '' };
    for (const name of LIST_FILTERS) filters[name] = list(params[name]);
    return filters;
  }

  private describe(err: unknown): string {
    const status = (err as { status?: number })?.status;
    if (status === 0) return 'Cannot reach the logs API. Is the FastAPI server running?';
    return `Failed to load logs${status ? ` (HTTP ${status})` : ''}.`;
  }
}
