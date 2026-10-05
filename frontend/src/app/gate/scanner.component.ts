import { DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, DestroyRef, ElementRef, ViewChild, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { AuthService } from '../core/auth.service';
import { EventsApiService } from '../core/events-api.service';
import { GateApiService } from '../core/gate-api.service';
import { apiErrorMessage } from '../core/http-error';
import type {
  DecisionRequest,
  EntryRead,
  EventRead,
  PartyMember,
  RejectionReason,
  ScanResponse,
  ScanResult,
} from '../core/models';
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

/** Shortest reasonable note for a refusal, matching the backend. */
const MIN_NOTE_LENGTH = 3;

export const REJECTION_REASONS: ReadonlyArray<{ value: RejectionReason; label: string }> = [
  { value: 'ID_MISMATCH', label: 'ID does not match the registered employee ID' },
  { value: 'ID_NOT_PRESENTED', label: 'No employee ID shown' },
  { value: 'OTHER', label: 'Other (add a note)' },
];

const RESULT_VIEWS: Record<ViewKind, Omit<ScanView, 'detail' | 'response'>> = {
  pending_verification: { kind: 'pending_verification', tone: 'warning', symbol: '?', heading: 'Verify guest' },
  pending_guests: { kind: 'pending_guests', tone: 'warning', symbol: '+', heading: 'Guests arriving' },
  admitted: { kind: 'admitted', tone: 'success', symbol: '✓', heading: 'Admitted' },
  rejected: { kind: 'rejected', tone: 'danger', symbol: '✕', heading: 'Entry refused' },
  already_checked_in: { kind: 'already_checked_in', tone: 'warning', symbol: '!', heading: 'Already checked in' },
  guests_already_entered: { kind: 'guests_already_entered', tone: 'warning', symbol: '!', heading: 'Already entered' },
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
  pending_verification: 'Check the employee’s ID card, tick everyone who is present, then approve or reject.',
  pending_guests: 'The employee is already in. Tick the guests who have arrived now, then approve.',
  admitted: 'Let in the people ticked.',
  rejected: 'Entry refused and recorded. Do not admit.',
  already_checked_in: 'Everyone on this pass has already entered. Do not admit again.',
  guests_already_entered: 'Some of those guests are already in. Nobody was added. Check who is still to arrive.',
  wrong_event: 'This pass is for a different event. Do not admit.',
  invalid: 'This is not a valid pass. Do not admit.',
  gate_closed: 'Entry is not open for this event right now. Do not admit.',
};

const PARTY_RESULTS: ReadonlyArray<ScanResult> = [
  'pending_verification',
  'pending_guests',
  'admitted',
  'already_checked_in',
  'guests_already_entered',
];

/** True while the officer still has to approve or reject the pass in front of them. */
export function awaitsDecision(view: ScanView): boolean {
  return view.kind === 'pending_verification' || view.kind === 'pending_guests';
}

export function viewForResponse(response: ScanResponse): ScanView {
  const base = RESULT_VIEWS[response.result] ?? RESULT_VIEWS.error;
  // Party details are shown only when the backend sends them, which it does only for passes of this event that
  // are awaiting a decision, admitted or already used.
  const showParty = PARTY_RESULTS.includes(response.result);
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
 * uploaded or stored. A scan only looks the pass up: the officer then checks the employee's ID card by eye, ticks
 * who is present and approves (or rejects) with `POST /gate/events/{id}/decision`. The same pass can be scanned
 * again later so guests who arrive after the employee can be let in. The backend decides every outcome and sets
 * the entry times. Scanning pauses while a request is in flight and while a result is shown, so one pass in front
 * of the camera produces one request.
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

  // The verification step for the pass on screen. Reset every time a pass is shown.
  readonly reasons = REJECTION_REASONS;
  /** The officer compared the employee's ID card with the registered employee ID. */
  readonly employeeChecked = signal(false);
  /** Accompanying guests ticked as present right now (never includes guests already inside). */
  readonly selectedGuests = signal<number[]>([]);
  readonly rejecting = signal(false);
  readonly rejectReason = signal<RejectionReason | ''>('');
  readonly rejectNote = signal('');
  /** True while an approve or reject request is in flight. */
  readonly deciding = signal(false);
  readonly decisionError = signal('');

  readonly entries = signal<EntryRead[]>([]);
  readonly entriesState = signal<'loading' | 'ready' | 'error'>('loading');
  readonly entriesError = signal('');

  private stream: MediaStream | null = null;
  private decoder: QrDecoder | null = null;
  private decodeTimer: ReturnType<typeof setTimeout> | null = null;
  private destroyed = false;
  private lastToken = '';
  private lastTokenReleasedAt = 0;
  /** The pass awaiting a decision; kept in memory only, and sent back with the decision. */
  private pendingToken = '';
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
      this.showResult(
        viewForResponse({ result: 'invalid', message: '', guest: null, checked_in_at: null, gate: null, people_entered: null }),
      );
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
    this.pendingToken = '';
    this.resetVerification();
  }

  // ---- verification: approve or reject ---------------------------------------------------------

  /** True while the officer still has to approve or reject the pass on screen. */
  awaiting(view: ScanView): boolean {
    return awaitsDecision(view);
  }

  /** "Adult" or "Kid, 8 yrs": what the officer needs to match a guest to the person in front of them. */
  memberLabel(member: PartyMember): string {
    if (member.type === 'KID') return member.age !== null ? `(Kid, ${member.age} yrs)` : '(Kid)';
    return member.type === 'ADULT' ? '(Adult)' : '';
  }

  /** Guests of the pass on screen who are not inside yet. */
  guestsToArrive(view: ScanView): number {
    return (view.response?.guest?.members ?? []).filter((member) => !member.entered).length;
  }

  isSelected(guestId: number): boolean {
    return this.selectedGuests().includes(guestId);
  }

  toggleGuest(guestId: number): void {
    this.selectedGuests.update((ids) => (ids.includes(guestId) ? ids.filter((id) => id !== guestId) : [...ids, guestId]));
  }

  /** People inside already, before this approval. */
  insideNow(view: ScanView): number {
    return view.response?.people_entered ?? 0;
  }

  /** People this approval would let in: the employee (first visit only) plus the ticked guests. */
  lettingIn(view: ScanView): number {
    const employee = view.kind === 'pending_verification' && this.employeeChecked() ? 1 : 0;
    return employee + this.selectedGuests().length;
  }

  canApprove(view: ScanView): boolean {
    if (this.deciding() || this.rejecting()) return false;
    // The first approval needs the employee's ID checked; later ones need at least one late guest ticked.
    return view.kind === 'pending_verification' ? this.employeeChecked() : this.selectedGuests().length > 0;
  }

  canConfirmReject(): boolean {
    const reason = this.rejectReason();
    if (this.deciding() || !reason) return false;
    return reason !== 'OTHER' || this.rejectNote().trim().length >= MIN_NOTE_LENGTH;
  }

  startReject(): void {
    this.decisionError.set('');
    this.rejecting.set(true);
  }

  cancelReject(): void {
    this.rejecting.set(false);
    this.rejectReason.set('');
    this.rejectNote.set('');
  }

  approve(): void {
    const view = this.result();
    if (!view || !awaitsDecision(view) || !this.canApprove(view)) return;
    // Only the first approval carries the ID check; guests arriving later are not the employee.
    const idCheck = view.kind === 'pending_verification' ? { employee_id_checked: true } : {};
    this.decide({ decision: 'approve', ...idCheck, guest_ids_entered: this.selectedGuests() });
  }

  confirmReject(): void {
    const reason = this.rejectReason();
    if (!reason || !this.canConfirmReject()) return;
    this.decide({ decision: 'reject', reason, note: this.rejectNote().trim() || null });
  }

  private decide(fields: Omit<DecisionRequest, 'token' | 'gate'>): void {
    if (this.deciding() || !this.pendingToken) return;
    this.deciding.set(true);
    this.decisionError.set('');
    this.api.decide(this.eventId, { token: this.pendingToken, gate: this.gate().trim() || null, ...fields }).subscribe({
      next: (response) => {
        this.deciding.set(false);
        if (response.result === 'admitted') {
          // No confirmation card: the officer goes straight back to scanning. A short buzz stands in for it, and
          // the recent-entries list shows the entry. The usual same-pass cooldown stops an instant re-read.
          this.scanNext();
          this.platform.vibrate(120);
          this.loadEntries();
          return;
        }
        this.showResponse(this.pendingToken, response);
      },
      error: (err) => {
        this.deciding.set(false);
        const view = viewForError(err);
        if (view.kind === 'not_assigned' || view.kind === 'session_expired' || view.kind === 'forbidden') {
          this.showResult(view);
          this.stopCamera();
          if (view.kind === 'session_expired') this.auth.clearSession();
        } else {
          // Stay on the verification panel so the officer can correct the ticks or try again.
          this.decisionError.set(this.decisionErrorMessage(err));
        }
      },
    });
  }

  private decisionErrorMessage(err: unknown): string {
    const status = err instanceof HttpErrorResponse ? err.status : -1;
    if (status === 0) return 'The decision did not reach the server, so nobody was checked in. Check the connection and try again.';
    if (status === 422) return apiErrorMessage(err, 'That decision was not accepted. Nobody was checked in. Scan the pass again.');
    return apiErrorMessage(err, 'The decision could not be completed. Nobody was checked in. Try again.');
  }

  private resetVerification(): void {
    this.employeeChecked.set(false);
    this.selectedGuests.set([]);
    this.rejecting.set(false);
    this.rejectReason.set('');
    this.rejectNote.set('');
    this.decisionError.set('');
  }

  /** Shows a scan or decision response; a pass still awaiting a decision starts a fresh verification. */
  private showResponse(token: string, response: ScanResponse): void {
    const view = viewForResponse(response);
    this.resetVerification();
    this.pendingToken = awaitsDecision(view) ? token : '';
    this.showResult(view);
  }

  private submit(token: string): void {
    this.submitting.set(true);
    this.lastToken = token;
    this.api.scan(this.eventId, { token, gate: this.gate().trim() || null }).subscribe({
      next: (response) => {
        this.submitting.set(false);
        this.showResponse(token, response);
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
    // A pass awaiting the officer's decision is neither good nor bad news, so it gets a short tap.
    this.platform.vibrate(awaitsDecision(view) ? 60 : view.tone === 'success' ? 120 : [200, 100, 200]);
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
