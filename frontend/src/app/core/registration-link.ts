/**
 * The public registration link for an event. Always built from the event's random `public_id`,
 * never its numeric database id, so links cannot be guessed or enumerated.
 */
export function registrationLink(origin: string, eventPublicId: string): string {
  return `${origin.replace(/\/+$/, '')}/register/${encodeURIComponent(eventPublicId)}`;
}
