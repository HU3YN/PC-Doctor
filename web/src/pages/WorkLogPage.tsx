import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api } from "../api";
import { Chips, ErrorNotice, Loading, StatusBadge } from "../components/Bits";
import { formatDate, formatMinutes } from "../format";
import { useDebounced } from "../useDebounced";

export function WorkLogPage() {
  const navigate = useNavigate();
  const client = useQueryClient();
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState("");
  const search = useDebounced(q, 250);
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: Infinity });
  const filters = { q: search, category, status };
  const log = useQuery({
    queryKey: ["worklog", filters],
    queryFn: () => api.workLog(filters),
    placeholderData: (previous) => previous,
  });
  const file = useRef<HTMLInputElement>(null);
  const importer = useMutation({
    mutationFn: async (chosen: File) => api.importWorkLog(JSON.parse(await chosen.text())),
    onSuccess: () => client.invalidateQueries(),
  });

  const items = log.data?.items ?? [];
  const filtered = Boolean(search || category || status);
  const minutes = items.reduce((sum, entry) => sum + (entry.minutes_spent ?? 0), 0);

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Work log</h1>
          <p className="sub">
            What was wrong, what you checked, what fixed it - so the next similar job is quicker.
          </p>
        </div>
        <div className="row">
          <a className="btn" href="/api/worklog/export?format=md" download>
            Export notes
          </a>
          <a className="btn" href="/api/worklog/export?format=csv" download>
            CSV
          </a>
          <a className="btn" href="/api/worklog/export?format=json" download="pcdoctor-worklog.json">
            Backup
          </a>
          <button className="btn" onClick={() => file.current?.click()} disabled={importer.isPending}>
            Restore
          </button>
          <input
            ref={file}
            type="file"
            accept=".json"
            hidden
            onChange={(event) => {
              const chosen = event.target.files?.[0];
              if (chosen) importer.mutate(chosen);
              event.target.value = "";
            }}
          />
        </div>
      </div>

      <div className="row">
        <input
          className="search"
          type="search"
          placeholder="Search: symptom, part, stop code, fix ..."
          aria-label="Search the work log"
          value={q}
          onChange={(event) => setQ(event.target.value)}
        />
        <select aria-label="Kind of fault" value={category} onChange={(event) => setCategory(event.target.value)} style={{ width: "auto" }}>
          <option value="">All kinds of fault</option>
          {Object.entries(meta.data?.categories ?? {}).map(([key, name]) => (
            <option key={key} value={key}>
              {name}
            </option>
          ))}
        </select>
        <select aria-label="Status" value={status} onChange={(event) => setStatus(event.target.value)} style={{ width: "auto" }}>
          <option value="">Any status</option>
          <option value="open">Open</option>
          <option value="fixed">Fixed</option>
          <option value="not_fixed">Not fixed</option>
        </select>
        {log.data && (
          <span className="muted small">
            {log.data.total} {log.data.total === 1 ? "entry" : "entries"}
            {minutes > 0 ? ` · ${formatMinutes(minutes)} logged` : ""}
          </span>
        )}
      </div>

      <ErrorNotice error={log.error ?? importer.error} />
      {importer.isSuccess && (
        <div className="notice good">
          Restored {importer.data.imported} entries
          {importer.data.skipped > 0 ? `; ${importer.data.skipped} were already in the log` : ""}.
        </div>
      )}
      {log.isLoading && <Loading what="Loading the work log" />}

      {log.isSuccess && items.length === 0 && (
        <div className="card empty">
          {filtered ? (
            <>
              <h2>Nothing matches</h2>
              <p>Try fewer words, or clear the filters.</p>
            </>
          ) : (
            <>
              <h2>Your work log is empty</h2>
              <p>
                Log a job in under a minute: a title is enough to start, and you can add the cause and
                the fix when you know them.
              </p>
              <p style={{ marginTop: 14 }}>
                <Link className="btn primary" to="/worklog/new">
                  + Log a job
                </Link>
              </p>
            </>
          )}
        </div>
      )}

      {items.length > 0 && (
        <div className="card table-wrap" style={{ padding: 0 }}>
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Job</th>
                <th>Kind</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {items.map((entry) => (
                <tr key={entry.id} className="clickable" onClick={() => navigate(`/worklog/${entry.id}`)}>
                  <td className="small" style={{ whiteSpace: "nowrap" }}>
                    {formatDate(entry.occurred_on)}
                  </td>
                  <td>
                    <Link
                      className="row-title"
                      to={`/worklog/${entry.id}`}
                      onClick={(event) => event.stopPropagation()}
                    >
                      {entry.title}
                    </Link>
                    <div className="muted small">
                      {[entry.device, entry.is_demo ? "Demo" : ""].filter(Boolean).join(" · ")}
                    </div>
                    {(entry.fix || entry.root_cause) && (
                      <div className="small" style={{ marginTop: 3, maxWidth: "70ch" }}>
                        {entry.fix ? `Fix: ${entry.fix}` : `Cause: ${entry.root_cause}`}
                      </div>
                    )}
                    <div style={{ marginTop: 5 }}>
                      <Chips items={entry.error_codes} code />
                    </div>
                  </td>
                  <td className="small">{meta.data?.categories[entry.category] ?? entry.category}</td>
                  <td>
                    <StatusBadge status={entry.status} />
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
