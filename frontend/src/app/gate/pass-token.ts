/**
 * The QR pass carries only an opaque random token (`secrets.token_urlsafe(32)` on the backend). Nothing in it
 * is trusted: the backend looks the token up and decides everything. This only rejects obvious non-passes
 * (other QR codes, URLs, text) before a request is made; it mirrors `PassToken` in `backend/app/modules/gate/schemas.py`.
 */
const PASS_TOKEN = /^[A-Za-z0-9_-]{20,128}$/;

export function extractPassToken(raw: string | null | undefined): string | null {
  const value = (raw ?? '').trim();
  return PASS_TOKEN.test(value) ? value : null;
}
