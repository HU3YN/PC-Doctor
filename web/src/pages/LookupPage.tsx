// One box for "what is this?": a stop code, or a description of a problem.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, type StopCode } from "../api";
import { ErrorNotice, SimilarCases } from "../components/Bits";
import { useDebounced } from "../useDebounced";

export function StopCodeCard({ code, categories }: { code: StopCode; categories: Record<string, string> }) {
  return (
    <div className="card">
      <div className="row">
        <span className="chip code">{code.hex}</span>
        <h3 className="grow" style={{ overflowWrap: "anywhere" }}>
          {code.name}
        </h3>
        {code.meaning && <span className="chip">{categories[code.category] ?? code.category}</span>}
      </div>
      {code.meaning ? (
        <>
          <p style={{ marginTop: 8 }}>{code.meaning}</p>
          {code.hardware_likely && (
            <p className="small muted" style={{ marginTop: 4 }}>
              Usually a hardware fault rather than software.
            </p>
          )}
          <div className="form-grid" style={{ marginTop: 10 }}>
            <div>
              <b className="small">Usual causes, most likely first</b>
              <ol style={{ margin: "4px 0 0", paddingLeft: 20 }}>
                {code.causes.map((cause) => (
                  <li key={cause}>{cause}</li>
                ))}
              </ol>
            </div>
            <div>
              <b className="small">What to check</b>
              <ol style={{ margin: "4px 0 0", paddingLeft: 20 }}>
                {code.checks.map((check) => (
                  <li key={check}>{check}</li>
                ))}
              </ol>
            </div>
          </div>
        </>
      ) : (
        <p className="muted small" style={{ marginTop: 6 }}>
          No written guidance for this code yet - the name is from the Windows SDK.
        </p>
      )}
    </div>
  );
}

export function LookupPage() {
  const [text, setText] = useState("");
  const q = useDebounced(text.trim(), 300);
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: Infinity });
  const codes = useQuery({
    queryKey: ["stopcodes", q],
    queryFn: () => api.stopCodes(q),
    placeholderData: (previous) => previous,
  });
  const auth = useQuery({ queryKey: ["auth"], queryFn: api.authStatus });
  const master = Boolean(auth.data?.signed_in);
  const cases = useQuery({
    queryKey: ["lookup-cases", q],
    enabled: master && q.length >= 3,
    queryFn: () => api.similar({ text: q, codes: /^(0x)?[0-9a-f]{2,8}$/i.test(q) ? [q.startsWith("0") ? q : `0x${q}`] : [], limit: 6 }),
    placeholderData: (previous) => previous,
  });
  const categories = meta.data?.categories ?? {};
  const found = codes.data ?? [];

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Look up</h1>
          <p className="sub">
            Type a stop code or describe the problem. You get what it means, where to look first, and
            the times you have fixed it before.
          </p>
        </div>
      </div>
      <input
        className="search"
        type="search"
        autoFocus
        placeholder="0x124, VIDEO_TDR, or: restarts under load"
        aria-label="Stop code or problem"
        value={text}
        onChange={(event) => setText(event.target.value)}
        style={{ maxWidth: 560, fontSize: "1.05rem" }}
      />
      <ErrorNotice error={codes.error ?? cases.error} />

      {master && q.length >= 3 && (
        <section className="stack" style={{ gap: 10 }}>
          <h2>From your work log</h2>
          <SimilarCases cases={cases.data ?? []} empty="Nothing in your work log matches yet." />
        </section>
      )}

      <section className="stack" style={{ gap: 10 }}>
        <h2>{q ? "Blue-screen stop codes" : "Common blue-screen stop codes"}</h2>
        {found.length === 0 && codes.isSuccess && <p className="muted small">No stop code matches.</p>}
        {found.map((code) => (
          <StopCodeCard key={code.code} code={code} categories={categories} />
        ))}
      </section>
    </div>
  );
}
