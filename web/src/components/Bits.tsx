// Small shared pieces: icons, badges, notices.
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import type { SimilarCase, WorkLogBrief } from "../api";
import { formatDate } from "../format";

const PATHS: Record<string, ReactNode> = {
  critical: <path d="M8 1.5 15 14H1L8 1.5Zm0 4.2v4.1m0 1.9v.4" />,
  warning: <path d="M8 1.6a6.4 6.4 0 1 0 0 12.8A6.4 6.4 0 0 0 8 1.6Zm0 3.2v4m0 2v.4" />,
  info: <path d="M8 1.6a6.4 6.4 0 1 0 0 12.8A6.4 6.4 0 0 0 8 1.6Zm0 5.6v4m0-6.4v.4" />,
  ok: <path d="M8 1.6a6.4 6.4 0 1 0 0 12.8A6.4 6.4 0 0 0 8 1.6Zm-3 6.6 2.1 2.1L11 6.4" />,
  open: <path d="M8 1.6a6.4 6.4 0 1 0 0 12.8A6.4 6.4 0 0 0 8 1.6Zm0 3V8l2.4 1.6" />,
  no: <path d="M8 1.6a6.4 6.4 0 1 0 0 12.8A6.4 6.4 0 0 0 8 1.6Zm-2.4 4 4.8 4.8m0-4.8-4.8 4.8" />,
  dash: <path d="M4 8h8" />,
};

export function Icon({ name }: { name: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {PATHS[name] ?? PATHS.info}
    </svg>
  );
}

const SEVERITY_WORD: Record<string, string> = {
  critical: "Critical",
  warning: "Warning",
  info: "Info",
  ok: "No faults",
};

/** A status is always an icon plus a word - never color alone. */
export function SeverityBadge({ level }: { level: string }) {
  return (
    <span className={`badge ${level}`}>
      <Icon name={level} />
      {SEVERITY_WORD[level] ?? level}
    </span>
  );
}

const STATUS: Record<string, { word: string; icon: string; tone: string }> = {
  open: { word: "Open", icon: "open", tone: "warning" },
  fixed: { word: "Fixed", icon: "ok", tone: "fixed" },
  not_fixed: { word: "Not fixed", icon: "no", tone: "critical" },
};

export function StatusBadge({ status }: { status: string }) {
  const item = STATUS[status] ?? { word: status, icon: "info", tone: "info" };
  return (
    <span className={`badge ${item.tone}`}>
      <Icon name={item.icon} />
      {item.word}
    </span>
  );
}

export function ErrorNotice({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div className="notice error" role="alert">
      <span>{message}</span>
    </div>
  );
}

export function Loading({ what = "Loading" }: { what?: string }) {
  return <p className="muted">{what} ...</p>;
}

export function Chips({ items, code = false }: { items: string[]; code?: boolean }) {
  if (items.length === 0) return null;
  return (
    <span className="chips">
      {items.map((item) => (
        <span key={item} className={code ? "chip code" : "chip"}>
          {item}
        </span>
      ))}
    </span>
  );
}

/** One earlier work-log case, with why it matched and what fixed it. */
export function CaseCard({ entry, reasons }: { entry: WorkLogBrief; reasons?: string[] }) {
  return (
    <div className="case">
      <div className="row">
        <Link className="row-title grow" to={`/worklog/${entry.id}`}>
          {entry.title}
        </Link>
        <StatusBadge status={entry.status} />
      </div>
      <div className="muted small">
        {formatDate(entry.occurred_on)}
        {entry.device ? ` · ${entry.device}` : ""}
      </div>
      {reasons && reasons.length > 0 && <div className="why">{reasons.join(" · ")}</div>}
      {entry.root_cause && (
        <p className="fix">
          <b>Cause:</b> {entry.root_cause}
        </p>
      )}
      {entry.fix && (
        <p className="fix">
          <b>Fix:</b> {entry.fix}
        </p>
      )}
    </div>
  );
}

export function SimilarCases({ cases, empty }: { cases: SimilarCase[]; empty?: string }) {
  if (cases.length === 0) return empty ? <p className="muted small">{empty}</p> : null;
  return (
    <div className="stack" style={{ gap: 10 }}>
      {cases.map((item) => (
        <CaseCard key={item.entry.id} entry={item.entry} reasons={item.reasons} />
      ))}
    </div>
  );
}
