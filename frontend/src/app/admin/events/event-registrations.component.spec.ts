import { HttpHeaders, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed, fakeAsync, tick } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { environment } from '../../../environments/environment';
import type { EventRead, RegistrationAdminRead } from '../../core/models';
import { EventRegistrationsComponent, registrationExportFilename } from './event-registrations.component';

const API = environment.apiBaseUrl;
const XLSX_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
const EVENT: EventRead = {
  id: 7,
  public_id: '3f2b8c1e-8a4d-4b7e-9c2a-1d2e3f4a5b6c',
  title: 'Diwali Night',
  description: null,
  location: 'Mumbai',
  starts_at: '2030-10-20T12:00:00',
  ends_at: null,
  capacity: 100,
  max_guests_per_registration: 5,
  registration_open: true,
  created_at: '2026-09-28T10:00:00',
  updated_at: '2026-09-28T10:00:00',
  created_by: 1,
  updated_by: 1,
  gate_opens_at: '2030-10-20T09:00:00',
  gate_closes_at: '2030-10-21T00:00:00',
};

const REGISTRATION: RegistrationAdminRead = {
  registration_id: '1f2b8c1e-8a4d-4b7e-9c2a-1d2e3f4a5b6c',
  employee_id: 'MT-104',
  employee_name: 'Asha Patil',
  email_masked: 'as•••@example.com',
  mobile_masked: null,
  attending: true,
  family_attending: true,
  guest_names: ['Ravi Patil'],
  adult_name: 'Ravi Patil',
  kid_names: [],
  kid_ages: [],
  food_preference: 'VEG',
  number_of_guests: 1,
  party_size: 2,
  status: 'VERIFIED',
  verified_at: '2030-10-20T12:00:00',
  qr_issued: true,
  qr_issued_at: '2030-10-20T12:00:00',
  checked_in_at: null,
  people_entered: 0,
  created_at: '2030-10-10T12:00:00',
};

describe('EventRegistrationsComponent export', () => {
  let fixture: ComponentFixture<EventRegistrationsComponent>;
  let component: EventRegistrationsComponent;
  let http: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [EventRegistrationsComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: ActivatedRoute, useValue: { snapshot: { paramMap: convertToParamMap({ id: '7' }) } } },
      ],
    }).compileComponents();

    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(EventRegistrationsComponent);
    component = fixture.componentInstance;
    http.expectOne(`${API}/events/7`).flush(EVENT);
    http
      .expectOne((request) => request.url === `${API}/events/7/registrations`)
      .flush({ items: [], total: 0, limit: 20, offset: 0 });
    fixture.detectChanges();
  });

  afterEach(() => http.verify());

  it('downloads every registration as the server-named Excel file', fakeAsync(() => {
    const objectUrl = spyOn(URL, 'createObjectURL').and.returnValue('blob:registration-export');
    const revoke = spyOn(URL, 'revokeObjectURL');
    const click = spyOn(HTMLAnchorElement.prototype, 'click');
    const buttons = fixture.nativeElement.querySelectorAll('button') as NodeListOf<HTMLButtonElement>;
    const button = Array.from(buttons).find((item) => item.textContent?.includes('Export all to Excel'))!;

    button.click();
    expect(component.exporting()).toBeTrue();
    const request = http.expectOne(`${API}/events/7/registrations/export.xlsx`);
    expect(request.request.method).toBe('GET');
    expect(request.request.responseType).toBe('blob');
    expect(request.request.params.keys()).toEqual([]);

    const file = new Blob(['xlsx'], { type: XLSX_TYPE });
    request.flush(file, {
      headers: new HttpHeaders({ 'Content-Disposition': 'attachment; filename="event-7-registrations.xlsx"' }),
    });

    expect(objectUrl).toHaveBeenCalledWith(file);
    expect(click).toHaveBeenCalled();
    const link = click.calls.mostRecent().object as HTMLAnchorElement;
    expect(link.download).toBe('event-7-registrations.xlsx');
    expect(link.href).toBe('blob:registration-export');
    expect(component.exporting()).toBeFalse();
    expect(component.exportMessage()).toBe('Excel export downloaded.');

    tick();
    expect(revoke).toHaveBeenCalledWith('blob:registration-export');
  }));

  it('shows an export error and clears the loading state', () => {
    component.exportAll();
    http
      .expectOne(`${API}/events/7/registrations/export.xlsx`)
      .flush(new Blob(['failed']), { status: 500, statusText: 'Server Error' });
    fixture.detectChanges();

    expect(component.exporting()).toBeFalse();
    expect(component.exportErrorMessage()).toBe('Could not export registrations.');
    expect(fixture.nativeElement.textContent).toContain('Could not export registrations.');
  });

  it('updates a registration without submitting or displaying the existing contact email', () => {
    component.startEdit(REGISTRATION);
    component.editEmployeeName.set('Asha Rao');
    component.editAdultName.set('Ravi Rao');
    component.addEditKid();
    component.setEditKidName(0, 'Mira Rao');
    component.setEditKidAge(0, '9');
    component.saveEdit();

    const request = http.expectOne(`${API}/events/7/registrations/${REGISTRATION.registration_id}`);
    expect(request.request.method).toBe('PATCH');
    expect(request.request.body).toEqual({
      employee_id: 'MT-104',
      employee_name: 'Asha Rao',
      adult_name: 'Ravi Rao',
      kid_names: ['Mira Rao'],
      kid_ages: [9],
    });
    request.flush({ ...REGISTRATION, employee_name: 'Asha Rao', adult_name: 'Ravi Rao', kid_names: ['Mira Rao'], kid_ages: [9] });

    expect(component.editing()).toBeNull();
    expect(component.editMessage()).toBe('Registration updated.');
  });

  it('downloads an admin-generated QR pass for a verified registration', () => {
    const click = spyOn(HTMLAnchorElement.prototype, 'click');
    component.generateQr(REGISTRATION);

    const request = http.expectOne(`${API}/events/7/registrations/${REGISTRATION.registration_id}/qr`);
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({});
    request.flush({
      registration_id: REGISTRATION.registration_id,
      employee_name: REGISTRATION.employee_name,
      qr_svg: 'data:image/svg+xml;base64,PHN2Zy8+',
      issued_at: '2030-10-20T12:00:00',
    });

    expect(click).toHaveBeenCalled();
    const link = click.calls.mostRecent().object as HTMLAnchorElement;
    expect(link.download).toBe(`event-7-registration-${REGISTRATION.registration_id}-qr.svg`);
    expect(component.qrMessage()).toContain('Send it manually by email.');
  });
});

describe('registrationExportFilename', () => {
  it('supports standard, encoded, and missing content-disposition filenames', () => {
    expect(registrationExportFilename('attachment; filename="event-7-registrations.xlsx"', 7)).toBe(
      'event-7-registrations.xlsx',
    );
    expect(registrationExportFilename("attachment; filename*=UTF-8''Diwali%20registrations.xlsx", 7)).toBe(
      'Diwali registrations.xlsx',
    );
    expect(registrationExportFilename(null, 7)).toBe('event-7-registrations.xlsx');
  });
});
