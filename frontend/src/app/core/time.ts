/** The backend stores and returns naive UTC timestamps; add the zone so the browser parses them as UTC. */
export function utcIso(value: string | null | undefined): string | null {
  if (!value) return null;
  return /(Z|[+-]\d{2}:?\d{2})$/.test(value) ? value : `${value}Z`;
}

/** Mumbai time, for `DatePipe`'s timezone argument. */
export const IST = '+0530';
