import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { environment } from '../../environments/environment';
import { AuthService } from '../core/auth.service';
import { OfficerLoginComponent } from './officer-login.component';

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

  it('asks for email and password, and never for an event id or a code', () => {
    expect(el('#event-id')).toBeNull();
    expect(el('#officer-code')).toBeNull();
    expect(el<HTMLInputElement>('#officer-password').type).toBe('password');
    expect(el<HTMLInputElement>('#officer-password').getAttribute('autocomplete')).toBe('current-password');
  });

  it('keeps Sign in disabled until a valid email and a password are entered', async () => {
    const button = () => el<HTMLButtonElement>('button[type="submit"]');
    expect(button().disabled).toBeTrue();
    await type('#officer-email', 'officer@example.com');
    expect(button().disabled).toBeTrue();
    await type('#officer-password', 'admin@123');
    expect(button().disabled).toBeFalse();
  });

  it('signs in to the assigned-event list, sending the password only in the body', async () => {
    const navigate = spyOn(router, 'navigateByUrl').and.resolveTo(true);
    await type('#officer-email', ' officer@example.com ');
    await type('#officer-password', 'admin@123');
    component.signIn();

    const req = http.expectOne(`${API}/auth/officer/login`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ email: 'officer@example.com', password: 'admin@123' });
    expect(req.request.urlWithParams).not.toContain('admin@123');
    req.flush({ access_token: 't', token_type: 'bearer', expires_in: 28800, user: { id: 5, role: 'security_officer', name: 'Ravi' } });

    expect(TestBed.inject(AuthService).currentUser()?.role).toBe('security_officer');
    expect(navigate).toHaveBeenCalledWith('/gate/events', { replaceUrl: true });
    expect(component.password()).toBe('');
  });

  it('shows one message for a wrong password, unknown email or locked account, and clears the password', () => {
    component.email.set('officer@example.com');
    component.password.set('wrong');
    component.signIn();
    http.expectOne(`${API}/auth/officer/login`).flush({ detail: 'x' }, { status: 401, statusText: 'Unauthorized' });

    expect(component.errorMessage()).toContain('Incorrect email or password');
    expect(component.password()).toBe('');
    expect(component.submitting()).toBeFalse();
  });

  it('explains a network failure', () => {
    component.email.set('officer@example.com');
    component.password.set('admin@123');
    component.signIn();
    http.expectOne(`${API}/auth/officer/login`).error(new ProgressEvent('error'), { status: 0 });
    expect(component.errorMessage()).toContain('Could not reach the server');
  });

  it('does not send an invalid email or an empty password', () => {
    component.email.set('not-an-email');
    component.password.set('admin@123');
    component.signIn();
    expect(component.errorMessage()).toContain('valid email');

    component.email.set('officer@example.com');
    component.password.set('');
    component.signIn();
    expect(component.errorMessage()).toContain('password');
    http.expectNone(`${API}/auth/officer/login`);
  });
});
