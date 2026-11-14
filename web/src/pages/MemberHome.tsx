// What a member sees: their own runs, and nothing of anyone else's.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { api } from "../api";
import { ErrorNotice, Loading, SeverityBadge } from "../components/Bits";
import { UploadZone } from "../components/UploadZone";
import { formatDateTime } from "../format";

export function MemberHome() {
  const client = useQueryClient();
  const runs = useQuery({ queryKey: ["my-runs"], queryFn: api.myRuns });
  const remove = useMutation({
    mutationFn: (id: string) => api.deleteMyRun(id),
    onSuccess: () => client.invalidateQueries({ queryKey: ["my-runs"] }),
  });
  const items = runs.data?.items ?? [];
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>My runs</h1>
          <p className="sub">The PCs you have checked. Only you and the technician can see them.</p>
        </div>
      </div>
      <UploadZone />
      <ErrorNotice error={runs.error ?? remove.error} />
      {runs.isLoading && <Loading what="Loading your runs" />}
      {runs.isSuccess && items.length === 0 && (
        <div className="card empty">
          <h2>No runs yet</h2>
          <p>
            <a href="/api/collector.zip" download>
              Download the collector
            </a>
            , run it on the PC, and drop the <code>.zip</code> it makes above.
          </p>
        </div>
      )}
      {items.length > 0 && (
        <div className="card table-wrap" style={{ padding: 0 }}>
          <table>
            <thead>
              <tr>
                <th>Result</th>
                <th>Diagnosis</th>
                <th>PC</th>
                <th>Uploaded</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {items.map((run) => (
                <tr key={run.id}>
                  <td>
                    <SeverityBadge level={run.verdict} />
                  </td>
                  <td>
                    <Link className="row-title" to={`/runs/${run.id}`}>
                      {run.headline}
                    </Link>
                    {run.label && <div className="muted small">{run.label}</div>}
                  </td>
                  <td className="small">{[run.cpu, run.gpu].filter(Boolean).join(" · ") || "Unknown"}</td>
                  <td className="small muted">{formatDateTime(run.created_at)}</td>
                  <td>
                    <button
                      className="btn quiet"
                      disabled={remove.isPending}
                      onClick={() => {
                        if (window.confirm("Delete this run? This cannot be undone.")) remove.mutate(run.id);
                      }}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
