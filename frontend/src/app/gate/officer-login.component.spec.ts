import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { environment } from '../../environments/environment';
import { AuthService } from '../core/auth.service';
import { CODE_SENT_MESSAGE, OfficerLoginComponent } from './officer-login.component';

const API = environment.apiBaseUrl;

@Component({ standalone: true, template: '' })
class BlankComponent {}

describe('OfficerLoginComponent', () => {
  let fixture: ComponentFixture<OfficerLoginComponent>;
  let component: OfficerLoginComponent;
  let http: HttpTestingController;
  let router: Router;

  function el<T extends HTMLElement>(selector: string): T {
    return fixture.nativeElement.querySelector(selector) as T;
  }

  async function type(selector: string, value: string): Promise<void> {
    const input = el<HTMLInputElement>(selector);
    input.value = value;
    input.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  }

  function inSeconds(seconds: number): string {
    // The backend sends naive UTC.
    return new Date(Date.now() + seconds * 1000).toISOString().replace('Z', '');
  }

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [OfficerLoginComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([{ path: '**', component: BlankComponent }])],
    }).compileComponents();
    http = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
    fixture = TestBed.createComponent(OfficerLoginComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  afterEach(() => http.verify());

  it('never asks for an event id or a password', () => {
    expect(el('#event-id')).toBeNull();
    expect(el('input[type="password"]')).toBeNull();
  });

  it('shows the same confirmation for any address and then asks for a 6-digit code', async () => {
    await type('#officer-email', 'someone@example.com');
    component.requestOtp();
    const req = http.expectOne(`${API}/auth/officer/otp`);
    expect(req.request.body).toEqual({ email: 'someone@example.com' });
    req.flush({ resend_available_at: inSeconds(60) }, { status: 202, statusText: 'Accepted' });
    fixture.detectChanges();

    expect(el('[data-testid="code-sent"]').textContent).toContain(CODE_SENT_MESSAGE);
    const code = el<HTMLInputElement>('#officer-code');
    expect(code.getAttribute('inputmode')).toBe('numeric');
    expect(code.getAttribute('autocomplete')).toBe('one-time-code');
  });

  it('keeps resend disabled until the server cooldown passes', async () => {
    component.email.set('officer@example.com');
    component.requestOtp();
    http.expectOne(`${API}/auth/officer/otp`).flush({ resend_available_at: inSeconds(45) });
    fixture.detectChanges();

    const resend = el<HTMLButtonElement>('[data-testid="resend"]');
    expect(resend.disabled).toBeTrue();
    expect(resend.textContent).toMatch(/Resend in (44|45)s/);
    component.resendOtp();
    http.expectNone(`${API}/auth/officer/otp`);

    component.now.set(Date.now() + 46_000);
    fixture.detectChanges();
    expect(resend.disabled).toBeFalse();
    component.resendOtp();
    http.expectOne(`${API}/auth/officer/otp`).flush({ resend_available_at: inSeconds(60) });
  });

  it('accepts digits only and signs in to the assigned-event list without going back to login', async () => {
    const navigate = spyOn(router, 'navigateByUrl').and.resolveTo(true);
    component.email.set('officer@example.com');
    component.requestOtp();
    http.expectOne(`${API}/auth/officer/otp`).flush({ resend_available_at: inSeconds(60) });
    fixture.detectChanges();

    component.onCodeInput('12a3-456789');
    expect(component.code()).toBe('123456');
    component.verifyOtp();
    const req = http.expectOne(`${API}/auth/officer/verify`);
    expect(req.request.body).toEqual({ email: 'officer@example.com', code: '123456' });
    expect(req.request.urlWithParams).not.toContain('123456');
    req.flush({ access_token: 't', token_type: 'bearer', expires_in: 28800, user: { id: 5, role: 'security_officer', name: 'Ravi' } });

    expect(TestBed.inject(AuthService).currentUser()?.role).toBe('security_officer');
    expect(navigate).toHaveBeenCalledWith('/gate/events', { replaceUrl: true });
    expect(component.code()).toBe('');
  });

  it('explains wrong/expired codes, throttling and outages', () => {
    component.email.set('officer@example.com');
    component.step.set('otp');
    component.code.set('000000');
    component.verifyOtp();
    http.expectOne(`${API}/auth/officer/verify`).flush({ detail: 'x' }, { status: 400, statusText: 'Bad Request' });
    expect(component.errorMessage()).toContain('incorrect, has expired, or has been tried too many times');

    component.changeEmail();
    component.requestOtp();
    http
      .expectOne(`${API}/auth/officer/otp`)
      .flush({ detail: 'x' }, { status: 429, statusText: 'Too Many', headers: { 'Retry-After': '120' } });
    expect(component.errorMessage()).toContain('Try again in 2 minutes');

    component.requestOtp();
    http.expectOne(`${API}/auth/officer/otp`).flush({ detail: 'x' }, { status: 503, statusText: 'Unavailable' });
    expect(component.errorMessage()).toContain('cannot be sent right now');
  });

  it('does not verify an incomplete code', () => {
    component.email.set('officer@example.com');
    component.step.set('otp');
    component.onCodeInput('123');
    component.verifyOtp();
    http.expectNone(`${API}/auth/officer/verify`);
    expect(component.errorMessage()).toContain('6-digit');
  });
});
