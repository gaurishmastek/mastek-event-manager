import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, HostListener, computed, input, output, signal } from '@angular/core';

import { LogEntry, LogFilters } from '../logs.models';

@Component({
  selector: 'app-log-detail',
  standalone: true,
  imports: [DatePipe, DecimalPipe],
  templateUrl: './log-detail.component.html',
  styleUrl: './log-detail.component.css',
})
export class LogDetailComponent {
  entry = input.required<LogEntry>();
  close = output<void>();
  filter = output<Partial<LogFilters>>();

  readonly copied = signal(false);

  readonly fields = computed(() => {
    const e = this.entry();
    const rows: { label: string; value: string; filter?: Partial<LogFilters> }[] = [
      { label: 'Request ID', value: e.request_id },
      { label: 'Service', value: e.service, filter: { service: [e.service] } },
      { label: 'Environment', value: e.environment, filter: { environment: [e.environment] } },
    ];
    if (e.host) rows.push({ label: 'Host', value: e.host, filter: { host: [e.host] } });
    if (e.route) rows.push({ label: 'Route', value: e.route, filter: { route: [e.route] } });
    if (e.query) rows.push({ label: 'Query', value: e.query });
    if (e.client_ip) rows.push({ label: 'Client IP', value: e.client_ip });
    if (e.user_agent) rows.push({ label: 'User Agent', value: e.user_agent });
    return rows;
  });

  @HostListener('document:keydown.escape')
  onEscape(): void {
    this.close.emit();
  }

  copyJson(): void {
    navigator.clipboard?.writeText(JSON.stringify(this.entry(), null, 2)).then(() => {
      this.copied.set(true);
      setTimeout(() => this.copied.set(false), 1500);
    });
  }

  statusClass(): string {
    const code = this.entry().status_code ?? 0;
    return code >= 500 ? 'status error' : code >= 400 ? 'status warning' : 'status ok';
  }
}
