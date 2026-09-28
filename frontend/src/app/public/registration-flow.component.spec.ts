import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap } from '@angular/router';
import { environment } from '../../environments/environment';
import type { PublicEventInfo } from '../core/models';
import { RegistrationFlowComponent } from './registration-flow.component';

const PUBLIC_ID = '3f2b8c1e-8a4d-4b7e-9c2a-1d2e3f4a5b6c';

const EVENT: PublicEventInfo = {
  public_id: PUBLIC_ID,
  title: 'Diwali Night',
  description: null,
  location: 'Mumbai',
  starts_at: '2030-10-20T12:00:00',
  ends_at: null,
  max_guests_per_registration: 3,
  registration_open: true,
  seats_left: 50,
};

describe('RegistrationFlowComponent', () => {
  let fixture: ComponentFixture<RegistrationFlowComponent>;
  let http: HttpTestingController;

  function el<T extends HTMLElement>(selector: string): T {
    return fixture.nativeElement.querySelector(selector) as T;
  }

  function guestInputs(): HTMLInputElement[] {
    return Array.from(fixture.nativeElement.querySelectorAll('input[id^="guest-name-"]'));
  }

  async function type(selector: string, value: string): Promise<void> {
    const input = el<HTMLInputElement>(selector);
    input.value = value;
    input.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  }

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [RegistrationFlowComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: ActivatedRoute, useValue: { snapshot: { paramMap: convertToParamMap({ eventPublicId: PUBLIC_ID }) } } },
      ],
    }).compileComponents();

    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(RegistrationFlowComponent);
    http.expectOne(`${environment.apiBaseUrl}/public/events/${PUBLIC_ID}`).flush(EVENT);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  });

  afterEach(() => http.verify());

  it('loads the event by its public id and shows no guest fields for zero guests', () => {
    expect(el('h1').textContent).toContain('Diwali Night');
    expect(guestInputs().length).toBe(0);
  });

  it('renders one labelled, required field per guest and keeps names when the count changes', async () => {
    await type('#guest-count', '2');
    expect(guestInputs().map((input) => input.id)).toEqual(['guest-name-0', 'guest-name-1']);
    expect(el('label[for="guest-name-1"]').textContent).toContain('Guest 2');
    expect(guestInputs().every((input) => input.required)).toBeTrue();

    await type('#guest-name-0', 'Ravi Patil');
    await type('#guest-name-1', 'Meera Patil');
    await type('#guest-count', '3');
    expect(guestInputs().map((input) => input.value)).toEqual(['Ravi Patil', 'Meera Patil', '']);

    await type('#guest-count', '1');
    expect(guestInputs().map((input) => input.value)).toEqual(['Ravi Patil']);

    await type('#guest-count', '0');
    expect(guestInputs().length).toBe(0);
  });

  it('shows an error instead of fields above the event limit', async () => {
    await type('#guest-count', '4');

    expect(guestInputs().length).toBe(0);
    expect(el('#guest-count-error').textContent).toContain('at most 3');
  });

  it('keeps Send code disabled until the form is valid, then posts the trimmed payload', async () => {
    const submit = () => el<HTMLButtonElement>('button[type="submit"]');
    expect(submit().disabled).toBeTrue();

    await type('#employee-id', 'MT-104');
    await type('#employee-name', 'Asha Patil');
    await type('#email', 'asha@example.com');
    await type('#mobile', '98765 43210');
    await type('#guest-count', '2');
    await type('#guest-name-0', 'Ravi Patil');
    await type('#guest-name-1', 'Meera Patil');
    await type('#guest-count', '1');
    expect(submit().disabled).toBeTrue(); // consent still missing

    const consent = el<HTMLInputElement>('#consent');
    consent.click();
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(submit().disabled).toBeFalse();

    submit().click();
    fixture.detectChanges();
    const request = http.expectOne(`${environment.apiBaseUrl}/public/events/${PUBLIC_ID}/registrations`);
    expect(request.request.body).toEqual({
      employee_id: 'MT-104',
      employee_name: 'Asha Patil',
      email: 'asha@example.com',
      mobile: '98765 43210',
      number_of_guests: 1,
      guest_names: ['Ravi Patil'],
      consent: true,
    });
    expect(submit().disabled).toBeTrue(); // in progress

    request.flush(
      { detail: 'This employee ID or email address is already registered for this event' },
      { status: 409, statusText: 'Conflict' },
    );
    fixture.detectChanges();
    expect(el('[role="alert"]').textContent).toContain('already registered');
  });
});
