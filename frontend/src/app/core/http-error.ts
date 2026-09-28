import { HttpErrorResponse } from '@angular/common/http';
import type { ApiError } from './models';

/**
 * Backend errors today are FastAPI's `{"detail": "..."}` (a string for domain errors, a list for
 * 422 validation errors); the `{"error": {code, message}}` envelope is the documented target.
 */
export function apiErrorMessage(err: unknown, fallback = 'Something went wrong. Please try again.'): string {
  if (err instanceof HttpErrorResponse) {
    const body = err.error as (ApiError & { detail?: unknown }) | undefined;
    if (body?.error?.message) {
      return body.error.message;
    }
    if (typeof body?.detail === 'string' && body.detail) {
      return body.detail;
    }
    if (err.status === 422) {
      return 'Some details are not valid. Please check the form and try again.';
    }
    if (err.status === 0) {
      return 'Could not reach the server. Check your connection and try again.';
    }
    if (err.status === 401) {
      return 'Please sign in again.';
    }
    if (err.status === 403) {
      return "You don't have permission to do that.";
    }
    if (err.status === 404) {
      return 'Not found.';
    }
    if (err.status === 429) {
      return 'Too many attempts. Please wait and try again.';
    }
  }
  return fallback;
}
