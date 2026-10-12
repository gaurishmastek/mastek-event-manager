import { DatePipe } from '@angular/common';
import { Component, computed, input } from '@angular/core';

import { Histogram } from '../logs.models';

const TICKS = 5;

@Component({
  selector: 'app-logs-timeline',
  standalone: true,
  imports: [DatePipe],
  template: `
    <div class="timeline">
      <div class="bars">
        @for (b of bars(); track b.start) {
          <div class="bar" [title]="b.title">
            <div class="stack" [style.height.%]="b.height">
              <div class="seg error" [style.flex-grow]="b.error"></div>
              <div class="seg warning" [style.flex-grow]="b.warning"></div>
              <div class="seg rest" [style.flex-grow]="b.rest"></div>
            </div>
          </div>
        }
      </div>
      <div class="ticks">
        @for (t of ticks(); track $index) {
          <span>{{ t | date: tickFormat() }}</span>
        }
      </div>
    </div>
  `,
  styles: `
    .timeline {
      padding: 4px 12px 0;
      border-bottom: 1px solid var(--logs-border);
    }
    .bars {
      display: flex;
      align-items: flex-end;
      gap: 2px;
      height: 32px;
      border-bottom: 1px solid var(--logs-border);
    }
    .bar {
      flex: 1;
      height: 100%;
      display: flex;
      align-items: flex-end;
    }
    .bar:hover .stack {
      opacity: 0.75;
    }
    .stack {
      width: 100%;
      min-height: 0;
      display: flex;
      flex-direction: column;
      border-radius: 2px 2px 0 0;
      overflow: hidden;
    }
    .seg {
      flex-basis: 0;
    }
    .error {
      background: var(--logs-error);
    }
    .warning {
      background: var(--logs-warning);
    }
    .rest {
      background: #3f3f46;
    }
    .ticks {
      display: flex;
      justify-content: space-between;
      padding: 4px 0 6px;
      font-family: var(--logs-mono);
      font-size: 10px;
      color: var(--logs-text-faint);
    }
  `,
})
export class LogsTimelineComponent {
  histogram = input<Histogram | null>(null);
  live = input(false);

  readonly bars = computed(() => {
    const h = this.histogram();
    if (!h) return [];
    const max = Math.max(1, ...h.buckets.map((b) => b.total));
    return h.buckets.map((b) => ({
      start: b.start,
      height: b.total ? Math.max(6, (b.total / max) * 100) : 0,
      error: b.error,
      warning: b.warning,
      rest: b.total - b.error - b.warning,
      title: `${new Date(b.start).toLocaleString()}\n${b.total} logs · ${b.warning} warnings · ${b.error} errors`,
    }));
  });

  readonly ticks = computed(() => {
    const h = this.histogram();
    if (!h) return [];
    const start = new Date(h.start).getTime();
    const end = new Date(h.end).getTime();
    return Array.from({ length: TICKS }, (_, i) => new Date(start + ((end - start) * i) / (TICKS - 1)));
  });

  /** Show the date only when the window spans more than a day. */
  readonly tickFormat = computed(() => {
    const h = this.histogram();
    if (!h) return 'HH:mm:ss';
    const span = new Date(h.end).getTime() - new Date(h.start).getTime();
    return span > 86_400_000 ? 'MMM d, HH:mm' : 'HH:mm:ss';
  });
}
