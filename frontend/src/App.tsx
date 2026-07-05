import { Navigate, NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { token } from "./api";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Queues from "./pages/Queues";
import QueueDetail from "./pages/QueueDetail";
import Workers from "./pages/Workers";
import JobDetail from "./pages/JobDetail";

function Shell({ children }: { children: React.ReactNode }) {
  const nav = useNavigate();
  if (!token.get()) return <Navigate to="/login" replace />;
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">Scheduler Console</div>
        <div className="brand-sub">distributed jobs</div>
        <nav className="nav">
          <NavLink to="/" end>Overview</NavLink>
          <NavLink to="/queues">Queues</NavLink>
          <NavLink to="/workers">Workers</NavLink>
        </nav>
        <div style={{ position: "absolute", bottom: 18, left: 14, right: 14 }}>
          <button className="btn" style={{ width: "100%" }}
            onClick={() => { token.clear(); nav("/login"); }}>Sign out</button>
        </div>
      </aside>
      <main className="content">{children}</main>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/" element={<Shell><Dashboard /></Shell>} />
      <Route path="/queues" element={<Shell><Queues /></Shell>} />
      <Route path="/queues/:queueId" element={<Shell><QueueDetail /></Shell>} />
      <Route path="/workers" element={<Shell><Workers /></Shell>} />
      <Route path="/jobs/:jobId" element={<Shell><JobDetail /></Shell>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
