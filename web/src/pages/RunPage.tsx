import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, type Check, type Finding, type RunDetail, type Troubleshooting } from "../api";
import { CaseCard, Chips, ErrorNotice, Icon, Loading, SeverityBadge, SimilarCases } from "../components/Bits";
import { RunCharts } from "../components/Charts";
import { formatDateTime, formatDuration, formatEvidence, formatNumber, humanizeKey } from "../format";

function FindingCard({ finding, categories }: { finding: Finding; categories: Record<string, string> }) {
  const evidence = Object.entries(finding.evidence);
  return (
    <article className={`finding ${finding.severity}`}>
      <div className="row">
        <SeverityBadge level={finding.severity} />
        <span className="chip">{categories[finding.category] ?? finding.category}</span>
        <Chips items={finding.error_codes} code />
      </div>
      <h3>{finding.title}</h3>
      <p className="summary">{finding.summary}</p>
      {finding.next_checks.length > 0 && (
        <>
          <div className="next-title">What to check next</div>
          <ol>
            {finding.next_checks.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
        </>
      )}
      {evidence.length > 0 && (
        <details>
          <summary>The numbers behind this</summary>
          <dl className="evidence">
            {evidence.map(([key, value]) => (
              <div key={key} style={{ display: "contents" }}>
                <dt>{humanizeKey(key)}</dt>
                <dd>{formatEvidence(value)}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}
    </article>
  );
}

function Tiles({ run }: { run: RunDetail }) {
  const frames = run.frame_stats;
  const sensors = run.sensor_stats;
  const tiles: { label: string; value: string; unit?: string; note?: string }[] = [];
  if (frames) {
    tiles.push({ label: "Average FPS", value: formatNumber(frames.avg_fps) });
    tiles.push({
      label: "1% low FPS",
      value: formatNumber(frames.fps_1pct_low),
      note: "average of the slowest 1% of frames",
    });
    tiles.push({
      label: "Frame spikes",
      value: formatNumber(frames.spike_count),
      note: `${formatNumber(frames.spikes_per_min)} per minute · ${frames.hitch_count} of 100 ms+`,
    });
  }
  if (sensors.cpu_temp_c) tiles.push({ label: "CPU peak", value: formatNumber(sensors.cpu_temp_c.max), unit: "°C" });
  if (sensors.gpu_temp_c) tiles.push({ label: "GPU peak", value: formatNumber(sensors.gpu_temp_c.max), unit: "°C" });
  if (tiles.length === 0) return null;
  return (
    <div className="tiles">
      {tiles.map((tile) => (
        <div className="tile" key={tile.label}>
          <div className="label">{tile.label}</div>
          <div className="value">
            {tile.value} {tile.unit && <small>{tile.unit}</small>}
          </div>
          {tile.note && <div className="note">{tile.note}</div>}
        </div>
      ))}
    </div>
  );
}

const CHECK_ICON: Record<Check["status"], string> = { passed: "ok", found: "warning", no_data: "dash", error: "no" };

function Checks({ checks }: { checks: Check[] }) {
  const passed = checks.filter((check) => check.status === "passed");
  const skipped = checks.filter((check) => check.status === "no_data" || check.status === "error");
  return (
    <div className="card">
      <h2>What was checked</h2>
      <p className="muted small" style={{ marginBottom: 8 }}>
        {passed.length} checks passed. {skipped.length} could not run because this run does not have the
        data they need{skipped.length > 0 ? " - a capture with PresentMon and LibreHardwareMonitor fills most of them in." : "."}
      </p>
      <div className="checks">
        {[...passed, ...skipped].map((check) => (
          <div key={check.code} className={`check ${check.status}`}>
            <Icon name={CHECK_ICON[check.status]} />
            <span>
              {check.title}
              {check.status === "no_data" && " - not checked"}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function SensorTable({ run }: { run: RunDetail }) {
  const rows = Object.entries(run.sensor_stats);
  if (rows.length === 0) return null;
  return (
    <div className="card table-wrap">
      <h2>Sensor readings</h2>
      <table>
        <thead>
          <tr>
            <th>Reading</th>
            <th className="num">Lowest</th>
            <th className="num">Average</th>
            <th className="num">95% of the time below</th>
            <th className="num">Highest</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([key, stat]) => (
            <tr key={key}>
              <td>{stat.label}</td>
              <td className="num">{formatNumber(stat.min, stat.unit)}</td>
              <td className="num">{formatNumber(stat.avg, stat.unit)}</td>
              <td className="num">{formatNumber(stat.p95, stat.unit)}</td>
              <td className="num">{formatNumber(stat.max, stat.unit)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The diagnosis of one run. With `shared`, it is a guest's private link:
 *  the same diagnosis, without the master's tools or work log. */
function List({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div>
      <strong>{title}</strong>
      <ol style={{ margin: "4px 0 0", paddingLeft: 20 }}>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ol>
    </div>
  );
}

// The AI troubleshooter. Shown to the master only, and only when a key is set.
function Troubleshooter({ runId, categories }: { runId: string; categories: Record<string, string> }) {
  const [question, setQuestion] = useState("");
  const assist = useQuery({ queryKey: ["assist"], queryFn: api.assist, staleTime: Infinity });
  const ask = useMutation<Troubleshooting, Error>({ mutationFn: () => api.troubleshoot(runId, question) });
  if (!assist.data?.available) return null;
  const answer = ask.data;
  return (
    <section className="card stack" style={{ gap: 10 }}>
      <div className="section-title">
        <h2>Ask the troubleshooter</h2>
      </div>
      <p className="muted small">
        Sends this run's findings, and your matching earlier jobs, to the AI provider. It suggests the most likely
        cause and how to confirm it. Treat it as a second opinion to check, not a verdict.
      </p>
      <div className="row" style={{ gap: 8 }}>
        <input
          className="grow"
          value={question}
          maxLength={2000}
          placeholder="Optional: what do you want to know? (e.g. could this be the PSU?)"
          onChange={(event) => setQuestion(event.target.value)}
        />
        <button className="btn" disabled={ask.isPending} onClick={() => ask.mutate()}>
          {ask.isPending ? "Thinking ..." : "Find the likely cause"}
        </button>
      </div>
      <ErrorNotice error={ask.error} />
      {answer && (
        <div className="stack" style={{ gap: 10 }}>
          <div>
            <strong>{answer.likely_cause || "No clear cause."}</strong>
            <div className="muted small">
              {categories[answer.category] ?? answer.category} - confidence: {answer.confidence}
            </div>
          </div>
          {answer.because.length > 0 && (
            <div>
              <strong>Based on</strong>
              <ul style={{ margin: "4px 0 0", paddingLeft: 20 }}>
                {answer.because.map((reason) => (
                  <li key={reason.finding + reason.why}>
                    <code>{reason.finding}</code>: {reason.why}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <List title="Check next, in order" items={answer.steps} />
          <List title="Also rule out" items={answer.rule_out} />
          <List title="Data that would help" items={answer.missing} />
        </div>
      )}
    </section>
  );
}

export function RunPage({ shared = false }: { shared?: boolean }) {
  const { id = "", key = "" } = useParams();
  const navigate = useNavigate();
  const client = useQueryClient();
  const run = useQuery({
    queryKey: shared ? ["shared", key] : ["run", id],
    queryFn: () => (shared ? api.sharedRun(key) : api.run(id)),
  });
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: Infinity });
  const hasCharts = Boolean(run.data?.has_frames || run.data?.has_sensors);
  const series = useQuery({
    queryKey: shared ? ["shared-series", key] : ["series", id],
    queryFn: () => (shared ? api.sharedSeries(key) : api.series(id)),
    enabled: hasCharts,
  });
  const [editing, setEditing] = useState(false);
  const [label, setLabel] = useState("");

  const refresh = (data: RunDetail) => {
    client.setQueryData(["run", id], data);
    void client.invalidateQueries({ queryKey: ["runs"] });
  };
  const rename = useMutation({
    mutationFn: () => api.updateRun(id, { label }),
    onSuccess: (data) => {
      refresh(data);
      setEditing(false);
    },
  });
  const reanalyze = useMutation({
    mutationFn: () => api.reanalyzeRun(id),
    onSuccess: (data) => {
      refresh(data);
      void client.invalidateQueries({ queryKey: ["series", id] });
    },
  });
  const remove = useMutation({
    mutationFn: () => api.deleteRun(id),
    onSuccess: () => {
      void client.invalidateQueries();
      navigate("/");
    },
  });

  if (run.isLoading) return <Loading what="Loading the run" />;
  if (run.error || !run.data) return <ErrorNotice error={run.error ?? "Run not found."} />;
  const data = run.data;
  const categories = meta.data?.categories ?? {};
  const problems = data.findings.filter((finding) => finding.severity !== "info");
  const notes = data.findings.filter((finding) => finding.severity === "info");
  const device = [data.device.cpu, data.device.gpu, data.ram_gb ? `${data.ram_gb} GB RAM` : null, data.device.motherboard, data.device.os]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          {!shared && (
            <Link to="/" className="small">
              &larr; All runs
            </Link>
          )}
          {shared ? (
            <h1>Your PC&apos;s diagnosis</h1>
          ) : editing ? (
            <form
              className="row"
              style={{ marginTop: 6 }}
              onSubmit={(event) => {
                event.preventDefault();
                rename.mutate();
              }}
            >
              <input
                autoFocus
                value={label}
                maxLength={200}
                onChange={(event) => setLabel(event.target.value)}
                placeholder="Label, e.g. bench 3 after repaste"
                aria-label="Run label"
                style={{ width: 320 }}
              />
              <button className="btn primary" disabled={rename.isPending}>
                Save
              </button>
              <button type="button" className="btn" onClick={() => setEditing(false)}>
                Cancel
              </button>
            </form>
          ) : (
            <h1 style={{ marginTop: 4 }}>
              {data.label || "Unlabelled run"}{" "}
              <button
                className="btn quiet small"
                onClick={() => {
                  setLabel(data.label);
                  setEditing(true);
                }}
              >
                Rename
              </button>
            </h1>
          )}
          <p className="sub small">
            {data.captured_at ? `Collected ${formatDateTime(data.captured_at)}` : `Uploaded ${formatDateTime(data.created_at)}`}
            {data.mode === "capture" && data.frame_stats ? ` · ${formatDuration(data.frame_stats.duration_s)} of ${data.frame_stats.application}` : ""}
            {data.mode === "quick" ? " · quick health check" : ""}
            {data.is_demo ? " · demo data" : ""}
          </p>
        </div>
        <div className="row" hidden={shared}>
          <Link className="btn primary" to={`/worklog/new?run=${data.id}`}>
            Log this job
          </Link>
          <a className="btn" href={`/api/runs/${data.id}/download`}>
            Download
          </a>
          <button
            className="btn danger"
            disabled={remove.isPending}
            onClick={() => {
              if (window.confirm("Delete this run? Work-log entries made from it are kept.")) remove.mutate();
            }}
          >
            Delete
          </button>
        </div>
      </div>

      <ErrorNotice error={rename.error ?? reanalyze.error ?? remove.error} />

      <div className={`verdict ${data.verdict}`}>
        <div className="grow">
          <SeverityBadge level={data.verdict} />
          <div className="headline" style={{ marginTop: 6 }}>
            {data.headline}
          </div>
          {device && <div className="muted small" style={{ marginTop: 4 }}>{device}</div>}
        </div>
      </div>

      {shared && (
        <div className="notice">
          <span>
            This page is private to this link - bookmark it or copy the address to come back.
            Nobody else&apos;s results are visible from here.
          </span>
        </div>
      )}

      {data.rules_outdated && !shared && (
        <div className="notice warn">
          <span className="grow">This run was analysed with older rules. Analyse it again to apply the current ones.</span>
          <button className="btn" onClick={() => reanalyze.mutate()} disabled={reanalyze.isPending}>
            {reanalyze.isPending ? "Analysing ..." : "Analyse again"}
          </button>
        </div>
      )}

      <Tiles run={data} />

      {problems.length > 0 && (
        <section className="stack" style={{ gap: 12 }}>
          <div className="section-title">
            <h2>What is wrong</h2>
          </div>
          {problems.map((finding) => (
            <FindingCard key={finding.code + finding.title} finding={finding} categories={categories} />
          ))}
        </section>
      )}

      {!shared && <Troubleshooter runId={data.id} categories={categories} />}

      {(data.similar_cases.length > 0 || data.work_log.length > 0) && (
        <section className="stack" style={{ gap: 12 }}>
          {data.work_log.length > 0 && (
            <>
              <div className="section-title">
                <h2>Logged from this run</h2>
              </div>
              {data.work_log.map((entry) => (
                <CaseCard key={entry.id} entry={entry} />
              ))}
            </>
          )}
          {data.similar_cases.length > 0 && (
            <>
              <div className="section-title">
                <h2>You have seen this before</h2>
                <span className="muted small">from your work log</span>
              </div>
              <SimilarCases cases={data.similar_cases} />
            </>
          )}
        </section>
      )}

      {notes.length > 0 && (
        <section className="stack" style={{ gap: 12 }}>
          <div className="section-title">
            <h2>Worth knowing</h2>
          </div>
          {notes.map((finding) => (
            <FindingCard key={finding.code + finding.title} finding={finding} categories={categories} />
          ))}
        </section>
      )}

      {hasCharts && (
        <section className="stack" style={{ gap: 12 }}>
          <div className="section-title">
            <h2>During the capture</h2>
          </div>
          {series.isLoading && <Loading what="Loading charts" />}
          <ErrorNotice error={series.error} />
          {series.data && <RunCharts series={series.data} />}
          <SensorTable run={data} />
        </section>
      )}

      <Checks checks={data.checks} />

      {data.analysis_notes.length > 0 && (
        <div className="card">
          <h2>Notes about this run</h2>
          <ul style={{ margin: 0, paddingLeft: 20 }}>
            {data.analysis_notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
