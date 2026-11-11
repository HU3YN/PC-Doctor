import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../api";
import { Chips, ErrorNotice, Loading, SimilarCases, StatusBadge } from "../components/Bits";
import { formatDate, formatMinutes } from "../format";

function Section({ title, text }: { title: string; text: string }) {
  if (!text) return null;
  return (
    <div className="entry-section">
      <h3>{title}</h3>
      <p className="entry-text">{text}</p>
    </div>
  );
}

export function WorkLogEntryPage() {
  const { id = "" } = useParams();
  const entryId = Number(id);
  const navigate = useNavigate();
  const client = useQueryClient();
  const entry = useQuery({ queryKey: ["entry", entryId], queryFn: () => api.entry(entryId) });
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: Infinity });
  const data = entry.data;
  const similar = useQuery({
    queryKey: ["similar-to", entryId],
    enabled: Boolean(data),
    queryFn: () =>
      api.similar({
        text: `${data!.title} ${data!.symptoms}`,
        codes: data!.error_codes,
        category: data!.category,
        parts: data!.components,
        exclude_id: entryId,
        limit: 4,
      }),
  });
  const remove = useMutation({
    mutationFn: () => api.deleteEntry(entryId),
    onSuccess: () => {
      void client.invalidateQueries();
      navigate("/worklog");
    },
  });

  if (entry.isLoading) return <Loading what="Loading the entry" />;
  if (entry.error || !data) return <ErrorNotice error={entry.error ?? "Entry not found."} />;

  const facts = [
    meta.data?.categories[data.category] ?? data.category,
    meta.data?.device_types[data.device_type] ?? data.device_type,
    data.device,
    formatMinutes(data.minutes_spent),
    data.reference ? `Ref ${data.reference}` : "",
  ].filter(Boolean);

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <Link to="/worklog" className="small">
            &larr; Work log
          </Link>
          <h1 style={{ marginTop: 4 }}>{data.title}</h1>
          <p className="sub small">
            {formatDate(data.occurred_on)} · {facts.join(" · ")}
            {data.is_demo ? " · demo data" : ""}
          </p>
        </div>
        <div className="row">
          <StatusBadge status={data.status} />
          <Link className="btn primary" to={`/worklog/${data.id}/edit`}>
            Edit
          </Link>
          <button
            className="btn danger"
            disabled={remove.isPending}
            onClick={() => {
              if (window.confirm("Delete this work-log entry?")) remove.mutate();
            }}
          >
            Delete
          </button>
        </div>
      </div>

      <ErrorNotice error={remove.error} />
      {data.privacy_warnings.length > 0 && (
        <div className="notice warn">
          <span>
            <b>Check for customer data.</b> {data.privacy_warnings.join(" ")} The work log is for the
            machine and the fix - never who owns it.
          </span>
        </div>
      )}

      <div className="two-col">
        <div className="card stack">
          {(data.error_codes.length > 0 || data.components.length > 0) && (
            <div className="row">
              <Chips items={data.error_codes} code />
              <Chips items={data.components} />
            </div>
          )}
          <Section title="Symptoms" text={data.symptoms} />
          <Section title="What I checked" text={data.steps} />
          <Section title="Root cause" text={data.root_cause} />
          <Section title="Fix" text={data.fix} />
          {!data.symptoms && !data.steps && !data.root_cause && !data.fix && (
            <p className="muted">No details yet. Edit this entry to add what you found.</p>
          )}
          {data.run_id && (
            <p className="small">
              Diagnosed from run: <Link to={`/runs/${data.run_id}`}>{data.run_label || "open run"}</Link>
            </p>
          )}
        </div>
        <div className="stack" style={{ gap: 10 }}>
          <h2>Similar jobs</h2>
          <SimilarCases cases={similar.data ?? []} empty="No similar jobs in the log yet." />
        </div>
      </div>
    </div>
  );
}
