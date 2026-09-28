import { DatePipe } from '@angular/common';
import { Component, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { AuthService } from '../core/auth.service';
import { EventsApiService } from '../core/events-api.service';
import { apiErrorMessage } from '../core/http-error';
import type { EventRead } from '../core/models';
import { IST, utcIso } from '../core/time';
import { SpinnerComponent } from '../ui/spinner/spinner.component';
import { ButtonComponent } from '../ui/button/button.component';
import { gateStatus, sortForGate, type GateStatus } from './gate-status';

/**
 * After sign-in: the events this officer may scan for. `GET /events` is already limited to the officer's
 * assignments by the backend, so an unassigned event never reaches this page. The officer always picks the
 * event explicitly, so a pass is never scanned against the wrong gate by accident.
 */
@Component({
  selector: 'app-assigned-events',
  standalone: true,
  imports: [DatePipe, RouterLink, ButtonComponent, SpinnerComponent],
  templateUrl: './assigned-events.component.html',
})
export class AssignedEventsComponent {
  private readonly api = inject(EventsApiService);
  protected readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  readonly ist = IST;
  readonly utc = utcIso;
  readonly loading = signal(true);
  readonly errorMessage = signal('');
  readonly events = signal<EventRead[]>([]);

  constructor() {
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.errorMessage.set('');
    this.api.list({ limit: 100 }).subscribe({
      next: (page) => {
        this.loading.set(false);
        this.events.set(sortForGate(page.items));
      },
      error: (err) => {
        this.loading.set(false);
        this.errorMessage.set(apiErrorMessage(err, 'Could not load your events.'));
        if (err?.status === 401) this.router.navigateByUrl('/gate/login', { replaceUrl: true });
      },
    });
  }

  status(event: EventRead): GateStatus {
    return gateStatus(event);
  }

  signOut(): void {
    this.auth.logout();
    this.router.navigateByUrl('/gate/login', { replaceUrl: true });
  }
}
