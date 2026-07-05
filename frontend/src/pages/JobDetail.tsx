import { useParams } from "react-router-dom";
import { api } from "../api";
import { ErrorBanner, StatePill, timeAgo, usePolling } from "../components";

const TERMINAL = ["dead", "cancelled", "completed"];

export default function JobDetail() {
  const { jobId = "" } = useParams();
  const { data: job, error } = usePolling(() => api.job(jobId), 2500, [jobId]);

  if (error) return <ErrorBanner message={error} />;
  if (!job) return <div className="muted">Loading…</div>;

  return (
    <div>
      <div className="between">
        <div>
          <h1 className="page-title" style={{ marginBottom: 4 }}>{job.task_name}</h1>
          <div className="row"><StatePill state={job.state} /><span className="mono muted" style={{ fontSize: 12 }}>{job.id}</span></div>
        </div>
        <div className="row">
          {TERMINAL.includes(job.state) && (
            <button className="btn" onClick={() => api.retryJob(job.id)}>Retry</button>
          )}
          {!TERMINAL.includes(job.state) && (
            <button className="btn btn-danger" onClick={() => api.cancelJob(job.id)}>Cancel</button>
          )}
        </div>
      </div>

      <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", margin: "18px 0" }}>
        <div className="card" style={{ padding: 16 }}>
          <div style={{ fontWeight: 600, marginBottom: 12 }}>Details</div>
          {[["Type", job.job_type], ["Priority", job.priority],
            ["Attempts", `${job.attempts} / ${job.max_attempts}`],
            ["Retry", job.retry_strategy], ["Cron", job.cron_expression ?? " "],
            ["Worker", job.claimed_by_worker_id?.slice(0, 8) ?? " "],
            ["Created", timeAgo(job.created_at)], ["Finished", timeAgo(job.finished_at)]].map(([k, v]) => (
            <div key={k as string} className="between" style={{ padding: "5px 0", fontSize: 13 }}>
              <span className="muted">{k}</span><span className="mono">{String(v)}</span>
            </div>
          ))}
        </div>
        <div className="card" style={{ padding: 16 }}>
          <div style={{ fontWeight: 600, marginBottom: 12 }}>Payload / result</div>
          <div className="field-label">Payload</div>
          <pre className="mono" style={{ background: "#0b0f14", padding: 10, borderRadius: 8, fontSize: 12, overflow: "auto", margin: "4px 0 12px" }}>
            {JSON.stringify(job.payload, null, 2)}</pre>
          {job.last_error && (
            <>
              <div className="field-label" style={{ color: "#ff8b8f" }}>Last error</div>
              <pre className="mono" style={{ background: "#1c1215", padding: 10, borderRadius: 8, fontSize: 12, color: "#ff8b8f", overflow: "auto", margin: "4px 0" }}>
                {job.last_error}</pre>
            </>
          )}
          {job.result && (
            <>
              <div className="field-label" style={{ color: "#2fbf88" }}>Result</div>
              <pre className="mono" style={{ background: "#0b0f14", padding: 10, borderRadius: 8, fontSize: 12, overflow: "auto", margin: "4px 0" }}>
                {JSON.stringify(job.result, null, 2)}</pre>
            </>
          )}
        </div>
      </div>

      <div className="card" style={{ padding: 16, marginBottom: 18 }}>
        <div style={{ fontWeight: 600, marginBottom: 10 }}>Execution history</div>
        <table>
          <thead><tr><th>Attempt</th><th>Status</th><th>Worker</th><th>Duration</th><th>Error</th></tr></thead>
          <tbody>
            {job.executions.map((e) => (
              <tr key={e.id}>
                <td className="mono">#{e.attempt_number}</td>
                <td><StatePill state={e.status === "succeeded" ? "completed" : e.status === "failed" ? "failed" : "running"} /></td>
                <td className="mono">{e.worker_id?.slice(0, 8) ?? " "}</td>
                <td className="mono">{e.duration_ms != null ? `${e.duration_ms}ms` : " "}</td>
                <td className="muted" style={{ maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{e.error ?? " "}</td>
              </tr>
            ))}
            {job.executions.length === 0 && <tr><td colSpan={5} className="muted">Not executed yet.</td></tr>}
          </tbody>
        </table>
      </div>

      <div className="card" style={{ padding: 16 }}>
        <div style={{ fontWeight: 600, marginBottom: 10 }}>Logs</div>
        <div className="mono" style={{ fontSize: 12, display: "flex", flexDirection: "column", gap: 4 }}>
          {job.logs.map((l) => (
            <div key={l.id} className="row" style={{ gap: 10 }}>
              <span className="muted" style={{ width: 52 }}>{timeAgo(l.created_at)}</span>
              <span style={{ width: 60, color: l.level === "error" ? "#ff8b8f" : l.level === "warning" ? "#f0a63a" : "#7a8699" }}>{l.level}</span>
              <span>{l.message}</span>
            </div>
          ))}
          {job.logs.length === 0 && <span className="muted">No logs.</span>}
        </div>
      </div>
    </div>
  );
}
