import { Component, ElementRef, HostListener, computed, input, output, signal, viewChild } from '@angular/core';

import { FacetName, FacetValue, Facets, ListFilterName, LogFilters, TIME_RANGES, TimeRange } from '../logs.models';

interface FacetSection {
  key: Exclude<ListFilterName, 'level'>;
  label: string;
}

const LEVELS = [
  { value: 'warning', label: 'Warning' },
  { value: 'error', label: 'Error' },
  { value: 'fatal', label: 'Fatal' },
];

const SECTIONS: FacetSection[] = [
  { key: 'type', label: 'Resource' },
  { key: 'environment', label: 'Environment' },
  { key: 'route', label: 'Route' },
  { key: 'status', label: 'Status Code' },
  { key: 'method', label: 'Request Method' },
  { key: 'host', label: 'Host' },
  { key: 'service', label: 'Service' },
];

@Component({
  selector: 'app-filter-sidebar',
  standalone: true,
  templateUrl: './filter-sidebar.component.html',
  styleUrl: './filter-sidebar.component.css',
})
export class FilterSidebarComponent {
  filters = input.required<LogFilters>();
  facets = input<Facets | null>(null);

  filtersChange = output<Partial<LogFilters>>();
  reset = output<void>();
  collapse = output<void>();

  readonly ranges = TIME_RANGES;
  readonly sections = SECTIONS;
  readonly find = signal('');
  private findInput = viewChild<ElementRef<HTMLInputElement>>('findInput');

  /** Press F anywhere outside a text field to jump to the Find box. */
  @HostListener('document:keydown', ['$event'])
  onKey(event: KeyboardEvent): void {
    const target = event.target as HTMLElement | null;
    const typing = target && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName));
    if (!typing && !event.ctrlKey && !event.metaKey && !event.altKey && event.key.toLowerCase() === 'f') {
      event.preventDefault();
      this.findInput()?.nativeElement.focus();
    }
  }

  /** Which sections are expanded. Timeline and levels start open, like Vercel. */
  readonly open = signal<Record<string, boolean>>({ timeline: true, level: true, path: false });

  readonly levelRows = computed(() => {
    const counts = new Map((this.facets()?.level ?? []).map((f) => [String(f.value), f.count]));
    return LEVELS.map((l) => ({ ...l, count: counts.get(l.value) ?? 0 }));
  });

  /** Sections narrowed by the "Find" box at the top of the sidebar. */
  readonly visibleSections = computed(() => {
    const term = this.find().trim().toLowerCase();
    return term ? SECTIONS.filter((s) => s.label.toLowerCase().includes(term)) : SECTIONS;
  });

  toggle(key: string): void {
    this.open.update((o) => ({ ...o, [key]: !o[key] }));
  }

  isOpen(key: string): boolean {
    // A section with an active filter stays open so the selection is visible.
    const f = this.filters();
    const active = key in f && Array.isArray(f[key as keyof LogFilters]) && (f[key as ListFilterName] as string[]).length > 0;
    return !!this.open()[key] || active;
  }

  options(key: FacetName): FacetValue[] {
    const values = this.facets()?.[key] ?? [];
    const selected = this.filters()[key as ListFilterName] ?? [];
    // Keep selected values listed even when their count drops to zero.
    const missing = selected
      .filter((s) => !values.some((v) => String(v.value) === s))
      .map((s) => ({ value: s, count: 0 }));
    return [...values, ...missing];
  }

  isChecked(key: ListFilterName, value: string | number): boolean {
    return this.filters()[key].includes(String(value));
  }

  toggleValue(key: ListFilterName, value: string | number): void {
    const current = this.filters()[key];
    const v = String(value);
    const next = current.includes(v) ? current.filter((x) => x !== v) : [...current, v];
    this.filtersChange.emit({ [key]: next });
  }

  setRange(value: string): void {
    this.filtersChange.emit({ range: value as TimeRange });
  }

  setPath(value: string): void {
    this.filtersChange.emit({ path: value });
  }

  statusClass(value: string | number): string {
    const code = Number(value);
    if (code >= 500) return 'dot error';
    if (code >= 400) return 'dot warning';
    return 'dot ok';
  }
}
