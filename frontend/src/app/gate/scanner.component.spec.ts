import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { environment } from '../../environments/environment';
import type { EventRead, ScanResponse } from '../core/models';
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
  created_at: '2026-09-28T10:00:00',
  updated_at: '2026-09-28T10:00:00',
  created_by: 1,
  updated_by: 1,
  gate_opens_at: '2030-10-20T09:30:00',
  gate_closes_at: '2030-10-20T17:30:00',
};

const ADMITTED: ScanResponse = {
  result: 'admitted',
  message: 'Entry allowed',
  guest: {
    name: 'Asha Patil',
    contact: 'as•••@example.com',
    employee_id: 'E1001',
    guest_names: ['Ravi Patil', 'Meera Patil'],
    party_size: 3,
    email_masked: 'as•••@example.com',
    mobile_masked: '98•••••210',
  },
  checked_in_at: '2030-10-20T13:05:00',
  gate: 'Gate 2',
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

  it('submits only the decoded opaque token and shows the admitted party with the server time', () => {
    component.gate.set('Gate 2');
    component.handleDecoded(`  ${TOKEN}  `);

    const req = http.expectOne(`${API}/gate/events/3/scan`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ token: TOKEN, gate: 'Gate 2' });
    req.flush(ADMITTED);
    http.expectOne(`${API}/gate/events/3/entries?limit=10&offset=0`).flush({ items: [], total: 0, limit: 10, offset: 0 });
    render();

    const result = el('[data-testid="scan-result"]')!;
    expect(result.getAttribute('data-kind')).toBe('admitted');
    expect(result.textContent).toContain('Admitted');
    expect(result.textContent).toContain('3 people');
    expect(result.textContent).toContain('E1001');
    expect(result.textContent).toContain('Meera Patil');
    expect(result.textContent).toContain('98•••••210');
    // 13:05 UTC is 6:35 PM in Mumbai.
    expect(el('[data-testid="checked-in-at"]')?.textContent).toContain('6:35:00 PM');
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
    http.expectOne(`${API}/gate/events/3/scan`).flush({ ...ADMITTED, result: 'invalid', guest: null });
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
      // Even if a response carried a guest, only admitted or already-used passes show one.
      http.expectOne(`${API}/gate/events/3/scan`).flush({ ...ADMITTED, result });
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
