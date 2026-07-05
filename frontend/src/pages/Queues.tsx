import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, Project, Queue } from "../api";
import { ErrorBanner, Modal, usePolling } from "../components";

export default function Queues() {
  const [projectId, setProjectId] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [showProject, setShowProject] = useState(false);
  const [showQueue, setShowQueue] = useState(false);

  const { data: projects } = usePolling(() => api.projects(), 8000);

  useEffect(() => {
    if (!projectId && projects && projects.length) setProjectId(projects[0].id);
  }, [projects, projectId]);

  const { data: queues, error: qErr } = usePolling(
    () => (projectId ? api.queues(projectId) : Promise.resolve([] as Queue[])),
    4000, [projectId]
  );

  return (
    <div>
      <div className="between">
        <div>
          <h1 className="page-title">Queues</h1>
          <div className="page-sub">Configure priority, concurrency and retry behaviour per queue.</div>
        </div>
        <div className="row">
          <button className="btn" onClick={() => setShowProject(true)}>New project</button>
          <button className="btn btn-primary" onClick={() => setShowQueue(true)} disabled={!projectId}>New queue</button>
        </div>
      </div>
      <ErrorBanner message={error || qErr} />

      {projects && projects.length > 0 && (
        <div className="row" style={{ marginBottom: 16 }}>
          <label className="field-label" style={{ margin: 0 }}>Project</label>
          <select className="input" style={{ width: 260 }} value={projectId}
            onChange={(e) => setProjectId(e.target.value)}>
            {projects.map((p: Project) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </div>
      )}

      <div className="card">
        <table>
          <thead>
            <tr><th>Queue</th><th>Priority</th><th>Concurrency</th><th>Retry</th><th>State</th><th></th></tr>
          </thead>
          <tbody>
            {(queues ?? []).map((q) => (
              <tr key={q.id}>
                <td><Link className="link" to={`/queues/${q.id}`}>{q.name}</Link></td>
                <td className="mono">{q.priority}</td>
                <td className="mono">{q.concurrency_limit}</td>
                <td className="mono">{q.retry_policy ? `${q.retry_policy.strategy} ×${q.retry_policy.max_attempts}` : "default"}</td>
                <td>{q.is_paused
                  ? <span className="tag" style={{ color: "#f0a63a" }}>paused</span>
                  : <span className="tag" style={{ color: "#2fbf88" }}>active</span>}</td>
                <td style={{ textAlign: "right" }}>
                  <button className="btn" onClick={async () => {
                    try { q.is_paused ? await api.resumeQueue(q.id) : await api.pauseQueue(q.id); }
                    catch (e: any) { setError(e.message); }
                  }}>{q.is_paused ? "Resume" : "Pause"}</button>
                </td>
              </tr>
            ))}
            {queues && queues.length === 0 && (
              <tr><td colSpan={6} className="muted" style={{ textAlign: "center", padding: 26 }}>
                No queues yet. Create one to start scheduling jobs.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {showProject && (
        <NewProject onClose={() => setShowProject(false)} onError={setError}
          onDone={(p) => { setProjectId(p.id); setShowProject(false); }} />
      )}
      {showQueue && projectId && (
        <NewQueue projectId={projectId} onClose={() => setShowQueue(false)} onError={setError} />
      )}
    </div>
  );
}

function NewProject({ onClose, onDone, onError }:
  { onClose: () => void; onDone: (p: Project) => void; onError: (m: string) => void }) {
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  return (
    <Modal title="New project" onClose={onClose}>
      <div style={{ display: "grid", gap: 12 }}>
        <div><label className="field-label">Name</label>
          <input className="input" value={name}
            onChange={(e) => { setName(e.target.value); setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")); }} /></div>
        <div><label className="field-label">Slug</label>
          <input className="input mono" value={slug} onChange={(e) => setSlug(e.target.value)} /></div>
        <button className="btn btn-primary" onClick={async () => {
          try { onDone(await api.createProject({ name, slug })); } catch (e: any) { onError(e.message); }
        }}>Create project</button>
      </div>
    </Modal>
  );
}

function NewQueue({ projectId, onClose, onError }:
  { projectId: string; onClose: () => void; onError: (m: string) => void }) {
  const [name, setName] = useState("");
  const [priority, setPriority] = useState(0);
  const [concurrency, setConcurrency] = useState(10);
  const [strategy, setStrategy] = useState("exponential");
  const [maxAttempts, setMaxAttempts] = useState(3);
  return (
    <Modal title="New queue" onClose={onClose}>
      <div style={{ display: "grid", gap: 12 }}>
        <div><label className="field-label">Name</label>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="emails" /></div>
        <div className="row">
          <div style={{ flex: 1 }}><label className="field-label">Priority</label>
            <input className="input mono" type="number" value={priority} onChange={(e) => setPriority(+e.target.value)} /></div>
          <div style={{ flex: 1 }}><label className="field-label">Concurrency limit</label>
            <input className="input mono" type="number" value={concurrency} onChange={(e) => setConcurrency(+e.target.value)} /></div>
        </div>
        <div className="row">
          <div style={{ flex: 1 }}><label className="field-label">Retry strategy</label>
            <select className="input" value={strategy} onChange={(e) => setStrategy(e.target.value)}>
              <option value="fixed">fixed</option><option value="linear">linear</option><option value="exponential">exponential</option>
            </select></div>
          <div style={{ flex: 1 }}><label className="field-label">Max attempts</label>
            <input className="input mono" type="number" value={maxAttempts} onChange={(e) => setMaxAttempts(+e.target.value)} /></div>
        </div>
        <button className="btn btn-primary" onClick={async () => {
          try {
            await api.createQueue(projectId, {
              name, priority, concurrency_limit: concurrency,
              retry_policy: { strategy, max_attempts: maxAttempts, base_delay_seconds: 5, backoff_factor: 2, jitter: 0.1 },
            });
            onClose();
          } catch (e: any) { onError(e.message); }
        }}>Create queue</button>
      </div>
    </Modal>
  );
}
