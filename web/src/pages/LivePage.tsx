// Live view of a capture while it runs: the collector streams frame times and
// sensor readings, and this page polls them about once a second.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, type LiveView } from "../api";
import { ErrorNotice, Loading } from "../components/Bits";
import { SENSOR_CHARTS, TimeChart } from "../components/Charts";
import { formatNumber } from "../format";

function ago(seconds: number | null): string {
  if (seconds === null) return "nothing yet";
  const gone = Math.max(0, Math.round(Date.now() / 1000 - seconds));
  return gone < 2 ? "just now" : `${gone} s ago`;
}

export function LiveListPage() {
  const client = useQueryClient();
  const sessions = useQuery({ queryKey: ["live"], queryFn: api.liveSessions, refetchInterval: 5000 });
  const [label, setLabel] = useState("");
  const open = useMutation({
    mutationFn: () => api.openLive(label),
    onSuccess: () => client.invalidateQueries({ queryKey: ["live"] }),
  });
  // On the master itself the page is "localhost", which the PC being tested
  // cannot reach: use this computer's network address instead (as the QR code does).
  const info = useQuery({ queryKey: ["collector"], queryFn: api.collector });
  const local = ["localhost", "127.0.0.1"].includes(window.location.hostname);
  const lan = info.data?.lan_addresses[0];
  const port = window.location.port ? `:${window.location.port}` : "";
  const base = local && lan ? `${window.location.protocol}//${lan}${port}` : window.location.origin;
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Live</h1>
          <p className="sub">
          Watch frame times and temperatures while a capture runs. The finished run is still uploaded as
          usual; nothing here is kept.
          </p>
        </div>
      </div>
      <form
        className="card stack"
        onSubmit={(event) => {
          event.preventDefault();
          open.mutate();
        }}
      >
        <h2>Start a live session</h2>
        <label className="field">
          Label (optional)
          <input maxLength={200} value={label} placeholder="bench 2, GPU swap" onChange={(e) => setLabel(e.target.value)} />
        </label>
        <ErrorNotice error={open.error} />
        <button className="btn primary" disabled={open.isPending}>
          Start
        </button>
        {open.data && (
          <div className="notice" style={{ flexDirection: "column" }}>
            <p>
              On the PC being tested, run the capture collector with this address. It is shown only once,
              and it can only add samples to this session:
            </p>
            <pre className="entry-text" style={{ wordBreak: "break-all" }}>
              pcdoctor-capture --process Game.exe --live-url {base + open.data.samples_path}
            </pre>
            <p className="small muted">
              Use HTTPS when the PC is not on your own network. The session ends after 6 hours.{" "}
              <Link to={`/live/${open.data.id}`}>Watch it</Link>
            </p>
          </div>
        )}
      </form>
      <div className="card">
        <h2>Sessions</h2>
        {sessions.isLoading && <Loading />}
        <ErrorNotice error={sessions.error} />
        {sessions.data?.length === 0 && <p className="muted">None open.</p>}
        <ul className="stack" style={{ listStyle: "none", padding: 0, gap: 6 }}>
          {sessions.data?.map((session) => (
            <li key={session.id}>
              <Link to={`/live/${session.id}`}>{session.label || "Untitled session"}</Link>{" "}
              <span className="muted small">
                {session.frames_total} frames · last sample {ago(session.last_sample_at)}
                {session.ended ? " · ended" : ""}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function Figure({ label, value, unit }: { label: string; value?: number; unit: string }) {
  return (
    <div className="tile">
      <div className="label">{label}</div>
      <div className="value">
        {value === undefined ? "–" : formatNumber(value)} <small>{unit}</small>
      </div>
    </div>
  );
}

function LiveCharts({ view }: { view: LiveView }) {
  // Times from the collector count from the start of its capture. The charts
  // show what is in the buffer, starting at its oldest sample.
  const start = Math.min(view.frames[0]?.t ?? Infinity, view.sensors[0]?.t ?? Infinity);
  const zero = Number.isFinite(start) ? start : 0;
  const frameRows = view.frames.map((frame) => ({ t: frame.t - zero, ms: frame.ms }));
  const sensorRows = view.sensors.map((row) => ({ t: row.t - zero, ...row.values }));
  const present = new Set(view.sensors.flatMap((row) => Object.keys(row.values)));
  return (
    <>
      {frameRows.length > 0 && (
        <TimeChart
          title="Frame time"
          unit="ms"
          zeroBased
          rows={frameRows}
          series={[{ key: "ms", label: "Frame time", color: "var(--series-1)" }]}
          note="The newest frames in the buffer. Lower and flatter is better; tall peaks are stutters."
        />
      )}
      {SENSOR_CHARTS.map((chart) => {
        const series = chart.series.filter((spec) => present.has(spec.key));
        if (series.length === 0) return null;
        return (
          <TimeChart
            key={chart.title}
            title={chart.title}
            unit={chart.unit}
            zeroBased={chart.zeroBased}
            rows={sensorRows}
            series={series}
          />
        );
      })}
    </>
  );
}

export function LivePage() {
  const { id = "" } = useParams();
  const client = useQueryClient();
  const live = useQuery({
    queryKey: ["live", id],
    queryFn: () => api.live(id),
    refetchInterval: (query) => (query.state.data?.ended || query.state.error ? false : 1000),
  });
  const close = useMutation({
    mutationFn: () => api.closeLive(id),
    onSuccess: () => client.invalidateQueries({ queryKey: ["live"] }),
  });
  if (live.isLoading) return <Loading />;
  if (live.error || !live.data) return <ErrorNotice error={live.error} />;
  const view = live.data;
  return (
    <div className="stack">
      <div>
        <p className="small">
          <Link to="/live">Live sessions</Link>
        </p>
        <h1>{view.label || "Live session"}</h1>
        <p className="muted">
          {view.frames_total} frames and {view.sensor_rows_total} sensor readings received · last sample{" "}
          {ago(view.last_sample_at)}
          {view.ended ? " · the collector has finished" : ""}
        </p>
      </div>
      <div className="tiles" aria-label="The last 10 seconds">
        <Figure label="Average FPS, last 10 s" value={view.stats.avg_fps_last_10_s} unit="fps" />
        <Figure label="1% low, last 10 s" value={view.stats.one_pct_low_fps_last_10_s} unit="fps" />
        <Figure label="Worst frame, last 10 s" value={view.stats.worst_frame_ms_last_10_s} unit="ms" />
      </div>
      {view.frames_total === 0 && view.sensor_rows_total === 0 ? (
        <div className="card empty">
          <h2>Waiting for the collector</h2>
          <p>Nothing has arrived yet. Start the capture with the address you were given.</p>
        </div>
      ) : (
        <LiveCharts view={view} />
      )}
      <div>
        <button className="btn" onClick={() => close.mutate()} disabled={close.isPending || close.isSuccess}>
          {close.isSuccess ? "Closed" : "Close this session"}
        </button>
        <ErrorNotice error={close.error} />
      </div>
    </div>
  );
}
