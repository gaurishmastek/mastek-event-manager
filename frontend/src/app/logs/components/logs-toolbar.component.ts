import { Component, DestroyRef, OnInit, effect, inject, input, output, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Subject, debounceTime, distinctUntilChanged } from 'rxjs';

@Component({
  selector: 'app-logs-toolbar',
  standalone: true,
  templateUrl: './logs-toolbar.component.html',
  styleUrl: './logs-toolbar.component.css',
})
export class LogsToolbarComponent implements OnInit {
  query = input('');
  live = input(false);
  loading = input(false);
  activeFilters = input(0);
  demo = input(false);
  generating = input(false);

  queryChange = output<string>();
  toggleLive = output<void>();
  refresh = output<void>();
  generate = output<void>();
  download = output<'json' | 'csv'>();

  readonly text = signal('');
  readonly menuOpen = signal(false);

  private typed$ = new Subject<string>();
  private destroyRef = inject(DestroyRef);

  constructor() {
    // Keep the box in sync when the query changes from outside (URL, Reset).
    effect(() => this.text.set(this.query()), { allowSignalWrites: true });
  }

  ngOnInit(): void {
    this.typed$
      .pipe(debounceTime(300), distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe((q) => this.queryChange.emit(q));
  }

  onInput(value: string): void {
    this.text.set(value);
    this.typed$.next(value);
  }

  clear(): void {
    this.text.set('');
    this.typed$.next('');
  }

  pick(format: 'json' | 'csv'): void {
    this.menuOpen.set(false);
    this.download.emit(format);
  }
}
