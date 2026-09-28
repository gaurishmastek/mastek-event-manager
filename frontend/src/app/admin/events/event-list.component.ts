import { DatePipe } from '@angular/common';
import { Component, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { EventsApiService } from '../../core/events-api.service';
import { apiErrorMessage } from '../../core/http-error';
import type { EventRead } from '../../core/models';
import { ButtonComponent } from '../../ui/button/button.component';
import { CardComponent } from '../../ui/card/card.component';
import { SpinnerComponent } from '../../ui/spinner/spinner.component';

@Component({
  selector: 'app-event-list',
  standalone: true,
  imports: [DatePipe, RouterLink, ButtonComponent, CardComponent, SpinnerComponent],
  templateUrl: './event-list.component.html',
})
export class EventListComponent {
  private readonly api = inject(EventsApiService);

  readonly loading = signal(true);
  readonly events = signal<EventRead[]>([]);
  readonly errorMessage = signal('');

  constructor() {
    this.reload();
  }

  reload(): void {
    this.loading.set(true);
    this.errorMessage.set('');
    this.api.list({ limit: 50 }).subscribe({
      next: (page) => {
        this.loading.set(false);
        this.events.set(page.items);
      },
      error: (err) => {
        this.loading.set(false);
        this.errorMessage.set(apiErrorMessage(err, 'Could not load events.'));
      },
    });
  }

  remove(event: EventRead): void {
    if (!confirm(`Delete "${event.title}"? This can be reversed by an admin later (soft delete).`)) return;
    this.api.delete(event.id).subscribe({
      next: () => this.reload(),
      error: (err) => this.errorMessage.set(apiErrorMessage(err, 'Could not delete this event.')),
    });
  }
}
