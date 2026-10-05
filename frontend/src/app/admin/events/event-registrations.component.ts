import { DatePipe, DOCUMENT } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { EventsApiService } from '../../core/events-api.service';
import { apiErrorMessage } from '../../core/http-error';
import type {
  EventRead,
  FoodPreference,
  RegistrationAdminRead,
  RegistrationAdminUpdate,
  RegistrationStatus,
} from '../../core/models';
import { emailError, employeeIdError, kidAgeError, MAX_KIDS, personNameError } from '../../public/registration-form';
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

export function registrationExportFilename(contentDisposition: string | null, eventId: number): string {
  const encoded = contentDisposition?.match(/filename\*\s*=\s*UTF-8''([^;]+)/i)?.[1];
  if (encoded) {
    try {
      return decodeURIComponent(encoded.trim());
    } catch {
      // Fall through to the ordinary filename or the safe local default.
    }
  }
  const filename = contentDisposition?.match(/filename\s*=\s*"([^"]+)"|filename\s*=\s*([^;\s]+)/i);
  return filename?.[1] ?? filename?.[2] ?? `event-${eventId}-registrations.xlsx`;
}

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
  private readonly document = inject(DOCUMENT);

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
  readonly exporting = signal(false);
  readonly exportErrorMessage = signal('');
  readonly exportMessage = signal('');
  readonly editing = signal<RegistrationAdminRead | null>(null);
  readonly editEmployeeId = signal('');
  readonly editEmployeeName = signal('');
  readonly replacementEmail = signal('');
  readonly editAdultName = signal('');
  readonly editKidNames = signal<string[]>([]);
  readonly editKidAges = signal<string[]>([]);
  readonly savingEdit = signal(false);
  readonly editErrorMessage = signal('');
  readonly editMessage = signal('');
  readonly qrRegistrationId = signal<string | null>(null);
  readonly qrErrorMessage = signal('');
  readonly qrMessage = signal('');
  readonly maxKids = MAX_KIDS;

  readonly hasFilters = computed(() => !!this.search().trim() || !!this.status());
  readonly pageEnd = computed(() => Math.min(this.offset() + this.items().length, this.total()));
  readonly editGuestsLocked = computed(() => this.editing()?.status === 'CHECKED_IN');

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

  exportAll(): void {
    this.exporting.set(true);
    this.exportErrorMessage.set('');
    this.exportMessage.set('');
    this.api.exportRegistrations(this.eventId).subscribe({
      next: (response) => {
        this.exporting.set(false);
        if (!response.body) {
          this.exportErrorMessage.set('The export was empty. Please try again.');
          return;
        }

        const objectUrl = URL.createObjectURL(response.body);
        const link = this.document.createElement('a');
        link.href = objectUrl;
        link.download = registrationExportFilename(response.headers.get('content-disposition'), this.eventId);
        link.click();
        setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
        this.exportMessage.set('Excel export downloaded.');
      },
      error: (err) => {
        this.exporting.set(false);
        this.exportErrorMessage.set(apiErrorMessage(err, 'Could not export registrations.'));
      },
    });
  }

  startEdit(registration: RegistrationAdminRead): void {
    this.editing.set(registration);
    this.editEmployeeId.set(registration.employee_id ?? '');
    this.editEmployeeName.set(registration.employee_name);
    this.replacementEmail.set('');
    this.editAdultName.set(registration.adult_name ?? '');
    this.editKidNames.set([...registration.kid_names]);
    this.editKidAges.set(registration.kid_ages.map((age) => (age === null ? '' : String(age))));
    this.editErrorMessage.set('');
    this.editMessage.set('');
  }

  cancelEdit(): void {
    this.editing.set(null);
    this.editErrorMessage.set('');
  }

  setEditKidName(index: number, value: string): void {
    this.editKidNames.update((names) => names.map((name, current) => (current === index ? value : name)));
  }

  setEditKidAge(index: number, value: string): void {
    this.editKidAges.update((ages) => ages.map((age, current) => (current === index ? value : age)));
  }

  addEditKid(): void {
    if (this.editGuestsLocked() || this.editKidNames().length >= MAX_KIDS) return;
    this.editKidNames.update((names) => [...names, '']);
    this.editKidAges.update((ages) => [...ages, '']);
  }

  removeEditKid(index: number): void {
    if (this.editGuestsLocked()) return;
    this.editKidNames.update((names) => names.filter((_, current) => current !== index));
    this.editKidAges.update((ages) => ages.filter((_, current) => current !== index));
  }

  saveEdit(): void {
    const registration = this.editing();
    if (!registration || this.savingEdit()) return;

    const employeeId = this.editEmployeeId().trim();
    const employeeName = this.editEmployeeName().trim();
    const replacementEmail = this.replacementEmail().trim();
    const adultName = this.editAdultName().trim();
    const kidNames = this.editKidNames().map((name) => name.trim());
    const kidAges = this.editKidAges().map((age) => age.trim());
    const errors = [
      employeeIdError(employeeId),
      personNameError(employeeName, 'employee name'),
      replacementEmail ? emailError(replacementEmail) : null,
      ...(!this.editGuestsLocked() && adultName ? [personNameError(adultName, 'adult name')] : []),
      ...(!this.editGuestsLocked() ? kidNames.map((name) => personNameError(name, 'kid name')) : []),
      ...(!this.editGuestsLocked() ? kidAges.map((age) => kidAgeError(age)) : []),
    ].filter((message): message is string => !!message);
    if (errors.length) {
      this.editErrorMessage.set(errors[0]);
      return;
    }

    const payload: RegistrationAdminUpdate = {
      employee_id: employeeId,
      employee_name: employeeName,
      adult_name: adultName || null,
      kid_names: kidNames,
      kid_ages: kidAges.map(Number),
    };
    if (replacementEmail) payload.email = replacementEmail;

    this.savingEdit.set(true);
    this.editErrorMessage.set('');
    this.api.updateRegistration(this.eventId, registration.registration_id, payload).subscribe({
      next: (updated) => {
        this.savingEdit.set(false);
        this.items.update((items) =>
          items.map((item) => (item.registration_id === updated.registration_id ? updated : item)),
        );
        this.editing.set(null);
        this.editMessage.set('Registration updated.');
      },
      error: (err) => {
        this.savingEdit.set(false);
        this.editErrorMessage.set(apiErrorMessage(err, 'Could not update this registration.'));
      },
    });
  }

  generateQr(registration: RegistrationAdminRead): void {
    if (registration.status !== 'VERIFIED' || this.qrRegistrationId()) return;
    this.qrRegistrationId.set(registration.registration_id);
    this.qrErrorMessage.set('');
    this.qrMessage.set('');
    this.api.generateRegistrationQr(this.eventId, registration.registration_id).subscribe({
      next: (pass) => {
        this.qrRegistrationId.set(null);
        const link = this.document.createElement('a');
        link.href = pass.qr_svg;
        link.download = `event-${this.eventId}-registration-${pass.registration_id}-qr.svg`;
        link.click();
        this.qrMessage.set(`QR code downloaded for ${pass.employee_name}. Send it manually by email.`);
      },
      error: (err) => {
        this.qrRegistrationId.set(null);
        this.qrErrorMessage.set(apiErrorMessage(err, 'Could not generate a QR code.'));
      },
    });
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
