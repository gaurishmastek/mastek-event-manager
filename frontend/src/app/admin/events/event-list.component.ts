import { DatePipe } from '@angular/common';
import { Component, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { EventsApiService } from '../../core/events-api.service';
import { apiErrorMessage } from '../../core/http-error';
import type { EventRead } from '../../core/models';
import { registrationLink } from '../../core/registration-link';
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
  /** Id of the event whose link was just copied, for the "Copied" feedback. */
  readonly copiedEventId = signal<number | null>(null);
  /** When the clipboard is unavailable: the link to show so the admin can select and copy it by hand. */
  readonly manualCopy = signal<{ eventId: number; link: string } | null>(null);
  private copiedTimer: ReturnType<typeof setTimeout> | undefined;

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

  linkFor(event: EventRead): string {
    return registrationLink(window.location.origin, event.public_id);
  }

  async copyLink(event: EventRead): Promise<void> {
    const link = this.linkFor(event);
    this.manualCopy.set(null);
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard API unavailable');
      await navigator.clipboard.writeText(link);
    } catch {
      // Insecure origin, denied permission or an old browser: show the link to copy by hand instead.
      this.copiedEventId.set(null);
      this.manualCopy.set({ eventId: event.id, link });
      return;
    }
    this.copiedEventId.set(event.id);
    clearTimeout(this.copiedTimer);
    this.copiedTimer = setTimeout(() => this.copiedEventId.set(null), 2000);
  }

  selectAll(target: EventTarget | null): void {
    (target as HTMLInputElement | null)?.select();
  }

  remove(event: EventRead): void {
    if (!confirm(`Delete "${event.title}"? This can be reversed by an admin later (soft delete).`)) return;
    this.api.delete(event.id).subscribe({
      next: () => this.reload(),
      error: (err) => this.errorMessage.set(apiErrorMessage(err, 'Could not delete this event.')),
    });
  }
}
