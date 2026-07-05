export type JobState =
  | "queued" | "scheduled" | "claimed" | "running"
  | "completed" | "failed" | "dead" | "cancelled";

export interface Project { id: string; name: string; slug: string; description: string; created_at: string; }
export interface RetryPolicy { strategy: string; max_attempts: number; base_delay_seconds: number; backoff_factor: number; }
export interface Queue {
  id: string; project_id: string; name: string; description: string;
  priority: number; concurrency_limit: number; rate_limit_per_sec: number;
  is_paused: boolean; created_at: string; retry_policy: RetryPolicy | null;
}
export interface QueueStats {
  queue_id: string; queued: number; scheduled: number; running: number;
  completed: number; dead: number; failed_recent: number; is_paused: boolean; concurrency_limit: number;
}
export interface Job {
  id: string; queue_id: string; task_name: string; payload: Record<string, unknown>;
  job_type: string; state: JobState; priority: number; run_at: string;
  attempts: number; max_attempts: number; retry_strategy: string;
  cron_expression: string | null; batch_id: string | null;
  claimed_by_worker_id: string | null; last_error: string | null;
  result: Record<string, unknown> | null;
  created_at: string; started_at: string | null; finished_at: string | null;
}
export interface Execution {
  id: string; attempt_number: number; status: string; worker_id: string | null;
  started_at: string; finished_at: string | null; duration_ms: number | null; error: string | null;
}
export interface JobLog { id: string; level: string; message: string; created_at: string; context: Record<string, unknown> | null; }
export interface JobDetail extends Job { executions: Execution[]; logs: JobLog[]; }
export interface Worker {
  id: string; hostname: string; pid: number; queues: string[]; concurrency: number;
  status: string; active_jobs: number; total_processed: number; total_failed: number;
  registered_at: string; last_heartbeat_at: string;
}
export interface DeadLetter {
  id: string; job_id: string; queue_id: string; task_name: string;
  total_attempts: number; last_error: string | null; failure_summary: string | null;
  created_at: string; replayed_at: string | null;
}
export interface Overview {
  jobs: Record<string, number>;
  workers: { alive: number; total: number };
  dead_letter_total: number; success_rate: number; health: string;
}
export interface Page<T> { items: T[]; total: number; page: number; page_size: number; pages: number; }

const BASE = "/api/v1";
const TOKEN_KEY = "scheduler_token";

export const token = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (t: string) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

async function req<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json", ...(opts.headers as any) };
  const t = token.get();
  if (t) headers["Authorization"] = `Bearer ${t}`;
  const res = await fetch(`${BASE}${path}`, { ...opts, headers });
  if (res.status === 401) { token.clear(); window.location.hash = "#/login"; }
  if (!res.ok) {
    let detail = res.statusText;
    try { const b = await res.json(); detail = b.detail ? (typeof b.detail === "string" ? b.detail : JSON.stringify(b.detail)) : detail; } catch { /* ignore */ }
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const api = {
  register: (b: { organization_name: string; email: string; password: string; full_name?: string }) =>
    req<{ access_token: string }>("/auth/register", { method: "POST", body: JSON.stringify(b) }),
  login: (b: { email: string; password: string }) =>
    req<{ access_token: string }>("/auth/login", { method: "POST", body: JSON.stringify(b) }),
  me: () => req<{ email: string; full_name: string; role: string }>("/auth/me"),

  projects: () => req<Project[]>("/projects"),
  createProject: (b: { name: string; slug: string; description?: string }) =>
    req<Project>("/projects", { method: "POST", body: JSON.stringify(b) }),

  queues: (projectId: string) => req<Queue[]>(`/projects/${projectId}/queues`),
  createQueue: (projectId: string, b: any) =>
    req<Queue>(`/projects/${projectId}/queues`, { method: "POST", body: JSON.stringify(b) }),
  queueStats: (queueId: string) => req<QueueStats>(`/queues/${queueId}/stats`),
  pauseQueue: (queueId: string) => req<Queue>(`/queues/${queueId}/pause`, { method: "POST" }),
  resumeQueue: (queueId: string) => req<Queue>(`/queues/${queueId}/resume`, { method: "POST" }),

  jobs: (queueId: string, params: Record<string, string> = {}) => {
    const q = new URLSearchParams(params).toString();
    return req<Page<Job>>(`/queues/${queueId}/jobs${q ? `?${q}` : ""}`);
  },
  createJob: (queueId: string, b: any) =>
    req<Job>(`/queues/${queueId}/jobs`, { method: "POST", body: JSON.stringify(b) }),
  job: (jobId: string) => req<JobDetail>(`/jobs/${jobId}`),
  retryJob: (jobId: string) => req<Job>(`/jobs/${jobId}/retry`, { method: "POST" }),
  cancelJob: (jobId: string) => req<Job>(`/jobs/${jobId}/cancel`, { method: "POST" }),

  deadLetters: (queueId: string) => req<Page<DeadLetter>>(`/queues/${queueId}/dead-letters`),
  replayDeadLetter: (entryId: string) => req<Job>(`/dead-letters/${entryId}/replay`, { method: "POST" }),

  workers: () => req<Worker[]>("/workers"),
  overview: () => req<Overview>("/dashboard/overview"),
  throughput: (minutes = 60, bucket = 60) =>
    req<{ buckets: { t: number; succeeded: number; failed: number }[]; bucket_seconds: number }>(
      `/dashboard/throughput?minutes=${minutes}&bucket_seconds=${bucket}`),
};
