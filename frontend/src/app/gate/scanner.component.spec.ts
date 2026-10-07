import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { environment } from '../../environments/environment';
import type { EventRead, PartyMember, ScannedGuest, ScanResponse } from '../core/models';
import { SCANNER_PLATFORM, type QrDecoder, type ScannerPlatform } from './camera';
import { ScannerComponent } from './scanner.component';

const API = environment.apiBaseUrl;

@Component({ standalone: true, template: '' })
class BlankComponent {}

const ROUTES = [{ path: '**', component: BlankComponent }];
const TOKEN = 'Abc_123-xyz_456-ABC_789-def_012-GHI_345';

const EVENT: EventRead = {
  id: 3,
  public_id: '3f2b8c1e-8a4d-4b7e-9c2a-1d2e3f4a5b6c',
  title: 'Navratri Garba Night',
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

const RAVI: PartyMember = { id: 11, name: 'Ravi Patil', type: 'ADULT', age: null, entered: false, entered_at: null };
const MEERA: PartyMember = { id: 12, name: 'Meera Patil', type: 'KID', age: 8, entered: false, entered_at: null };

const GUEST: ScannedGuest = {
  name: 'Asha Patil',
  contact: 'as•••@example.com',
  employee_id: 'E1001',
  guest_names: ['Ravi Patil', 'Meera Patil'],
  party_size: 3,
  email_masked: 'as•••@example.com',
  mobile_masked: '98•••••210',
  employee_entered: false,
  members: [RAVI, MEERA],
};

/** First visit: the pass was only looked up. */
const PENDING: ScanResponse = {
  result: 'pending_verification',
  message: '',
  guest: GUEST,
  checked_in_at: null,
  gate: null,
  people_entered: null,
};

/** The employee and Ravi are inside; Meera has not arrived. */
const LATE: ScanResponse = {
  result: 'pending_guests',
  message: '',
  guest: {
    ...GUEST,
    employee_entered: true,
    members: [{ ...RAVI, entered: true, entered_at: '2030-10-20T13:05:00' }, MEERA],
  },
  checked_in_at: '2030-10-20T13:05:00',
  gate: 'Gate 2',
  people_entered: 2,
};

const ADMITTED: ScanResponse = {
  result: 'admitted',
  message: 'Entry allowed',
  guest: {
    ...GUEST,
    employee_entered: true,
    members: [
      { ...RAVI, entered: true, entered_at: '2030-10-20T13:05:00' },
      { ...MEERA, entered: true, entered_at: '2030-10-20T13:05:00' },
    ],
  },
  checked_in_at: '2030-10-20T13:05:00',
  gate: 'Gate 2',
  people_entered: 3,
};

class FakeTrack {
  stopped = false;
  private listeners: Array<() => void> = [];
  stop(): void {
    this.stopped = true;
  }
  addEventListener(_type: string, listener: () => void): void {
    this.listeners.push(listener);
  }
  end(): void {
    this.listeners.forEach((listener) => listener());
  }
}

/** A real (empty) MediaStream so it can be attached to a <video>, reporting the fake track. */
function fakeStream(track: FakeTrack): MediaStream {
  const stream = new MediaStream();
  const tracks = [track] as unknown as MediaStreamTrack[];
  stream.getTracks = () => tracks;
  stream.getVideoTracks = () => tracks;
  return stream;
}

describe('ScannerComponent', () => {
  let fixture: ComponentFixture<ScannerComponent>;
  let component: ScannerComponent;
  let http: HttpTestingController;
  let platform: jasmine.SpyObj<ScannerPlatform>;
  let getUserMedia: jasmine.Spy;
  let track: FakeTrack;

  function el(selector: string): HTMLElement | null {
    return fixture.nativeElement.querySelector(selector);
  }

  function render(): void {
    fixture.detectChanges();
  }

  beforeEach(async () => {
    track = new FakeTrack();
    getUserMedia = jasmine.createSpy('getUserMedia').and.callFake(async () => fakeStream(track));
    const decoder: QrDecoder = { decode: async () => null };
    platform = jasmine.createSpyObj<ScannerPlatform>('platform', ['isSecureContext', 'mediaDevices', 'createDecoder', 'vibrate']);
    platform.isSecureContext.and.returnValue(true);
    platform.mediaDevices.and.returnValue({ getUserMedia } as unknown as MediaDevices);
    platform.createDecoder.and.resolveTo(decoder);

    await TestBed.configureTestingModule({
      imports: [ScannerComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter(ROUTES),
        { provide: SCANNER_PLATFORM, useValue: platform },
        { provide: ActivatedRoute, useValue: { snapshot: { paramMap: convertToParamMap({ eventId: '3' }) } } },
      ],
    }).compileComponents();

    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(ScannerComponent);
    component = fixture.componentInstance;
    spyOn(HTMLMediaElement.prototype, 'play').and.resolveTo();
    http.expectOne(`${API}/events/3`).flush(EVENT);
    http.expectOne(`${API}/gate/events/3/entries?limit=10&offset=0`).flush({ items: [], total: 0, limit: 10, offset: 0 });
    render();
  });

  afterEach(() => {
    fixture.destroy();
    http.verify();
  });

  it('asks before using the camera and requests the rear camera only after the officer taps', async () => {
    expect(getUserMedia).not.toHaveBeenCalled();
    expect(fixture.nativeElement.textContent).toContain('Allow camera and start scanning');

    await component.startCamera();
    render();

    expect(getUserMedia).toHaveBeenCalledOnceWith({ video: { facingMode: { ideal: 'environment' } }, audio: false });
    expect(component.cameraState()).toBe('active');
    const video = el('video') as HTMLVideoElement;
    expect(video.muted).toBeTrue();
    expect(video.hasAttribute('playsinline')).toBeTrue();
  });

  it('releases the camera when scanning stops, when leaving the page, and on sign-out', async () => {
    await component.startCamera();
    component.stopCamera();
    expect(track.stopped).toBeTrue();

    track = new FakeTrack();
    await component.startCamera();
    fixture.destroy();
    expect(track.stopped).toBeTrue();
  });

  it('stops the camera on sign-out', async () => {
    await component.startCamera();
    component.signOut();
    http.expectOne(`${API}/auth/logout`).flush(null);
    expect(track.stopped).toBeTrue();
  });

  it('shows permission-denied guidance', async () => {
    getUserMedia.and.rejectWith(new DOMException('denied', 'NotAllowedError'));
    await component.startCamera();
    render();

    expect(el('[data-testid="camera-error"]')?.getAttribute('data-kind')).toBe('denied');
    expect(fixture.nativeElement.textContent).toContain('Camera permission was denied');
  });

  it('distinguishes an unsupported browser, an insecure page, no camera and a busy camera', async () => {
    const cases: Array<[() => void, string]> = [
      [() => platform.mediaDevices.and.returnValue(undefined), 'unsupported'],
      [() => platform.isSecureContext.and.returnValue(false), 'insecure'],
      [() => getUserMedia.and.rejectWith(new DOMException('none', 'NotFoundError')), 'no-camera'],
      [() => getUserMedia.and.rejectWith(new DOMException('busy', 'NotReadableError')), 'in-use'],
      [() => platform.createDecoder.and.rejectWith(new Error('no decoder')), 'decoder-unsupported'],
    ];
    for (const [arrange, kind] of cases) {
      platform.isSecureContext.and.returnValue(true);
      platform.mediaDevices.and.returnValue({ getUserMedia } as unknown as MediaDevices);
      getUserMedia.and.callFake(async () => fakeStream(new FakeTrack()));
      platform.createDecoder.and.resolveTo({ decode: async () => null });
      arrange();

      await component.startCamera();
      render();

      expect(el('[data-testid="camera-error"]')?.getAttribute('data-kind')).withContext(kind).toBe(kind);
    }
  });

  it('reports an interrupted camera stream', async () => {
    await component.startCamera();
    track.end();
    render();
    expect(el('[data-testid="camera-error"]')?.getAttribute('data-kind')).toBe('interrupted');
  });

  /** Scan the pass and show the response; nothing else is sent. */
  function scanPass(response: ScanResponse = PENDING, token = TOKEN): void {
    component.handleDecoded(token);
    http.expectOne(`${API}/gate/events/3/scan`).flush(response);
    render();
  }

  function input(testId: string): HTMLInputElement {
    return el(`[data-testid="${testId}"]`) as HTMLInputElement;
  }

  function click(testId: string): void {
    input(testId).click();
    render();
  }

  function flushEntries(): void {
    http.expectOne(`${API}/gate/events/3/entries?limit=10&offset=0`).flush({ items: [], total: 0, limit: 10, offset: 0 });
  }

  it('submits only the decoded opaque token, then asks the officer to verify instead of admitting', () => {
    component.gate.set('Gate 2');
    component.handleDecoded(`  ${TOKEN}  `);

    const req = http.expectOne(`${API}/gate/events/3/scan`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ token: TOKEN, gate: 'Gate 2' });
    req.flush(PENDING);
    render();

    const result = el('[data-testid="scan-result"]')!;
    expect(result.getAttribute('data-kind')).toBe('pending_verification');
    expect(result.textContent).toContain('Verify guest');
    expect(el('[data-testid="party-size"]')?.textContent).toContain('3 people');
    expect(el('[data-testid="employee-id"]')?.textContent).toContain('E1001');
    expect(result.textContent).toContain('Meera Patil');
    expect(result.textContent).toContain('Kid, 8 yrs');
    expect(result.textContent).not.toContain('Admitted');
    // Looking a pass up lets nobody in and records no entry.
    http.expectNone(`${API}/gate/events/3/decision`);
    http.expectNone(`${API}/gate/events/3/entries?limit=10&offset=0`);
  });

  it('keeps Approve disabled until the employee ID is ticked, then admits those ticked with the server time', () => {
    component.gate.set('Gate 2');
    scanPass();

    expect((el('[data-testid="approve"]') as HTMLButtonElement).disabled).toBeTrue();
    expect(el('[data-testid="entering-count"]')?.textContent).toContain('Letting in 0 now · 0 of 3 inside');

    click('employee-checked');
    click('guest-11');
    expect((el('[data-testid="approve"]') as HTMLButtonElement).disabled).toBeFalse();
    expect(el('[data-testid="entering-count"]')?.textContent).toContain('Letting in 2 now · 2 of 3 inside');

    click('approve');
    const req = http.expectOne(`${API}/gate/events/3/decision`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({
      token: TOKEN,
      gate: 'Gate 2',
      decision: 'approve',
      employee_id_checked: true,
      guest_ids_entered: [11],
    });
    req.flush(ADMITTED);
    flushEntries();
    render();

    // No "Admitted" card: the scanner is straight back to ready, with a buzz instead.
    expect(el('[data-testid="scan-result"]')).toBeNull();
    expect(component.result()).toBeNull();
    expect(platform.vibrate).toHaveBeenCalledWith(120);
  });

  it('refreshes the recent entries after an approval and ignores the same pass for 3 seconds', () => {
    scanPass(LATE);
    click('guest-12');
    click('approve');
    http.expectOne(`${API}/gate/events/3/decision`).flush(ADMITTED);
    flushEntries();

    component.handleDecoded(TOKEN);
    http.expectNone(`${API}/gate/events/3/scan`);
    // A different pass is read immediately.
    component.handleDecoded('Zzz_999-yyy_888-XXX_777-www_666');
    http.expectOne(`${API}/gate/events/3/scan`).flush(PENDING);
  });

  it('can untick a guest again, and the employee alone can be admitted', () => {
    scanPass();
    click('employee-checked');
    click('guest-12');
    click('guest-12');
    expect(el('[data-testid="entering-count"]')?.textContent).toContain('Letting in 1 now');

    click('approve');
    const req = http.expectOne(`${API}/gate/events/3/decision`);
    expect(req.request.body.guest_ids_entered).toEqual([]);
    req.flush({ ...ADMITTED, people_entered: 1 });
    flushEntries();
  });

  it('lets late guests in on the same pass without another ID check', () => {
    scanPass(LATE);

    expect(el('[data-testid="scan-result"]')?.getAttribute('data-kind')).toBe('pending_guests');
    expect(el('[data-testid="employee-checked"]')).toBeNull();
    expect(el('[data-testid="employee-inside"]')?.textContent).toContain('Asha Patil is already inside');
    // Ravi is in already: ticked, locked, with his entry time.
    expect(input('guest-11').checked).toBeTrue();
    expect(input('guest-11').disabled).toBeTrue();
    expect(el('[data-testid="member-entered-at"]')?.textContent).toContain('6:35 PM');
    expect(input('guest-12').disabled).toBeFalse();
    expect((el('[data-testid="approve"]') as HTMLButtonElement).disabled).toBeTrue();
    expect(el('[data-testid="entering-count"]')?.textContent).toContain('Letting in 0 now · 2 of 3 inside');

    click('guest-12');
    expect(el('[data-testid="entering-count"]')?.textContent).toContain('Letting in 1 now · 3 of 3 inside');
    click('approve');

    const req = http.expectOne(`${API}/gate/events/3/decision`);
    expect(req.request.body).toEqual({ token: TOKEN, gate: null, decision: 'approve', guest_ids_entered: [12] });
    req.flush(ADMITTED);
    flushEntries();
  });

  it('refuses entry with a reason, records nothing else and offers the next guest', () => {
    scanPass();
    click('employee-checked');
    click('reject');

    expect(el('[data-testid="reject-panel"]')).not.toBeNull();
    expect((el('[data-testid="confirm-reject"]') as HTMLButtonElement).disabled).toBeTrue();
    click('reason-ID_MISMATCH');
    expect((el('[data-testid="confirm-reject"]') as HTMLButtonElement).disabled).toBeFalse();
    click('confirm-reject');

    const req = http.expectOne(`${API}/gate/events/3/decision`);
    expect(req.request.body).toEqual({ token: TOKEN, gate: null, decision: 'reject', reason: 'ID_MISMATCH', note: null });
    req.flush({ result: 'rejected', message: '', guest: null, checked_in_at: null, gate: null, people_entered: null });
    render();

    expect(el('[data-testid="scan-result"]')?.getAttribute('data-kind')).toBe('rejected');
    expect(el('[data-testid="scan-result"]')?.textContent).toContain('Entry refused');
    expect(el('[data-testid="scan-result"]')?.textContent).not.toContain('Asha Patil');
    expect(el('[data-testid="scan-next"]')?.textContent).toContain('Scan next guest');
    http.expectNone(`${API}/gate/events/3/entries?limit=10&offset=0`);
  });

  it('needs a note of at least three characters when the reason is Other', () => {
    scanPass();
    click('reject');
    click('reason-OTHER');
    const confirm = el('[data-testid="confirm-reject"]') as HTMLButtonElement;
    expect(confirm.disabled).toBeTrue();

    const note = el('[data-testid="reject-note"]') as HTMLTextAreaElement;
    note.value = 'ab';
    note.dispatchEvent(new Event('input'));
    render();
    expect(confirm.disabled).toBeTrue();

    note.value = '  Badge is someone else’s ';
    note.dispatchEvent(new Event('input'));
    render();
    expect(confirm.disabled).toBeFalse();

    click('confirm-reject');
    const req = http.expectOne(`${API}/gate/events/3/decision`);
    expect(req.request.body).toEqual({ token: TOKEN, gate: null, decision: 'reject', reason: 'OTHER', note: 'Badge is someone else’s' });
    req.flush({ result: 'rejected', message: '', guest: null, checked_in_at: null, gate: null, people_entered: null });
  });

  it('can go back from the reject panel to the approval without sending anything', () => {
    scanPass();
    click('reject');
    click('cancel-reject');

    expect(el('[data-testid="reject-panel"]')).toBeNull();
    expect(el('[data-testid="approve"]')).not.toBeNull();
    http.expectNone(`${API}/gate/events/3/decision`);
  });

  it('stays on the verification panel when a decision is not accepted or does not reach the server', () => {
    scanPass();
    click('employee-checked');
    click('approve');
    http
      .expectOne(`${API}/gate/events/3/decision`)
      .flush({ detail: 'Some of the selected guests are not on this pass. Scan the pass again.' }, { status: 422, statusText: 'Unprocessable' });
    render();
    expect(el('[data-testid="decision-error"]')?.textContent).toContain('not on this pass');
    expect(el('[data-testid="scan-result"]')?.getAttribute('data-kind')).toBe('pending_verification');

    click('approve');
    http.expectOne(`${API}/gate/events/3/decision`).error(new ProgressEvent('error'), { status: 0 });
    render();
    expect(el('[data-testid="decision-error"]')?.textContent).toContain('nobody was checked in');
    // The ticks survive, so the officer can simply try again.
    expect(input('employee-checked').checked).toBeTrue();
  });

  it('sends one decision at a time', () => {
    scanPass();
    click('employee-checked');
    component.approve();
    component.approve();

    http.expectOne(`${API}/gate/events/3/decision`).flush(ADMITTED);
    flushEntries();
  });

  it('shows the pass as it now stands when guests were already let in elsewhere', () => {
    scanPass(LATE);
    click('guest-12');
    click('approve');
    http.expectOne(`${API}/gate/events/3/decision`).flush({ ...LATE, result: 'guests_already_entered' });
    render();

    expect(el('[data-testid="scan-result"]')?.getAttribute('data-kind')).toBe('guests_already_entered');
    expect(el('[data-testid="scan-result"]')?.textContent).toContain('Already entered');
  });

  it('ends the session and stops on an expired token during a decision', () => {
    scanPass();
    click('employee-checked');
    click('approve');
    http.expectOne(`${API}/gate/events/3/decision`).flush({ detail: 'expired' }, { status: 401, statusText: 'Unauthorized' });
    render();

    expect(el('[data-testid="scan-result"]')?.getAttribute('data-kind')).toBe('session_expired');
  });

  it('clears the ticks when the next pass is scanned', () => {
    scanPass();
    click('employee-checked');
    click('guest-11');
    click('scan-next');

    scanPass(PENDING, 'Zzz_999-yyy_888-XXX_777-www_666');

    expect(input('employee-checked').checked).toBeFalse();
    expect(input('guest-11').checked).toBeFalse();
  });

  it('sends one request however many frames show the same pass, until "Scan next guest"', () => {
    component.handleDecoded(TOKEN);
    component.handleDecoded(TOKEN);
    component.handleDecoded(TOKEN);
    const req = http.expectOne(`${API}/gate/events/3/scan`);
    req.flush({ ...ADMITTED, result: 'already_checked_in' });
    render();

    // Result on screen: frames are still ignored.
    component.handleDecoded(TOKEN);
    http.expectNone(`${API}/gate/events/3/scan`);

    (el('[data-testid="scan-next"]') as HTMLButtonElement).click();
    // The same pass held in front of the camera is not re-read straight away...
    component.handleDecoded(TOKEN);
    http.expectNone(`${API}/gate/events/3/scan`);
    // ...but the next guest's pass is.
    component.handleDecoded('Zzz_999-yyy_888-XXX_777-www_666');
    http.expectOne(`${API}/gate/events/3/scan`).flush({ ...PENDING, result: 'invalid', guest: null });
  });

  it('rejects codes that are not pass tokens without calling the API', () => {
    component.handleDecoded('https://example.com/?token=abc');
    render();
    http.expectNone(`${API}/gate/events/3/scan`);
    expect(el('[data-testid="scan-result"]')?.getAttribute('data-kind')).toBe('invalid');
  });

  it('shows no party details for wrong-event, invalid or gate-closed results', () => {
    for (const result of ['wrong_event', 'invalid', 'gate_closed'] as const) {
      component.scanNext();
      component.handleDecoded(TOKEN.replace('A', result[0]));
      // Even if a response carried a guest, only passes awaiting a decision, admitted or used show one.
      http.expectOne(`${API}/gate/events/3/scan`).flush({ ...PENDING, result });
      render();
      const card = el('[data-testid="scan-result"]')!;
      expect(card.getAttribute('data-kind')).toBe(result);
      expect(card.textContent).not.toContain('Asha Patil');
      expect(card.textContent).not.toContain('as•••@example.com');
    }
  });

  it('explains a removed assignment and a network failure', () => {
    component.handleDecoded(TOKEN);
    http.expectOne(`${API}/gate/events/3/scan`).flush({ detail: 'Event not found' }, { status: 404, statusText: 'Not Found' });
    render();
    expect(el('[data-testid="scan-result"]')?.getAttribute('data-kind')).toBe('not_assigned');

    component.scanNext();
    component.handleDecoded(TOKEN.replace('A', 'B'));
    http.expectOne(`${API}/gate/events/3/scan`).error(new ProgressEvent('error'), { status: 0 });
    render();
    expect(el('[data-testid="scan-result"]')?.getAttribute('data-kind')).toBe('network');
  });
});

describe('ScannerComponent for an unassigned event', () => {
  it('shows that the event is unavailable and never loads its entries', async () => {
    await TestBed.configureTestingModule({
      imports: [ScannerComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter(ROUTES),
        { provide: ActivatedRoute, useValue: { snapshot: { paramMap: convertToParamMap({ eventId: '9' }) } } },
      ],
    }).compileComponents();
    const http = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(ScannerComponent);
    http.expectOne(`${API}/events/9`).flush({ detail: 'Event not found' }, { status: 404, statusText: 'Not Found' });
    fixture.detectChanges();

    expect(fixture.nativeElement.textContent).toContain('This event isn’t available.');
    http.verify();
    fixture.destroy();
  });
});
