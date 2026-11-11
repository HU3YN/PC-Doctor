import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";

import { api } from "../api";
import { ErrorNotice, Loading, SeverityBadge } from "../components/Bits";
import { UploadZone } from "../components/UploadZone";
import { formatDateTime, formatNumber } from "../format";

function GettingStarted() {
  const client = useQueryClient();
  const demo = useMutation({ mutationFn: api.loadDemo, onSuccess: () => client.invalidateQueries() });
  return (
    <div className="card empty">
      <h2>No runs yet</h2>
      <p>A run is a snapshot of one PC, made by the collector.</p>
      <ol className="steps">
        <li>
          Copy the <code>collector</code> folder to the PC you want to check (a USB stick works).
        </li>
        <li>
          Double-click <code>PCDoctor.cmd</code> and pick a quick health check or a 5-minute capture.
        </li>
        <li>
          Drop the <code>.zip</code> it makes onto this page.
        </li>
      </ol>
      <p style={{ marginTop: 16 }}>
        <button className="btn" onClick={() => demo.mutate()} disabled={demo.isPending}>
          {demo.isPending ? "Loading ..." : "Load demo data to look around"}
        </button>
      </p>
      <p className="muted small" style={{ marginTop: 6 }}>
        Demo data is made up, clearly marked, and removed with one click.
      </p>
      <ErrorNotice error={demo.error} />
    </div>
  );
}

export function RunsPage() {
  const navigate = useNavigate();
  const runs = useQuery({ queryKey: ["runs"], queryFn: api.runs });
  const items = runs.data?.items ?? [];

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Runs</h1>
          <p className="sub">Upload a run to find out what is wrong with a PC, in plain English.</p>
        </div>
      </div>
      <UploadZone />
      <ErrorNotice error={runs.error} />
      {runs.isLoading && <Loading what="Loading runs" />}
      {runs.isSuccess && items.length === 0 && <GettingStarted />}
      {items.length > 0 && (
        <div className="card table-wrap" style={{ padding: 0 }}>
          <table>
            <thead>
              <tr>
                <th>Result</th>
                <th>Diagnosis</th>
                <th>PC</th>
                <th className="num">Avg FPS</th>
                <th className="num">1% low</th>
                <th>Uploaded</th>
              </tr>
            </thead>
            <tbody>
              {items.map((run) => (
                <tr key={run.id} className="clickable" onClick={() => navigate(`/runs/${run.id}`)}>
                  <td>
                    <SeverityBadge level={run.verdict} />
                  </td>
                  <td>
                    <Link
                      className="row-title"
                      to={`/runs/${run.id}`}
                      onClick={(event) => event.stopPropagation()}
                    >
                      {run.headline}
                    </Link>
                    <div className="muted small">
                      {[run.label, run.mode === "capture" ? "Capture" : run.mode === "quick" ? "Quick check" : "", run.is_demo ? "Demo" : ""]
                        .filter(Boolean)
                        .join(" · ")}
                    </div>
                  </td>
                  <td className="small">
                    {run.cpu ?? <span className="muted">Unknown CPU</span>}
                    <div className="muted">{[run.gpu, run.ram_gb ? `${run.ram_gb} GB` : null].filter(Boolean).join(" · ")}</div>
                  </td>
                  <td className="num">{formatNumber(run.avg_fps)}</td>
                  <td className="num">{formatNumber(run.fps_1pct_low)}</td>
                  <td className="small muted">{formatDateTime(run.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
