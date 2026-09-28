import { DatePipe } from '@angular/common';
import { Component, ElementRef, OnDestroy, ViewChild, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { GateApiService } from '../core/gate-api.service';
import { apiErrorMessage } from '../core/http-error';
import type { EntryRead, ScanResponse } from '../core/models';
import { BadgeComponent, type BadgeTone } from '../ui/badge/badge.component';
import { ButtonComponent } from '../ui/button/button.component';
import { InputComponent } from '../ui/input/input.component';

// The Chrome/Android Shape Detection API. Not in TS lib.dom yet.
interface BarcodeDetectorLike {
  detect(source: CanvasImageSource): Promise<Array<{ rawValue: string }>>;
}
declare const BarcodeDetector: { new (options: { formats: string[] }): BarcodeDetectorLike } | undefined;

const RESULT_TONE: Record<ScanResponse['result'], BadgeTone> = {
  admitted: 'success',
  already_checked_in: 'warning',
  wrong_event: 'destructive',
  invalid: 'destructive',
  gate_closed: 'destructive',
};

/**
 * Mobile-first gate scanner: scans the guest's QR pass with the device camera when the
 * browser supports the Shape Detection API, and always offers manual token entry as a
 * fallback (matches "if scanning is down, the gate fails closed" from the spec, plus a way
 * to keep moving without a working camera). Calls `POST /gate/events/{id}/scan`.
 */
@Component({
  selector: 'app-scanner',
  standalone: true,
  imports: [DatePipe, FormsModule, ButtonComponent, InputComponent, BadgeComponent],
  templateUrl: './scanner.component.html',
})
export class ScannerComponent implements OnDestroy {
  @ViewChild('video') private videoRef?: ElementRef<HTMLVideoElement>;

  private readonly route = inject(ActivatedRoute);
  private readonly api = inject(GateApiService);

  readonly eventId = Number(this.route.snapshot.paramMap.get('eventId'));
  readonly gate = signal('');
  readonly manualToken = signal('');
  readonly cameraSupported = signal(typeof BarcodeDetector !== 'undefined');
  readonly cameraActive = signal(false);
  readonly cameraError = signal('');
  readonly scanning = signal(false);
  readonly lastResult = signal<ScanResponse | null>(null);
  readonly entries = signal<EntryRead[]>([]);

  private stream: MediaStream | null = null;
  private detectLoop: number | null = null;
  private lastTokenScanned = '';
  private lastTokenScannedAt = 0;

  constructor() {
    this.loadEntries();
  }

  ngOnDestroy(): void {
    this.stopCamera();
  }

  toneFor(result: ScanResponse['result']): BadgeTone {
    return RESULT_TONE[result];
  }

  loadEntries(): void {
    this.api.entries(this.eventId, 10, 0).subscribe({ next: (page) => this.entries.set(page.items) });
  }

  async startCamera(): Promise<void> {
    this.cameraError.set('');
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } });
      const video = this.videoRef?.nativeElement;
      if (!video) return;
      video.srcObject = this.stream;
      await video.play();
      this.cameraActive.set(true);
      this.runDetectionLoop(video);
    } catch {
      this.cameraError.set('Could not access the camera. Use manual entry below.');
    }
  }

  stopCamera(): void {
    if (this.detectLoop !== null) {
      cancelAnimationFrame(this.detectLoop);
      this.detectLoop = null;
    }
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
    this.cameraActive.set(false);
  }

  private runDetectionLoop(video: HTMLVideoElement): void {
    if (typeof BarcodeDetector === 'undefined') return;
    const detector = new BarcodeDetector({ formats: ['qr_code'] });

    const tick = async () => {
      if (!this.cameraActive()) return;
      try {
        const codes = await detector.detect(video);
        const token = codes[0]?.rawValue;
        const now = Date.now();
        if (token && !(token === this.lastTokenScanned && now - this.lastTokenScannedAt < 4000)) {
          this.lastTokenScanned = token;
          this.lastTokenScannedAt = now;
          this.submitScan(token);
        }
      } catch {
        // Detection hiccup on one frame; keep the camera loop going.
      }
      this.detectLoop = requestAnimationFrame(tick);
    };
    this.detectLoop = requestAnimationFrame(tick);
  }

  submitManualToken(): void {
    const token = this.manualToken().trim();
    if (!token) return;
    this.submitScan(token);
    this.manualToken.set('');
  }

  private submitScan(token: string): void {
    if (this.scanning()) return;
    this.scanning.set(true);
    this.api.scan(this.eventId, { token, gate: this.gate().trim() || null }).subscribe({
      next: (result) => {
        this.scanning.set(false);
        this.lastResult.set(result);
        if (result.result === 'admitted') {
          this.loadEntries();
        }
      },
      error: (err) => {
        this.scanning.set(false);
        this.lastResult.set({
          result: 'invalid',
          message: apiErrorMessage(err, 'Scan failed. Try again.'),
          guest: null,
          checked_in_at: null,
          gate: null,
        });
      },
    });
  }
}
