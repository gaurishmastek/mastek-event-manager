import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { environment } from '../../../environments/environment';
import type { EventRead, StaffUser } from '../../core/models';
import { EventSecurityComponent, officerNameError, optionalMobileError } from './event-security.component';

const API = environment.apiBaseUrl;

const EVENT: EventRead = {
  id: 7,
  public_id: '3f2b8c1e-8a4d-4b7e-9c2a-1d2e3f4a5b6c',
  title: 'Diwali Night',
  description: null,
  location: 'Mastek campus, Mumbai',
  starts_at: '2030-10-20T12:30:00',
  ends_at: null,
  capacity: 100,
  max_guests_per_registration: 5,
  created_at: '2026-09-28T10:00:00',
  updated_at: '2026-09-28T10:00:00',
  created_by: 1,
  updated_by: 1,
  gate_opens_at: '2030-10-20T09:30:00',
  gate_closes_at: '2030-10-21T00:30:00',
};

function officer(id: number, name: string, active = true): StaffUser {
  return {
    id,
    email: `${name.toLowerCase()}@example.com`,
    full_name: name,
    role: 'security_officer',
    is_active: active,
    created_at: '2026-09-28T10:00:00',
    last_login_at: null,
  };
}

describe('EventSecurityComponent', () => {
  let fixture: ComponentFixture<EventSecurityComponent>;
  let component: EventSecurityComponent;
  let http: HttpTestingController;

  function text(): string {
    fixture.detectChanges();
    return fixture.nativeElement.textContent;
  }

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [EventSecurityComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: ActivatedRoute, useValue: { snapshot: { paramMap: convertToParamMap({ id: '7' }) } } },
      ],
    }).compileComponents();
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(EventSecurityComponent);
    component = fixture.componentInstance;

    http.expectOne(`${API}/events/7`).flush(EVENT);
    http
      .expectOne(`${API}/users?role=security_officer`)
      .flush([officer(5, 'Ravi'), officer(6, 'Meera'), officer(8, 'Old', false)]);
    http.expectOne(`${API}/events/7/officers`).flush([5]);
    fixture.detectChanges();
  });

  afterEach(() => http.verify());

  it('shows the event, the assigned officers, and only active unassigned officers to pick', () => {
    const page = text();
    expect(page).toContain('Diwali Night');
    expect(page).toContain('Mastek campus, Mumbai');
    // 12:30 UTC is 6:00 PM in Mumbai.
    expect(page).toContain('6:00 PM IST');
    const rows: HTMLElement[] = Array.from(fixture.nativeElement.querySelectorAll('[data-testid="assigned-officer"]'));
    expect(rows.length).toBe(1);
    expect(rows[0].textContent).toContain('ravi@example.com');
    expect(rows[0].textContent).toContain('Active');
    expect(component.available().map((u) => u.id)).toEqual([6]);
  });

  it('never offers a password field', () => {
    expect(fixture.nativeElement.querySelector('input[type="password"]')).toBeNull();
  });

  it('assigns an existing officer', () => {
    component.selectedOfficerId.set(6);
    component.assignSelected();
    const req = http.expectOne(`${API}/events/7/officers/6`);
    expect(req.request.method).toBe('PUT');
    req.flush(null, { status: 204, statusText: 'No Content' });

    expect(component.assignedIds()).toEqual([5, 6]);
    expect(text()).toContain('Assigned Meera to this event.');
  });

  it('unassigns with the soft-delete endpoint', () => {
    spyOn(window, 'confirm').and.returnValue(true);
    component.unassign(5, 'Ravi');
    const req = http.expectOne(`${API}/events/7/officers/5`);
    expect(req.request.method).toBe('DELETE');
    req.flush(null, { status: 204, statusText: 'No Content' });
    expect(component.assignedIds()).toEqual([]);
  });

  it('creates an officer as security_officer without a password, then assigns them', () => {
    component.fullName.set('  Asha Rao ');
    component.email.set('asha.rao@example.com');
    component.mobile.set('98765 43210');
    component.createAndAssign();
    component.createAndAssign(); // a double click sends nothing more

    const create = http.expectOne(`${API}/users`);
    expect(create.request.body).toEqual({
      full_name: 'Asha Rao',
      email: 'asha.rao@example.com',
      mobile: '98765 43210',
      role: 'security_officer',
    });
    create.flush(officer(9, 'Asha'), { status: 201, statusText: 'Created' });
    http.expectOne(`${API}/events/7/officers/9`).flush(null, { status: 204, statusText: 'No Content' });

    expect(component.assignedIds()).toEqual([5, 9]);
    expect(text()).toContain('Created Asha and assigned them to this event.');
  });

  it('keeps the created account and retries only the assignment when assigning fails', () => {
    component.fullName.set('Asha Rao');
    component.email.set('asha@example.com');
    component.createAndAssign();
    http.expectOne(`${API}/users`).flush(officer(9, 'Asha'), { status: 201, statusText: 'Created' });
    http.expectOne(`${API}/events/7/officers/9`).error(new ProgressEvent('error'), { status: 0 });

    const page = text();
    expect(page).toContain('The account for asha@example.com was created');
    expect(page).toContain('Retry assigning Asha');
    // A second create is blocked while the account waits for its assignment.
    component.fullName.set('Asha Rao');
    component.email.set('asha@example.com');
    component.createAndAssign();
    http.expectNone(`${API}/users`);

    component.retryPendingAssignment();
    http.expectOne(`${API}/events/7/officers/9`).flush(null, { status: 204, statusText: 'No Content' });
    expect(component.pendingAssignment()).toBeNull();
    expect(component.assignedIds()).toEqual([5, 9]);
  });

  it('explains duplicate email and mobile conflicts', () => {
    component.fullName.set('Asha Rao');
    component.email.set('ravi@example.com');
    component.createAndAssign();
    http
      .expectOne(`${API}/users`)
      .flush({ detail: 'A user with this email already exists' }, { status: 409, statusText: 'Conflict' });
    expect(component.createError()).toContain('already exists');

    component.createAndAssign();
    http
      .expectOne(`${API}/users`)
      .flush({ detail: 'A user with this mobile already exists' }, { status: 409, statusText: 'Conflict' });
    expect(component.createError()).toContain('mobile number');
  });

  it('validates the form before calling the API', () => {
    component.email.set('not-an-email');
    component.mobile.set('12345');
    component.createAndAssign();
    http.expectNone(`${API}/users`);
    const page = text();
    expect(page).toContain('Enter the officer’s full name.');
    expect(page).toContain('Enter a valid email address');
    expect(page).toContain('valid Indian mobile number');
  });
});

describe('officer form rules', () => {
  it('mirror the backend', () => {
    expect(officerNameError(' ')).not.toBeNull();
    expect(officerNameError('x'.repeat(121))).not.toBeNull();
    expect(officerNameError('Ravi')).toBeNull();
    expect(optionalMobileError('')).toBeNull();
    expect(optionalMobileError('+91 98765 43210')).toBeNull();
    expect(optionalMobileError('12345')).not.toBeNull();
  });
});
