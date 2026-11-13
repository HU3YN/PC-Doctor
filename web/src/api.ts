// Everything the dashboard asks the API, with the shapes it gets back.
// The shapes mirror api/pcdoctor_api/schemas.py.

export type Severity = "critical" | "warning" | "info";
export type Verdict = "critical" | "warning" | "ok";

export interface Finding {
  code: string;
  category: string;
  severity: Severity;
  title: string;
  summary: string;
  next_checks: string[];
  evidence: Record<string, unknown>;
  error_codes: string[];
}

export interface Troubleshooting {
  likely_cause: string;
  category: string;
  confidence: "low" | "medium" | "high";
  because: { finding: string; why: string }[];
  steps: string[];
  rule_out: string[];
  missing: string[];
}

export interface RunSummary {
  id: string;
  created_at: string;
  captured_at: string | null;
  label: string;
  mode: string;
  verdict: Verdict;
  headline: string;
  critical_count: number;
  warning_count: number;
  info_count: number;
  cpu: string | null;
  gpu: string | null;
  ram_gb: number | null;
  avg_fps: number | null;
  fps_1pct_low: number | null;
  is_demo: boolean;
  rules_version: string;
}

export interface WorkLogBrief {
  id: number;
  occurred_on: string;
  title: string;
  status: string;
  category: string;
  device_type: string;
  device: string;
  root_cause: string;
  fix: string;
  components: string[];
  error_codes: string[];
  is_demo: boolean;
  run_id: string | null;
}

export interface WorkLogEntry extends WorkLogBrief {
  created_at: string;
  updated_at: string;
  symptoms: string;
  steps: string;
  reference: string;
  minutes_spent: number | null;
  run_label: string | null;
  privacy_warnings: string[];
}

/** What the create / edit form sends. */
export interface WorkLogInput {
  title: string;
  occurred_on: string | null;
  status: string;
  category: string;
  device_type: string;
  device: string;
  symptoms: string;
  steps: string;
  root_cause: string;
  fix: string;
  components: string[];
  error_codes: string[];
  reference: string;
  minutes_spent: number | null;
  run_id: string | null;
}

export interface SimilarCase {
  entry: WorkLogBrief;
  score: number;
  reasons: string[];
}

export interface Check {
  code: string;
  category: string;
  title: string;
  status: "found" | "passed" | "no_data" | "error";
}

export interface SensorStat {
  label: string;
  unit: string;
  min: number;
  avg: number;
  p95: number;
  max: number;
  samples: number;
}

export interface FrameStats {
  application: string;
  frames: number;
  duration_s: number;
  avg_fps: number;
  fps_1pct_low: number;
  fps_01pct_low: number;
  frame_time_median_ms: number;
  frame_time_p99_ms: number;
  frame_time_max_ms: number;
  spike_count: number;
  spikes_per_min: number;
  hitch_count: number;
  enough_frames: boolean;
}

export interface RunDetail extends RunSummary {
  notes: string;
  collector_version: string;
  file_bytes: number;
  rules_outdated: boolean;
  findings: Finding[];
  checks: Check[];
  device: Record<string, string | number | null>;
  frame_stats: FrameStats | null;
  sensor_stats: Record<string, SensorStat>;
  analysis_notes: string[];
  has_frames: boolean;
  has_sensors: boolean;
  similar_cases: SimilarCase[];
  work_log: WorkLogBrief[];
}

export interface Series {
  frames?: { t: number[]; avg_ms: number[]; max_ms: number[] };
  sensors?: { t: number[] } & Record<string, (number | null)[]>;
}

export interface Rule {
  code: string;
  category: string;
  title: string;
  detects: string;
  needs: string;
}

export interface Meta {
  version: string;
  rules_version: string;
  categories: Record<string, string>;
  statuses: Record<string, string>;
  device_types: Record<string, string>;
  rules: Rule[];
}

export interface StopCode {
  code: number;
  hex: string;
  name: string;
  category: string;
  meaning: string;
  causes: string[];
  checks: string[];
  hardware_likely: boolean;
  cases?: SimilarCase[];
}

export interface Stats {
  runs: number;
  work_log_entries: number;
  demo_runs: number;
  demo_work_log: number;
  fault_types_detectable: number;
}

export interface NoBootSymptom {
  key: string;
  title: string;
  meaning: string;
  category: string;
  causes: string[];
  checks: string[];
}

export interface PhotoReading {
  text: string;
  is_blue_screen: boolean;
  stop_codes: StopCode[];
  unknown_codes: string[];
  drivers: string[];
  cases: SimilarCase[];
}

export interface CollectorInfo {
  available: boolean;
  includes_presentmon: boolean;
  lan_addresses: string[];
  photo_reading: boolean;
}

export interface AuthStatus {
  setup_needed: boolean;
  signed_in: boolean;
  username: string | null;
}

export interface PhotoNotes {
  summary: string;
  observations: string[];
  error_codes: string[];
  category: string;
  next_checks: string[];
  uncertain: string[];
}

export interface InboxPhoto {
  id: string;
  created_at: string;
  label: string;
  text: string;
  stop_codes: StopCode[];
  unknown_codes: string[];
  drivers: string[];
  is_blue_screen: boolean;
  ai: PhotoNotes | null;
  work_log_id: number | null;
  cases: SimilarCase[];
}

export interface Draft {
  title: string;
  category: string;
  symptoms: string;
  steps: string;
  root_cause: string;
  fix: string;
  error_codes: string[];
  components: string[];
}

/** An error whose message is safe and useful to show to the user. */
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

function describe(detail: unknown, status: number): string {
  if (typeof detail === "string") return detail;
  // FastAPI validation errors: [{loc: ["body", "title"], msg: "..."}]
  if (Array.isArray(detail) && detail.length > 0) {
    return detail
      .map((item: { loc?: unknown[]; msg?: string }) => {
        const field = (item.loc ?? []).filter((part) => part !== "body").join(".");
        return field ? `${field}: ${item.msg}` : (item.msg ?? "invalid");
      })
      .join("; ");
  }
  return `The server answered with an error (${status}).`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new ApiError("Cannot reach the PC Doctor server. Is it running?", 0);
  }
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  let body: unknown;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null; // not JSON (a proxy error page, for example)
  }
  if (!response.ok) {
    const detail = (body as { detail?: unknown } | null)?.detail;
    throw new ApiError(describe(detail, response.status), response.status);
  }
  return body as T;
}

const json = (method: string, data: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(data),
});

function query(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export const api = {
  meta: () => request<Meta>("/api/meta"),
  stats: () => request<Stats>("/api/stats"),

  runs: () => request<{ items: RunSummary[]; total: number }>("/api/runs?limit=200"),
  run: (id: string) => request<RunDetail>(`/api/runs/${id}`),
  series: (id: string) => request<Series>(`/api/runs/${id}/series`),
  uploadRun: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ run: RunSummary; duplicate: boolean; share_key: string | null }>("/api/runs", {
      method: "POST",
      body: form,
    });
  },
  updateRun: (id: string, patch: { label?: string; notes?: string }) =>
    request<RunDetail>(`/api/runs/${id}`, json("PATCH", patch)),
  reanalyzeRun: (id: string) => request<RunDetail>(`/api/runs/${id}/reanalyze`, { method: "POST" }),
  deleteRun: (id: string) => request<void>(`/api/runs/${id}`, { method: "DELETE" }),

  workLog: (filters: { q?: string; category?: string; status?: string }) =>
    request<{ items: WorkLogEntry[]; total: number }>(`/api/worklog${query({ ...filters, limit: 500 })}`),
  entry: (id: number) => request<WorkLogEntry>(`/api/worklog/${id}`),
  createEntry: (input: WorkLogInput) => request<WorkLogEntry>("/api/worklog", json("POST", input)),
  updateEntry: (id: number, input: WorkLogInput) =>
    request<WorkLogEntry>(`/api/worklog/${id}`, json("PUT", input)),
  deleteEntry: (id: number) => request<void>(`/api/worklog/${id}`, { method: "DELETE" }),
  similar: (body: {
    text?: string;
    codes?: string[];
    category?: string | null;
    parts?: string[];
    exclude_id?: number | null;
    limit?: number;
  }) => request<SimilarCase[]>("/api/worklog/similar", json("POST", body)),
  importWorkLog: (document: unknown) =>
    request<{ imported: number; skipped: number }>("/api/worklog/import", json("POST", document)),

  stopCodes: (q: string) => request<StopCode[]>(`/api/stopcodes${query({ q, limit: 12 })}`),
  stopCode: (code: string) => request<StopCode>(`/api/stopcodes/${encodeURIComponent(code)}`),

  authStatus: () => request<AuthStatus>("/api/auth/status"),
  setup: (body: { username: string; password: string; setup_code: string }) =>
    request<AuthStatus>("/api/auth/setup", json("POST", body)),
  login: (body: { username: string; password: string }) =>
    request<AuthStatus>("/api/auth/login", json("POST", body)),
  logout: () => request<AuthStatus>("/api/auth/logout", { method: "POST" }),

  sharedRun: (key: string) => request<RunDetail>(`/api/shared/${encodeURIComponent(key)}`),
  sharedSeries: (key: string) => request<Series>(`/api/shared/${encodeURIComponent(key)}/series`),

  createPhotoLink: (label: string) =>
    request<{ token: string; path: string; label: string; expires_at: string }>(
      "/api/photo-links",
      json("POST", { label }),
    ),
  photoLink: (token: string) =>
    request<{ label: string; expires_at: string }>(`/api/photo-links/${encodeURIComponent(token)}`),
  sendPhoto: (token: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ received: boolean }>(`/api/photo-links/${encodeURIComponent(token)}/photos`, {
      method: "POST",
      body: form,
    });
  },
  inbox: () => request<{ items: InboxPhoto[]; waiting: number }>("/api/inbox"),
  describePhoto: (id: string) => request<InboxPhoto>(`/api/inbox/${id}/describe`, { method: "POST" }),
  linkPhoto: (id: string, workLogId: number | null) =>
    request<InboxPhoto>(`/api/inbox/${id}`, json("PATCH", { work_log_id: workLogId })),
  deletePhoto: (id: string) => request<void>(`/api/inbox/${id}`, { method: "DELETE" }),

  assist: () => request<{ available: boolean; model: string }>("/api/assist"),
  draft: (body: { run_id?: string | null; photo_id?: string | null; notes?: string }) =>
    request<Draft>("/api/assist/draft", json("POST", body)),

  troubleshoot: (runId: string, question: string) =>
    request<Troubleshooting>("/api/assist/troubleshoot", json("POST", { run_id: runId, question })),

  collector: () => request<CollectorInfo>("/api/collector"),
  noBoot: () => request<NoBootSymptom[]>("/api/noboot"),
  readPhoto: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<PhotoReading>("/api/photos", { method: "POST", body: form });
  },

  loadDemo: () => request<{ runs: number; work_log: number }>("/api/demo", { method: "POST" }),
  clearDemo: () => request<{ runs: number; work_log: number }>("/api/demo", { method: "DELETE" }),
};
