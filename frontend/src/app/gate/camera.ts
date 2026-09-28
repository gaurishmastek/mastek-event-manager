import { InjectionToken } from '@angular/core';

/** Decodes a QR code from the current video frame. Resolves to the raw text, or null when no code is visible. */
export interface QrDecoder {
  decode(video: HTMLVideoElement): Promise<string | null>;
}

export type CameraErrorKind =
  | 'unsupported'
  | 'insecure'
  | 'denied'
  | 'no-camera'
  | 'in-use'
  | 'decoder-unsupported'
  | 'interrupted'
  | 'unknown';

export const CAMERA_ERROR_MESSAGES: Record<CameraErrorKind, { title: string; help: string }> = {
  unsupported: {
    title: 'This browser cannot use the camera',
    help: 'Open this page in a current version of Chrome, Safari, Edge or Firefox, or type the pass code below.',
  },
  insecure: {
    title: 'Camera needs a secure connection',
    help: 'Browsers only allow the camera on HTTPS pages. Open the gate site using its https:// address.',
  },
  denied: {
    title: 'Camera permission was denied',
    help: 'Allow camera access for this site in your browser’s site settings (the lock icon beside the address), then try again.',
  },
  'no-camera': {
    title: 'No camera found',
    help: 'This device has no usable camera. Use a phone or tablet with a camera, or type the pass code below.',
  },
  'in-use': {
    title: 'The camera is busy',
    help: 'Another app or browser tab is using the camera. Close it and try again.',
  },
  'decoder-unsupported': {
    title: 'QR scanning is not available',
    help: 'The QR reader could not load in this browser. Check your connection and try again, or type the pass code below.',
  },
  interrupted: {
    title: 'The camera stopped',
    help: 'The camera feed was interrupted (for example by another app or the screen locking). Start the camera again.',
  },
  unknown: {
    title: 'Could not start the camera',
    help: 'Try again. If it keeps failing, reload the page or type the pass code below.',
  },
};

/** Maps a `getUserMedia` failure to guidance the officer can act on. */
export function classifyCameraError(err: unknown): CameraErrorKind {
  const name = (err as { name?: string } | null)?.name ?? '';
  switch (name) {
    case 'NotAllowedError':
    case 'PermissionDeniedError':
    case 'SecurityError':
      return 'denied';
    case 'NotFoundError':
    case 'DevicesNotFoundError':
    case 'OverconstrainedError':
      return 'no-camera';
    case 'NotReadableError':
    case 'TrackStartError':
    case 'AbortError':
      return 'in-use';
    default:
      return 'unknown';
  }
}

/** Browser capabilities the scanner needs, behind a token so tests can replace them. */
export interface ScannerPlatform {
  isSecureContext(): boolean;
  mediaDevices(): Pick<MediaDevices, 'getUserMedia'> | undefined;
  /** A QR decoder: the native `BarcodeDetector` when it supports QR codes, otherwise the ZXing fallback. */
  createDecoder(): Promise<QrDecoder>;
  vibrate(pattern: number | number[]): void;
}

// The Shape Detection API (Chrome/Android, some Safari builds). Not in TypeScript's DOM lib.
interface BarcodeDetectorInstance {
  detect(source: CanvasImageSource): Promise<Array<{ rawValue: string }>>;
}
interface BarcodeDetectorStatic {
  new (options: { formats: string[] }): BarcodeDetectorInstance;
  getSupportedFormats?: () => Promise<string[]>;
}

async function nativeDecoder(): Promise<QrDecoder | null> {
  const Detector = (globalThis as { BarcodeDetector?: BarcodeDetectorStatic }).BarcodeDetector;
  if (!Detector) return null;
  try {
    const formats = (await Detector.getSupportedFormats?.()) ?? ['qr_code'];
    if (!formats.includes('qr_code')) return null;
    const detector = new Detector({ formats: ['qr_code'] });
    return {
      decode: async (video) => (await detector.detect(video))[0]?.rawValue ?? null,
    };
  } catch {
    return null;
  }
}

async function zxingDecoder(): Promise<QrDecoder> {
  // Loaded only when the scanner starts and the browser has no native detector, to keep it out of other pages.
  const { BrowserQRCodeReader } = await import('@zxing/browser');
  const reader = new BrowserQRCodeReader();
  return {
    decode: async (video) => {
      try {
        // Draws the current frame to an in-memory canvas and decodes it locally; nothing is uploaded or kept.
        return reader.decode(video).getText();
      } catch {
        return null; // No QR code in this frame.
      }
    },
  };
}

export const browserScannerPlatform: ScannerPlatform = {
  isSecureContext: () => globalThis.isSecureContext === true,
  mediaDevices: () => (typeof navigator !== 'undefined' ? navigator.mediaDevices : undefined),
  createDecoder: async () => (await nativeDecoder()) ?? (await zxingDecoder()),
  vibrate: (pattern) => {
    try {
      navigator.vibrate?.(pattern);
    } catch {
      // Vibration is optional feedback.
    }
  },
};

export const SCANNER_PLATFORM = new InjectionToken<ScannerPlatform>('SCANNER_PLATFORM', {
  providedIn: 'root',
  factory: () => browserScannerPlatform,
});
