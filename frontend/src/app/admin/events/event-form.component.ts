import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { EventsApiService } from '../../core/events-api.service';
import { apiErrorMessage } from '../../core/http-error';
import { ButtonComponent } from '../../ui/button/button.component';
import { CardComponent } from '../../ui/card/card.component';
import { InputComponent } from '../../ui/input/input.component';

/** Mirrors `MAX_GUESTS_PER_REGISTRATION_CAP` in `backend/app/modules/events/models.py`. */
export const MAX_GUESTS_CAP = 10;

/** `starts_at`/`ends_at` need a timezone offset (`AwareDatetime` on the backend); IST is +05:30. */
function toApiDateTime(localValue: string): string {
  return `${localValue}:00+05:30`;
}

function toLocalInputValue(isoValue: string): string {
  // Backend returns naive UTC; render it back as an IST `datetime-local` value.
  const date = new Date(`${isoValue.endsWith('Z') ? isoValue : `${isoValue}Z`}`);
  const ist = new Date(date.getTime() + 5.5 * 60 * 60 * 1000);
  return ist.toISOString().slice(0, 16);
}

@Component({
  selector: 'app-event-form',
  standalone: true,
  imports: [FormsModule, RouterLink, ButtonComponent, CardComponent, InputComponent],
  templateUrl: './event-form.component.html',
})
export class EventFormComponent {
  private readonly api = inject(EventsApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  private readonly eventId = this.route.snapshot.paramMap.get('id');
  readonly isEdit = this.eventId !== null;

  readonly title = signal('');
  readonly description = signal('');
  readonly location = signal('');
  readonly startsAt = signal('');
  readonly endsAt = signal('');
  readonly capacity = signal(100);
  readonly maxGuests = signal(5);

  readonly loading = signal(false);
  readonly submitting = signal(false);
  readonly errorMessage = signal('');

  constructor() {
    if (this.eventId) {
      this.loading.set(true);
      this.api.get(Number(this.eventId)).subscribe({
        next: (event) => {
          this.loading.set(false);
          this.title.set(event.title);
          this.description.set(event.description ?? '');
          this.location.set(event.location);
          this.startsAt.set(toLocalInputValue(event.starts_at));
          this.endsAt.set(event.ends_at ? toLocalInputValue(event.ends_at) : '');
          this.capacity.set(event.capacity);
          this.maxGuests.set(event.max_guests_per_registration);
        },
        error: (err) => {
          this.loading.set(false);
          this.errorMessage.set(apiErrorMessage(err, 'Could not load this event.'));
        },
      });
    }
  }

  maxGuestsValid(): boolean {
    const value = this.maxGuests();
    return Number.isInteger(value) && value >= 0 && value <= MAX_GUESTS_CAP;
  }

  submit(): void {
    if (!this.title().trim() || !this.location().trim() || !this.startsAt() || !this.maxGuestsValid()) return;
    this.submitting.set(true);
    this.errorMessage.set('');

    const payload = {
      title: this.title().trim(),
      description: this.description().trim() || null,
      location: this.location().trim(),
      starts_at: toApiDateTime(this.startsAt()),
      ends_at: this.endsAt() ? toApiDateTime(this.endsAt()) : null,
      capacity: this.capacity(),
      max_guests_per_registration: this.maxGuests(),
    };

    const save$ = this.isEdit ? this.api.update(Number(this.eventId), payload) : this.api.create(payload);

    save$.subscribe({
      next: () => {
        this.submitting.set(false);
        this.router.navigateByUrl('/admin/events');
      },
      error: (err) => {
        this.submitting.set(false);
        this.errorMessage.set(apiErrorMessage(err, 'Could not save this event.'));
      },
    });
  }
}
