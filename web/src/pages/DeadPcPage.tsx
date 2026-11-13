// For a PC the collector cannot run on: read a photo of the error, or pick
// the symptom and get a checklist.
import { useMutation, useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link } from "react-router-dom";

import { api, type NoBootSymptom, type PhotoReading } from "../api";
import { ErrorNotice, Loading, SimilarCases } from "../components/Bits";
import { StopCodeCard } from "./LookupPage";

function logLink(fields: Record<string, string>): string {
  return `/worklog/new?${new URLSearchParams(fields).toString()}`;
}

function PhotoResult({ reading, categories }: { reading: PhotoReading; categories: Record<string, string> }) {
  const codes = [...reading.stop_codes.map((code) => code.hex), ...reading.unknown_codes];
  const top = reading.stop_codes[0];
  const nothing = codes.length === 0 && reading.drivers.length === 0;
  return (
    <div className="stack" style={{ gap: 12 }}>
      {nothing ? (
        <div className="notice warn">
          <span>
            No stop code could be read from this photo. Photos of screens are hard: get closer, hold
            the phone square to the screen, avoid glare, and make sure the code is in focus. You can
            also type the code into <Link to="/lookup">Look up</Link>.
          </span>
        </div>
      ) : (
        <div className="notice good">
          <span className="grow">
            Read from the photo: <b>{codes.join(", ") || "no stop code"}</b>
            {reading.drivers.length > 0 && <> · blamed driver: <b>{reading.drivers.join(", ")}</b></>}
            . Check it against the screen - reading photos is not perfect.
          </span>
          <Link
            className="btn primary"
            to={logLink({
              title: top ? `Blue screen: ${top.name}` : `Error ${codes[0] ?? reading.drivers[0]}`,
              codes: codes.join(", "),
              category: top && top.category !== "other" ? top.category : "os",
              symptoms: reading.drivers.length > 0 ? `Blue screen names ${reading.drivers.join(", ")}.` : "",
            })}
          >
            Log this job
          </Link>
        </div>
      )}
      {reading.cases.length > 0 && (
        <>
          <h2>You have seen this before</h2>
          <SimilarCases cases={reading.cases} />
        </>
      )}
      {reading.stop_codes.map((code) => (
        <StopCodeCard key={code.code} code={code} categories={categories} />
      ))}
      {reading.unknown_codes.length > 0 && (
        <p className="muted small">
          {reading.unknown_codes.join(", ")} is not in the built-in stop-code list.
        </p>
      )}
      {reading.text && (
        <details>
          <summary>All the text read from the photo</summary>
          <pre className="entry-text small" style={{ marginTop: 6 }}>{reading.text}</pre>
        </details>
      )}
    </div>
  );
}

function SymptomCard({ symptom, categories }: { symptom: NoBootSymptom; categories: Record<string, string> }) {
  return (
    <div className="card">
      <div className="row">
        <h3 className="grow">{symptom.title}</h3>
        <span className="chip">{categories[symptom.category] ?? symptom.category}</span>
      </div>
      <p style={{ marginTop: 6 }}>{symptom.meaning}</p>
      <div className="form-grid" style={{ marginTop: 10 }}>
        <div>
          <b className="small">Usual causes, most likely first</b>
          <ol style={{ margin: "4px 0 0", paddingLeft: 20 }}>
            {symptom.causes.map((cause) => (
              <li key={cause}>{cause}</li>
            ))}
          </ol>
        </div>
        <div>
          <b className="small">What to try, in order</b>
          <ol style={{ margin: "4px 0 0", paddingLeft: 20 }}>
            {symptom.checks.map((check) => (
              <li key={check}>{check}</li>
            ))}
          </ol>
        </div>
      </div>
      <p style={{ marginTop: 12 }}>
        <Link className="btn" to={logLink({ title: symptom.title, category: symptom.category })}>
          Log this job
        </Link>
      </p>
    </div>
  );
}

export function DeadPcPage() {
  const input = useRef<HTMLInputElement>(null);
  const [picked, setPicked] = useState("");
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: Infinity });
  const info = useQuery({ queryKey: ["collector"], queryFn: api.collector });
  const guide = useQuery({ queryKey: ["noboot"], queryFn: api.noBoot, staleTime: Infinity });
  const photo = useMutation({ mutationFn: api.readPhoto });
  const categories = meta.data?.categories ?? {};
  const symptom = guide.data?.find((item) => item.key === picked);

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Won&apos;t start</h1>
          <p className="sub">
            For a PC that cannot run the collector: one that blue-screens before Windows loads, or
            does not start at all.
          </p>
        </div>
      </div>

      <div className="card stack" style={{ gap: 10 }}>
        <h2>It shows an error: take a photo</h2>
        <p>
          Photograph the blue screen with your phone and upload it. The stop code is read off the
          photo and looked up, along with any earlier job that had it. The photo is not stored.
        </p>
        {info.data && !info.data.photo_reading && (
          <div className="notice warn">
            Photo reading is not installed on this server (it needs the Tesseract OCR program; the
            Docker version includes it). Type the code into <Link to="/lookup">Look up</Link> instead.
          </div>
        )}
        <div className="row">
          <button className="btn primary" onClick={() => input.current?.click()} disabled={photo.isPending}>
            {photo.isPending ? "Reading the photo ..." : "Choose or take a photo"}
          </button>
          <input
            ref={input}
            type="file"
            accept="image/*"
            capture="environment"
            hidden
            aria-label="Photo of the error screen"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) photo.mutate(file);
              event.target.value = "";
            }}
          />
          <span className="muted small">Fill the frame with the screen, square on, no glare.</span>
        </div>
        <ErrorNotice error={photo.error} />
        {photo.data && <PhotoResult reading={photo.data} categories={categories} />}
      </div>

      <div className="card stack" style={{ gap: 10 }}>
        <h2>It shows nothing, or stops early: what do you see?</h2>
        {guide.isLoading && <Loading />}
        <ErrorNotice error={guide.error} />
        <div className="row">
          {(guide.data ?? []).map((item) => (
            <button
              key={item.key}
              className={item.key === picked ? "btn primary" : "btn"}
              style={{ whiteSpace: "normal", textAlign: "left" }}
              aria-pressed={item.key === picked}
              onClick={() => setPicked(item.key === picked ? "" : item.key)}
            >
              {item.title}
            </button>
          ))}
        </div>
      </div>
      {symptom && <SymptomCard symptom={symptom} categories={categories} />}
    </div>
  );
}
