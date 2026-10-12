export type LogLevel = 'debug' | 'info' | 'warning' | 'error' | 'fatal';

export interface LogMessage {
  timestamp: string;
  level: LogLevel;
  logger: string;
  message: string;
  exception?: string;
}

export interface LogEntry {
  id: string;
  request_id: string;
  type: 'request' | 'app';
  timestamp: string;
  service: string;
  environment: string;
  host?: string;
  method?: string;
  path?: string;
  route?: string;
  query?: string;
  status_code?: number;
  duration_ms?: number;
  client_ip?: string;
  user_agent?: string;
  level: LogLevel;
  levels: LogLevel[];
  messages: LogMessage[];
}

export interface LogPage {
  items: LogEntry[];
  next_cursor: string | null;
}

export interface FacetValue {
  value: string | number;
  count: number;
}

export type FacetName = 'level' | 'status' | 'method' | 'route' | 'host' | 'service' | 'environment' | 'type';

export type Facets = Record<FacetName, FacetValue[]>;

export interface HistogramBucket {
  start: string;
  total: number;
  warning: number;
  error: number;
}

export interface Histogram {
  start: string;
  end: string;
  bucket_seconds: number;
  buckets: HistogramBucket[];
}

export type TimeRange = '15m' | '1h' | '6h' | '24h' | '3d' | '7d' | '30d';

export const TIME_RANGES: { value: TimeRange; label: string }[] = [
  { value: '15m', label: 'Last 15 minutes' },
  { value: '1h', label: 'Last hour' },
  { value: '6h', label: 'Last 6 hours' },
  { value: '24h', label: 'Last 24 hours' },
  { value: '3d', label: 'Last 3 days' },
  { value: '7d', label: 'Last 7 days' },
  { value: '30d', label: 'Last 30 days' },
];

/** Everything the user can filter by. Mirrors the backend's query parameters. */
export interface LogFilters {
  q: string;
  range: TimeRange;
  level: string[];
  status: string[];
  method: string[];
  route: string[];
  path: string;
  host: string[];
  service: string[];
  environment: string[];
  type: string[];
}

export const DEFAULT_FILTERS: LogFilters = {
  q: '',
  range: '1h',
  level: [],
  status: [],
  method: [],
  route: [],
  path: '',
  host: [],
  service: [],
  environment: [],
  type: [],
};

export const LIST_FILTERS = ['level', 'status', 'method', 'route', 'host', 'service', 'environment', 'type'] as const;
export type ListFilterName = (typeof LIST_FILTERS)[number];

export interface LogsStatus {
  mongodb: string;
  target: string;
  /** True when the backend runs with LOGS_ENABLE_DEMO_DATA=true. */
  demo_data?: boolean;
}

/** What the Live stream reports to the page. */
export type LiveEvent =
  | { type: 'open' }
  | { type: 'reconnecting' }
  | { type: 'failure'; detail: string }
  | { type: 'log'; entry: LogEntry };

export type LiveStatus = 'off' | 'connecting' | 'live' | 'reconnecting' | 'failed';
