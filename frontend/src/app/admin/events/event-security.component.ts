import { DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';
import { EventsApiService } from '../../core/events-api.service';
import { apiErrorMessage } from '../../core/http-error';
import type { EventRead, StaffUser } from '../../core/models';
import { IST, utcIso } from '../../core/time';
import { UsersApiService } from '../../core/users-api.service';
import { emailError, mobileError } from '../../public/registration-form';
import { BadgeComponent } from '../../ui/badge/badge.component';
import { ButtonComponent } from '../../ui/button/button.component';
import { CardComponent } from '../../ui/card/card.component';
import { SpinnerComponent } from '../../ui/spinner/spinner.component';

const CONTROL_CHARS = /[\x00-\x1f\x7f]/;

/** Mirrors `UserCreate.full_name` in `backend/app/modules/users/schemas.py` (1–120 characters). */
export function officerNameError(value: string): string | null {
  const name = value.trim();
  if (!name) return 'Enter the officer’s full name.';
  if (name.length > 120) return 'Must be 120 characters or fewer.';
  if (CONTROL_CHARS.test(name)) return 'Use a single line of plain text.';
  return null;
}

/** The mobile is optional for staff; when given it must be a valid Indian number. */
export function optionalMobileError(value: string): string | null {
  return value.trim() ? mobileError(value) : null;
}

type Field = 'fullName' | 'email' | 'mobile';

/**
 * Admin page for one event's security officers (`/admin/events/:id/security`): list, assign, unassign,
 * and create a new officer who is assigned straight away. Officers have no password; they sign in with an
 * emailed code. The backend enforces the admin role on every call; the route guard is only a convenience.
 */
@Component({
  selector: 'app-event-security',
  standalone: true,
  imports: [DatePipe, FormsModule, RouterLink, BadgeComponent, ButtonComponent, CardComponent, SpinnerComponent],
  templateUrl: './event-security.component.html',
})
export class EventSecurityComponent {
  private readonly events = inject(EventsApiService);
  private readonly users = inject(UsersApiService);
  private readonly route = inject(ActivatedRoute);

  readonly eventId = Number(this.route.snapshot.paramMap.get('id'));
  readonly ist = IST;
  readonly utc = utcIso;

  readonly loading = signal(true);
  readonly loadError = signal('');
  readonly event = signal<EventRead | null>(null);
  readonly officers = signal<StaffUser[]>([]);
  readonly assignedIds = signal<number[]>([]);

  readonly selectedOfficerId = signal<number | null>(null);
  /** Id of the officer being assigned or unassigned, to disable that row and prevent double clicks. */
  readonly busyOfficerId = signal<number | null>(null);
  readonly actionError = signal('');
  readonly successMessage = signal('');

  readonly fullName = signal('');
  readonly email = signal('');
  readonly mobile = signal('');
  readonly touched = signal<Record<Field, boolean>>({ fullName: false, email: false, mobile: false });
  readonly creating = signal(false);
  readonly createError = signal('');
  /** An account that was created but could not be assigned: offer to retry the assignment only. */
  readonly pendingAssignment = signal<StaffUser | null>(null);

  readonly officerNameError = officerNameError;
  readonly emailError = emailError;
  readonly optionalMobileError = optionalMobileError;

  /** Assigned officers, in assignment-list order. An id with no visible account (e.g. deleted) still shows. */
  readonly assigned = computed(() => {
    const byId = new Map(this.officers().map((user) => [user.id, user]));
    return this.assignedIds().map((id) => ({ id, user: byId.get(id) ?? null }));
  });

  /** Active officers not yet assigned to this event, for the picker. */
  readonly available = computed(() => {
    const taken = new Set(this.assignedIds());
    return this.officers().filter((user) => user.is_active && !taken.has(user.id));
  });

  constructor() {
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.loadError.set('');
    forkJoin({
      event: this.events.get(this.eventId),
      officers: this.users.list('security_officer'),
      assigned: this.events.officerIds(this.eventId),
    }).subscribe({
      next: ({ event, officers, assigned }) => {
        this.event.set(event);
        this.officers.set(officers);
        this.assignedIds.set(assigned);
        this.loading.set(false);
      },
      error: (err) => {
        this.loading.set(false);
        this.loadError.set(apiErrorMessage(err, 'Could not load this event’s security officers.'));
      },
    });
  }

  assignSelected(): void {
    const id = this.selectedOfficerId();
    const officer = this.officers().find((user) => user.id === id);
    if (officer) this.assign(officer);
  }

  assign(officer: StaffUser, afterCreate = false): void {
    if (this.busyOfficerId() !== null) return;
    this.busyOfficerId.set(officer.id);
    this.actionError.set('');
    this.successMessage.set('');
    this.events.assignOfficer(this.eventId, officer.id).subscribe({
      next: () => {
        this.busyOfficerId.set(null);
        this.pendingAssignment.set(null);
        this.selectedOfficerId.set(null);
        if (!this.assignedIds().includes(officer.id)) {
          this.assignedIds.update((ids) => [...ids, officer.id]);
        }
        this.successMessage.set(
          afterCreate
            ? `Created ${officer.full_name} and assigned them to this event. They sign in at the gate with a code sent to ${officer.email}.`
            : `Assigned ${officer.full_name} to this event.`,
        );
      },
      error: (err) => {
        this.busyOfficerId.set(null);
        const reason = apiErrorMessage(err, 'The assignment failed.');
        if (afterCreate || this.pendingAssignment()?.id === officer.id) {
          this.pendingAssignment.set(officer);
          this.actionError.set(
            `The account for ${officer.email} was created, but assigning it to this event failed: ${reason} ` +
              'Retry the assignment; the account does not need to be created again.',
          );
        } else {
          this.actionError.set(`Could not assign ${officer.full_name}: ${reason}`);
        }
      },
    });
  }

  retryPendingAssignment(): void {
    const officer = this.pendingAssignment();
    if (officer) this.assign(officer, true);
  }

  unassign(officerId: number, name: string): void {
    if (this.busyOfficerId() !== null) return;
    if (!confirm(`Remove ${name} from this event? They lose access to its gate scanner immediately.`)) return;
    this.busyOfficerId.set(officerId);
    this.actionError.set('');
    this.successMessage.set('');
    this.events.unassignOfficer(this.eventId, officerId).subscribe({
      next: () => {
        this.busyOfficerId.set(null);
        this.assignedIds.update((ids) => ids.filter((id) => id !== officerId));
        this.successMessage.set(`Removed ${name} from this event.`);
      },
      error: (err) => {
        this.busyOfficerId.set(null);
        if (err instanceof HttpErrorResponse && err.status === 404) {
          // Already removed elsewhere; reflect the server's state.
          this.assignedIds.update((ids) => ids.filter((id) => id !== officerId));
        }
        this.actionError.set(apiErrorMessage(err, `Could not remove ${name}.`));
      },
    });
  }

  markTouched(field: Field): void {
    this.touched.update((state) => ({ ...state, [field]: true }));
  }

  show(field: Field): boolean {
    return this.touched()[field];
  }

  formValid(): boolean {
    return !officerNameError(this.fullName()) && !emailError(this.email()) && !optionalMobileError(this.mobile());
  }

  createAndAssign(): void {
    if (this.creating() || this.pendingAssignment()) return;
    this.touched.set({ fullName: true, email: true, mobile: true });
    if (!this.formValid()) return;

    this.creating.set(true);
    this.createError.set('');
    this.actionError.set('');
    this.successMessage.set('');
    const mobile = this.mobile().trim();
    this.users
      .createSecurityOfficer({ full_name: this.fullName().trim(), email: this.email().trim(), mobile: mobile || null })
      .subscribe({
        next: (officer) => {
          this.creating.set(false);
          this.officers.update((list) => [...list, officer]);
          this.resetForm();
          this.assign(officer, true);
        },
        error: (err) => {
          this.creating.set(false);
          this.createError.set(this.createErrorMessage(err));
        },
      });
  }

  private createErrorMessage(err: unknown): string {
    if (err instanceof HttpErrorResponse && err.status === 409) {
      const detail = typeof err.error?.detail === 'string' ? err.error.detail : '';
      if (/mobile/i.test(detail)) {
        return 'Another staff account already uses this mobile number. Use a different number or leave it blank.';
      }
      return (
        'A staff account with this email already exists. If it is a security officer, pick it from ' +
        '“Assign an existing officer” instead.'
      );
    }
    return apiErrorMessage(err, 'Could not create the officer.');
  }

  private resetForm(): void {
    this.fullName.set('');
    this.email.set('');
    this.mobile.set('');
    this.touched.set({ fullName: false, email: false, mobile: false });
  }
}
