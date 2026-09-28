import { classifyCameraError } from './camera';
import { gateStatus, sortForGate } from './gate-status';
import { extractPassToken } from './pass-token';

describe('extractPassToken', () => {
  it('accepts only the opaque URL-safe token the backend issues', () => {
    const token = 'Abc_123-xyz_456-ABC_789-def_012-GHI_345';
    expect(extractPassToken(` ${token}\n`)).toBe(token);
    for (const raw of ['', 'short', 'https://evil.example/pass', '{"event":1,"name":"x"}', 'x'.repeat(129), 'a b c d e f g h i j k l']) {
      expect(extractPassToken(raw)).withContext(raw).toBeNull();
    }
  });
});

describe('classifyCameraError', () => {
  it('maps getUserMedia errors to guidance kinds', () => {
    expect(classifyCameraError(new DOMException('', 'NotAllowedError'))).toBe('denied');
    expect(classifyCameraError(new DOMException('', 'NotFoundError'))).toBe('no-camera');
    expect(classifyCameraError(new DOMException('', 'OverconstrainedError'))).toBe('no-camera');
    expect(classifyCameraError(new DOMException('', 'NotReadableError'))).toBe('in-use');
    expect(classifyCameraError(new Error('?'))).toBe('unknown');
  });
});

describe('gateStatus', () => {
  const window = { gate_opens_at: '2030-10-20T09:30:00', gate_closes_at: '2030-10-20T17:30:00' };

  it('uses the backend gate window, read as UTC', () => {
    expect(gateStatus(window, Date.parse('2030-10-20T09:29:00Z'))).toBe('upcoming');
    expect(gateStatus(window, Date.parse('2030-10-20T12:00:00Z'))).toBe('open');
    expect(gateStatus(window, Date.parse('2030-10-20T17:31:00Z'))).toBe('closed');
  });

  it('lists open gates first, then upcoming, then finished', () => {
    const now = Date.parse('2030-10-20T12:00:00Z');
    const closed = { id: 1, gate_opens_at: '2030-10-19T09:00:00', gate_closes_at: '2030-10-19T17:00:00' };
    const open = { id: 2, ...window };
    const upcoming = { id: 3, gate_opens_at: '2030-10-21T09:00:00', gate_closes_at: '2030-10-21T17:00:00' };
    expect(sortForGate([closed, open, upcoming], now).map((e) => e.id)).toEqual([2, 3, 1]);
  });
});
