import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap } from '@angular/router';
import { environment } from '../../environments/environment';
import type { PublicEventInfo } from '../core/models';
import { RegistrationFlowComponent } from './registration-flow.component';
import { MAX_KIDS } from './registration-form';

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

  function kidInputs(): HTMLInputElement[] {
    return Array.from(fixture.nativeElement.querySelectorAll('input[id^="kid-name-"]'));
  }

  function ageInputs(): HTMLInputElement[] {
    return Array.from(fixture.nativeElement.querySelectorAll('input[id^="kid-age-"]'));
  }

  async function settle(): Promise<void> {
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  }

  async function click(selector: string): Promise<void> {
    el<HTMLInputElement>(selector).click();
    await settle();
  }

  async function fillDetails(): Promise<void> {
    await type('#employee-id', 'MT-104');
    await type('#employee-name', 'Asha Patil');
    await type('#email', 'asha@example.com');
  }

  const submit = () => el<HTMLButtonElement>('button[type="submit"]');
  const registrationsUrl = () => `${environment.apiBaseUrl}/public/events/${PUBLIC_ID}/registrations`;

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

  it('loads the event by its public id and asks about attendance on the event date', () => {
    expect(el('h1').textContent).toContain('Diwali Night');
    // 12:00 UTC is 17:30 in Mumbai, still 20 October.
    expect(el('#attending-group legend').textContent).toContain('Will you be attending the event on');
    expect(el('#attending-group legend').textContent).toContain('Sunday, 20 October 2030');
    expect(el('#family-group')).toBeNull();
    expect(el('#food-group')).toBeNull();
  });

  it('hides the mobile field and places the attendance question right after the email field', () => {
    expect(el('#mobile')).toBeNull();
    const fields = Array.from(fixture.nativeElement.querySelectorAll('#email, #attending-group, #consent')).map(
      (node) => (node as HTMLElement).id,
    );
    expect(fields).toEqual(['email', 'attending-group', 'consent']);
  });

  it('shows the family and food questions only when attending, and clears them when switching to No', async () => {
    await click('#attending-yes');
    expect(el('#family-group legend').textContent).toContain('Will you be accompanied by your family members?');
    expect(el('#food-group legend').textContent).toContain('Please mention your food preference.');

    await click('#family-yes');
    await click('#with-adult');
    await type('#adult-name', 'Ravi Patil');
    await click('#food-JAIN');

    await click('#attending-no');
    expect(el('#family-group')).toBeNull();
    expect(el('#food-group')).toBeNull();

    await click('#attending-yes');
    expect(el<HTMLInputElement>('#family-yes').checked).toBeFalse();
    expect(el<HTMLInputElement>('#food-JAIN').checked).toBeFalse();
    expect(fixture.componentInstance.answers().adultName).toBe('');
  });

  it('clears family details when family attendance changes from Yes to No', async () => {
    await click('#attending-yes');
    await click('#family-yes');
    await click('#with-adult');
    await type('#adult-name', 'Ravi Patil');
    await click('#with-kids');
    await type('#kid-name-0', 'Meera Patil');

    await click('#family-no');
    expect(el('#family-members-group')).toBeNull();
    await click('#family-yes');

    expect(el<HTMLInputElement>('#with-adult').checked).toBeFalse();
    expect(el<HTMLInputElement>('#with-kids').checked).toBeFalse();
    expect(el('#adult-name')).toBeNull();
    expect(kidInputs().length).toBe(0);
  });

  it('shows a required Adult Name only while Adult is ticked, and clears it when unticked', async () => {
    await click('#attending-yes');
    await click('#family-yes');
    await click('#with-adult');
    expect(el<HTMLInputElement>('#adult-name').required).toBeTrue();
    expect(el('label[for="adult-name"]').textContent).toContain('Adult Name');
    await type('#adult-name', 'Ravi Patil');

    await click('#with-adult');
    expect(el('#adult-name')).toBeNull();
    await click('#with-adult');
    expect(el<HTMLInputElement>('#adult-name').value).toBe('');
  });

  it('lets the guest add kids up to the limit and remove them, with a labelled age beside each name', async () => {
    await click('#attending-yes');
    await click('#family-yes');
    await click('#with-kids');
    expect(kidInputs().map((input) => input.id)).toEqual(['kid-name-0']);
    expect(ageInputs().map((input) => input.id)).toEqual(['kid-age-0']);
    expect(el('#remove-kid-0')).toBeNull(); // at least one kid is required

    await type('#kid-name-0', 'Meera');
    await type('#kid-age-0', '6');
    await click('#add-kid');
    await type('#kid-name-1', 'Kiran');
    await type('#kid-age-1', '9');
    while (el('#add-kid')) await click('#add-kid');
    const last = MAX_KIDS - 1;
    expect(kidInputs().length).toBe(MAX_KIDS);
    expect(el(`label[for="kid-name-${last}"]`).textContent).toContain(`Kid ${MAX_KIDS}`);
    expect(kidInputs().every((input) => input.required)).toBeTrue();
    expect(ageInputs().length).toBe(MAX_KIDS); // an age field beside every kid name
    expect(ageInputs().every((input) => input.required && input.min === '0' && input.max === '17')).toBeTrue();
    expect(el(`label[for="kid-age-${last}"]`).textContent).toContain(`Kid ${MAX_KIDS}`);
    expect(el(`label[for="kid-age-${last}"]`).textContent).toContain('Age');
    // The name and age sit side by side in one row.
    expect(el('#kid-age-0').closest('.items-end')).toBe(el('#kid-name-0').closest('.items-end'));
    expect(el('#add-kid')).toBeNull(); // no fifth kid

    await click('#remove-kid-0');
    const empties = Array(MAX_KIDS - 2).fill('');
    expect(kidInputs().map((input) => input.value)).toEqual(['Kiran', ...empties]);
    expect(ageInputs().map((input) => input.value)).toEqual(['9', ...empties]); // each age stays with its kid
    expect(el('#add-kid')).not.toBeNull();
    expect(el('#remove-kid-1').getAttribute('aria-label')).toBe('Remove kid 2');

    await click('#with-kids');
    expect(kidInputs().length).toBe(0);
    expect(ageInputs().length).toBe(0);
    await click('#with-kids');
    expect(ageInputs().map((input) => input.value)).toEqual(['']); // cleared, not restored
  });

  it('shows an error for a kid age outside 0 to 17', async () => {
    await click('#attending-yes');
    await click('#family-yes');
    await click('#with-kids');
    await type('#kid-age-0', '18');
    el<HTMLInputElement>('#kid-age-0').dispatchEvent(new Event('blur'));
    await settle();

    expect(el('#kid-age-0-error').textContent).toContain('from 0 to 17');
    expect(el('#kid-age-0').getAttribute('aria-invalid')).toBe('true');
  });

  it('lets a guest who is not attending submit without answering anything else', async () => {
    await fillDetails();
    await click('#attending-no');
    await click('#consent');
    expect(submit().disabled).toBeFalse();

    submit().click();
    fixture.detectChanges();
    const request = http.expectOne(registrationsUrl());
    expect(request.request.body).toEqual({
      employee_id: 'MT-104',
      employee_name: 'Asha Patil',
      email: 'asha@example.com',
      mobile: '',
      attending: false,
      consent: true,
    });
    request.flush({
      registration_id: '11111111-1111-4111-8111-111111111111',
      email: 'as•••@example.com',
      otp_expires_at: '2030-10-01T10:05:00',
      resend_available_at: '2030-10-01T10:01:00',
    });
    await settle();

    const support = el('#otp-support');
    expect(support.textContent).toContain("Didn't receive the verification code? Contact Pearl Kinny");
    expect(support.querySelector('a')!.getAttribute('href')).toBe('mailto:pearl.kinny@mastek.com');
    expect(support.textContent).toContain('pearl.kinny@mastek.com');

    await type('app-input input', '123456');
    submit().click();
    http
      .expectOne(`${environment.apiBaseUrl}/public/registrations/11111111-1111-4111-8111-111111111111/verify`)
      .flush({
        registration_id: '11111111-1111-4111-8111-111111111111',
        status: 'DECLINED',
        attending: false,
        employee_id: 'MT-104',
        employee_name: 'Asha Patil',
        event: EVENT,
        verified_at: '2030-10-01T10:02:00',
      });
    await settle();

    expect(el('[role="status"]').textContent).toContain("won't be attending Diwali Night");
    expect(fixture.nativeElement.querySelector('img')).toBeNull(); // no QR pass
  });

  it('keeps Send code disabled until the conditional answers are complete, then posts only what applies', async () => {
    expect(submit().disabled).toBeTrue();
    await fillDetails();
    await click('#consent');
    expect(submit().disabled).toBeTrue(); // attendance not answered

    await click('#attending-yes');
    await click('#family-yes');
    expect(submit().disabled).toBeTrue(); // neither Adult nor Kids
    await click('#with-adult');
    await click('#with-kids');
    await type('#adult-name', ' Ravi Patil ');
    await type('#kid-name-0', 'Meera Patil');
    await click('#food-FAST_FOOD');
    expect(submit().disabled).toBeTrue(); // kid age missing
    await type('#kid-age-0', '7');
    await click('#food-VEG');
    await click('#food-FAST_FOOD');
    await click('#food-FAST_FOOD');
    expect(submit().disabled).toBeFalse();

    submit().click();
    fixture.detectChanges();
    const request = http.expectOne(registrationsUrl());
    expect(request.request.body).toEqual({
      employee_id: 'MT-104',
      employee_name: 'Asha Patil',
      email: 'asha@example.com',
      mobile: '',
      attending: true,
      family_attending: true,
      accompanying_adult: true,
      adult_name: 'Ravi Patil',
      accompanying_kids: true,
      kid_names: ['Meera Patil'],
      kid_ages: [7],
      food_preference: 'FAST_FOOD',
      consent: true,
    });
    expect(submit().disabled).toBeTrue(); // in progress

    request.flush(
      { detail: 'This employee ID or email address is already registered for this event' },
      { status: 409, statusText: 'Conflict' },
    );
    fixture.detectChanges();
    expect(el('[role="alert"]').textContent).toContain('already registered');
    expect(submit().disabled).toBeFalse(); // can retry
  });

  it('shows an error when the family is larger than the event allows', async () => {
    await click('#attending-yes');
    await click('#family-yes');
    await click('#with-adult');
    await click('#with-kids');
    await click('#add-kid');
    await click('#add-kid');

    expect(el('#party-error').textContent).toContain('at most 3 guests');
  });

  it('tells an attending employee that the QR pass is also on its way to their email', async () => {
    await fillDetails();
    await click('#attending-yes');
    await click('#family-no');
    await click('#food-VEG');
    await click('#consent');
    submit().click();
    fixture.detectChanges();
    http.expectOne(registrationsUrl()).flush({
      registration_id: '11111111-1111-4111-8111-111111111111',
      email: 'as•••@example.com',
      otp_expires_at: '2030-10-01T10:05:00',
      resend_available_at: '2030-10-01T10:01:00',
    });
    await settle();

    await type('app-input input', '123456');
    submit().click();
    http
      .expectOne(`${environment.apiBaseUrl}/public/registrations/11111111-1111-4111-8111-111111111111/verify`)
      .flush({
        registration_id: '11111111-1111-4111-8111-111111111111',
        status: 'VERIFIED',
        attending: true,
        employee_id: 'MT-104',
        employee_name: 'Asha Patil',
        guest_names: [],
        adult_name: null,
        kid_names: [],
        kid_ages: [],
        food_preference: 'VEG',
        party_size: 1,
        event: EVENT,
        qr_token: 'token',
        qr_svg: 'data:image/svg+xml;base64,PHN2Zy8+',
        issued_at: '2030-10-01T10:02:00',
      });
    await settle();

    expect(el('img').getAttribute('alt')).toBe('QR entry pass');
    expect(el('#pass-emailed').textContent).toContain('emailing this QR pass to your registered email address');
  });
});
