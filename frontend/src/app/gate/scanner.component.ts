import { DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, DestroyRef, ElementRef, ViewChild, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { AuthService } from '../core/auth.service';
import { EventsApiService } from '../core/events-api.service';
import { GateApiService } from '../core/gate-api.service';
import { apiErrorMessage } from '../core/http-error';
import type { EntryRead, EventRead, ScanResponse, ScanResult } from '../core/models';
import { IST, utcIso } from '../core/time';
import { ButtonComponent } from '../ui/button/button.component';
import { SpinnerComponent } from '../ui/spinner/spinner.component';
import { CAMERA_ERROR_MESSAGES, SCANNER_PLATFORM, classifyCameraError, type CameraErrorKind, type QrDecoder } from './camera';
import { extractPassToken } from './pass-token';

/** How often a video frame is decoded while scanning. */
const DECODE_INTERVAL_MS = 250;
/** After "Scan next guest", the pass just handled is ignored this long so it isn't read again straight away. */
const SAME_PASS_COOLDOWN_MS = 3000;

type CameraState = 'idle' | 'starting' | 'active' | 'error';
type ViewKind = ScanResult | 'not_assigned' | 'session_expired' | 'forbidden' | 'network' | 'error';

export interface ScanView {
  kind: ViewKind;
  tone: 'success' | 'warning' | 'danger';
  symbol: string;
  heading: string;
  detail: string;
  response: ScanResponse | null;
}

const RESULT_VIEWS: Record<ViewKind, Omit<ScanView, 'detail' | 'response'>> = {
  admitted: { kind: 'admitted', tone: 'success', symbol: '✓', heading: 'Admitted' },
  already_checked_in: { kind: 'already_checked_in', tone: 'warning', symbol: '!', heading: 'Already checked in' },
  wrong_event: { kind: 'wrong_event', tone: 'danger', symbol: '✕', heading: 'Wrong event' },
  invalid: { kind: 'invalid', tone: 'danger', symbol: '✕', heading: 'Invalid pass' },
  gate_closed: { kind: 'gate_closed', tone: 'danger', symbol: '✕', heading: 'Gate closed' },
  not_assigned: { kind: 'not_assigned', tone: 'danger', symbol: '✕', heading: 'Not assigned to this event' },
  session_expired: { kind: 'session_expired', tone: 'danger', symbol: '✕', heading: 'Signed out' },
  forbidden: { kind: 'forbidden', tone: 'danger', symbol: '✕', heading: 'Not allowed' },
  network: { kind: 'network', tone: 'danger', symbol: '✕', heading: 'No connection' },
  error: { kind: 'error', tone: 'danger', symbol: '✕', heading: 'Scan failed' },
};

const RESULT_DETAIL: Record<ScanResult, string> = {
  admitted: 'Let the whole party in.',
  already_checked_in: 'This pass was already used. Do not admit again.',
  wrong_event: 'This pass is for a different event. Do not admit.',
  invalid: 'This is not a valid pass. Do not admit.',
  gate_closed: 'Entry is not open for this event right now. Do not admit.',
};

export function viewForResponse(response: ScanResponse): ScanView {
  const base = RESULT_VIEWS[response.result] ?? RESULT_VIEWS.error;
  // Party details are shown only when the backend sends them, which it does only for admitted or used passes.
  const showParty = response.result === 'admitted' || response.result === 'already_checked_in';
  return {
    ...base,
    detail: RESULT_DETAIL[response.result] ?? response.message,
    response: showParty ? response : { ...response, guest: null },
  };
}

export function viewForError(err: unknown): ScanView {
  const status = err instanceof HttpErrorResponse ? err.status : -1;
  const make = (kind: ViewKind, detail: string): ScanView => ({ ...RESULT_VIEWS[kind], detail, response: null });
  switch (status) {
    case 0:
      return make('network', 'The scan did not reach the server, so nobody was checked in. Check the connection and scan again.');
    case 401:
      return make('session_expired', 'Your session has ended. Sign in again to keep scanning.');
    case 403:
      return make('forbidden', 'Your account is not allowed to scan passes.');
    case 404:
      return make('not_assigned', 'This event is no longer assigned to you. Contact an administrator.');
    case 422:
      return make('invalid', 'This is not a valid pass. Do not admit.');
    default:
      return make('error', apiErrorMessage(err, 'The scan could not be completed. Nobody was checked in. Try again.'));
  }
}

/**
 * Mobile-first gate scanner for one assigned event (`/gate/scan/:eventId`).
 *
 * The camera starts only when the officer asks, decodes QR codes on the device (native `BarcodeDetector` or the
 * ZXing fallback), and submits only the opaque pass token to `POST /gate/events/{id}/scan`. Frames are never
 * uploaded or stored. The backend decides every outcome and sets the check-in time. Scanning pauses while a
 * request is in flight and while a result is shown, so one pass in front of the camera produces one request.
 */
@Component({
  selector: 'app-scanner',
  standalone: true,
  imports: [DatePipe, FormsModule, RouterLink, ButtonComponent, SpinnerComponent],
  templateUrl: './scanner.component.html',
})
export class ScannerComponent {
  @ViewChild('video', { static: true }) private videoRef!: ElementRef<HTMLVideoElement>;

  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly api = inject(GateApiService);
  private readonly eventsApi = inject(EventsApiService);
  private readonly auth = inject(AuthService);
  private readonly platform = inject(SCANNER_PLATFORM);

  readonly eventId = Number(this.route.snapshot.paramMap.get('eventId'));
  readonly ist = IST;
  readonly utc = utcIso;

  readonly event = signal<EventRead | null>(null);
  readonly eventState = signal<'loading' | 'ready' | 'unavailable' | 'error'>('loading');
  readonly eventError = signal('');

  readonly gate = signal('');
  readonly manualToken = signal('');
  readonly manualError = signal('');

  readonly cameraState = signal<CameraState>('idle');
  readonly cameraError = signal<CameraErrorKind | null>(null);
  readonly cameraMessages = CAMERA_ERROR_MESSAGES;

  /** True while a scan request is in flight. */
  readonly submitting = signal(false);
  readonly result = signal<ScanView | null>(null);

  readonly entries = signal<EntryRead[]>([]);
  readonly entriesState = signal<'loading' | 'ready' | 'error'>('loading');
  readonly entriesError = signal('');

  private stream: MediaStream | null = null;
  private decoder: QrDecoder | null = null;
  private decodeTimer: ReturnType<typeof setTimeout> | null = null;
  private destroyed = false;
  private lastToken = '';
  private lastTokenReleasedAt = 0;
  private readonly onVisibilityChange = () => {
    // Never keep the camera running in the background.
    if (document.visibilityState === 'hidden') this.stopCamera();
  };

  constructor() {
    document.addEventListener('visibilitychange', this.onVisibilityChange);
    inject(DestroyRef).onDestroy(() => {
      this.destroyed = true;
      document.removeEventListener('visibilitychange', this.onVisibilityChange);
      this.stopCamera();
    });
    this.loadEvent();
  }

  // ---- event and entries ------------------------------------------------------------------

  loadEvent(): void {
    this.eventState.set('loading');
    this.eventsApi.get(this.eventId).subscribe({
      next: (event) => {
        this.event.set(event);
        this.eventState.set('ready');
        this.loadEntries();
      },
      error: (err) => {
        if (err instanceof HttpErrorResponse && (err.status === 404 || err.status === 422)) {
          this.eventState.set('unavailable');
        } else if (err instanceof HttpErrorResponse && err.status === 401) {
          this.sessionEnded();
        } else {
          this.eventState.set('error');
          this.eventError.set(apiErrorMessage(err, 'Could not load this event.'));
        }
      },
    });
  }

  loadEntries(): void {
    this.entriesState.set('loading');
    this.api.entries(this.eventId, 10, 0).subscribe({
      next: (page) => {
        this.entries.set(page.items);
        this.entriesState.set('ready');
      },
      error: (err) => {
        this.entriesState.set('error');
        this.entriesError.set(apiErrorMessage(err, 'Could not load recent entries.'));
      },
    });
  }

  // ---- camera --------------------------------------------------------------------------------

  async startCamera(): Promise<void> {
    if (this.cameraState() === 'starting' || this.cameraState() === 'active') return;
    this.cameraError.set(null);

    if (!this.platform.isSecureContext()) return this.failCamera('insecure');
    const media = this.platform.mediaDevices();
    if (!media?.getUserMedia) return this.failCamera('unsupported');

    this.cameraState.set('starting');
    try {
      this.decoder = await this.platform.createDecoder();
    } catch {
      return this.failCamera('decoder-unsupported');
    }

    let stream: MediaStream;
    try {
      stream = await media.getUserMedia({ video: { facingMode: { ideal: 'environment' } }, audio: false });
    } catch (err) {
      return this.failCamera(classifyCameraError(err));
    }
    if (this.destroyed || this.cameraState() !== 'starting') {
      // The officer left (or stopped) while the permission prompt was open.
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    this.stream = stream;
    stream.getVideoTracks().forEach((track) =>
      track.addEventListener('ended', () => {
        if (this.stream === stream) this.failCamera('interrupted');
      }),
    );

    const video = this.videoRef.nativeElement;
    video.muted = true;
    video.setAttribute('playsinline', '');
    video.srcObject = stream;
    try {
      await video.play();
    } catch {
      // Autoplay of a muted, inline stream is allowed after a user gesture; a failure here is not fatal.
    }
    this.cameraState.set('active');
    this.scheduleDecode();
  }

  stopCamera(): void {
    if (this.decodeTimer !== null) {
      clearTimeout(this.decodeTimer);
      this.decodeTimer = null;
    }
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
    const video = this.videoRef?.nativeElement;
    if (video) video.srcObject = null;
    if (this.cameraState() !== 'error') this.cameraState.set('idle');
  }

  private failCamera(kind: CameraErrorKind): void {
    this.stopCamera();
    this.cameraError.set(kind);
    this.cameraState.set('error');
  }

  private scheduleDecode(): void {
    if (this.destroyed || this.cameraState() !== 'active') return;
    this.decodeTimer = setTimeout(() => void this.decodeFrame(), DECODE_INTERVAL_MS);
  }

  private async decodeFrame(): Promise<void> {
    this.decodeTimer = null;
    const video = this.videoRef.nativeElement;
    // Skip frames while a scan is in flight or a result is on screen: the officer must move on explicitly.
    if (this.decoder && !this.submitting() && !this.result() && video.readyState >= 2 && video.videoWidth > 0) {
      try {
        const text = await this.decoder.decode(video);
        if (text) this.handleDecoded(text);
      } catch {
        // A single bad frame; keep scanning.
      }
    }
    this.scheduleDecode();
  }

  // ---- scanning ------------------------------------------------------------------------------

  /** Called with each decoded QR text. Ignores repeats, non-pass codes, and anything while busy. */
  handleDecoded(raw: string): void {
    if (this.submitting() || this.result()) return;
    const token = extractPassToken(raw);
    if (token === null) {
      this.showResult(viewForResponse({ result: 'invalid', message: '', guest: null, checked_in_at: null, gate: null }));
      return;
    }
    if (token === this.lastToken && Date.now() - this.lastTokenReleasedAt < SAME_PASS_COOLDOWN_MS) return;
    this.submit(token);
  }

  submitManualToken(): void {
    this.manualError.set('');
    if (this.submitting() || this.result()) return;
    const token = extractPassToken(this.manualToken());
    if (token === null) {
      this.manualError.set('That is not a pass code. Codes are 20–128 letters, digits, - or _.');
      return;
    }
    this.manualToken.set('');
    this.submit(token);
  }

  scanNext(): void {
    this.lastTokenReleasedAt = Date.now();
    this.result.set(null);
  }

  private submit(token: string): void {
    this.submitting.set(true);
    this.lastToken = token;
    this.api.scan(this.eventId, { token, gate: this.gate().trim() || null }).subscribe({
      next: (response) => {
        this.submitting.set(false);
        this.showResult(viewForResponse(response));
        if (response.result === 'admitted') this.loadEntries();
      },
      error: (err) => {
        this.submitting.set(false);
        const view = viewForError(err);
        this.showResult(view);
        if (view.kind === 'not_assigned' || view.kind === 'session_expired' || view.kind === 'forbidden') {
          this.stopCamera();
        }
        if (view.kind === 'session_expired') this.auth.clearSession();
      },
    });
  }

  private showResult(view: ScanView): void {
    this.result.set(view);
    this.platform.vibrate(view.tone === 'success' ? 120 : [200, 100, 200]);
  }

  // ---- navigation ----------------------------------------------------------------------------

  changeEvent(): void {
    this.stopCamera();
    this.router.navigateByUrl('/gate/events');
  }

  signOut(): void {
    this.stopCamera();
    this.auth.logout();
    this.router.navigateByUrl('/gate/login', { replaceUrl: true });
  }

  signInAgain(): void {
    this.stopCamera();
    this.router.navigateByUrl('/gate/login', { replaceUrl: true });
  }

  private sessionEnded(): void {
    this.auth.clearSession();
    this.router.navigateByUrl('/gate/login', { replaceUrl: true });
  }
}
