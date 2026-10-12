import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, input, output } from '@angular/core';

import { LogEntry } from '../logs.models';

@Component({
  selector: 'app-logs-table',
  standalone: true,
  imports: [DatePipe, DecimalPipe],
  templateUrl: './logs-table.component.html',
  styleUrl: './logs-table.component.css',
})
export class LogsTableComponent {
  entries = input<LogEntry[]>([]);
  loading = input(false);
  demo = input(false);
  generating = input(false);
  loadingMore = input(false);
  hasMore = input(false);
  selectedId = input<string | null>(null);

  select = output<LogEntry>();
  loadMore = output<void>();
  resetFilters = output<void>();
  refresh = output<void>();
  generate = output<void>();

  onScroll(el: HTMLElement): void {
    if (this.hasMore() && el.scrollTop + el.clientHeight >= el.scrollHeight - 200) {
      this.loadMore.emit();
    }
  }

  /** The text for the Messages column: the most severe message, else the last one. */
  summary(entry: LogEntry): { text: string; level: string } | null {
    if (!entry.messages.length) return null;
    const order = ['debug', 'info', 'warning', 'error', 'fatal'];
    const top = entry.messages.reduce((a, b) => (order.indexOf(b.level) >= order.indexOf(a.level) ? b : a));
    return { text: top.message, level: top.level };
  }

  statusClass(entry: LogEntry): string {
    const code = entry.status_code;
    if (code == null) return 'status none';
    if (code >= 500) return 'status error';
    if (code >= 400) return 'status warning';
    return 'status ok';
  }
}
