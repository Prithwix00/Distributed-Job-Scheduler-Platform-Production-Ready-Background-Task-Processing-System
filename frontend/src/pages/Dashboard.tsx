import { api } from "../api";
import { ErrorBanner, Stat, usePolling } from "../components";
import {
  Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

export default function Dashboard() {
  const { data: ov, error } = usePolling(() => api.overview(), 3000);
  const { data: tp } = usePolling(() => api.throughput(60, 60), 5000);

  const buckets = (tp?.buckets ?? []).map((b) => ({
    time: new Date(b.t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    succeeded: b.succeeded,
    failed: b.failed,
  }));

  const j = ov?.jobs ?? {};
  const healthy = (ov?.workers.alive ?? 0) > 0;

  return (
    <div>
      <h1 className="page-title">Overview</h1>
      <div className="page-sub">Live system health, updated every few seconds.</div>
      <ErrorBanner message={error} />

      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", marginBottom: 16 }}>
        <Stat label="Running" value={j.running ?? 0} color="#f0a63a" />
        <Stat label="Queued" value={j.queued ?? 0} color="#5b8def" />
        <Stat label="Scheduled" value={j.scheduled ?? 0} color="#a06bff" />
        <Stat label="Completed" value={j.completed ?? 0} color="#2fbf88" />
        <Stat label="Dead letter" value={ov?.dead_letter_total ?? 0} color="#e5484d" />
      </div>

      <div className="grid" style={{ gridTemplateColumns: "2fr 1fr", alignItems: "stretch" }}>
        <div className="card" style={{ padding: 18 }}>
          <div className="between" style={{ marginBottom: 10 }}>
            <div style={{ fontWeight: 600, fontSize: 14 }}>Throughput (last hour)</div>
            <div className="muted" style={{ fontSize: 12 }}>succeeded vs failed / min</div>
          </div>
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={buckets} margin={{ top: 4, right: 8, left: -18, bottom: 0 }}>
              <defs>
                <linearGradient id="g1" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#2fbf88" stopOpacity={0.5} />
                  <stop offset="100%" stopColor="#2fbf88" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="g2" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#e5484d" stopOpacity={0.5} />
                  <stop offset="100%" stopColor="#e5484d" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="#1a212b" vertical={false} />
              <XAxis dataKey="time" tick={{ fill: "#6b7688", fontSize: 11 }} stroke="#1e2630" minTickGap={30} />
              <YAxis tick={{ fill: "#6b7688", fontSize: 11 }} stroke="#1e2630" allowDecimals={false} />
              <Tooltip contentStyle={{ background: "#11161d", border: "1px solid #1e2630", borderRadius: 8, fontSize: 12 }} />
              <Area type="monotone" dataKey="succeeded" stroke="#2fbf88" fill="url(#g1)" strokeWidth={2} />
              <Area type="monotone" dataKey="failed" stroke="#e5484d" fill="url(#g2)" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        <div className="card" style={{ padding: 18 }}>
          <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 14 }}>System health</div>
          <div className="row" style={{ marginBottom: 14 }}>
            <span className="health-dot" style={{ background: healthy ? "#2fbf88" : "#e5484d" }} />
            <span style={{ fontWeight: 500 }}>{healthy ? "Healthy" : "No live workers"}</span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div className="between"><span className="muted">Workers online</span>
              <span className="mono">{ov?.workers.alive ?? 0} / {ov?.workers.total ?? 0}</span></div>
            <div className="between"><span className="muted">Success rate</span>
              <span className="mono">{((ov?.success_rate ?? 1) * 100).toFixed(1)}%</span></div>
            <div className="between"><span className="muted">Total jobs</span>
              <span className="mono">{j.total ?? 0}</span></div>
          </div>
        </div>
      </div>
    </div>
  );
}
