import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed, fakeAsync, flushMicrotasks, tick } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { environment } from '../../../environments/environment';
import type { EventRead } from '../../core/models';
import { EventListComponent } from './event-list.component';

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
  created_at: '2026-09-28T10:00:00',
  updated_at: '2026-09-28T10:00:00',
  created_by: 1,
  updated_by: 1,
  gate_opens_at: '2030-10-20T09:00:00',
  gate_closes_at: '2030-10-21T00:00:00',
};

describe('EventListComponent registration link', () => {
  let fixture: ComponentFixture<EventListComponent>;
  const link = `${window.location.origin}/register/${EVENT.public_id}`;

  function copyButton(): HTMLButtonElement {
    return fixture.nativeElement.querySelector('button[aria-label^="Copy registration link"]');
  }

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [EventListComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    }).compileComponents();
    fixture = TestBed.createComponent(EventListComponent);
    const http = TestBed.inject(HttpTestingController);
    http.expectOne(`${environment.apiBaseUrl}/events?limit=50`).flush({ items: [EVENT], total: 1, limit: 50, offset: 0 });
    fixture.detectChanges();
  });

  it('sits before Edit and Delete and opens the public-id link, never the numeric id', () => {
    const actions = Array.from(fixture.nativeElement.querySelectorAll('td:last-child a, td:last-child button')).map(
      (node) => (node as HTMLElement).textContent!.trim(),
    );
    expect(actions).toEqual(['Copy registration link', 'Open', 'Registrations', 'Manage security', 'Edit', 'Delete']);
    const open: HTMLAnchorElement = fixture.nativeElement.querySelector('a[target="_blank"]');
    expect(open.href).toBe(link);
    expect(open.rel).toContain('noopener');
  });

  it('copies the link and says Copied for a moment', fakeAsync(() => {
    const writeText = spyOn(navigator.clipboard, 'writeText').and.resolveTo();

    copyButton().click();
    flushMicrotasks();
    fixture.detectChanges();

    expect(writeText).toHaveBeenCalledWith(link);
    expect(copyButton().textContent).toContain('Copied');

    tick(2000);
    fixture.detectChanges();
    expect(copyButton().textContent).toContain('Copy registration link');
  }));

  it('shows a selectable link when the clipboard fails', async () => {
    spyOn(navigator.clipboard, 'writeText').and.rejectWith(new Error('denied'));

    copyButton().click();
    await fixture.whenStable();
    fixture.detectChanges();

    const fallback: HTMLInputElement = fixture.nativeElement.querySelector('#link-7');
    expect(fallback.value).toBe(link);
    expect(fallback.readOnly).toBeTrue();
    expect(copyButton().textContent).toContain('Copy registration link');
  });
});
