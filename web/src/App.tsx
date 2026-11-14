import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";

import { api } from "./api";
import { ErrorNotice, Loading } from "./components/Bits";
import { AccountPage } from "./pages/AccountPage";
import { LoginPage, SetupPage } from "./pages/AuthPages";
import { DeadPcPage } from "./pages/DeadPcPage";
import { GetCollectorPage } from "./pages/GetCollectorPage";
import { GuestHome } from "./pages/GuestHome";
import { InboxPage } from "./pages/InboxPage";
import { LiveListPage, LivePage } from "./pages/LivePage";
import { LookupPage } from "./pages/LookupPage";
import { MemberHome } from "./pages/MemberHome";
import { RunPage } from "./pages/RunPage";
import { RunsPage } from "./pages/RunsPage";
import { SnapPage } from "./pages/SnapPage";
import { WorkLogEntryPage } from "./pages/WorkLogEntryPage";
import { WorkLogFormPage } from "./pages/WorkLogFormPage";
import { WorkLogPage } from "./pages/WorkLogPage";

function Footer({ master }: { master: boolean }) {
  const client = useQueryClient();
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: Infinity });
  const stats = useQuery({ queryKey: ["stats"], queryFn: api.stats, enabled: master });
  const clear = useMutation({ mutationFn: api.clearDemo, onSuccess: () => client.invalidateQueries() });
  const demo = (stats.data?.demo_runs ?? 0) + (stats.data?.demo_work_log ?? 0);
  return (
    <footer className="footer">
      <span>
        PC Doctor {meta.data?.version} · rules {meta.data?.rules_version} ·{" "}
        {meta.data?.rules.length ?? "-"} fault types
      </span>
      {master && demo > 0 && (
        <span className="row" style={{ gap: 6 }}>
          Demo data is loaded (made-up runs and notes).
          <button className="btn quiet" onClick={() => clear.mutate()} disabled={clear.isPending}>
            Remove demo data
          </button>
        </span>
      )}
    </footer>
  );
}

function NotFound() {
  return (
    <div className="card empty">
      <h2>Page not found</h2>
      <p>
        <Link to="/">Back to the start</Link>
      </p>
    </div>
  );
}

export function App() {
  const client = useQueryClient();
  const location = useLocation();
  const auth = useQuery({ queryKey: ["auth"], queryFn: api.authStatus });
  const inbox = useQuery({
    queryKey: ["inbox"],
    queryFn: api.inbox,
    enabled: auth.data?.role === "master",
    refetchInterval: 15000,
  });
  const navigate = useNavigate();
  const logout = useMutation({
    mutationFn: api.logout,
    onSuccess: async () => {
      client.clear(); // forget everything the master had on screen
      navigate("/");
      await client.invalidateQueries();
    },
  });

  // The phone page stands alone: no menu, nothing to tap by mistake.
  if (location.pathname.startsWith("/snap/")) {
    return (
      <main>
        <Routes>
          <Route path="/snap/:token" element={<SnapPage />} />
        </Routes>
      </main>
    );
  }
  if (auth.isLoading) {
    return (
      <main>
        <Loading />
      </main>
    );
  }
  if (auth.error || !auth.data) {
    return (
      <main>
        <ErrorNotice error={auth.error ?? "Cannot reach the PC Doctor server."} />
      </main>
    );
  }
  // Signed in is not enough: a member sees only their own runs.
  const master = auth.data.role === "master";
  const member = auth.data.signed_in && !master;
  const waiting = inbox.data?.waiting ?? 0;

  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <Link to="/" className="brand">
            <img src="/favicon.svg" alt="" />
            PC Doctor
          </Link>
          {master ? (
            <nav className="nav" aria-label="Main">
              <NavLink to="/" end>
                Runs
              </NavLink>
              <NavLink to="/worklog">Work log</NavLink>
              <NavLink to="/inbox">Photos{waiting > 0 ? ` (${waiting})` : ""}</NavLink>
              <NavLink to="/lookup">Look up</NavLink>
              <NavLink to="/wont-start">Won&apos;t start</NavLink>
              <NavLink to="/live">Live</NavLink>
              <NavLink to="/get">Get collector</NavLink>
              <NavLink to="/account">Account</NavLink>
            </nav>
          ) : (
            <nav className="nav" aria-label="Main">
              <NavLink to="/" end>
                {member ? "My runs" : "Check a PC"}
              </NavLink>
              <NavLink to="/lookup">Look up a stop code</NavLink>
              <NavLink to="/wont-start">Won&apos;t start</NavLink>
            </nav>
          )}
          {master ? (
            <span className="row">
              <Link to="/worklog/new" className="btn primary">
                + Log a job
              </Link>
              <button className="btn quiet" onClick={() => logout.mutate()} title={`Signed in as ${auth.data.username}`}>
                Sign out
              </button>
            </span>
          ) : member ? (
            <button className="btn quiet" onClick={() => logout.mutate()} title={`Signed in as ${auth.data.username}`}>
              Sign out
            </button>
          ) : (
            !auth.data.setup_needed && (
              <Link to="/login" className="btn">
                Sign in
              </Link>
            )
          )}
        </div>
      </header>
      <main>
        {auth.data.setup_needed ? (
          <Routes>
            <Route path="/r/:key" element={<RunPage shared />} />
            <Route path="*" element={<SetupPage />} />
          </Routes>
        ) : master ? (
          <Routes>
            <Route path="/" element={<RunsPage />} />
            <Route path="/runs/:id" element={<RunPage />} />
            <Route path="/r/:key" element={<RunPage shared />} />
            <Route path="/worklog" element={<WorkLogPage />} />
            <Route path="/worklog/new" element={<WorkLogFormPage />} />
            <Route path="/worklog/:id" element={<WorkLogEntryPage />} />
            <Route path="/worklog/:id/edit" element={<WorkLogFormPage />} />
            <Route path="/inbox" element={<InboxPage />} />
            <Route path="/lookup" element={<LookupPage />} />
            <Route path="/wont-start" element={<DeadPcPage />} />
            <Route path="/get" element={<GetCollectorPage />} />
            <Route path="/account" element={<AccountPage />} />
            <Route path="/live" element={<LiveListPage />} />
            <Route path="/live/:id" element={<LivePage />} />
            <Route path="/login" element={<RunsPage />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        ) : member ? (
          <Routes>
            <Route path="/" element={<MemberHome />} />
            <Route path="/runs/:id" element={<RunPage mine />} />
            <Route path="/r/:key" element={<RunPage shared />} />
            <Route path="/lookup" element={<LookupPage />} />
            <Route path="/wont-start" element={<DeadPcPage guest />} />
            <Route path="*" element={<MemberHome />} />
          </Routes>
        ) : (
          <Routes>
            <Route path="/" element={<GuestHome />} />
            <Route path="/r/:key" element={<RunPage shared />} />
            <Route path="/lookup" element={<LookupPage />} />
            <Route path="/wont-start" element={<DeadPcPage guest />} />
            <Route path="/get" element={<GuestHome />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="*" element={<LoginPage />} />
          </Routes>
        )}
      </main>
      <Footer master={master} />
    </>
  );
}
