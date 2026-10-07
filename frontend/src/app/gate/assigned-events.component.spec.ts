import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { environment } from '../../environments/environment';
import type { EventRead } from '../core/models';
import { AssignedEventsComponent } from './assigned-events.component';

const API = environment.apiBaseUrl;

@Component({ standalone: true, template: '' })
class BlankComponent {}

function event(id: number, title: string): EventRead {
  return {
    id,
    public_id: `3f2b8c1e-8a4d-4b7e-9c2a-1d2e3f4a5b6${id}`,
    title,
    description: null,
    location: 'Mastek campus, Mumbai',
    starts_at: '2030-10-20T12:30:00',
    ends_at: '2030-10-20T17:30:00',
    capacity: 100,
    max_guests_per_registration: 5,
    registration_open: true,
    created_at: '2026-09-28T10:00:00',
    updated_at: '2026-09-28T10:00:00',
    created_by: 1,
    updated_by: 1,
    gate_opens_at: '2030-10-20T09:30:00',
    gate_closes_at: '2030-10-20T17:30:00',
  };
}

describe('AssignedEventsComponent', () => {
  async function setup() {
    await TestBed.configureTestingModule({
      imports: [AssignedEventsComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([{ path: '**', component: BlankComponent }])],
    }).compileComponents();
    const http = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(AssignedEventsComponent);
    return { http, fixture };
  }

  it('lists the events the backend returns for this officer, in IST, each with a scanner link', async () => {
    const { http, fixture } = await setup();
    http.expectOne(`${API}/events?limit=100`).flush({ items: [event(3, 'Navratri'), event(4, 'Diwali')], total: 2, limit: 100, offset: 0 });
    fixture.detectChanges();

    const cards: HTMLElement[] = Array.from(fixture.nativeElement.querySelectorAll('[data-testid="assigned-event"]'));
    expect(cards.map((c) => c.querySelector('h2')!.textContent!.trim())).toEqual(['Navratri', 'Diwali']);
    // 12:30 UTC is 6:00 PM in Mumbai.
    expect(cards[0].textContent).toContain('6:00 PM IST');
    expect(cards[0].querySelector('a')!.getAttribute('href')).toBe('/gate/scan/3');
    http.verify();
  });

  it('says so when nothing is assigned', async () => {
    const { http, fixture } = await setup();
    http.expectOne(`${API}/events?limit=100`).flush({ items: [], total: 0, limit: 100, offset: 0 });
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('No events assigned.');
    expect(fixture.nativeElement.textContent).toContain('Contact an administrator.');
  });

  it('shows a retryable error', async () => {
    const { http, fixture } = await setup();
    http.expectOne(`${API}/events?limit=100`).error(new ProgressEvent('error'), { status: 0 });
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Could not reach the server');
    expect(fixture.nativeElement.textContent).toContain('Try again');
  });
});
