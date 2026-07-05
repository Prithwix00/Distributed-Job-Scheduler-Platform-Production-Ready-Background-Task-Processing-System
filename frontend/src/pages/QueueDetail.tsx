import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, Job } from "../api";
import { ErrorBanner, Modal, StatePill, timeAgo, usePolling } from "../components";

const STATES = ["", "queued", "scheduled", "claimed", "running", "completed", "dead", "cancelled"];

export default function QueueDetail() {
  const { queueId = "" } = useParams();
  const [tab, setTab] = useState<"jobs" | "dlq">("jobs");
  const [stateFilter, setStateFilter] = useState("");
  const [page, setPage] = useState(1);
  const [showJob, setShowJob] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { data: stats } = usePolling(() => api.queueStats(queueId), 3000, [queueId]);
  const { data: jobs } = usePolling(
    () => api.jobs(queueId, { page: String(page), page_size: "20", ...(stateFilter ? { state: stateFilter } : {}) }),
    2500, [queueId, page, stateFilter]
  );
  const { data: dlq } = usePolling(() => api.deadLetters(queueId), 4000, [queueId]);

  return (
    <div>
      <div className="between">
        <div>
          <Link className="link" to="/queues" style={{ fontSize: 12 }}>← Queues</Link>
          <h1 className="page-title" style={{ marginTop: 4 }}>Queue</h1>
          <div className="page-sub mono">{queueId}</div>
        </div>
        <button className="btn btn-primary" onClick={() => setShowJob(true)}>Enqueue job</button>
      </div>
      <ErrorBanner message={error} />

      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(110px,1fr))", marginBottom: 18 }}>
        {[["queued", stats?.queued, "#5b8def"], ["scheduled", stats?.scheduled, "#a06bff"],
          ["running", stats?.running, "#f0a63a"], ["completed", stats?.completed, "#2fbf88"],
          ["dead", stats?.dead, "#e5484d"]].map(([label, v, c]) => (
          <div key={label as string} className="card" style={{ padding: "12px 14px" }}>
            <div className="field-label">{label as string}</div>
            <div className="mono" style={{ fontSize: 22, fontWeight: 600, color: c as string }}>{(v as number) ?? 0}</div>
          </div>
        ))}
      </div>

      <div className="row" style={{ marginBottom: 14, gap: 6 }}>
        <button className={`btn ${tab === "jobs" ? "btn-primary" : ""}`} onClick={() => setTab("jobs")}>Jobs</button>
        <button className={`btn ${tab === "dlq" ? "btn-primary" : ""}`} onClick={() => setTab("dlq")}>
          Dead letters {dlq?.total ? `(${dlq.total})` : ""}
        </button>
      </div>

      {tab === "jobs" && (
        <>
          <div className="row" style={{ marginBottom: 10 }}>
            <label className="field-label" style={{ margin: 0 }}>State</label>
            <select className="input" style={{ width: 180 }} value={stateFilter}
              onChange={(e) => { setStateFilter(e.target.value); setPage(1); }}>
              {STATES.map((s) => <option key={s} value={s}>{s || "all"}</option>)}
            </select>
          </div>
          <div className="card">
            <table>
              <thead><tr><th>Job</th><th>Task</th><th>State</th><th>Attempts</th><th>Created</th></tr></thead>
              <tbody>
                {(jobs?.items ?? []).map((j: Job) => (
                  <tr key={j.id}>
                    <td><Link className="link mono" to={`/jobs/${j.id}`}>{j.id.slice(0, 8)}</Link></td>
                    <td className="mono">{j.task_name}</td>
                    <td><StatePill state={j.state} /></td>
                    <td className="mono">{j.attempts}/{j.max_attempts}</td>
                    <td className="muted">{timeAgo(j.created_at)}</td>
                  </tr>
                ))}
                {jobs && jobs.items.length === 0 && (
                  <tr><td colSpan={5} className="muted" style={{ textAlign: "center", padding: 24 }}>No jobs match this filter.</td></tr>
                )}
              </tbody>
            </table>
          </div>
          {jobs && jobs.pages > 1 && (
            <div className="row" style={{ justifyContent: "flex-end", marginTop: 10 }}>
              <button className="btn" disabled={page <= 1} onClick={() => setPage(page - 1)}>Prev</button>
              <span className="muted mono" style={{ fontSize: 12 }}>{page} / {jobs.pages}</span>
              <button className="btn" disabled={page >= jobs.pages} onClick={() => setPage(page + 1)}>Next</button>
            </div>
          )}
        </>
      )}

      {tab === "dlq" && (
        <div className="card">
          <table>
            <thead><tr><th>Task</th><th>Attempts</th><th>Last error</th><th>Failed</th><th></th></tr></thead>
            <tbody>
              {(dlq?.items ?? []).map((d) => (
                <tr key={d.id}>
                  <td className="mono">{d.task_name}</td>
                  <td className="mono">{d.total_attempts}</td>
                  <td className="muted" style={{ maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{d.last_error}</td>
                  <td className="muted">{timeAgo(d.created_at)}</td>
                  <td style={{ textAlign: "right" }}>
                    <button className="btn" disabled={!!d.replayed_at} onClick={async () => {
                      try { await api.replayDeadLetter(d.id); } catch (e: any) { setError(e.message); }
                    }}>{d.replayed_at ? "Replayed" : "Replay"}</button>
                  </td>
                </tr>
              ))}
              {dlq && dlq.items.length === 0 && (
                <tr><td colSpan={5} className="muted" style={{ textAlign: "center", padding: 24 }}>Nothing dead-lettered. That is a good sign.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {showJob && <EnqueueJob queueId={queueId} onClose={() => setShowJob(false)} onError={setError} />}
    </div>
  );
}

function EnqueueJob({ queueId, onClose, onError }:
  { queueId: string; onClose: () => void; onError: (m: string) => void }) {
  const [type, setType] = useState("immediate");
  const [task, setTask] = useState("echo");
  const [payload, setPayload] = useState('{\n  "hello": "world"\n}');
  const [delay, setDelay] = useState(10);
  const [cron, setCron] = useState("*/5 * * * *");

  async function submit() {
    let parsed: any = {};
    try { parsed = JSON.parse(payload || "{}"); }
    catch { return onError("Payload is not valid JSON"); }
    const body: any = { task_name: task, payload: parsed, job_type: type };
    if (type === "delayed") body.delay_seconds = delay;
    if (type === "scheduled") body.run_at = new Date(Date.now() + delay * 1000).toISOString();
    if (type === "recurring") body.cron_expression = cron;
    try { await api.createJob(queueId, body); onClose(); }
    catch (e: any) { onError(e.message); }
  }

  return (
    <Modal title="Enqueue job" onClose={onClose}>
      <div style={{ display: "grid", gap: 12 }}>
        <div><label className="field-label">Type</label>
          <select className="input" value={type} onChange={(e) => setType(e.target.value)}>
            <option value="immediate">immediate</option><option value="delayed">delayed</option>
            <option value="scheduled">scheduled</option><option value="recurring">recurring (cron)</option>
          </select></div>
        <div><label className="field-label">Task name</label>
          <input className="input mono" value={task} onChange={(e) => setTask(e.target.value)} />
          <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>Demo handlers: echo, add, sleep, flaky, fail, send_email</div></div>
        {(type === "delayed" || type === "scheduled") && (
          <div><label className="field-label">Delay (seconds from now)</label>
            <input className="input mono" type="number" value={delay} onChange={(e) => setDelay(+e.target.value)} /></div>
        )}
        {type === "recurring" && (
          <div><label className="field-label">Cron expression</label>
            <input className="input mono" value={cron} onChange={(e) => setCron(e.target.value)} /></div>
        )}
        <div><label className="field-label">Payload (JSON)</label>
          <textarea className="input mono" rows={5} value={payload} onChange={(e) => setPayload(e.target.value)} /></div>
        <button className="btn btn-primary" onClick={submit}>Enqueue</button>
      </div>
    </Modal>
  );
}
