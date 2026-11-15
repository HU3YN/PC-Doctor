// The master's photo inbox: show a QR code, and photos arrive here read and
// matched to earlier jobs.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import QRCode from "qrcode";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, type InboxPhoto } from "../api";
import { Chips, ErrorNotice, Loading, SimilarCases } from "../components/Bits";
import { formatDateTime } from "../format";

function QrPanel() {
  const info = useQuery({ queryKey: ["collector"], queryFn: api.collector });
  const [label, setLabel] = useState("");
  const [image, setImage] = useState("");
  const [address, setAddress] = useState("");
  const client = useQueryClient();
  const create = useMutation({
    mutationFn: () => api.createPhotoLink(label),
    onSuccess: () => client.invalidateQueries({ queryKey: ["photo-links"] }),
  });
  const local = ["localhost", "127.0.0.1"].includes(window.location.hostname);
  // On the master itself the page is "localhost", which a phone cannot open:
  // use the computer's network address in the code instead.
  const lan = info.data?.lan_addresses[0];
  const port = window.location.port ? `:${window.location.port}` : "";
  const base = local && lan ? `${window.location.protocol}//${lan}${port}` : window.location.origin;
  const path = create.data?.path;

  useEffect(() => {
    if (!path) return;
    const url = base + path;
    setAddress(url);
    void QRCode.toDataURL(url, { width: 416, margin: 0 }).then(setImage);
  }, [path, base]);

  return (
    <div className="card stack" style={{ gap: 10 }}>
      <h2>Get photos from a phone</h2>
      <p>
        Show a QR code, scan it with the phone&apos;s camera, and take the photo. It lands here, already
        read. No app and no sign-in on the phone.
      </p>
      <form
        className="row"
        onSubmit={(event) => {
          event.preventDefault();
          create.mutate();
        }}
      >
        <input
          value={label}
          maxLength={200}
          onChange={(event) => setLabel(event.target.value)}
          placeholder="What is it for? e.g. bench 2, no POST (optional)"
          aria-label="Label for these photos"
          style={{ maxWidth: 380 }}
        />
        <button className="btn primary" disabled={create.isPending}>
          {image ? "New QR code" : "Show QR code"}
        </button>
      </form>
      <ErrorNotice error={create.error} />
      {image && path && (
        <div className="row" style={{ alignItems: "flex-start", gap: 18 }}>
          <img className="qr" src={image} alt="QR code for sending photos" />
          <div className="stack grow" style={{ gap: 6 }}>
            <p>
              Scan with the phone&apos;s camera. Works for 12 hours, for as many photos as you like.
            </p>
            <p className="small muted" style={{ overflowWrap: "anywhere" }}>{address}</p>
            {local && (
              <div className="notice warn small">
                <span>
                  {lan
                    ? "The phone must be on the same network as this computer, and PC Doctor must have been started with -Lan."
                    : "This page is open as localhost, which a phone cannot reach. Start PC Doctor with -Lan (or host it) and open it by its network address."}
                </span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/** The phone links that still work, each with a way to revoke it early. */
function OpenLinks() {
  const client = useQueryClient();
  const links = useQuery({ queryKey: ["photo-links"], queryFn: api.photoLinks });
  const revoke = useMutation({
    mutationFn: (id: number) => api.revokePhotoLink(id),
    onSuccess: () => client.invalidateQueries({ queryKey: ["photo-links"] }),
  });
  if (links.error) return <ErrorNotice error={links.error} />;
  const items = links.data ?? [];
  if (items.length === 0) return null;
  return (
    <div className="card stack" style={{ gap: 10 }}>
      <h2>Open phone links</h2>
      <p className="muted small">
        Each QR code works until it expires. Revoke one early if it was shared by mistake; photos already sent
        stay in the inbox.
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Label</th>
              <th>Made</th>
              <th>Expires</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((link) => (
              <tr key={link.id}>
                <td>{link.label || <span className="muted">no label</span>}</td>
                <td>{formatDateTime(link.created_at)}</td>
                <td>{formatDateTime(link.expires_at)}</td>
                <td className="num">
                  <button
                    className="btn danger small"
                    disabled={revoke.isPending}
                    onClick={() => {
                      if (window.confirm("Revoke this link? The phone will no longer be able to send photos with it."))
                        revoke.mutate(link.id);
                    }}
                  >
                    Revoke
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ErrorNotice error={revoke.error} />
    </div>
  );
}

function PhotoCard({ photo, aiAvailable }: { photo: InboxPhoto; aiAvailable: boolean }) {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: ["inbox"] });
  const describe = useMutation({ mutationFn: () => api.describePhoto(photo.id), onSuccess: refresh });
  const remove = useMutation({ mutationFn: () => api.deletePhoto(photo.id), onSuccess: refresh });
  const codes = [...photo.stop_codes.map((code) => code.hex), ...photo.unknown_codes, ...(photo.ai?.error_codes ?? [])];
  const unique = [...new Set(codes)];
  const top = photo.stop_codes[0];
  const title = top ? `Blue screen: ${top.name}` : (photo.ai?.summary.slice(0, 90) ?? photo.label);
  const category = top && top.category !== "other" ? top.category : photo.ai?.category || "other";
  const logParams = new URLSearchParams({ photo: photo.id, title, codes: unique.join(", "), category });

  return (
    <div className="card photo-card">
      <a href={`/api/inbox/${photo.id}/image`} target="_blank" rel="noreferrer">
        <img src={`/api/inbox/${photo.id}/image`} alt="Photo sent from a phone" loading="lazy" />
      </a>
      <div className="stack" style={{ gap: 8 }}>
        <div className="row">
          <span className="muted small grow">
            {formatDateTime(photo.created_at)}
            {photo.label ? ` · ${photo.label}` : ""}
          </span>
          {photo.work_log_id ? (
            <Link className="btn" to={`/worklog/${photo.work_log_id}`}>
              Logged - open entry
            </Link>
          ) : (
            <Link className="btn primary" to={`/worklog/new?${logParams.toString()}`}>
              Log this job
            </Link>
          )}
          <button
            className="btn danger"
            disabled={remove.isPending}
            onClick={() => {
              if (window.confirm("Delete this photo?")) remove.mutate();
            }}
          >
            Delete
          </button>
        </div>
        {photo.stop_codes.map((code) => (
          <div key={code.code}>
            <b>
              {code.hex} {code.name}
            </b>
            {code.meaning && <span> - {code.meaning}</span>}
            {code.checks.length > 0 && <div className="small muted">First check: {code.checks[0]}</div>}
          </div>
        ))}
        {photo.stop_codes.length === 0 && !photo.ai && (
          <p className="muted small">
            No stop code could be read automatically.
            {photo.text ? "" : " No text was found in the photo."}
          </p>
        )}
        <Chips items={[...photo.unknown_codes, ...photo.drivers]} code />
        {photo.ai && (
          <div className="notice" style={{ display: "block" }}>
            <b className="small">AI description - check it against the photo</b>
            <p>{photo.ai.summary}</p>
            {photo.ai.observations.length > 0 && (
              <ul style={{ margin: "4px 0 0", paddingLeft: 20 }}>
                {photo.ai.observations.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            )}
            {photo.ai.next_checks.length > 0 && (
              <p className="small" style={{ marginTop: 4 }}>
                <b>Try:</b> {photo.ai.next_checks.join(" · ")}
              </p>
            )}
            {photo.ai.uncertain.length > 0 && (
              <p className="small muted">Could not make out: {photo.ai.uncertain.join("; ")}</p>
            )}
          </div>
        )}
        {aiAvailable && !photo.ai && (
          <div>
            <button className="btn" disabled={describe.isPending} onClick={() => describe.mutate()}>
              {describe.isPending ? "Looking ..." : "Describe with AI"}
            </button>
            <span className="muted small"> Sends this photo to the AI provider.</span>
          </div>
        )}
        <ErrorNotice error={describe.error ?? remove.error} />
        {photo.cases.length > 0 && (
          <>
            <b className="small">You have seen this before</b>
            <SimilarCases cases={photo.cases} />
          </>
        )}
      </div>
    </div>
  );
}

export function InboxPage() {
  // New photos show up by themselves while the page is open.
  const inbox = useQuery({ queryKey: ["inbox"], queryFn: api.inbox, refetchInterval: 4000 });
  const assist = useQuery({ queryKey: ["assist"], queryFn: api.assist, staleTime: Infinity });
  const items = inbox.data?.items ?? [];
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Photo inbox</h1>
          <p className="sub">
            For PCs that will not start: photos of the error screen, the motherboard&apos;s LEDs or a
            damaged part, sent straight from a phone.
          </p>
        </div>
        <Link className="btn" to="/wont-start">
          No-boot checklist
        </Link>
      </div>
      <QrPanel />
      <OpenLinks />
      <ErrorNotice error={inbox.error} />
      {inbox.isLoading && <Loading what="Loading photos" />}
      {inbox.isSuccess && items.length === 0 && (
        <div className="card empty">
          <h2>No photos yet</h2>
          <p>Show the QR code above and scan it with a phone. Photos appear here within seconds.</p>
        </div>
      )}
      {items.map((photo) => (
        <PhotoCard key={photo.id} photo={photo} aiAvailable={Boolean(assist.data?.available)} />
      ))}
      {assist.data && !assist.data.available && items.length > 0 && (
        <p className="muted small">
          The AI helper is off (no API key on this server), so photos are read by OCR only: stop codes on
          screens, not LEDs or damage.
        </p>
      )}
    </div>
  );
}
