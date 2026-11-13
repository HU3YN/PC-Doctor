import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, NavLink, Route, Routes } from "react-router-dom";

import { api } from "./api";
import { DeadPcPage } from "./pages/DeadPcPage";
import { GetCollectorPage } from "./pages/GetCollectorPage";
import { LookupPage } from "./pages/LookupPage";
import { RunPage } from "./pages/RunPage";
import { RunsPage } from "./pages/RunsPage";
import { WorkLogEntryPage } from "./pages/WorkLogEntryPage";
import { WorkLogFormPage } from "./pages/WorkLogFormPage";
import { WorkLogPage } from "./pages/WorkLogPage";

function Footer() {
  const client = useQueryClient();
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: Infinity });
  const stats = useQuery({ queryKey: ["stats"], queryFn: api.stats });
  const clear = useMutation({
    mutationFn: api.clearDemo,
    onSuccess: () => client.invalidateQueries(),
  });
  const demo = (stats.data?.demo_runs ?? 0) + (stats.data?.demo_work_log ?? 0);
  return (
    <footer className="footer">
      <span>
        PC Doctor {meta.data?.version} · rules {meta.data?.rules_version} ·{" "}
        {meta.data?.rules.length ?? "-"} fault types
      </span>
      {demo > 0 && (
        <span className="row" style={{ gap: 6 }}>
          Demo data is loaded (made-up runs and notes).
          <button className="btn quiet" onClick={() => clear.mutate()} disabled={clear.isPending}>
            Remove demo data
          </button>
        </span>
      )}
      <a href="/api/docs">API docs</a>
    </footer>
  );
}

function NotFound() {
  return (
    <div className="card empty">
      <h2>Page not found</h2>
      <p>
        <Link to="/">Back to runs</Link>
      </p>
    </div>
  );
}

export function App() {
  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <Link to="/" className="brand">
            <img src="/favicon.svg" alt="" />
            PC Doctor
          </Link>
          <nav className="nav" aria-label="Main">
            <NavLink to="/" end>
              Runs
            </NavLink>
            <NavLink to="/worklog">Work log</NavLink>
            <NavLink to="/lookup">Look up</NavLink>
            <NavLink to="/wont-start">Won't start</NavLink>
            <NavLink to="/get">Get collector</NavLink>
          </nav>
          <Link to="/worklog/new" className="btn primary">
            + Log a job
          </Link>
        </div>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<RunsPage />} />
          <Route path="/runs/:id" element={<RunPage />} />
          <Route path="/worklog" element={<WorkLogPage />} />
          <Route path="/worklog/new" element={<WorkLogFormPage />} />
          <Route path="/worklog/:id" element={<WorkLogEntryPage />} />
          <Route path="/worklog/:id/edit" element={<WorkLogFormPage />} />
          <Route path="/lookup" element={<LookupPage />} />
          <Route path="/wont-start" element={<DeadPcPage />} />
          <Route path="/get" element={<GetCollectorPage />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
      <Footer />
    </>
  );
}
