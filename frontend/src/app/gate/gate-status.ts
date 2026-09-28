import type { EventRead } from '../core/models';
import { utcIso } from '../core/time';

export type GateStatus = 'open' | 'upcoming' | 'closed';

/** Whether the event's gate accepts scans at `now`, from the backend's gate window. The backend still decides each scan. */
export function gateStatus(event: Pick<EventRead, 'gate_opens_at' | 'gate_closes_at'>, now = Date.now()): GateStatus {
  const opens = Date.parse(utcIso(event.gate_opens_at) ?? '');
  const closes = Date.parse(utcIso(event.gate_closes_at) ?? '');
  if (now < opens) return 'upcoming';
  if (now > closes) return 'closed';
  return 'open';
}

const ORDER: Record<GateStatus, number> = { open: 0, upcoming: 1, closed: 2 };

/** Open gates first, then upcoming, then finished events; stable within each group (the API sorts by start). */
export function sortForGate<T extends Pick<EventRead, 'gate_opens_at' | 'gate_closes_at'>>(events: T[], now = Date.now()): T[] {
  return events
    .map((event, index) => ({ event, index, rank: ORDER[gateStatus(event, now)] }))
    .sort((a, b) => a.rank - b.rank || a.index - b.index)
    .map(({ event }) => event);
}
