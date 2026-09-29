import { DatePipe } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { EventsApiService } from '../../core/events-api.service';
import { apiErrorMessage } from '../../core/http-error';
import type { EventRead, FoodPreference, RegistrationAdminRead, RegistrationStatus } from '../../core/models';
import { BadgeComponent, type BadgeTone } from '../../ui/badge/badge.component';
import { ButtonComponent } from '../../ui/button/button.component';
import { CardComponent } from '../../ui/card/card.component';
import { SpinnerComponent } from '../../ui/spinner/spinner.component';

const PAGE_SIZE = 20;

const STATUS_LABEL: Record<RegistrationStatus, string> = {
  PENDING_OTP: 'Pending OTP',
  VERIFIED: 'Verified',
  CHECKED_IN: 'Checked in',
  DECLINED: 'Not attending',
};

const FOOD_LABEL: Record<FoodPreference, string> = { VEG: 'Veg', JAIN: 'Jain', FAST_FOOD: 'Fast Food' };

const STATUS_TONE: Record<RegistrationStatus, BadgeTone> = {
  PENDING_OTP: 'neutral',
  VERIFIED: 'success',
  CHECKED_IN: 'warning',
  DECLINED: 'destructive',
};

/**
 * Admin-only list of an event's registrations (`GET /events/{id}/registrations`). Contacts arrive
 * masked; the route guard is a convenience, the backend enforces the admin role.
 */
@Component({
  selector: 'app-event-registrations',
  standalone: true,
  imports: [DatePipe, FormsModule, RouterLink, BadgeComponent, ButtonComponent, CardComponent, SpinnerComponent],
  templateUrl: './event-registrations.component.html',
})
export class EventRegistrationsComponent {
  private readonly api = inject(EventsApiService);
  private readonly route = inject(ActivatedRoute);

  readonly eventId = Number(this.route.snapshot.paramMap.get('id'));
  readonly statuses = Object.keys(STATUS_LABEL) as RegistrationStatus[];
  readonly pageSize = PAGE_SIZE;

  readonly event = signal<EventRead | null>(null);
  readonly items = signal<RegistrationAdminRead[]>([]);
  readonly total = signal(0);
  readonly offset = signal(0);
  readonly search = signal('');
  readonly status = signal<RegistrationStatus | ''>('');
  readonly loading = signal(true);
  readonly errorMessage = signal('');

  readonly hasFilters = computed(() => !!this.search().trim() || !!this.status());
  readonly pageEnd = computed(() => Math.min(this.offset() + this.items().length, this.total()));

  constructor() {
    this.api.get(this.eventId).subscribe({ next: (event) => this.event.set(event), error: () => {} });
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.errorMessage.set('');
    this.api
      .registrations(this.eventId, {
        search: this.search().trim() || undefined,
        status: this.status(),
        limit: PAGE_SIZE,
        offset: this.offset(),
      })
      .subscribe({
        next: (page) => {
          this.loading.set(false);
          this.items.set(page.items);
          this.total.set(page.total);
        },
        error: (err) => {
          this.loading.set(false);
          this.errorMessage.set(apiErrorMessage(err, 'Could not load registrations.'));
        },
      });
  }

  applyFilters(): void {
    this.offset.set(0);
    this.load();
  }

  clearFilters(): void {
    this.search.set('');
    this.status.set('');
    this.applyFilters();
  }

  previousPage(): void {
    this.offset.set(Math.max(0, this.offset() - PAGE_SIZE));
    this.load();
  }

  nextPage(): void {
    this.offset.set(this.offset() + PAGE_SIZE);
    this.load();
  }

  foodLabel(food: FoodPreference | null): string {
    return food ? FOOD_LABEL[food] : '—';
  }

  statusLabel(status: RegistrationStatus): string {
    return STATUS_LABEL[status] ?? status;
  }

  statusTone(status: RegistrationStatus): BadgeTone {
    return STATUS_TONE[status] ?? 'neutral';
  }

  /** The backend sends naive UTC timestamps. */
  utc(value: string | null): string | null {
    return value ? `${value}Z` : null;
  }
}
