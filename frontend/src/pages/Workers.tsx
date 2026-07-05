import { api } from "../api";
import { ErrorBanner, timeAgo, usePolling } from "../components";

const STALE_MS = 30_000;

export default function Workers() {
  const { data: workers, error } = usePolling(() => api.workers(), 2500);

  return (
    <div>
      <h1 className="page-title">Workers</h1>
      <div className="page-sub">Live worker fleet. A worker is considered offline after 30s without a heartbeat.</div>
      <ErrorBanner message={error} />

      <div className="card">
        <table>
          <thead>
            <tr><th>Worker</th><th>Host</th><th>Status</th><th>Active</th><th>Processed</th><th>Failed</th><th>Last heartbeat</th></tr>
          </thead>
          <tbody>
            {(workers ?? []).map((w) => {
              const stale = Date.now() - new Date(w.last_heartbeat_at + "Z").getTime() > STALE_MS;
              const online = !stale && w.status !== "dead";
              return (
                <tr key={w.id}>
                  <td className="mono">{w.id.slice(0, 8)}</td>
                  <td className="mono">{w.hostname}</td>
                  <td>
                    <span className="row" style={{ gap: 6 }}>
                      <span className="health-dot" style={{ background: online ? "#2fbf88" : "#e5484d" }} />
                      {online ? "online" : "offline"}
                    </span>
                  </td>
                  <td className="mono">{w.active_jobs}/{w.concurrency}</td>
                  <td className="mono">{w.total_processed}</td>
                  <td className="mono" style={{ color: w.total_failed ? "#ff8b8f" : undefined }}>{w.total_failed}</td>
                  <td className="muted">{timeAgo(w.last_heartbeat_at)}</td>
                </tr>
              );
            })}
            {workers && workers.length === 0 && (
              <tr><td colSpan={7} className="muted" style={{ textAlign: "center", padding: 26 }}>
                No workers registered. Start one with the worker process.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
