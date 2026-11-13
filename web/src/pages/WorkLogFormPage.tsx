// New entry and edit entry. Only the title is required: capture the job in
// seconds, fill in the cause and the fix when you know them.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { api, type RunDetail, type WorkLogEntry, type WorkLogInput } from "../api";
import { ErrorNotice, Loading, SimilarCases } from "../components/Bits";
import { splitList, today } from "../format";
import { useDebounced } from "../useDebounced";

interface FormState {
  title: string;
  occurred_on: string;
  status: string;
  category: string;
  device_type: string;
  device: string;
  symptoms: string;
  steps: string;
  root_cause: string;
  fix: string;
  components: string;
  error_codes: string;
  reference: string;
  minutes_spent: string;
  run_id: string | null;
}

const EMPTY: FormState = {
  title: "",
  occurred_on: today(),
  status: "open",
  category: "other",
  device_type: "gaming_pc",
  device: "",
  symptoms: "",
  steps: "",
  root_cause: "",
  fix: "",
  components: "",
  error_codes: "",
  reference: "",
  minutes_spent: "",
  run_id: null,
};

function fromEntry(entry: WorkLogEntry): FormState {
  return {
    title: entry.title,
    occurred_on: entry.occurred_on,
    status: entry.status,
    category: entry.category,
    device_type: entry.device_type,
    device: entry.device,
    symptoms: entry.symptoms,
    steps: entry.steps,
    root_cause: entry.root_cause,
    fix: entry.fix,
    components: entry.components.join(", "),
    error_codes: entry.error_codes.join(", "),
    reference: entry.reference,
    minutes_spent: entry.minutes_spent === null ? "" : String(entry.minutes_spent),
    run_id: entry.run_id,
  };
}

/** Start an entry from what a run found, so nothing has to be retyped. */
export function fromRun(run: RunDetail): FormState {
  const problems = run.findings.filter((finding) => finding.severity !== "info");
  const top = problems[0];
  const codes = [...new Set(problems.flatMap((finding) => finding.error_codes))];
  const parts = [run.cpu, run.gpu].filter((part): part is string => Boolean(part));
  return {
    ...EMPTY,
    title: top ? top.title : run.label || "No fault found",
    category: top ? top.category : "no_fault_found",
    device_type: run.device.type === "laptop" ? "laptop" : run.device.type === "server" ? "server" : "gaming_pc",
    device: [run.cpu, run.gpu, run.ram_gb ? `${run.ram_gb} GB` : null].filter(Boolean).join(" / "),
    steps: problems.length > 0 ? `PC Doctor found:\n${problems.map((finding) => `- ${finding.title}`).join("\n")}` : "PC Doctor run: no faults found.",
    components: parts.join(", "),
    error_codes: codes.join(", "),
    run_id: run.id,
  };
}

function toInput(form: FormState): WorkLogInput {
  const minutes = form.minutes_spent.trim();
  return {
    title: form.title,
    occurred_on: form.occurred_on || null,
    status: form.status,
    category: form.category,
    device_type: form.device_type,
    device: form.device,
    symptoms: form.symptoms,
    steps: form.steps,
    root_cause: form.root_cause,
    fix: form.fix,
    components: splitList(form.components),
    error_codes: splitList(form.error_codes),
    reference: form.reference,
    minutes_spent: minutes === "" ? null : Number(minutes),
    run_id: form.run_id,
  };
}

export function WorkLogFormPage() {
  const { id } = useParams();
  const entryId = id ? Number(id) : null;
  const [params] = useSearchParams();
  const runId = entryId === null ? params.get("run") : null;
  const navigate = useNavigate();
  const client = useQueryClient();

  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: Infinity });
  const existing = useQuery({
    queryKey: ["entry", entryId],
    queryFn: () => api.entry(entryId!),
    enabled: entryId !== null,
  });
  const run = useQuery({ queryKey: ["run", runId], queryFn: () => api.run(runId!), enabled: Boolean(runId) });

  // Other pages can start an entry: /worklog/new?title=...&codes=...&category=...
  const [form, setForm] = useState<FormState>(() => ({
    ...EMPTY,
    title: params.get("title") ?? "",
    error_codes: params.get("codes") ?? "",
    category: params.get("category") ?? EMPTY.category,
    symptoms: params.get("symptoms") ?? "",
    components: params.get("parts") ?? "",
  }));
  const [loaded, setLoaded] = useState(entryId === null && !runId);
  useEffect(() => {
    if (loaded) return;
    if (existing.data) {
      setForm(fromEntry(existing.data));
      setLoaded(true);
    } else if (run.data) {
      setForm(fromRun(run.data));
      setLoaded(true);
    }
  }, [existing.data, run.data, loaded]);

  const set = (field: keyof FormState) => (
    event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>,
  ) => setForm((current) => ({ ...current, [field]: event.target.value }));

  // "Have I seen this before?" - updates as the symptoms and codes are typed.
  const probe = useDebounced(
    { text: `${form.title} ${form.symptoms}`.trim(), codes: form.error_codes, parts: form.components },
    400,
  );
  const similar = useQuery({
    queryKey: ["similar-live", probe, entryId],
    enabled: loaded && (probe.text.length >= 4 || probe.codes.trim().length > 0),
    queryFn: () =>
      api.similar({
        text: probe.text,
        codes: splitList(probe.codes),
        parts: splitList(probe.parts),
        exclude_id: entryId,
        limit: 4,
      }),
    placeholderData: (previous) => previous,
  });

  const photoId = entryId === null ? params.get("photo") : null;
  const assist = useQuery({ queryKey: ["assist"], queryFn: api.assist, staleTime: Infinity });
  const draft = useMutation({
    mutationFn: () =>
      api.draft({
        run_id: form.run_id,
        photo_id: photoId,
        notes: [form.title, form.symptoms, form.steps, form.root_cause, form.fix].filter(Boolean).join("\n"),
      }),
    // The draft only fills what is still empty: nothing you typed is replaced.
    onSuccess: (suggested) =>
      setForm((current) => ({
        ...current,
        title: current.title || suggested.title,
        category: current.category === "other" ? suggested.category : current.category,
        symptoms: current.symptoms || suggested.symptoms,
        steps: current.steps || suggested.steps,
        root_cause: current.root_cause || suggested.root_cause,
        fix: current.fix || suggested.fix,
        error_codes: current.error_codes || suggested.error_codes.join(", "),
        components: current.components || suggested.components.join(", "),
      })),
  });

  const save = useMutation({
    mutationFn: async () => {
      const saved = await (entryId === null ? api.createEntry(toInput(form)) : api.updateEntry(entryId, toInput(form)));
      if (photoId) await api.linkPhoto(photoId, saved.id);
      return saved;
    },
    onSuccess: (saved) => {
      void client.invalidateQueries();
      navigate(`/worklog/${saved.id}`);
    },
  });

  if (!loaded) {
    if (existing.error || run.error) return <ErrorNotice error={existing.error ?? run.error} />;
    return <Loading />;
  }
  const back = entryId !== null ? `/worklog/${entryId}` : runId ? `/runs/${runId}` : "/worklog";

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>{entryId === null ? "Log a job" : "Edit entry"}</h1>
          <p className="sub">
            Only the title is needed. Write about the machine and the fix - never the customer: no
            names, phone numbers or serial numbers.
          </p>
        </div>
      </div>

      <div className="two-col">
        <form
          className="card stack"
          onSubmit={(event) => {
            event.preventDefault();
            save.mutate();
          }}
        >
          {form.run_id && (
            <div className="notice">
              <span className="grow">
                Linked to a <Link to={`/runs/${form.run_id}`}>PC Doctor run</Link>. Details were filled
                in from it - change anything.
              </span>
              <button type="button" className="btn quiet" onClick={() => setForm((current) => ({ ...current, run_id: null }))}>
                Unlink
              </button>
            </div>
          )}
          <label className="field">
            Title
            <input
              required
              autoFocus
              maxLength={200}
              value={form.title}
              onChange={set("title")}
              placeholder="e.g. Restarts under load, no blue screen"
            />
          </label>

          <div className="form-grid">
            <label className="field">
              Date
              <input type="date" value={form.occurred_on} onChange={set("occurred_on")} />
            </label>
            <label className="field">
              Status
              <select value={form.status} onChange={set("status")}>
                {Object.entries(meta.data?.statuses ?? {}).map(([key, name]) => (
                  <option key={key} value={key}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Kind of fault
              <select value={form.category} onChange={set("category")}>
                {Object.entries(meta.data?.categories ?? {}).map(([key, name]) => (
                  <option key={key} value={key}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Machine
              <select value={form.device_type} onChange={set("device_type")}>
                {Object.entries(meta.data?.device_types ?? {}).map(([key, name]) => (
                  <option key={key} value={key}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <label className="field">
            The build
            <input value={form.device} maxLength={300} onChange={set("device")} placeholder="e.g. Ryzen 7 5800X / RTX 3080 / 650 W PSU" />
          </label>
          <label className="field">
            Symptoms
            <textarea value={form.symptoms} onChange={set("symptoms")} placeholder="What it does, and when." />
          </label>
          <div className="form-grid">
            <label className="field">
              Error codes
              <span className="hint">Separate with commas: 0x124, WHEA-18, POST 55</span>
              <input value={form.error_codes} onChange={set("error_codes")} />
            </label>
            <label className="field">
              Parts involved
              <span className="hint">Separate with commas: RTX 3080, B550, 650W PSU</span>
              <input value={form.components} onChange={set("components")} />
            </label>
          </div>
          <label className="field">
            What I checked
            <textarea value={form.steps} onChange={set("steps")} placeholder="Tests, swaps, readings - including what ruled things out." />
          </label>
          <label className="field">
            Root cause
            <textarea value={form.root_cause} onChange={set("root_cause")} style={{ minHeight: 60 }} />
          </label>
          <label className="field">
            Fix
            <textarea value={form.fix} onChange={set("fix")} style={{ minHeight: 60 }} />
          </label>
          <div className="form-grid">
            <label className="field">
              Minutes spent
              <input type="number" min={0} max={100000} value={form.minutes_spent} onChange={set("minutes_spent")} />
            </label>
            <label className="field">
              Your job number
              <span className="hint">Optional. Never a customer name.</span>
              <input value={form.reference} maxLength={80} onChange={set("reference")} />
            </label>
          </div>

          <ErrorNotice error={save.error ?? draft.error} />
          <div className="row">
            <button className="btn primary" disabled={save.isPending}>
              {save.isPending ? "Saving ..." : "Save"}
            </button>
            {assist.data?.available && (
              <button type="button" className="btn" disabled={draft.isPending} onClick={() => draft.mutate()}>
                {draft.isPending ? "Drafting ..." : "Draft the rest with AI"}
              </button>
            )}
            <Link className="btn" to={back}>
              Cancel
            </Link>
          </div>
          {assist.data?.available && (
            <p className="muted small">
              The AI fills only empty fields, from the run or photo and what you typed. It sends
              that text to the AI provider. Read the draft before saving - it can be wrong.
            </p>
          )}
        </form>

        <aside className="stack" style={{ gap: 10 }}>
          <h2>Seen this before?</h2>
          <SimilarCases
            cases={similar.data ?? []}
            empty="Earlier jobs that match will appear here as you type the symptoms and codes."
          />
        </aside>
      </div>
    </div>
  );
}
